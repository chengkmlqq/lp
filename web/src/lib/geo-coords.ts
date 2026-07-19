/**
 * WGS84 经纬度 → 局部平面坐标（平面近似，适用于 1°×1° 范围）
 */
export function geoToLocal(
  lon: number,
  lat: number,
  originLon: number,
  originLat: number,
  scale: number = 1,
): { x: number; z: number } {
  const METERS_PER_DEG_LAT = 111320;
  const METERS_PER_DEG_LON =
    111320 * Math.cos(((lat + originLat) / 2 * Math.PI) / 180);
  return {
    x: (lon - originLon) * METERS_PER_DEG_LON * scale,
    z: (lat - originLat) * METERS_PER_DEG_LAT * scale,
  };
}

/**
 * 计算包围盒（返回 center + halfExtents）
 */
export function computeBoundingBox(
  points: Array<{ x: number; z: number }>,
): {
  centerX: number;
  centerZ: number;
  halfExtentX: number;
  halfExtentZ: number;
} {
  if (points.length === 0) {
    return { centerX: 0, centerZ: 0, halfExtentX: 0, halfExtentZ: 0 };
  }
  let minX = Infinity,
    maxX = -Infinity;
  let minZ = Infinity,
    maxZ = -Infinity;
  for (const p of points) {
    if (p.x < minX) minX = p.x;
    if (p.x > maxX) maxX = p.x;
    if (p.z < minZ) minZ = p.z;
    if (p.z > maxZ) maxZ = p.z;
  }
  return {
    centerX: (minX + maxX) / 2,
    centerZ: (minZ + maxZ) / 2,
    halfExtentX: (maxX - minX) / 2,
    halfExtentZ: (maxZ - minZ) / 2,
  };
}

/**
 * 将经度/纬度列表转为局部坐标数组
 */
export function geoPathToLocal(
  path: Array<{ lon: number; lat: number }>,
  originLon: number,
  originLat: number,
  scale?: number,
): Array<{ x: number; z: number }> {
  return path.map((p) => geoToLocal(p.lon, p.lat, originLon, originLat, scale));
}
