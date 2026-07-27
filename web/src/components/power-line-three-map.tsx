"use client";

import { AimOutlined, MinusOutlined, PlusOutlined } from "@ant-design/icons";
import { Alert, Button, Checkbox, Empty, Spin, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";

import { getApiBaseUrl } from "@/lib/api";
import { geoToLocal, computeBoundingBox } from "@/lib/geo-coords";
import { sampleHeight, toFloat32Heights } from "@/lib/terrain-utils";
import {
  countLineTowersOutsideTerrainBounds,
  getElevationTerrainRenderState,
} from "@/lib/elevation-terrain";
import {
  buildRouteSegments,
  collectTowerGeoPoints,
  type RouteSegment,
  type TowerGeoPoint,
} from "@/lib/power-line-route";
import type { ElevationDatasetSummary, LineTowerSummary } from "@/types/auth";

export type HeightmapData = {
  width: number;
  height: number;
  west: number;
  south: number;
  east: number;
  north: number;
  minHeight: number;
  maxHeight: number;
  heights: number[];
};

type PowerLineThreeMapProps = {
  lineCode?: string;
  lineName?: string;
  towers: LineTowerSummary[];
  terrainDataset?: Pick<
    ElevationDatasetSummary,
    "id" | "name" | "terrain_status" | "terrain_url_template" | "terrain_bounds" | "terrain_metadata"
  > | null;
  accessToken?: string | null;
  exaggeration?: number;
  loading?: boolean;
  height?: number;
  onRouteLengthChange?: (lengthKm: number) => void;
};

const DEFAULT_MAP_HEIGHT = 560;
const MIN_CAMERA_RANGE = 1500;
const DEFAULT_POINT_COLOR = "#38bdf8";
const RISK_COLOR_BY_LEVEL: Record<string, string> = {
  "1": "#22c55e",
  "2": "#f59e0b",
  "3": "#ef4444",
};
const TERRAIN_SEGMENTS = 128;
const SCALE = 0.001;

function normalizeRiskLevel(value: string | null): string {
  const text = (value ?? "").trim();
  return text || "unknown";
}

function toRad(value: number): number {
  return (value * Math.PI) / 180;
}

function calcGeoDistanceKm(start: TowerGeoPoint, end: TowerGeoPoint): number {
  const lat1 = toRad(start.latitude);
  const lat2 = toRad(end.latitude);
  const dLat = lat2 - lat1;
  const dLon = toRad(end.longitude - start.longitude);
  const sinHalfLat = Math.sin(dLat / 2);
  const sinHalfLon = Math.sin(dLon / 2);
  const a =
    sinHalfLat * sinHalfLat +
    Math.cos(lat1) * Math.cos(lat2) * sinHalfLon * sinHalfLon;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return 6371 * c;
}

function estimateRouteLengthKm(segments: RouteSegment[]): number {
  return segments.reduce((total, segment) => {
    if (segment.points.length < 2) return total;
    let length = 0;
    for (let i = 1; i < segment.points.length; i += 1) {
      length += calcGeoDistanceKm(segment.points[i - 1], segment.points[i]);
    }
    return total + length;
  }, 0);
}

function terrainColorForHeight(height: number, minH: number, maxH: number): THREE.Color {
  if (maxH <= minH) return new THREE.Color(0x38bdf8);
  const ratio = (height - minH) / (maxH - minH);
  if (ratio >= 0.85) return new THREE.Color(0xdc2626);
  if (ratio >= 0.65) return new THREE.Color(0xf97316);
  if (ratio >= 0.45) return new THREE.Color(0xeab308);
  if (ratio >= 0.25) return new THREE.Color(0x84cc16);
  return new THREE.Color(0x38bdf8);
}

export function PowerLineThreeMap({
  lineCode,
  lineName,
  towers,
  terrainDataset = null,
  accessToken = null,
  exaggeration = 1,
  loading = false,
  height = DEFAULT_MAP_HEIGHT,
  onRouteLengthChange,
}: PowerLineThreeMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    labelRenderer: CSS2DRenderer;
    controls: OrbitControls;
    terrainGroup: THREE.Group;
    lineGroup: THREE.Group;
    towerGroup: THREE.Group;
    labelGroup: THREE.Group;
  } | null>(null);

  const [initError, setInitError] = useState("");
  const [ready, setReady] = useState(false);
  const [terrainError, setTerrainError] = useState("");
  const [pointerInfo, setPointerInfo] = useState("");
  const [colorByRisk, setColorByRisk] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [heightmapData, setHeightmapData] = useState<HeightmapData | null>(null);
  const [heightmapLoading, setHeightmapLoading] = useState(false);

  const terrainRenderState = useMemo(
    () => (terrainDataset ? getElevationTerrainRenderState(terrainDataset) : "fallback"),
    [terrainDataset],
  );
  const towersOutsideTerrainBounds = useMemo(
    () => countLineTowersOutsideTerrainBounds(towers, terrainDataset?.terrain_bounds ?? null),
    [terrainDataset?.terrain_bounds, towers],
  );

  const sortedTowers = useMemo(() => [...towers].sort((a, b) => a.seq_no - b.seq_no), [towers]);
  const towerGeoPoints = useMemo<TowerGeoPoint[]>(() => collectTowerGeoPoints(sortedTowers), [sortedTowers]);
  const routeSegments = useMemo(() => buildRouteSegments(sortedTowers), [sortedTowers]);
  const routeLengthKm = useMemo(() => estimateRouteLengthKm(routeSegments), [routeSegments]);
  const controlsDisabled = !ready || towerGeoPoints.length === 0;

  const routeLengthKmRef = useRef(routeLengthKm);
  useEffect(() => {
    if (onRouteLengthChange && routeLengthKm !== routeLengthKmRef.current) {
      routeLengthKmRef.current = routeLengthKm;
      onRouteLengthChange(routeLengthKm);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeLengthKm]);

  // --- Initialize Three.js Scene ---
  useEffect(() => {
    const container = containerRef.current;
    if (!container || sceneRef.current) return;

    const w = container.clientWidth || 800;
    const h = container.clientHeight || 400;

    // Scene
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);

    // Camera
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 20000);
    camera.position.set(0, 800, 0);
    camera.lookAt(0, 0, 0);

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // CSS2D Renderer
    const labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(w, h);
    labelRenderer.domElement.style.position = "absolute";
    labelRenderer.domElement.style.top = "0";
    labelRenderer.domElement.style.left = "0";
    labelRenderer.domElement.style.pointerEvents = "none";
    container.appendChild(labelRenderer.domElement);

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 50;
    controls.maxDistance = 20000;
    controls.target.set(0, 0, 0);

    // Lights
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.0);
    dirLight.position.set(100, 200, 50);
    scene.add(dirLight);
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-100, 50, -100);
    scene.add(fillLight);

    // Groups
    const terrainGroup = new THREE.Group();
    terrainGroup.name = "terrain";
    scene.add(terrainGroup);
    const lineGroup = new THREE.Group();
    lineGroup.name = "lines";
    scene.add(lineGroup);
    const towerGroup = new THREE.Group();
    towerGroup.name = "towers";
    scene.add(towerGroup);
    const labelGroup = new THREE.Group();
    labelGroup.name = "labels";
    scene.add(labelGroup);

    sceneRef.current = {
      scene, camera, renderer, labelRenderer, controls,
      terrainGroup, lineGroup, towerGroup, labelGroup,
    };

    // Animation loop
    let animationId: number;
    function animate() {
      animationId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      labelRenderer.render(scene, camera);
    }
    animate();

    // Resize
    const onResize = () => {
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      if (cw === 0 || ch === 0) return;
      camera.aspect = cw / ch;
      camera.updateProjectionMatrix();
      renderer.setSize(cw, ch);
      labelRenderer.setSize(cw, ch);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    setReady(true);
    setInitError("");

    return () => {
      cancelAnimationFrame(animationId);
      ro.disconnect();
      renderer?.dispose?.();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
      if (container.contains(labelRenderer.domElement)) container.removeChild(labelRenderer.domElement);
      setReady(false);
      sceneRef.current = null;
    };
  }, []);

  // --- Fetch Heightmap ---
  useEffect(() => {
    let cancelled = false;
    async function loadHeightmap() {
      if (terrainRenderState !== "ready" || !terrainDataset?.id) {
        setHeightmapData(null);
        return;
      }
      setHeightmapLoading(true);
      setTerrainError("");
      try {
        const baseUrl = getApiBaseUrl();
        const url = `${baseUrl}/api/v1/elevation/datasets/${terrainDataset.id}/heightmap?res=129`;
        const headers: Record<string, string> = {};
        if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
        const res = await fetch(url, { headers });
        if (cancelled) return;
        if (!res.ok) throw new Error(`heightmap 请求失败 (${res.status})`);
        const data: HeightmapData = await res.json();
        if (cancelled) return;
        setHeightmapData(data);
      } catch (error) {
        if (!cancelled) {
          setTerrainError(error instanceof Error ? error.message : "heightmap 加载失败");
          setHeightmapData(null);
        }
      } finally {
        if (!cancelled) setHeightmapLoading(false);
      }
    }
    void loadHeightmap();
    return () => { cancelled = true; };
  }, [accessToken, terrainDataset, terrainRenderState]);

  // --- Compute origin ---
  const origin = useMemo(() => {
    if (heightmapData) return { lon: heightmapData.west, lat: heightmapData.south };
    const bounds = terrainDataset?.terrain_bounds;
    if (bounds) return { lon: bounds.west, lat: bounds.south };
    if (towerGeoPoints.length > 0) {
      return {
        lon: Math.floor(towerGeoPoints[0].longitude),
        lat: Math.floor(towerGeoPoints[0].latitude),
      };
    }
    return { lon: 0, lat: 0 };
  }, [heightmapData, terrainDataset, towerGeoPoints]);

  // --- Render scene (terrain, towers, lines, labels) ---
  useEffect(() => {
    const ctx = sceneRef.current;
    if (!ctx || !ready) return;
    const { terrainGroup, lineGroup, towerGroup, labelGroup, controls, camera } = ctx;

    // Clear all groups
    [terrainGroup, lineGroup, towerGroup, labelGroup].forEach((g) => {
      while (g.children.length) {
        const child = g.children[0];
        g.remove(child);
        if (child instanceof THREE.Mesh || child instanceof THREE.Points || child instanceof THREE.Line) {
          child.geometry?.dispose();
          if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
          else child.material?.dispose();
        } else if (child instanceof CSS2DObject) {
          child.element?.remove();
        }
      }
    });

    const { lon: originLon, lat: originLat } = origin;

    // === TERRAIN MESH ===
    if (heightmapData && heightmapData.heights.length > 0) {
      const { width: hmW, height: hmH, heights, minHeight, maxHeight } = heightmapData;
      const heightsFloat = toFloat32Heights(heights);
      const segW = Math.min(hmW - 1, TERRAIN_SEGMENTS);
      const segH = Math.min(hmH - 1, TERRAIN_SEGMENTS);
      const extentX = (heightmapData.east - originLon) * 111320 * SCALE;
      const extentZ = (heightmapData.north - originLat) * 111320 * SCALE;

      const geom = new THREE.PlaneGeometry(extentX, extentZ, segW, segH);
      geom.rotateX(-Math.PI / 2);
      const positions = geom.attributes.position.array;
      const colors = new Float32Array(positions.length);

      for (let i = 0; i <= segW; i++) {
        for (let j = 0; j <= segH; j++) {
          const idx = (j * (segW + 1) + i) * 3;
          const fracX = i / segW;
          const fracZ = j / segH;
          const lon = originLon + fracX * (heightmapData.east - originLon);
          const lat = originLat + fracZ * (heightmapData.north - originLat);
          const h = sampleHeight(heightsFloat, hmW, hmH,
            heightmapData.west, heightmapData.south, heightmapData.east, heightmapData.north,
            lon, lat);
          const yVal = h !== null ? h * exaggeration : 0;
          positions[idx + 1] = yVal;
          const color = terrainColorForHeight(h ?? 0, minHeight, maxHeight);
          colors[idx] = color.r;
          colors[idx + 1] = color.g;
          colors[idx + 2] = color.b;
        }
      }
      geom.setAttribute("color", new THREE.BufferAttribute(colors, 3));
      geom.computeVertexNormals();

      const mesh = new THREE.Mesh(geom, new THREE.MeshStandardMaterial({
        vertexColors: true, roughness: 0.6, metalness: 0.1,
      }));
      terrainGroup.add(mesh);
    } else {
      // Flat fallback
      const flatGeom = new THREE.PlaneGeometry(5000, 5000, 1, 1);
      flatGeom.rotateX(-Math.PI / 2);
      const flatMesh = new THREE.Mesh(flatGeom, new THREE.MeshStandardMaterial({
        color: 0x1e293b, roughness: 0.8,
      }));
      terrainGroup.add(flatMesh);
    }

    const allPositions: THREE.Vector3[] = [];

    // === LINE SEGMENTS ===
    routeSegments.forEach((segment) => {
      if (segment.points.length < 2) return;
      const pts = segment.points.map((tp) => {
        const local = geoToLocal(tp.longitude, tp.latitude, originLon, originLat, SCALE);
        let h = tp.altitudeM;
        if (heightmapData) {
          const sampled = sampleHeight(
            toFloat32Heights(heightmapData.heights), heightmapData.width, heightmapData.height,
            heightmapData.west, heightmapData.south, heightmapData.east, heightmapData.north,
            tp.longitude, tp.latitude,
          );
          if (sampled !== null) h = sampled;
        }
        const vec = new THREE.Vector3(local.x, h * exaggeration, local.z);
        allPositions.push(vec);
        return vec;
      });
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineBasicMaterial({ color: 0xf97316 }),
      );
      lineGroup.add(line);
    });

    // === TOWERS (Points) ===
    if (towerGeoPoints.length > 0) {
      const pointPositions: number[] = [];
      const pointColors: number[] = [];
      const lastIndex = towerGeoPoints.length - 1;

      towerGeoPoints.forEach((tp, index) => {
        const local = geoToLocal(tp.longitude, tp.latitude, originLon, originLat, SCALE);
        let h = tp.altitudeM;
        if (heightmapData) {
          const sampled = sampleHeight(
            toFloat32Heights(heightmapData.heights), heightmapData.width, heightmapData.height,
            heightmapData.west, heightmapData.south, heightmapData.east, heightmapData.north,
            tp.longitude, tp.latitude,
          );
          if (sampled !== null) h = sampled;
          else if (tp.longitude < heightmapData.west || tp.longitude > heightmapData.east ||
                   tp.latitude < heightmapData.south || tp.latitude > heightmapData.north) {
            h = 0; // outside bounds
          }
        }
        const yVal = h * exaggeration;
        pointPositions.push(local.x, yVal, local.z);
        allPositions.push(new THREE.Vector3(local.x, yVal, local.z));

        const risk = normalizeRiskLevel(tp.riskLevel);
        const colorStr = colorByRisk ? (RISK_COLOR_BY_LEVEL[risk] ?? DEFAULT_POINT_COLOR) : DEFAULT_POINT_COLOR;
        const c = new THREE.Color(colorStr);
        pointColors.push(c.r, c.g, c.b);
      });

      const pointGeom = new THREE.BufferGeometry();
      pointGeom.setAttribute("position", new THREE.Float32BufferAttribute(pointPositions, 3));
      pointGeom.setAttribute("color", new THREE.Float32BufferAttribute(pointColors, 3));
      const points = new THREE.Points(pointGeom, new THREE.PointsMaterial({
        size: 8, vertexColors: true, sizeAttenuation: true, opacity: 0.9, transparent: true,
      }));
      towerGroup.add(points);

      // === LABELS ===
      if (showLabels) {
        const shouldShowAllLabels = towerGeoPoints.length <= 40;
        towerGeoPoints.forEach((tp, index) => {
          const isEdgePoint = index === 0 || index === lastIndex;
          if (!(shouldShowAllLabels || isEdgePoint)) return;

          const local = geoToLocal(tp.longitude, tp.latitude, originLon, originLat, SCALE);
          let h = tp.altitudeM;
          if (heightmapData) {
            const sampled = sampleHeight(
              toFloat32Heights(heightmapData.heights), heightmapData.width, heightmapData.height,
              heightmapData.west, heightmapData.south, heightmapData.east, heightmapData.north,
              tp.longitude, tp.latitude,
            );
            if (sampled !== null) h = sampled;
          }

          const labelText = index === 0 ? `起点 ${tp.towerNo}`
            : index === lastIndex ? `终点 ${tp.towerNo}`
            : tp.towerNo;
          const div = document.createElement("div");
          div.textContent = labelText;
          div.style.color = "#fff";
          div.style.fontSize = "12px";
          div.style.fontWeight = "600";
          div.style.fontFamily = "sans-serif";
          div.style.textShadow = "0 0 4px rgba(0,0,0,0.8)";
          div.style.padding = "2px 6px";
          div.style.borderRadius = "3px";
          div.style.background = "rgba(0,0,0,0.5)";
          div.style.whiteSpace = "nowrap";

          const label = new CSS2DObject(div);
          label.position.set(local.x, h * exaggeration + 8, local.z);
          labelGroup.add(label);
        });
      }
    }

    // === FOCUS CAMERA ===
    if (allPositions.length > 0) {
      const box = new THREE.Box3().setFromPoints(allPositions);
      const center = new THREE.Vector3();
      box.getCenter(center);
      const size = new THREE.Vector3();
      box.getSize(size);
      const radius = Math.max(size.x, size.z) / 2;
      controls.target.copy(center);
      const camDist = Math.max(radius * 2.5, MIN_CAMERA_RANGE);
      camera.position.set(center.x, camDist, center.z);
      controls.update();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heightmapData, exaggeration, ready, towerGeoPoints, routeSegments, colorByRisk, showLabels, origin]);

  return (
    <div className="space-y-3">
      {terrainDataset ? (
        <Typography.Text type="secondary">
          地形底图：{terrainDataset.name}，状态 {terrainDataset.terrain_status}
          {terrainDataset.terrain_status === "ready" ? `，夸张 ${exaggeration.toFixed(1)}x` : "，未启用真实地形"}
          {towersOutsideTerrainBounds > 0 ? `，超出范围杆塔 ${towersOutsideTerrainBounds} 个` : ""}
        </Typography.Text>
      ) : null}
      {terrainDataset && towersOutsideTerrainBounds > 0 ? (
        <Alert type="warning" showIcon message={`有 ${towersOutsideTerrainBounds} 个杆塔超出所选 DEM 覆盖范围`} />
      ) : null}
      {terrainError ? (
        <Alert type="warning" showIcon message={`地形加载失败，已回退到平面模式：${terrainError}`} />
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Checkbox checked={colorByRisk} onChange={(e) => setColorByRisk(e.target.checked)}>按风险着色</Checkbox>
        <Checkbox checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)}>显示塔号</Checkbox>
      </div>
      {initError ? <Alert type="error" showIcon message="走向图加载失败" description={initError} /> : null}

      <div className="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-900/90" style={{ height }}>
        <div ref={containerRef} className="h-full w-full" />
        <div className="absolute right-3 top-3 z-10 flex flex-col gap-2 rounded-md border border-slate-700/80 bg-slate-950/70 p-1.5 shadow-lg backdrop-blur-sm">
          <Button size="small" shape="circle" icon={<PlusOutlined />} aria-label="放大" title="放大" disabled={controlsDisabled} />
          <Button size="small" shape="circle" icon={<MinusOutlined />} aria-label="缩小" title="缩小" disabled={controlsDisabled} />
          <Button size="small" shape="circle" icon={<AimOutlined />} aria-label="居中重置" title="居中重置" disabled={controlsDisabled} />
        </div>
        <div className="pointer-events-none absolute left-3 top-3 rounded bg-slate-950/75 px-2 py-1 text-xs text-slate-200">
          线路走向专题视图
        </div>
        {(loading || heightmapLoading || !ready) && !initError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/25">
            <Spin size="large" />
          </div>
        ) : null}
      </div>
      {pointerInfo ? <div className="text-xs text-slate-500">{pointerInfo}</div> : null}

      {towerGeoPoints.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选条件下没有可用经纬度数据，无法绘制线路走向。" />
      ) : null}
    </div>
  );
}
