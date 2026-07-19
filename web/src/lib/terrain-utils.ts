/**
 * 从高度数组中双线性插值采样指定经纬度的高度
 */
export function sampleHeight(
  heights: number[] | Float32Array,
  width: number,
  height: number,
  west: number,
  south: number,
  east: number,
  north: number,
  lon: number,
  lat: number,
): number | null {
  if (lon < west || lon > east || lat < south || lat > north) return null;
  const fx = ((lon - west) / (east - west)) * (width - 1);
  const fy = ((lat - south) / (north - south)) * (height - 1);
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = Math.min(x0 + 1, width - 1);
  const y1 = Math.min(y0 + 1, height - 1);
  const dx = fx - x0;
  const dy = fy - y0;
  const h00 = heights[y0 * width + x0];
  const h10 = heights[y0 * width + x1];
  const h01 = heights[y1 * width + x0];
  const h11 = heights[y1 * width + x1];
  if (
    !Number.isFinite(h00) ||
    !Number.isFinite(h10) ||
    !Number.isFinite(h01) ||
    !Number.isFinite(h11)
  ) {
    // fallback: 找最近有效值
    const valid = [h00, h10, h01, h11].filter((v) => Number.isFinite(v));
    return valid.length > 0 ? valid[0] : null;
  }
  return (1 - dy) * (1 - dx) * h00 + (1 - dy) * dx * h10 + dy * (1 - dx) * h01 + dy * dx * h11;
}

/**
 * 从高度数组中获取指定网格索引的高度
 */
export function getGridHeight(
  heights: number[] | Float32Array,
  width: number,
  row: number,
  col: number,
): number | null {
  const idx = row * width + col;
  const h = heights[idx];
  return Number.isFinite(h) ? h : null;
}

/**
 * 将一维高度数组解析为 Float32Array
 */
export function toFloat32Heights(raw: number[]): Float32Array {
  return new Float32Array(raw);
}
