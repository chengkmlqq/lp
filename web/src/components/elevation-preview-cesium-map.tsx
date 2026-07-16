"use client";

import { Alert, Empty, Spin } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";

import { getApiBaseUrl } from "@/lib/api";
import { withBasePath } from "@/lib/base-path";
import { reloadOnceOnChunkError } from "@/lib/chunk-error";
import {
  getElevationTerrainLayerUrl,
  getElevationTerrainRenderState,
  shouldUseElevationTerrainTiles,
} from "@/lib/elevation-terrain";
import type { ElevationDatasetPreviewPoint, ElevationDatasetSummary } from "@/types/auth";
import type { GeometryAttributes } from "cesium";

type ElevationPreviewHeightGrid = {
  rows: number;
  cols: number;
  west: number;
  south: number;
  east: number;
  north: number;
  heights: (number | null)[];
};

type ElevationPreviewCesiumMapProps = {
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

type CesiumNamespace = typeof import("cesium");

declare global {
  interface Window {
    CESIUM_BASE_URL?: string;
  }
}

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

function formatErrorMessage(candidate: unknown): string {
  if (candidate instanceof Error && candidate.message) return candidate.message;
  return "Cesium 初始化失败，请检查静态资源是否已同步。";
}

export function ElevationPreviewCesiumMap({
  dataset = null,
  accessToken = null,
  points,
  heightGrid = null,
  loading = false,
  height = 520,
}: ElevationPreviewCesiumMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<import("cesium").Viewer | null>(null);
  const cesiumRef = useRef<CesiumNamespace | null>(null);
  const meshPrimitiveRef = useRef<import("cesium").Primitive | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [terrainError, setTerrainError] = useState("");
  const [pointerInfo, setPointerInfo] = useState("");

  const terrainRenderState = useMemo(
    () => (dataset ? getElevationTerrainRenderState(dataset) : "fallback"),
    [dataset],
  );
  const shouldLoadTerrain = useMemo(
    () => shouldUseElevationTerrainTiles(terrainRenderState),
    [terrainRenderState],
  );
  const previewHint = useMemo(() => {
    return "地形模式加载真实三维瓦片，并保留少量参考点用于定位。";
  }, []);
  const terrainErrorMessage = useMemo(() => {
    if (!terrainError) {
      return "";
    }
    return `地形瓦片加载失败：${terrainError}`;
  }, [terrainError]);

  const safePoints = useMemo(
    () =>
      points.filter(
        (item) =>
          Number.isFinite(item.longitude)
          && Number.isFinite(item.latitude)
          && Number.isFinite(item.altitude_m)
          && item.longitude >= -180
          && item.longitude <= 180
          && item.latitude >= -90
          && item.latitude <= 90,
      ),
    [points],
  );
  const altitudeRange = useMemo(() => {
    if (safePoints.length === 0) {
      return { min: 0, max: 0 };
    }
    let min = safePoints[0].altitude_m;
    let max = safePoints[0].altitude_m;
    for (const point of safePoints) {
      if (point.altitude_m < min) min = point.altitude_m;
      if (point.altitude_m > max) max = point.altitude_m;
    }
    return { min, max };
  }, [safePoints]);

  useEffect(() => {
    let cancelled = false;
    async function initViewer() {
      if (!containerRef.current || viewerRef.current) return;
      try {
        window.CESIUM_BASE_URL = withBasePath("/cesium");
        const Cesium = await import("cesium");
        if (cancelled || !containerRef.current) return;

        const viewer = new Cesium.Viewer(containerRef.current, {
          animation: false,
          baseLayer: false,
          baseLayerPicker: false,
          fullscreenButton: false,
          geocoder: false,
          homeButton: false,
          infoBox: true,
          navigationHelpButton: false,
          sceneModePicker: false,
          selectionIndicator: false,
          skyBox: false,
          skyAtmosphere: false,
          timeline: false,
          shouldAnimate: false,
        });
        viewer.scene.globe.depthTestAgainstTerrain = false;
        viewer.scene.globe.showGroundAtmosphere = false;
        viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#0f172a");
        // Enable lighting to enhance terrain visibility with shadows
        viewer.scene.globe.enableLighting = true;
        // Increase lighting intensity for better terrain shadow contrast
        viewer.scene.light = new Cesium.DirectionalLight({
          direction: new Cesium.Cartesian3(0.2, 0.5, -0.8),
          intensity: 2.0,
        });
        viewer.scene.backgroundColor = Cesium.Color.fromCssColorString("#020617");
        viewer.scene.screenSpaceCameraController.enableCollisionDetection = true;
        const creditContainer = viewer.cesiumWidget.creditContainer as HTMLElement | null;
        if (creditContainer) {
          creditContainer.style.display = "none";
        }
        viewer.screenSpaceEventHandler.setInputAction((movement: { endPosition?: import("cesium").Cartesian2 }) => {
          if (!movement.endPosition) {
            setPointerInfo("");
            return;
          }
          const ray = viewer.camera.getPickRay(movement.endPosition);
          const cartesian = ray
            ? viewer.scene.globe.pick(ray, viewer.scene)
            : viewer.camera.pickEllipsoid(movement.endPosition, viewer.scene.globe.ellipsoid);
          if (!cartesian) {
            setPointerInfo("");
            return;
          }
          const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
          const lon = Cesium.Math.toDegrees(cartographic.longitude);
          const lat = Cesium.Math.toDegrees(cartographic.latitude);
          const height = viewer.scene.globe.getHeight(cartographic) ?? cartographic.height ?? 0;
          const datasetName = dataset?.name ? ` | ${dataset.name}` : "";
          setPointerInfo(`${lon.toFixed(5)}, ${lat.toFixed(5)} | ${height.toFixed(2)} m${datasetName}`);
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

        viewerRef.current = viewer;
        cesiumRef.current = Cesium;
        setReady(true);
        setError("");
      } catch (candidate) {
        if (reloadOnceOnChunkError(candidate)) {
          return;
        }
        setError(formatErrorMessage(candidate));
      }
    }

    void initViewer();
    return () => {
      cancelled = true;
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy();
      }
      viewerRef.current = null;
      cesiumRef.current = null;
      setReady(false);
      setPointerInfo("");
    };
  }, [dataset?.name]);

  useEffect(() => {
    let cancelled = false;
    let addedImageryLayer: import("cesium").ImageryLayer | null = null;

    async function updateTerrain() {
      const viewer = viewerRef.current;
      const Cesium = cesiumRef.current;
      if (!viewer || !Cesium || !ready) {
        return;
      }

      setTerrainError("");
      // Significantly increase vertical exaggeration for SRTM data (90m resolution)
      // SRTM data often has subtle elevation changes that need strong exaggeration
      viewer.scene.verticalExaggeration = 5.0;
      viewer.scene.verticalExaggerationRelativeHeight = 0.0;

      // Remove all existing imagery layers first
      viewer.imageryLayers.removeAll();

      if (!shouldLoadTerrain || !dataset) {
        viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
        viewer.scene.globe.depthTestAgainstTerrain = false;
        return;
      }

      try {
        const layerBaseUrl = `${getApiBaseUrl()}${getElevationTerrainLayerUrl(dataset)}`;
        const resource = new Cesium.Resource({
          url: layerBaseUrl,
          headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
        });
        const terrainProvider = await Cesium.CesiumTerrainProvider.fromUrl(resource, {
          requestMetadata: true,
          requestWaterMask: false,
          requestVertexNormals: false,
        });
        if (cancelled) {
          return;
        }
        viewer.terrainProvider = terrainProvider;
        viewer.scene.globe.depthTestAgainstTerrain = false;

        // Add a solid color imagery layer to make terrain geometry visible
        // Without imagery, terrain is just geometry without surface color
        // Use a brighter beige/tan color to clearly show terrain relief
        // Create a canvas with a solid color instead of using base64 PNG
        const canvas = document.createElement('canvas');
        canvas.width = 1;
        canvas.height = 1;
        const ctx = canvas.getContext('2d');
        if (ctx) {
          // Use a light beige/tan color (#d4c4a8) for better terrain visibility
          ctx.fillStyle = '#d4c4a8';
          ctx.fillRect(0, 0, 1, 1);
        }
        const imageryProvider = new Cesium.SingleTileImageryProvider({
          url: canvas.toDataURL(),
          rectangle: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90),
          tileWidth: 256,
          tileHeight: 256,
        });
        addedImageryLayer = viewer.imageryLayers.addImageryProvider(imageryProvider);

        // Ensure the imagery layer is fully opaque
        if (addedImageryLayer) {
          addedImageryLayer.alpha = 1.0;
          addedImageryLayer.brightness = 1.0;
        }
      } catch (candidate) {
        if (!cancelled) {
          viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
          viewer.scene.globe.depthTestAgainstTerrain = false;
          setTerrainError(formatErrorMessage(candidate));
        }
      }
    }

    void updateTerrain();
    return () => {
      cancelled = true;
      const viewer = viewerRef.current;
      if (viewer && addedImageryLayer && !viewer.isDestroyed()) {
        viewer.imageryLayers.remove(addedImageryLayer, false);
      }
    };
  }, [accessToken, dataset, ready, shouldLoadTerrain]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = cesiumRef.current;
    if (!viewer || !Cesium || !ready) {
      return;
    }
    viewer.entities.removeAll();
    if (safePoints.length === 0) {
      if (!dataset?.terrain_bounds) {
        return;
      }
    }

    const positions: import("cesium").Cartesian3[] = [];

    // When heightGrid is available, render terrain mesh instead of point cloud
    // Only render a few reference points for orientation, not the full point cloud
    if (heightGrid) {
      // Add corner markers for visual reference
      const gridCorners = [
        [heightGrid.west, heightGrid.south],
        [heightGrid.east, heightGrid.south],
        [heightGrid.west, heightGrid.north],
        [heightGrid.east, heightGrid.north],
      ];
      for (let i = 0; i < gridCorners.length; i++) {
        const [lon, lat] = gridCorners[i];
        const pos = Cesium.Cartesian3.fromDegrees(lon, lat, 0);
        positions.push(pos);
        viewer.entities.add({
          id: `height-grid-corner-${i}`,
          position: pos,
          point: {
            pixelSize: 3,
            color: Cesium.Color.WHITE.withAlpha(0.4),
          },
        });
      }
    } else {
      // Fallback: render individual point cloud entities
      for (let index = 0; index < safePoints.length; index += 1) {
        const point = safePoints[index];
        const position = Cesium.Cartesian3.fromDegrees(point.longitude, point.latitude, point.altitude_m);
        positions.push(position);
        const color = pointColorByAltitude(point.altitude_m, altitudeRange.min, altitudeRange.max);
        const size = pointSizeByAltitude(point.altitude_m, altitudeRange.min, altitudeRange.max);

        viewer.entities.add({
          id: `elevation-point-${index}`,
          position,
          point: {
            pixelSize: size,
            color: Cesium.Color.fromCssColorString(color),
            outlineColor: Cesium.Color.WHITE.withAlpha(0.9),
            outlineWidth: 1.0,
          },
          description: `
            <div style="line-height:1.7;">
              <div><strong>经度：</strong>${point.longitude.toFixed(6)}</div>
              <div><strong>纬度：</strong>${point.latitude.toFixed(6)}</div>
              <div><strong>高程(m)：</strong>${point.altitude_m.toFixed(3)}</div>
            </div>
          `,
        });
      }
    }

    const terrainBounds = dataset?.terrain_bounds;
    if (terrainBounds) {
      const centerLon = (terrainBounds.west + terrainBounds.east) / 2;
      const centerLat = (terrainBounds.south + terrainBounds.north) / 2;
      // Use average altitude from preview data for better camera positioning
      const avgAltitude = altitudeRange.min && altitudeRange.max
        ? (altitudeRange.min + altitudeRange.max) / 2
        : 0;
      positions.push(Cesium.Cartesian3.fromDegrees(centerLon, centerLat, avgAltitude));

      // Add corner positions for better bounding sphere calculation
      positions.push(Cesium.Cartesian3.fromDegrees(terrainBounds.west, terrainBounds.south, avgAltitude));
      positions.push(Cesium.Cartesian3.fromDegrees(terrainBounds.east, terrainBounds.north, avgAltitude));

      viewer.entities.add({
        id: "elevation-dataset-bounds",
        rectangle: {
          coordinates: Cesium.Rectangle.fromDegrees(
            terrainBounds.west,
            terrainBounds.south,
            terrainBounds.east,
            terrainBounds.north,
          ),
          material: Cesium.Color.WHITE.withAlpha(0.02),
          outline: true,
          outlineColor: Cesium.Color.fromCssColorString("#f8fafc"),
          height: 0,
        },
        description: `
          <div style="line-height:1.7;">
            <div><strong>数据集：</strong>${dataset?.name ?? "-"}</div>
            <div><strong>范围：</strong>${terrainBounds.west.toFixed(4)}, ${terrainBounds.south.toFixed(4)} ~ ${terrainBounds.east.toFixed(4)}, ${terrainBounds.north.toFixed(4)}</div>
          </div>
        `,
      });
    }

    if (positions.length > 0) {
      const boundingSphere = Cesium.BoundingSphere.fromPoints(positions);
      void viewer.camera.flyToBoundingSphere(boundingSphere, {
        duration: 0.8,
        // Use steeper pitch angle (-1.0) to better show terrain relief
        // Closer distance (2.0x instead of 2.4x) to see more detail
        offset: new Cesium.HeadingPitchRange(0, -1.0, Math.max(1200, boundingSphere.radius * 2.0)),
      });
    }
  }, [altitudeRange.max, altitudeRange.min, dataset, heightGrid, ready, safePoints, terrainError, terrainRenderState]);

  // Build 3D terrain mesh from height grid data
  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = cesiumRef.current;
    if (!viewer || !Cesium || !ready || !heightGrid) {
      return;
    }

    // Remove previous mesh
    if (meshPrimitiveRef.current) {
      viewer.scene.primitives.remove(meshPrimitiveRef.current);
      meshPrimitiveRef.current = null;
    }

    const { rows, cols, west, south, east, north, heights } = heightGrid;
    const lonStep = (east - west) / (cols - 1);
    const latStep = (north - south) / (rows - 1);

    // Check if grid is valid
    if (!Number.isFinite(lonStep) || !Number.isFinite(latStep) || lonStep <= 0 || latStep <= 0) {
      return;
    }

    const vertexPositions: number[] = [];
    const indices: number[] = [];
    // Track which grid positions have valid vertices
    const validVertex: boolean[] = new Array(rows * cols).fill(false);
    const vertexIndex: number[] = new Array(rows * cols).fill(-1);
    let nextIndex = 0;

    // First pass: build vertex list
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const idx = r * cols + c;
        const h = heights[idx];
        if (h === null || h === undefined || !Number.isFinite(h)) {
          continue;
        }
        const lon = west + c * lonStep;
        const lat = south + r * latStep;
        const pos = Cesium.Cartesian3.fromDegrees(lon, lat, h);
        vertexPositions.push(pos.x, pos.y, pos.z);
        validVertex[idx] = true;
        vertexIndex[idx] = nextIndex;
        nextIndex++;
      }
    }

    // Second pass: build triangle indices (each quad = 2 triangles)
    for (let r = 0; r < rows - 1; r++) {
      for (let c = 0; c < cols - 1; c++) {
        const i00 = r * cols + c;
        const i01 = r * cols + (c + 1);
        const i10 = (r + 1) * cols + c;
        const i11 = (r + 1) * cols + (c + 1);

        // Skip quads with missing corners
        if (!validVertex[i00] || !validVertex[i01] || !validVertex[i10] || !validVertex[i11]) {
          continue;
        }

        const vi00 = vertexIndex[i00];
        const vi01 = vertexIndex[i01];
        const vi10 = vertexIndex[i10];
        const vi11 = vertexIndex[i11];

        // Triangle 1: (r,c) - (r,c+1) - (r+1,c)
        indices.push(vi00, vi01, vi10);
        // Triangle 2: (r+1,c) - (r,c+1) - (r+1,c+1)
        indices.push(vi10, vi01, vi11);
      }
    }

    if (vertexPositions.length === 0 || indices.length === 0) {
      return;
    }

    const geometry = new Cesium.Geometry({
      attributes: {
        position: new Cesium.GeometryAttribute({
          componentDatatype: Cesium.ComponentDatatype.DOUBLE,
          componentsPerAttribute: 3,
          values: new Float64Array(vertexPositions),
        }),
      } as GeometryAttributes,
      indices: new Uint32Array(indices),
      primitiveType: Cesium.PrimitiveType.TRIANGLES,
      boundingSphere: Cesium.BoundingSphere.fromVertices(vertexPositions),
    });

    // Compute vertex normals for smooth shading
    Cesium.GeometryPipeline.computeNormal(geometry);

    const finalPrimitive = new Cesium.Primitive({
      geometryInstances: new Cesium.GeometryInstance({
        geometry,
      }),
      appearance: new Cesium.MaterialAppearance({
        flat: false,
        faceForward: true,
        translucent: false,
        renderState: {
          depthTest: {
            enabled: true,
          },
        },
        material: new Cesium.Material({
          fabric: {
            type: 'ElevationRamp',
            uniforms: {
              minValue: altitudeRange.min,
              maxValue: altitudeRange.max,
            },
          },
        }),
      }),
      releaseGeometryInstances: true,
      allowPicking: false,
      asynchronous: false,
    });

    viewer.scene.primitives.add(finalPrimitive);
    meshPrimitiveRef.current = finalPrimitive;

    return () => {
      if (meshPrimitiveRef.current && !viewer.isDestroyed()) {
        viewer.scene.primitives.remove(meshPrimitiveRef.current);
        meshPrimitiveRef.current = null;
      }
    };
  }, [altitudeRange.max, altitudeRange.min, heightGrid, ready]);

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={`预览地图加载失败：${error}`}
      />
    );
  }

  if (safePoints.length === 0 && !loading) {
    return <Empty description="暂无可展示的高程预览点。" />;
  }

  return (
    <div className="space-y-2">
      <div className="text-xs text-slate-500">
        {previewHint}
      </div>
      {terrainRenderState !== "ready" ? (
        <Alert
          type={terrainRenderState === "failed" ? "warning" : "info"}
          showIcon
          message={`地形瓦片状态：${terrainRenderState}，暂以椭球底面显示参考点。`}
        />
      ) : null}
      {terrainError ? (
        <Alert
          type="warning"
          showIcon
          message={terrainErrorMessage}
        />
      ) : null}
      <div
        ref={containerRef}
        className="w-full overflow-hidden rounded-md border border-slate-200 bg-slate-100"
        style={{ height }}
      />
      {pointerInfo ? <div className="text-xs text-slate-500">{pointerInfo}</div> : null}
      {loading && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Spin size="small" />
          预览数据加载中...
        </div>
      )}
    </div>
  );
}
