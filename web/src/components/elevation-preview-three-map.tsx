"use client";

import { Alert, Empty, Spin } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { getApiBaseUrl } from "@/lib/api";
import { geoToLocal } from "@/lib/geo-coords";
import { sampleHeight, toFloat32Heights } from "@/lib/terrain-utils";
import { getElevationTerrainRenderState } from "@/lib/elevation-terrain";
import type { ElevationDatasetPreviewPoint, ElevationDatasetSummary } from "@/types/auth";
import type { HeightmapData } from "./power-line-three-map";

type ElevationPreviewHeightGrid = {
  rows: number;
  cols: number;
  west: number;
  south: number;
  east: number;
  north: number;
  heights: (number | null)[];
};

type ElevationPreviewThreeMapProps = {
  dataset?: Pick<
    ElevationDatasetSummary,
    "id" | "name" | "terrain_status" | "terrain_url_template" | "terrain_bounds" | "terrain_metadata"
  > | null;
  accessToken?: string | null;
  points: ElevationDatasetPreviewPoint[];
  heightGrid?: ElevationPreviewHeightGrid | null;
  loading?: boolean;
  height?: number | string;
};

const SCALE = 0.001;
const TERRAIN_SEGMENTS = 128;

function pointColorByAltitude(altitude: number, minAltitude: number, maxAltitude: number): string {
  if (maxAltitude <= minAltitude) return "#38bdf8";
  const ratio = (altitude - minAltitude) / (maxAltitude - minAltitude);
  if (ratio >= 0.85) return "#dc2626";
  if (ratio >= 0.65) return "#f97316";
  if (ratio >= 0.45) return "#eab308";
  if (ratio >= 0.25) return "#84cc16";
  return "#38bdf8";
}

function pointSizeByAltitude(altitude: number, minAltitude: number, maxAltitude: number): number {
  if (maxAltitude <= minAltitude) return 6;
  const ratio = (altitude - minAltitude) / (maxAltitude - minAltitude);
  if (ratio >= 0.85) return 11;
  if (ratio >= 0.65) return 9;
  if (ratio >= 0.45) return 8;
  if (ratio >= 0.25) return 7;
  return 6;
}

function terrainColorByAltitude(altitude: number, minA: number, maxA: number): THREE.Color {
  if (maxA <= minA) return new THREE.Color(0x38bdf8);
  const ratio = (altitude - minA) / (maxA - minA);
  if (ratio >= 0.85) return new THREE.Color(0xdc2626);
  if (ratio >= 0.65) return new THREE.Color(0xf97316);
  if (ratio >= 0.45) return new THREE.Color(0xeab308);
  if (ratio >= 0.25) return new THREE.Color(0x84cc16);
  return new THREE.Color(0x38bdf8);
}

export function ElevationPreviewThreeMap({
  dataset = null,
  accessToken = null,
  points,
  heightGrid = null,
  loading = false,
  height = 520,
}: ElevationPreviewThreeMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sceneRef = useRef<{
    scene: THREE.Scene; camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer; controls: OrbitControls;
    terrainGroup: THREE.Group; pointGroup: THREE.Group;
  } | null>(null);

  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [terrainError, setTerrainError] = useState("");
  const [pointerInfo, setPointerInfo] = useState("");
  const [heightmapData, setHeightmapData] = useState<HeightmapData | null>(null);
  const [heightmapLoading, setHeightmapLoading] = useState(false);

  const terrainRenderState = useMemo(
    () => (dataset ? getElevationTerrainRenderState(dataset) : "fallback"),
    [dataset],
  );

  const safePoints = useMemo(
    () =>
      points.filter(
        (item) =>
          Number.isFinite(item.longitude) &&
          Number.isFinite(item.latitude) &&
          Number.isFinite(item.altitude_m) &&
          item.longitude >= -180 &&
          item.longitude <= 180 &&
          item.latitude >= -90 &&
          item.latitude <= 90,
      ),
    [points],
  );

  const altitudeRange = useMemo(() => {
    if (safePoints.length === 0) return { min: 0, max: 0 };
    let min = safePoints[0].altitude_m;
    let max = safePoints[0].altitude_m;
    for (const p of safePoints) {
      if (p.altitude_m < min) min = p.altitude_m;
      if (p.altitude_m > max) max = p.altitude_m;
    }
    return { min, max };
  }, [safePoints]);

  // --- Init Three.js Scene ---
  useEffect(() => {
    const container = containerRef.current;
    if (!container || sceneRef.current) return;

    const w = container.clientWidth || 800;
    const h_val = container.clientHeight || 400;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);

    const camera = new THREE.PerspectiveCamera(45, w / h_val, 0.1, 20000);
    camera.position.set(0, 300, 500);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(w, h_val);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 10;
    controls.maxDistance = 20000;
    controls.target.set(0, 0, 0);

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.5);
    scene.add(ambientLight);
    const dirLight = new THREE.DirectionalLight(0xffffff, 1.2);
    dirLight.position.set(100, 200, 50);
    scene.add(dirLight);
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.3);
    fillLight.position.set(-100, 50, -100);
    scene.add(fillLight);

    const terrainGroup = new THREE.Group();
    terrainGroup.name = "terrain";
    scene.add(terrainGroup);
    const pointGroup = new THREE.Group();
    pointGroup.name = "points";
    scene.add(pointGroup);

    sceneRef.current = { scene, camera, renderer, controls, terrainGroup, pointGroup };

    let animId: number;
    function animate() {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    const onResize = () => {
      const cw = container.clientWidth;
      const ch = container.clientHeight;
      if (cw === 0 || ch === 0) return;
      camera.aspect = cw / ch;
      camera.updateProjectionMatrix();
      renderer.setSize(cw, ch);
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(container);

    setReady(true);
    setError("");

    return () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
      controls?.dispose?.();
      renderer?.dispose?.();
      if (container.contains(renderer.domElement)) container.removeChild(renderer.domElement);
      sceneRef.current = null;
    };
  }, []);

  // --- Fetch Heightmap ---
  useEffect(() => {
    let cancelled = false;
    async function loadHeightmap() {
      if (terrainRenderState !== "ready" || !dataset?.id) {
        setHeightmapData(null);
        return;
      }
      setHeightmapLoading(true);
      setTerrainError("");
      try {
        const baseUrl = getApiBaseUrl();
        const url = `${baseUrl}/api/v1/elevation/datasets/${dataset.id}/heightmap?res=129`;
        const headers: Record<string, string> = {};
        if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;
        const res = await fetch(url, { headers });
        if (cancelled) return;
        if (!res.ok) throw new Error(`heightmap 请求失败 (${res.status})`);
        const data: HeightmapData = await res.json();
        if (cancelled) return;
        setHeightmapData(data);
      } catch (e) {
        if (!cancelled) {
          setTerrainError(e instanceof Error ? e.message : "heightmap 加载失败");
          setHeightmapData(null);
        }
      } finally {
        if (!cancelled) setHeightmapLoading(false);
      }
    }
    void loadHeightmap();
    return () => { cancelled = true; };
  }, [accessToken, dataset, terrainRenderState]);

  // --- Origin ---
  const origin = useMemo(() => {
    if (heightmapData) return { lon: heightmapData.west, lat: heightmapData.south };
    const bounds = dataset?.terrain_bounds;
    if (bounds) return { lon: bounds.west, lat: bounds.south };
    if (safePoints.length > 0) {
      return {
        lon: Math.floor(safePoints[0].longitude),
        lat: Math.floor(safePoints[0].latitude),
      };
    }
    if (heightGrid) return { lon: heightGrid.west, lat: heightGrid.south };
    return { lon: 0, lat: 0 };
  }, [heightmapData, dataset, safePoints, heightGrid]);

  // --- Render scene ---
  useEffect(() => {
    const ctx = sceneRef.current;
    if (!ctx || !ready) return;
    const { terrainGroup, pointGroup, controls, camera } = ctx;
    const { lon: originLon, lat: originLat } = origin;

    // Clear groups
    [terrainGroup, pointGroup].forEach((g) => {
      while (g.children.length) {
        const child = g.children[0];
        g.remove(child);
        if (child instanceof THREE.Mesh || child instanceof THREE.Points || child instanceof THREE.Line) {
          child.geometry?.dispose();
          if (Array.isArray(child.material)) child.material.forEach((m) => m.dispose());
          else child.material?.dispose();
        }
      }
    });

    const allPositions: THREE.Vector3[] = [];

    // === Terrain Mesh ===
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
          const yVal = h !== null ? h * 5 : 0; // fixed 5x exaggeration for preview
          positions[idx + 1] = yVal;
          const color = terrainColorByAltitude(h ?? 0, minHeight, maxHeight);
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
    } else if (heightGrid) {
      // Build terrain mesh from heightGrid
      const { rows, cols, west, south, east, north, heights } = heightGrid;
      const segW = Math.min(cols - 1, TERRAIN_SEGMENTS);
      const segH = Math.min(rows - 1, TERRAIN_SEGMENTS);
      const extentX = (east - originLon) * 111320 * SCALE;
      const extentZ = (north - originLat) * 111320 * SCALE;

      const geom = new THREE.PlaneGeometry(extentX, extentZ, segW, segH);
      geom.rotateX(-Math.PI / 2);
      const positions = geom.attributes.position.array;
      let minH = Infinity, maxH = -Infinity;
      const validHeights: number[] = [];

      for (let i = 0; i <= segW; i++) {
        for (let j = 0; j <= segH; j++) {
          const idx = (j * (segW + 1) + i) * 3;
          const fracX = i / segW;
          const fracZ = j / segH;
          const lon = originLon + fracX * (east - originLon);
          const lat = originLat + fracZ * (north - originLat);
          // Sample from heightGrid
          const fx = ((lon - west) / (east - west)) * (cols - 1);
          const fy = ((lat - south) / (north - south)) * (rows - 1);
          const x0 = Math.floor(fx), y0 = Math.floor(fy);
          const x1 = Math.min(x0 + 1, cols - 1), y1 = Math.min(y0 + 1, rows - 1);
          const dx = fx - x0, dy = fy - y0;
          const h00 = heights[y0 * cols + x0];
          const h10 = heights[y0 * cols + x1];
          const h01 = heights[y1 * cols + x0];
          const h11 = heights[y1 * cols + x1];
          const allVal = [h00, h10, h01, h11].filter(v => v !== null && Number.isFinite(v)) as number[];
          const hVal = allVal.length > 0 ? allVal.reduce((a, b) => a + b, 0) / allVal.length : 0;
          const yVal = hVal * 5;
          positions[idx + 1] = yVal;
          validHeights.push(hVal);
          if (hVal < minH) minH = hVal;
          if (hVal > maxH) maxH = hVal;
        }
      }
      if (minH === Infinity) { minH = 0; maxH = 0; }

      // Vertex colors
      const colorsArr = new Float32Array(positions.length);
      for (let i = 0; i < validHeights.length; i++) {
        const color = terrainColorByAltitude(validHeights[i], minH, maxH);
        colorsArr[i * 3] = color.r;
        colorsArr[i * 3 + 1] = color.g;
        colorsArr[i * 3 + 2] = color.b;
      }
      geom.setAttribute("color", new THREE.BufferAttribute(colorsArr, 3));
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

    // === Dataset Boundary Box ===
    const bounds = dataset?.terrain_bounds || heightGrid;
    if (bounds) {
      const w = bounds.west;
      const s = bounds.south;
      const e = bounds.east;
      const n = bounds.north;
      const corners = [
        geoToLocal(w, s, originLon, originLat, SCALE),
        geoToLocal(e, s, originLon, originLat, SCALE),
        geoToLocal(e, n, originLon, originLat, SCALE),
        geoToLocal(w, n, originLon, originLat, SCALE),
        geoToLocal(w, s, originLon, originLat, SCALE),
      ];
      const pts = corners.map((c) => new THREE.Vector3(c.x, 0, c.z));
      const edgeGeom = new THREE.BufferGeometry().setFromPoints(pts);
      const edgeLine = new THREE.Line(edgeGeom, new THREE.LineBasicMaterial({ color: 0xf8fafc }));
      terrainGroup.add(edgeLine);

      // Corner markers
      corners.slice(0, 4).forEach((c) => {
        const dotGeom = new THREE.BufferGeometry();
        dotGeom.setAttribute("position", new THREE.Float32BufferAttribute([c.x, 0, c.z], 3));
        const dotMat = new THREE.PointsMaterial({ color: 0xffffff, size: 6, sizeAttenuation: true });
        const dot = new THREE.Points(dotGeom, dotMat);
        terrainGroup.add(dot);
      });

      allPositions.push(...pts);
    }

    // === Points / Sampling Points ===
    if (safePoints.length > 0) {
      const ptPositions: number[] = [];
      const ptColors: number[] = [];

      safePoints.forEach((pt) => {
        const local = geoToLocal(pt.longitude, pt.latitude, originLon, originLat, SCALE);
        let h = pt.altitude_m;
        if (heightmapData) {
          const sampled = sampleHeight(
            toFloat32Heights(heightmapData.heights), heightmapData.width, heightmapData.height,
            heightmapData.west, heightmapData.south, heightmapData.east, heightmapData.north,
            pt.longitude, pt.latitude,
          );
          if (sampled !== null) h = sampled;
        }
        const yVal = h * 5;
        ptPositions.push(local.x, yVal, local.z);
        allPositions.push(new THREE.Vector3(local.x, yVal, local.z));
        const colorStr = pointColorByAltitude(pt.altitude_m, altitudeRange.min, altitudeRange.max);
        const c = new THREE.Color(colorStr);
        ptColors.push(c.r, c.g, c.b);
      });

      const ptGeom = new THREE.BufferGeometry();
      ptGeom.setAttribute("position", new THREE.Float32BufferAttribute(ptPositions, 3));
      ptGeom.setAttribute("color", new THREE.Float32BufferAttribute(ptColors, 3));
      const pts = new THREE.Points(ptGeom, new THREE.PointsMaterial({
        size: 7, vertexColors: true, sizeAttenuation: true, opacity: 0.9, transparent: true,
      }));
      pointGroup.add(pts);
    }

    // === Focus Camera ===
    if (allPositions.length > 0) {
      const box = new THREE.Box3().setFromPoints(allPositions);
      const center = new THREE.Vector3();
      box.getCenter(center);
      const size = new THREE.Vector3();
      box.getSize(size);
      const radius = Math.max(size.x, size.z, size.y) / 2;
      controls.target.copy(center);
      camera.position.set(center.x, center.y + radius * 0.8, center.z + radius * 2);
      controls.update();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heightmapData, ready, safePoints, heightGrid, dataset, altitudeRange, origin]);

  if (error) {
    return <Alert type="error" showIcon message={`预览地图加载失败：${error}`} />;
  }

  if (safePoints.length === 0 && !loading && !heightmapData && !heightGrid) {
    return <Empty description="暂无可展示的高程预览点。" />;
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-slate-500">
        Three.js 地形预览模式（加载真实高程数据）
      </div>
      {terrainError ? (
        <Alert type="warning" showIcon message={`地形加载失败：${terrainError}`} />
      ) : null}
      {terrainRenderState !== "ready" ? (
        <Alert
          type={terrainRenderState === "failed" ? "warning" : "info"}
          showIcon
          message={`地形瓦片状态：${terrainRenderState}，暂以平面显示参考点。`}
        />
      ) : null}
      <div
        ref={containerRef}
        className="w-full overflow-hidden rounded-md border border-slate-200 bg-slate-100"
        style={{ height }}
      />
      {pointerInfo ? <div className="text-xs text-slate-500">{pointerInfo}</div> : null}
      {(loading || heightmapLoading) && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Spin size="small" />
          预览数据加载中...
        </div>
      )}
    </div>
  );
}
