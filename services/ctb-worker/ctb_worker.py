"""
ctb_worker.py — Cesium Terrain Builder Celery Worker

订阅 LP 的 Celery 消息队列，处理 terrain build 任务:
- 接收 DEM 文件路径 + 参数
- 调用 ctb-tile 命令行生成 Cesium heightmap-1.0 地形瓦片
- 瓦片写入共享卷 /data/terrain/，供 Nginx 直接服务
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from celery import Celery

logger = logging.getLogger(__name__)

# ── Celery 配置 ──────────────────────────────────────────
# 从环境变量读取，与 LP 现有 Celery worker 共用同一 Redis
BROKER_URL = os.environ.get(
    "CELERY_BROKER_URL",
    "redis://:Cp990803@redis:6379/0",
)
RESULT_BACKEND = os.environ.get(
    "CELERY_RESULT_BACKEND",
    "redis://:Cp990803@redis:6379/1",
)

celery_app = Celery(
    "ctb",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
)

# ── 常量 ─────────────────────────────────────────────────
TERRAIN_ROOT = Path(os.environ.get("TERRAIN_ROOT", "/data/terrain"))
TILE_SIZE = 65  # Cesium heightmap-1.0 标准瓦片尺寸
TERRAIN_CONTENT_TYPE = "application/octet-stream"


def _compute_zoom_limits(
    input_path: str,
) -> tuple[int, int]:
    """
    用 gdalinfo 获取 DEM 分辨率，推算合适的 zoom range。
    与 LP elevation_service.py 中的 _resolve_terrain_zoom_limits 等效。
    """
    import json as _json

    result = subprocess.run(
        ["gdalinfo", "-json", input_path],
        capture_output=True, text=True, check=True,
    )
    info = _json.loads(result.stdout)

    # 从 cornerCoordinates 计算 bounds
    corners = info.get("cornerCoordinates", {})
    if "lowerLeft" in corners and "upperRight" in corners:
        ll = corners["lowerLeft"]
        ur = corners["upperRight"]
        west, south = ll[0], ll[1]
        east, north = ur[0], ur[1]
    else:
        wgs84 = info.get("wgs84Extent", {})
        west = wgs84.get("west", -180)
        south = wgs84.get("south", -90)
        east = wgs84.get("east", 180)
        north = wgs84.get("north", 90)

    # 从 size + geoTransform 推算分辨率
    size = info.get("size", [1, 1])
    geo = info.get("geoTransform", [0, 1, 0, 0, 0, -1])
    res_x = abs(geo[1]) if geo[1] else 1.0
    res_y = abs(geo[5]) if geo[5] else 1.0
    resolution_m = max(res_x, res_y) * 111320  # 度→米的粗略转换（赤道附近）

    # 根据分辨率算 zoom
    # 瓦片分辨率 = 180° / 2^zoom / tile_size
    tile_span_deg = 180.0 / (1 << 0) / TILE_SIZE
    max_zoom = 0
    while tile_span_deg > resolution_m / 111320 and max_zoom < 18:
        max_zoom += 1
        tile_span_deg = 180.0 / (1 << max_zoom) / TILE_SIZE

    min_zoom = 0

    logger.info(
        "Zoom limits: min=%d max=%d (bounds=%.4f,%.4f,%.4f,%.4f, res=%.2fm)",
        min_zoom, max_zoom, west, south, east, north, resolution_m,
    )
    return min_zoom, max_zoom


def _build_layer_json(
    output_dir: Path,
    min_zoom: int,
    max_zoom: int,
    bounds: list[float],
    name: str,
) -> None:
    """
    生成 Cesium terrain layer.json。
    """
    # 从实际瓦片文件扫 availability
    available: dict[int, list[dict]] = {}
    for z in range(min_zoom, max_zoom + 1):
        z_dir = output_dir / str(z)
        if not z_dir.exists():
            continue
        tiles: list[dict[str, int]] = []
        for x_dir in sorted(z_dir.iterdir()):
            if not x_dir.is_dir():
                continue
            x = int(x_dir.name)
            ys = sorted(
                int(f.stem)
                for f in x_dir.glob("*.terrain")
            )
            if ys:
                tiles.append({"startX": x, "startY": ys[0], "endX": x, "endY": ys[-1]})
        if tiles:
            available[z] = tiles

    layer = {
        "tiles": ["{z}/{x}/{y}.terrain"],
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "attribution": name,
        "bounds": bounds,
        "available": [available.get(z, []) for z in range(0, max_zoom + 1)],
    }
    layer_path = output_dir / "layer.json"
    with open(layer_path, "w") as f:
        json.dump(layer, f, ensure_ascii=True, separators=(",", ":"))
    logger.info("layer.json written to %s", layer_path)


@celery_app.task(
    bind=True,
    name="app.tasks.ctb.build_file_record_terrain",
    max_retries=2,
    default_retry_delay=30,
    queue="ctb",
)
def build_file_record_terrain(
    self,
    record_id: str,
    input_path: str,
    *,
    name: str = "",
    min_zoom: int | None = None,
    max_zoom: int | None = None,
    bounds: list[float] | None = None,
) -> dict:
    """
    为单个文件记录生成地形瓦片。

    Args:
        record_id: 文件记录 ID（用于命名 tileset 输出目录）
        input_path: DEM GeoTIFF 文件路径（在容器内可访问）
        name: tileset 名称（用于 layer.json attribution）
        min_zoom: 起始 zoom 层（None 自动推算）
        max_zoom: 结束 zoom 层（None 自动推算）
        bounds: [west, south, east, north]（None 自动推算）
    """
    logger.info(
        "Building terrain for record=%s input=%s zoom=%s-%s",
        record_id, input_path, min_zoom, max_zoom,
    )

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"DEM not found: {input_path}")

    # 推算 zoom limits
    if min_zoom is None or max_zoom is None or bounds is None:
        _min_z, _max_z = _compute_zoom_limits(input_path)
        min_zoom = min_zoom if min_zoom is not None else _min_z
        max_zoom = max_zoom if max_zoom is not None else _max_z

    # 输出目录：/data/terrain/{record_id}/
    output_dir = TERRAIN_ROOT / record_id
    if output_dir.exists():
        logger.warning("Removing existing output: %s", output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 用 ctb-tile 生成瓦片
    cmd = [
        "ctb-tile",
        "--output-dir", str(output_dir),
        "--output-format", "Terrain",
        "--profile", "geodetic",
        "--tile-size", str(TILE_SIZE),
        "--thread-count", "4",
        "--resampling-method", "average",
        f"--start-zoom={max_zoom}",
        f"--end-zoom={min_zoom}",
        input_path,
    ]
    logger.info("Running: %s", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    if result.returncode != 0:
        error_msg = f"ctb-tile failed (rc={result.returncode}): {result.stderr[:2000]}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info("ctb-tile output:\n%s", result.stdout[:1000])

    # 计数瓦片
    tile_count = sum(1 for _ in output_dir.rglob("*.terrain"))

    # 构建 bounds
    if bounds is None:
        # 从第一个瓦片的 geo 坐标推算
        result2 = subprocess.run(
            ["gdalinfo", "-json", input_path],
            capture_output=True, text=True, check=True,
        )
        import json as _json
        info = _json.loads(result2.stdout)
        corners = info.get("cornerCoordinates", {})
        if "lowerLeft" in corners and "upperRight" in corners:
            ll, ur = corners["lowerLeft"], corners["upperRight"]
            bounds = [ll[0], ll[1], ur[0], ur[1]]

    # 生成 layer.json
    _build_layer_json(output_dir, min_zoom, max_zoom, bounds or [0, 0, 0, 0], name or record_id)

    logger.info(
        "Terrain build complete: record=%s tiles=%d zoom=%d-%d",
        record_id, tile_count, min_zoom, max_zoom,
    )

    return {
        "record_id": record_id,
        "output_dir": str(output_dir),
        "tile_count": tile_count,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "bounds": bounds,
        "layer_url": f"/terrain/{record_id}/layer.json",
    }


# 启动时打印配置
logger.info(
    "ctb-worker started: broker=%s backend=%s terrain_root=%s",
    BROKER_URL, RESULT_BACKEND, TERRAIN_ROOT,
)
