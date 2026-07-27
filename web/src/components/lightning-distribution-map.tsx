"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { withBasePath } from "@/lib/base-path";
import type {
  LightningDistributionGridCell,
  LightningDistributionScatterPoint,
} from "@/types/auth";

type LightningDistributionMapProps = {
  points: LightningDistributionScatterPoint[];
  grids: LightningDistributionGridCell[];
  loading?: boolean;
};

type CesiumNamespace = typeof import("cesium");

function hasValidCoord(lon: number, lat: number): boolean {
  if (Number.isNaN(lon) || Number.isNaN(lat)) return false;
  return lon >= -180 && lon <= 180 && lat >= -90 && lat <= 90;
}

function pointColorByAbsCurrent(absCurrent: number | null | undefined): string {
  if (absCurrent === null || absCurrent === undefined) return "#93c5fd";
  if (absCurrent >= 100) return "#ef4444";
  if (absCurrent >= 50) return "#f97316";
  if (absCurrent >= 20) return "#f59e0b";
  return "#3b82f6";
}

function pointSizeByAbsCurrent(absCurrent: number | null | undefined): number {
  if (absCurrent === null || absCurrent === undefined) return 6;
  if (absCurrent >= 200) return 13;
  if (absCurrent >= 100) return 11;
  if (absCurrent >= 50) return 9;
  if (absCurrent >= 20) return 8;
  return 6;
}

export function LightningDistributionMap({
  points,
  grids,
  loading = false,
}: LightningDistributionMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<import("cesium").Viewer | null>(null);
  const cesiumRef = useRef<CesiumNamespace | null>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);

  const safePoints = useMemo(
    () => points.filter((item) => hasValidCoord(item.longitude, item.latitude)),
    [points],
  );
  const safeGrids = useMemo(
    () =>
      grids.filter(
        (item) =>
          hasValidCoord(item.min_lon, item.min_lat)
          && hasValidCoord(item.max_lon, item.max_lat)
          && item.max_lon > item.min_lon
          && item.max_lat > item.min_lat,
      ),
    [grids],
  );

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;

    const init = async () => {
      if (typeof window === "undefined" || !containerRef.current) {
        return;
      }
      try {
        const Cesium = await import("cesium");
        if (disposed || !containerRef.current) return;

        (window as typeof window & { CESIUM_BASE_URL?: string }).CESIUM_BASE_URL = withBasePath("/cesium");
        Cesium.Ion.defaultAccessToken = "";

        const viewer = new Cesium.Viewer(containerRef.current, {
          animation: false,
          timeline: false,
          sceneModePicker: false,
          geocoder: false,
          homeButton: false,
          baseLayerPicker: true,
          fullscreenButton: false,
          navigationHelpButton: false,
          infoBox: true,
          selectionIndicator: true,
        });
        viewer.scene.globe.depthTestAgainstTerrain = false;
        viewerRef.current = viewer;
        cesiumRef.current = Cesium;
        viewer.resize();

        // Ensure Cesium canvas fills the container
        const canvas = viewer.scene.canvas as HTMLCanvasElement;
        if (canvas) {
          canvas.style.position = "absolute";
          canvas.style.top = "0";
          canvas.style.left = "0";
          canvas.style.width = "100%";
          canvas.style.height = "100%";
        }

        resizeObserver = new ResizeObserver(() => {
          if (viewerRef.current && !viewerRef.current.isDestroyed()) {
            viewerRef.current.resize();
          }
        });
        resizeObserver.observe(containerRef.current);

        setReady(true);
        setError("");
      } catch (candidate) {
        const message = candidate instanceof Error ? candidate.message : "地图初始化失败";
        setError(message);
      }
    };

    void init();
    return () => {
      disposed = true;
      if (resizeObserver) {
        resizeObserver.disconnect();
      }
      setReady(false);
      if (viewerRef.current && !viewerRef.current.isDestroyed?.()) {
        viewerRef.current.destroy();
      }
      viewerRef.current = null;
      cesiumRef.current = null;
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !ready) return;
    const Cesium = cesiumRef.current;
    if (!Cesium) return;

    viewer.entities.removeAll();

    const maxCount = safeGrids.reduce((max, item) => Math.max(max, item.strike_count), 0);
    safeGrids.forEach((cell) => {
      const ratio = maxCount > 0 ? cell.strike_count / maxCount : 0;
      const alpha = Math.max(0.08, Math.min(0.45, ratio * 0.45));
      viewer.entities.add({
        id: `grid-${cell.grid_x}-${cell.grid_y}`,
        rectangle: {
          coordinates: Cesium.Rectangle.fromDegrees(
            cell.min_lon,
            cell.min_lat,
            cell.max_lon,
            cell.max_lat,
          ),
          material: Cesium.Color.fromCssColorString("#ef4444").withAlpha(alpha),
          outline: false,
        },
      });
    });

    const positions: import("cesium").Cartesian3[] = [];
    safePoints.forEach((point) => {
      const absCurrent = point.abs_current_ka ?? (point.current_ka ? Math.abs(point.current_ka) : null);
      const color = Cesium.Color.fromCssColorString(pointColorByAbsCurrent(absCurrent));
      const size = pointSizeByAbsCurrent(absCurrent);
      const position = Cesium.Cartesian3.fromDegrees(point.longitude, point.latitude, 0);
      positions.push(position);

      viewer.entities.add({
        id: `lightning-${point.id}`,
        position,
        point: {
          pixelSize: size,
          color,
          outlineColor: Cesium.Color.WHITE.withAlpha(0.85),
          outlineWidth: 1.2,
        },
        description: `
          <div style="line-height:1.7;">
            <div><strong>事件：</strong>${point.event_id}</div>
            <div><strong>坐标：</strong>${point.longitude.toFixed(6)}, ${point.latitude.toFixed(6)}</div>
            <div><strong>电流(kA)：</strong>${point.current_ka ?? "-"}</div>
            <div><strong>绝对值(kA)：</strong>${point.abs_current_ka ?? "-"}</div>
            <div><strong>区域：</strong>${point.location_tag ?? "-"}</div>
            <div><strong>城市：</strong>${point.city ?? "-"}</div>
          </div>
        `,
      });
    });

    if (positions.length > 0) {
      const boundingSphere = Cesium.BoundingSphere.fromPoints(positions);
      void viewer.camera.flyToBoundingSphere(boundingSphere, {
        duration: 0.8,
        offset: new Cesium.HeadingPitchRange(0, -0.6, boundingSphere.radius * 2.0),
      });
    }
  }, [safePoints, safeGrids, ready]);

  // After ready, force resize on next animation frame to sync canvas with
  // the final container layout.
  useEffect(() => {
    if (!ready) {
      return;
    }
    const raf = requestAnimationFrame(() => {
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.resize();
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [ready]);

  if (error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-600">
        地图加载失败：{error}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-slate-500">
        红色网格表示雷击密度更高；散点颜色表示电流幅值（红色高、蓝色低）。
      </div>
      <div ref={containerRef} className="relative h-[520px] w-full overflow-hidden rounded-md border border-slate-200 bg-slate-100" />
      {loading && <div className="text-xs text-slate-500">地图数据加载中...</div>}
    </div>
  );
}
