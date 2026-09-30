"use client";

// ATP 模型 3D 场景查看器
// 数据源：GET /api/v1/atp/assets/{assetId}/scene（schema lp.atp.scene/1，
// 后端 atp_scene_service.parse_atp_scene 产出：节点/支路/开关/电源/INCLUDE/参数）。
// 渲染：原生 three.js（不引 @react-three/fiber，规避 React 19 兼容风险），
// 力导向三维布局 + OrbitControls 旋转缩放 + 悬停高亮 + 点击查看元素详情。

import { useQuery } from "@tanstack/react-query";
import { Alert, Collapse, Descriptions, Empty, Spin, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

// ───────────────────────── 场景类型（lp.atp.scene/1） ─────────────────────────

interface AtpSceneNode {
  id: string;
  kind: string; // internal | switch | source | include | line | other
}

interface AtpSceneBranch {
  n1: string;
  n2: string;
  r?: string;
  l?: string;
  c?: string;
  raw?: string;
}

interface AtpSceneSwitch {
  n1: string;
  n2: string;
  type?: string;
  control?: string;
  raw?: string;
}

interface AtpSceneSource {
  node: string;
  amplitude?: string;
  freq?: string;
  phase?: string;
  raw?: string;
}

interface AtpSceneInclude {
  path: string;
  ports: string[];
}

interface AtpSceneParameter {
  name: string;
  value: string;
}

interface AtpSceneStats {
  node_count: number;
  branch_count: number;
  switch_count: number;
  source_count: number;
  include_count: number;
  param_count: number;
  warnings: number;
}

interface AtpScene {
  schema: string;
  source_file: string;
  parameters: AtpSceneParameter[];
  includes: AtpSceneInclude[];
  nodes: AtpSceneNode[];
  branches: AtpSceneBranch[];
  switches: AtpSceneSwitch[];
  sources: AtpSceneSource[];
  stats: AtpSceneStats;
  warnings: string[];
}

const KIND_COLORS: Record<string, number> = {
  internal: 0x90a4ae,
  switch: 0x42a5f5,
  source: 0x66bb6a,
  include: 0xffa726,
  line: 0xab47bc,
  other: 0x78909c,
};

const KIND_LABELS: Record<string, string> = {
  internal: "内部节点",
  switch: "开关",
  source: "电源",
  include: "线路段(.lib)",
  line: "线路端口",
  other: "其他",
};

// ───────────────────────── 元件形状构建（按 kind 绘制不同 3D 符号） ─────────────────────────

function nodeMaterial(color: number): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0.15 });
}

/**
 * 按元件类型构建 3D 符号（拓扑布局不变，仅节点形状区分类型）：
 *   source   电源：圆柱体 + 顶部锥体（电池/电源符号）
 *   switch   开关：立方体 + 两侧触点柱
 *   include  线路段：短圆柱（导线段）
 *   line     线路端口：圆环
 *   internal 内部节点：小球（弱化，结构噪声）
 *   other    未知：深灰小球
 * 返回 Object3D（可能是 Group），每个子 mesh 允许被射线拾取。
 */
function buildNodeShape(kind: string, color: number): THREE.Object3D {
  switch (kind) {
    case "source": {
      const group = new THREE.Group();
      const body = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 1.1, 14), nodeMaterial(color));
      const cap = new THREE.Mesh(new THREE.ConeGeometry(0.52, 0.62, 14), nodeMaterial(color));
      cap.position.y = 0.86;
      group.add(body, cap);
      return group;
    }
    case "switch": {
      const group = new THREE.Group();
      const box = new THREE.Mesh(new THREE.BoxGeometry(0.85, 0.85, 0.85), nodeMaterial(color));
      const contactMaterial = new THREE.MeshStandardMaterial({ color: 0xd6d6d6, roughness: 0.3, metalness: 0.6 });
      const postGeometry = new THREE.CylinderGeometry(0.13, 0.13, 0.55, 8);
      const post1 = new THREE.Mesh(postGeometry, contactMaterial);
      post1.position.set(0.5, 0.25, 0);
      const post2 = new THREE.Mesh(postGeometry, contactMaterial);
      post2.position.set(-0.5, 0.25, 0);
      group.add(box, post1, post2);
      return group;
    }
    case "include": {
      return new THREE.Mesh(new THREE.CylinderGeometry(0.52, 0.52, 1.5, 12), nodeMaterial(color));
    }
    case "line": {
      return new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.15, 8, 18), nodeMaterial(color));
    }
    default: {
      return new THREE.Mesh(
        new THREE.SphereGeometry(kind === "internal" ? 0.4 : 0.5, 16, 16),
        nodeMaterial(color),
      );
    }
  }
}

// ───────────────────────── 力导向布局（三维 Fruchterman-Reingold） ─────────────────────────

interface CoulombNode {
  id: string;
  kind: string;
  x: number;
  y: number;
  z: number;
  degree: number;
}

interface EdgeRef {
  a: string;
  b: string;
  weight: number;
}

function computeLayout(scene: AtpScene, iterations = 260): CoulombNode[] {
  const nodes: CoulombNode[] = scene.nodes.map((node) => ({
    id: node.id,
    kind: node.kind,
    x: (Math.random() - 0.5) * 24,
    y: (Math.random() - 0.5) * 24,
    z: (Math.random() - 0.5) * 10,
    degree: 0,
  }));
  if (nodes.length === 0) return nodes;
  const nodeIndex = new Map(nodes.map((node, index) => [node.id, index]));

  // 建边（支路 + 开关；同对节点多条边加权）
  const edgeMap = new Map<string, EdgeRef>();
  const addEdge = (a: string, b: string) => {
    if (a === b) return;
    const [u, v] = a < b ? [a, b] : [b, a];
    const key = `${u}|${v}`;
    const existing = edgeMap.get(key);
    if (existing) existing.weight += 1;
    else edgeMap.set(key, { a: u, b: v, weight: 1 });
  };
  for (const branch of scene.branches) addEdge(branch.n1, branch.n2);
  for (const sw of scene.switches) addEdge(sw.n1, sw.n2);
  const edges = [...edgeMap.values()];
  for (const edge of edges) {
    const ia = nodeIndex.get(edge.a);
    const ib = nodeIndex.get(edge.b);
    if (ia === undefined || ib === undefined) continue;
    nodes[ia].degree += 1;
    nodes[ib].degree += 1;
  }

  const area = Math.max(nodes.length, 4) * 36;
  const k = 0.9 * Math.sqrt(area / Math.max(nodes.length, 1));
  let temperature = 1.6;

  const displacement = nodes.map(() => ({ x: 0, y: 0, z: 0 }));

  for (let iter = 0; iter < iterations; iter += 1) {
    for (let i = 0; i < displacement.length; i += 1) {
      displacement[i].x = 0;
      displacement[i].y = 0;
      displacement[i].z = 0;
    }

    // 两两斥力
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let dz = a.z - b.z;
        let dist2 = dx * dx + dy * dy + dz * dz;
        if (dist2 < 0.01) {
          dx = (Math.random() - 0.5) * 0.1;
          dy = (Math.random() - 0.5) * 0.1;
          dz = (Math.random() - 0.5) * 0.1;
          dist2 = dx * dx + dy * dy + dz * dz;
        }
        const dist = Math.sqrt(dist2);
        const force = (k * k) / dist;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        const fz = (dz / dist) * force;
        displacement[i].x += fx;
        displacement[i].y += fy;
        displacement[i].z += fz;
        displacement[j].x -= fx;
        displacement[j].y -= fy;
        displacement[j].z -= fz;
      }
    }

    // 边弹簧引力
    for (const edge of edges) {
      const ia = nodeIndex.get(edge.a);
      const ib = nodeIndex.get(edge.b);
      if (ia === undefined || ib === undefined) continue;
      const a = nodes[ia];
      const b = nodes[ib];
      let dx = a.x - b.x;
      let dy = a.y - b.y;
      let dz = a.z - b.z;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
      const force = (dist * dist) / k * edge.weight;
      dx /= dist;
      dy /= dist;
      dz /= dist;
      displacement[ia].x -= dx * force;
      displacement[ia].y -= dy * force;
      displacement[ia].z -= dz * force;
      displacement[ib].x += dx * force;
      displacement[ib].y += dy * force;
      displacement[ib].z += dz * force;
    }

    // 中心引力（防止四散）
    for (let i = 0; i < nodes.length; i += 1) {
      displacement[i].x -= nodes[i].x * 0.08;
      displacement[i].y -= nodes[i].y * 0.08;
      displacement[i].z -= nodes[i].z * 0.08;
    }

    // 应用位移（温度限幅）
    for (let i = 0; i < nodes.length; i += 1) {
      const d = displacement[i];
      const magnitude = Math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z);
      if (magnitude > 0.01) {
        const limited = Math.min(magnitude, temperature);
        nodes[i].x += (d.x / magnitude) * limited;
        nodes[i].y += (d.y / magnitude) * limited;
        nodes[i].z += (d.z / magnitude) * limited;
      }
    }

    temperature *= 0.975;
  }

  return nodes;
}

// ───────────────────────── 组件 ─────────────────────────

interface AtpSceneViewerProps {
  assetId: string;
}

interface SelectedNodeDetail {
  id: string;
  kind: string;
  branches: AtpSceneBranch[];
  switches: AtpSceneSwitch[];
  sources: AtpSceneSource[];
  includes: AtpSceneInclude[];
}

export function AtpSceneViewer({ assetId }: AtpSceneViewerProps) {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const containerRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<SelectedNodeDetail | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  const sceneQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "scene"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/scene`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpScene;
    },
  });

  // three.js 渲染生命周期
  useEffect(() => {
    const container = containerRef.current;
    const scene = sceneQuery.data;
    if (!container || !scene || scene.nodes.length === 0) return;

    // 布局
    const layout = computeLayout(scene);
    const positionById = new Map(layout.map((node) => [node.id, node]));

    // 场景基础
    const threeScene = new THREE.Scene();
    threeScene.background = new THREE.Color(0x0f1419);

    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1000);
    camera.position.set(30, 22, 34);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.target.set(0, 0, 0);

    // 灯
    const ambient = new THREE.AmbientLight(0xffffff, 0.65);
    threeScene.add(ambient);
    const directional = new THREE.DirectionalLight(0xffffff, 1.1);
    directional.position.set(20, 30, 25);
    threeScene.add(directional);

    // 节点：按 kind 绘制元件符号（Group/Mesh），子 mesh 全部登记供射线拾取
    const nodeObjects = new Map<string, THREE.Object3D>();
    const nodeMeshes: THREE.Mesh[] = [];
    const markNodeId = (object: THREE.Object3D, nodeId: string) => {
      if ((object as THREE.Mesh).isMesh) {
        object.userData.nodeId = nodeId;
        nodeMeshes.push(object as THREE.Mesh);
      }
      for (const child of object.children) {
        markNodeId(child, nodeId);
      }
    };
    for (const node of scene.nodes) {
      const pos = positionById.get(node.id);
      if (!pos) continue;
      const color = KIND_COLORS[node.kind] ?? KIND_COLORS.other;
      const object = buildNodeShape(node.kind, color);
      object.position.set(pos.x, pos.y, pos.z);
      markNodeId(object, node.id);
      threeScene.add(object);
      nodeObjects.set(node.id, object);
    }

    // 元件符号高亮（按 nodeId 改所有子 mesh 的自发光）
    const setNodeEmissive = (nodeId: string | null, hexColor: number) => {
      if (!nodeId) return;
      for (const mesh of nodeMeshes) {
        if (mesh.userData.nodeId === nodeId) {
          (mesh.material as THREE.MeshStandardMaterial).emissive = new THREE.Color(hexColor);
        }
      }
    };

    // 支路/开关连线
    const lineMaterial = new THREE.LineBasicMaterial({ color: 0x4a6b8a, transparent: true, opacity: 0.55 });
    const linePairs: number[] = [];
    const includeLineMaterial = new THREE.LineBasicMaterial({ color: 0xffa726, transparent: true, opacity: 0.35 });
    const includePairs: number[] = [];

    const pushEdge = (pairs: number[], n1: string, n2: string) => {
      const p1 = positionById.get(n1);
      const p2 = positionById.get(n2);
      if (!p1 || !p2) return;
      pairs.push(p1.x, p1.y, p1.z, p2.x, p2.y, p2.z);
    };

    for (const branch of scene.branches) pushEdge(linePairs, branch.n1, branch.n2);
    for (const sw of scene.switches) pushEdge(linePairs, sw.n1, sw.n2);
    for (const inc of scene.includes) {
      for (let i = 0; i + 1 < inc.ports.length; i += 1) {
        pushEdge(includePairs, inc.ports[i], inc.ports[i + 1]);
      }
    }

    if (linePairs.length > 0) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(linePairs, 3));
      threeScene.add(new THREE.LineSegments(geometry, lineMaterial));
    }
    if (includePairs.length > 0) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(includePairs, 3));
      threeScene.add(new THREE.LineSegments(geometry, includeLineMaterial));
    }

    // 网格辅助（地面参考）
    const grid = new THREE.GridHelper(46, 23, 0x2a3b4d, 0x1d2a39);
    grid.position.y = -14;
    threeScene.add(grid);

    // 射线拾取
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2(1, 1); // 初始在画布外
    let hoveredNodeId: string | null = null;

    const pickNode = (clientX: number, clientY: number): string | null => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(nodeMeshes, false);
      return hits.length > 0 ? ((hits[0].object.userData.nodeId as string) ?? null) : null;
    };

    const onPointerMove = (event: PointerEvent) => {
      const id = pickNode(event.clientX, event.clientY);
      if (id !== hoveredNodeId) {
        // 恢复上一个高亮
        setNodeEmissive(hoveredNodeId, 0x000000);
        hoveredNodeId = id;
        if (id) {
          setNodeEmissive(id, 0x3377ff);
        }
        setHovered(id);
      }
      if (id) {
        setTooltipPos({ x: event.clientX, y: event.clientY });
      } else {
        setTooltipPos(null);
      }
    };

    const onClick = (event: PointerEvent) => {
      const id = pickNode(event.clientX, event.clientY);
      if (!id) {
        setSelected(null);
        return;
      }
      const node = scene.nodes.find((n) => n.id === id);
      if (!node) return;
      const detail: SelectedNodeDetail = {
        id,
        kind: node.kind,
        branches: scene.branches.filter((b) => b.n1 === id || b.n2 === id),
        switches: scene.switches.filter((s) => s.n1 === id || s.n2 === id),
        sources: scene.sources.filter((s) => s.node === id),
        includes: scene.includes.filter((inc) => inc.ports.includes(id)),
      };
      setSelected(detail);
    };

    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("click", onClick);

    // 尺寸自适应
    const resize = () => {
      const width = container.clientWidth || 600;
      const height = container.clientHeight || 420;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    // 动画循环
    let frameId = 0;
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(threeScene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("click", onClick);
      controls.dispose();
      const disposeObject = (object: THREE.Object3D) => {
        const mesh = object as THREE.Mesh;
        if (mesh.geometry) {
          mesh.geometry.dispose();
        }
        const material = mesh.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(material)) {
          for (const item of material) item.dispose();
        } else if (material) {
          material.dispose();
        }
        for (const child of object.children) {
          disposeObject(child);
        }
      };
      for (const object of nodeObjects.values()) {
        disposeObject(object);
      }
      nodeObjects.clear();
      nodeMeshes.length = 0;
      lineMaterial.dispose();
      includeLineMaterial.dispose();
      grid.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement);
      }
    };
  }, [sceneQuery.data, assetId]);

  if (initializing) {
    return <div style={{ textAlign: "center", padding: "40px 0" }}><Spin /></div>;
  }

  if (!user) {
    return <Alert type="warning" showIcon message="请先登录后查看 ATP 模型场景。" />;
  }

  if (!canRead) {
    return <Alert type="error" showIcon message="当前账号缺少 ATP 模型读取权限（需要 atp.read / atp.run / atp.manage）。" />;
  }

  const scene = sceneQuery.data;

  const statsItems = scene
    ? [
        { key: "nodes", label: "节点", children: scene.stats.node_count },
        { key: "branches", label: "支路", children: scene.stats.branch_count },
        { key: "switches", label: "开关", children: scene.stats.switch_count },
        { key: "sources", label: "电源", children: scene.stats.source_count },
        { key: "includes", label: "线路段", children: scene.stats.include_count },
        { key: "params", label: "参数", children: scene.stats.param_count },
      ]
    : [];

  return (
    <div>
      <Typography.Title level={5}>
        场景拓扑预览
        {scene ? <Typography.Text type="secondary" style={{ fontSize: 13, marginLeft: 8 }}>入口 {scene.source_file}（schema {scene.schema}）</Typography.Text> : null}
      </Typography.Title>

      {sceneQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}><Spin /></div>
      ) : sceneQuery.isError ? (
        <Alert type="error" showIcon message="加载场景失败" description={sceneQuery.error instanceof Error ? sceneQuery.error.message : ""} />
      ) : scene && scene.nodes.length > 0 ? (
        <>
          <Descriptions size="small" column={6} style={{ marginBottom: 8 }} items={statsItems} />

          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
            {Object.entries(KIND_LABELS).map(([kind, label]) => (
              <span key={kind} style={{ fontSize: 12, color: "#ccc", display: "inline-flex", alignItems: "center", gap: 4 }}>
                <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: `#${(KIND_COLORS[kind] ?? KIND_COLORS.other).toString(16).padStart(6, "0")}` }} />
                {label}
              </span>
            ))}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>形状=元件类型（⚡电源 · ▦开关 · ‖线路段 · ◎端口 · ●内部节点）· 拖拽旋转 · 滚轮缩放 · 点击节点查看详情</Typography.Text>
          </div>

          {scene.warnings.length > 0 ? (
            <Alert type="warning" showIcon style={{ marginBottom: 8 }} message={`解析警告 ${scene.warnings.length} 条（尽力而为渲染）`} description={scene.warnings.slice(0, 5).join("；")} />
          ) : null}

          <div ref={containerRef} style={{ position: "relative", width: "100%", height: 440, borderRadius: 8, overflow: "hidden", border: "1px solid #2a3b4d", background: "#0f1419" }}>
            {hovered && tooltipPos ? (
              <div style={{ position: "fixed", left: tooltipPos.x + 12, top: tooltipPos.y + 12, zIndex: 1000, pointerEvents: "none", transform: "translateY(0)", background: "rgba(15,20,25,0.92)", border: "1px solid #3a4b5d", borderRadius: 6, padding: "4px 10px", fontSize: 12, color: "#e8e8e8" }}>
                <b>{hovered}</b> · {KIND_LABELS[scene.nodes.find((n) => n.id === hovered)?.kind ?? "other"] ?? hovered}
              </div>
            ) : null}
          </div>

          {selected ? (
            <div style={{ marginTop: 10 }}>
              <Typography.Title level={5}>
                节点 {selected.id}
                <Tag style={{ marginLeft: 8 }} color="blue">{KIND_LABELS[selected.kind] ?? selected.kind}</Tag>
              </Typography.Title>
              {selected.branches.length > 0 ? (
                <Descriptions size="small" column={1} bordered style={{ marginBottom: 8 }}
                  items={selected.branches.map((branch, index) => ({
                    key: `b${index}`,
                    label: `支路 ${branch.n1} ⇄ ${branch.n2}`,
                    children: branch.raw ?? `R=${branch.r ?? "-"}  L=${branch.l ?? "-"}  C=${branch.c ?? "-"}`,
                  }))}
                />
              ) : null}
              {selected.switches.length > 0 ? (
                <Descriptions size="small" column={1} bordered style={{ marginBottom: 8 }}
                  items={selected.switches.map((sw, index) => ({
                    key: `s${index}`,
                    label: `开关 ${sw.n1} ⇄ ${sw.n2}`,
                    children: `type=${sw.type ?? "-"}${sw.control ? `, 控制量=${sw.control}` : ""}${sw.raw ? `,  ${sw.raw}` : ""}`,
                  }))}
                />
              ) : null}
              {selected.sources.length > 0 ? (
                <Descriptions size="small" column={1} bordered style={{ marginBottom: 8 }}
                  items={selected.sources.map((src, index) => ({
                    key: `src${index}`,
                    label: `电源 ${src.node}`,
                    children: `幅值=${src.amplitude ?? "-"} 频率=${src.freq ?? "-"} 相位=${src.phase ?? "-"}`,
                  }))}
                />
              ) : null}
              {selected.includes.length > 0 ? (
                <Descriptions size="small" column={1} bordered style={{ marginBottom: 8 }}
                  items={selected.includes.map((inc, index) => ({
                    key: `i${index}`,
                    label: `线路段端口 (${inc.ports.length} 端口)`,
                    children: inc.path,
                  }))}
                />
              ) : null}
              {selected.branches.length === 0 && selected.switches.length === 0 && selected.sources.length === 0 && selected.includes.length === 0 ? (
                <Typography.Text type="secondary">该节点没有直接相连的元件。</Typography.Text>
              ) : null}
            </div>
          ) : null}

          {scene.parameters.length > 0 ? (
            <Collapse
              style={{ marginTop: 10 }}
              items={[
                {
                  key: "params",
                  label: `参数表（${scene.parameters.length}）`,
                  children: (
                    <div style={{ maxHeight: 220, overflow: "auto", display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "2px 12px", fontSize: 12 }}>
                      {scene.parameters.map((param) => (
                        <div key={param.name} style={{ display: "flex", justifyContent: "space-between", gap: 8, padding: "2px 4px" }}>
                          <code style={{ color: "#ffd479" }}>{param.name}</code>
                          <span style={{ color: "#9acdff" }}>{param.value}</span>
                        </div>
                      ))}
                    </div>
                  ),
                },
              ]}
            />
          ) : null}
        </>
      ) : scene && scene.nodes.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该模型无可绘制的拓扑（.atp 解析结果为空）" />
      ) : null}
    </div>
  );
}