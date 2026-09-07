"""雷电流地闪密度模块的纯统计逻辑。

从 lightning_service.py 中抽取的纯函数集合（网格 / Ng / 极性比 / 电流统计 / 出图），
供导入异步任务与线路回填任务共用，便于单元测试。本模块不直接访问数据库。
"""

from __future__ import annotations

import io
import math
import re
from datetime import datetime
from typing import Any

DEGREE_TO_KM = 111.32
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
TOKEN_SPLIT_PATTERN = re.compile(r"[,\t; ]+")
MAX_DISTRIBUTION_ROWS = 2_000_000

# 每条落雷数据的字段名
STRIKE_LAT = "lat"
STRIKE_LON = "lon"
STRIKE_CURRENT = "current_ka"
STRIKE_POLARITY = "polarity"


# ---------------------------------------------------------------------------
# 文本解码与行解析
# ---------------------------------------------------------------------------
def decode_text_bytes(content: bytes) -> str:
    """按候选编码顺序解码文本文件内容。"""
    for encoding in TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("文件编码不受支持")


def parse_distribution_line(raw_line: str) -> tuple[float, float, float] | None:
    """解析一行 \"纬度 经度 电流\"，返回 (lat, lon, current_ka) 或 None。"""
    stripped = raw_line.strip()
    if not stripped:
        return None
    tokens = [token for token in TOKEN_SPLIT_PATTERN.split(stripped) if token]
    if len(tokens) < 3:
        return None
    values: list[float] = []
    for token in tokens:
        parsed = _parse_float(token)
        if parsed is not None:
            values.append(parsed)
        if len(values) >= 3:
            break
    if len(values) < 3:
        return None
    return (values[0], values[1], values[2])


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 解析 + 校验
# ---------------------------------------------------------------------------
def parse_distribution_content(
    text: str,
    *,
    max_rows: int = MAX_DISTRIBUTION_ROWS,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """逐行解析文本并校验，返回合法落雷集合。

    返回列表元素：{lat, lon, current_ka, polarity}
    warnings 会在原地累计（最多 50 条）。
    """
    result: list[dict[str, Any]] = []
    collected_warnings: list[str] = warnings if warnings is not None else []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if len(result) >= max_rows:
            break
        parsed = parse_distribution_line(raw_line)
        if not parsed:
            stripped = raw_line.strip()
            if stripped and len(collected_warnings) < 50:
                collected_warnings.append(f'第 {line_no} 行无法解析为"纬度 经度 电流"，已跳过')
            continue

        latitude, longitude, current_ka = parsed
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            if len(collected_warnings) < 50:
                collected_warnings.append(f"第 {line_no} 行坐标越界（lat={latitude}, lon={longitude}），已跳过")
            continue

        if math.isclose(current_ka, 0.0, abs_tol=1e-12):
            polarity: str = "unknown"
        else:
            polarity = "positive" if current_ka > 0 else "negative"

        result.append(
            {
                STRIKE_LAT: latitude,
                STRIKE_LON: longitude,
                STRIKE_CURRENT: current_ka,
                STRIKE_POLARITY: polarity,
            }
        )

    return result


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def safe_km_per_lon(latitude: float) -> float:
    """在给定纬度上，1°经度大约多少公里。"""
    factor = abs(math.cos(math.radians(latitude)))
    return max(DEGREE_TO_KM * factor, 1e-6)


def resolve_data_years(event_times: list[datetime | None], default: float = 1.0) -> float:
    """根据事件时间跨度推算数据年数；无足够时间信息时返回默认值。"""
    values = [t for t in event_times if t is not None]
    if len(values) < 2:
        return default
    minimum = min(values)
    maximum = max(values)
    delta_days = (maximum - minimum).total_seconds() / 86400.0
    return max(delta_days / 365.25, default)


def compute_statistics(
    strikes: list[dict[str, Any]],
    *,
    grid_size_km: float,
    data_years: float | None = None,
    event_times: list[datetime | None] | None = None,
    include_grid_cells: bool = False,
) -> dict[str, Any]:
    """基于内存中的落雷集合计算统计结果（纯函数，不查库）。

    返回 dict 包含：
      total_records / area_km2 / data_years / overall_ng /
      max_abs_current / avg_abs_current / positive_count / negative_count /
      unknown_count / bbox（落雷经纬度范围 {min_lat, max_lat, min_lon, max_lon}）/
      grid_cells（网格列表，仅 include_grid_cells=True 时构建）

    include_grid_cells：grid_cells 是纯内部网格聚合明细，20 万格时构建约 185MB，
    且无 API/前端消费者（导入任务与列表接口都不持久化/返回它），密度图由
    render_density_image 独立从落点重聚合。故默认关闭，避免无谓的内存与序列化开销。
    """
    grid_cells: list[dict[str, Any]] = []
    total = len(strikes)
    if total == 0:
        return {
            "total_records": 0,
            "area_km2": 0.0,
            "data_years": float(data_years or 1.0),
            "overall_ng": 0.0,
            "max_abs_current": None,
            "avg_abs_current": None,
            "positive_count": 0,
            "negative_count": 0,
            "unknown_count": 0,
            "bbox": None,
            "grid_cells": grid_cells,
        }

    lats = [float(s[STRIKE_LAT]) for s in strikes]
    lons = [float(s[STRIKE_LON]) for s in strikes]
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    center_lat = (min_lat + max_lat) / 2.0
    km_per_lon = safe_km_per_lon(center_lat)

    width_km = max((max_lon - min_lon) * km_per_lon, grid_size_km)
    height_km = max((max_lat - min_lat) * DEGREE_TO_KM, grid_size_km)
    area_km2 = max(width_km * height_km, grid_size_km * grid_size_km)

    if data_years is not None:
        years = float(data_years)
    elif event_times:
        years = resolve_data_years(event_times)
    else:
        years = 1.0
    years = max(years, 1e-6)

    overall_ng = total / (area_km2 * years)

    positive_count = 0
    negative_count = 0
    unknown_count = 0
    abs_currents: list[float] = []
    for s in strikes:
        polarity = s.get(STRIKE_POLARITY)
        if polarity == "positive":
            positive_count += 1
        elif polarity == "negative":
            negative_count += 1
        else:
            unknown_count += 1
        current = s.get(STRIKE_CURRENT)
        if current is not None:
            abs_currents.append(abs(float(current)))

    max_abs = max(abs_currents) if abs_currents else None
    avg_abs = sum(abs_currents) / len(abs_currents) if abs_currents else None

    # 网格聚合
    cell_counts: dict[tuple[int, int], int] = {}
    cell_imax: dict[tuple[int, int], float] = {}
    cell_positive: dict[tuple[int, int], int] = {}
    for s in strikes:
        cell_x = int(math.floor(((float(s[STRIKE_LON]) - min_lon) * km_per_lon) / grid_size_km))
        cell_y = int(math.floor(((float(s[STRIKE_LAT]) - min_lat) * DEGREE_TO_KM) / grid_size_km))
        key = (cell_x, cell_y)
        cell_counts[key] = cell_counts.get(key, 0) + 1
        abs_current = abs(float(s[STRIKE_CURRENT]))
        if abs_current > cell_imax.get(key, 0.0):
            cell_imax[key] = abs_current
        if s.get(STRIKE_POLARITY) == "positive":
            cell_positive[key] = cell_positive.get(key, 0) + 1

    grid_cells = _build_grid_cells(
        cell_counts,
        cell_imax,
        cell_positive,
        min_lat=min_lat,
        min_lon=min_lon,
        grid_size_km=grid_size_km,
        years=years,
    ) if include_grid_cells else []

    return {
        "total_records": total,
        "area_km2": area_km2,
        "data_years": years,
        "overall_ng": overall_ng,
        "max_abs_current": max_abs,
        "avg_abs_current": avg_abs,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "unknown_count": unknown_count,
        "bbox": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
        "grid_cells": grid_cells,
    }


def _build_grid_cells(
    cell_counts: dict[tuple[int, int], int],
    cell_imax: dict[tuple[int, int], float],
    cell_positive: dict[tuple[int, int], int],
    *,
    min_lat: float,
    min_lon: float,
    grid_size_km: float,
    years: float,
) -> list[dict[str, Any]]:
    """把网格聚合结果展开成 grid_cells 明细列表（按 strike_count 降序）。"""
    grid_cells: list[dict[str, Any]] = []
    for (cell_x, cell_y), count in cell_counts.items():
        x0_km = cell_x * grid_size_km
        x1_km = (cell_x + 1) * grid_size_km
        y0_km = cell_y * grid_size_km
        y1_km = (cell_y + 1) * grid_size_km
        cell_min_lat = min_lat + y0_km / DEGREE_TO_KM
        cell_max_lat = min_lat + y1_km / DEGREE_TO_KM
        cell_center_lat = (cell_min_lat + cell_max_lat) / 2.0
        cell_km_per_lon = safe_km_per_lon(cell_center_lat)
        cell_min_lon = min_lon + x0_km / cell_km_per_lon
        cell_max_lon = min_lon + x1_km / cell_km_per_lon
        cell_center_lon = (cell_min_lon + cell_max_lon) / 2.0
        positive_in_cell = cell_positive.get((cell_x, cell_y), 0)
        grid_cells.append(
            {
                "grid_x": cell_x,
                "grid_y": cell_y,
                "min_lat": cell_min_lat,
                "max_lat": cell_max_lat,
                "min_lon": cell_min_lon,
                "max_lon": cell_max_lon,
                "center_lat": cell_center_lat,
                "center_lon": cell_center_lon,
                "strike_count": count,
                "ng_per_km2_year": count / (grid_size_km * grid_size_km * years),
                "i_max_ka": cell_imax.get((cell_x, cell_y)),
                "positive_ratio": (positive_in_cell / count) if count > 0 else 0.0,
            }
        )

    grid_cells.sort(key=lambda cell: cell["strike_count"], reverse=True)
    return grid_cells


# ---------------------------------------------------------------------------
# 密度图渲染
# ---------------------------------------------------------------------------
def build_density_matrix(
    cell_counts: dict[tuple[int, int], int],
) -> Any:
    """把网格聚合结果填充为二维密度矩阵（numpy 数组），返回 None 表示无网格数据。

    矩阵原点：(min_x, min_y)，即 cell 坐标减去网格最小横/纵坐标后的下标。
    通过显式 `import numpy` 独立可用，方便在未安装 matplotlib 的环境中做性能回归测试。
    """
    try:
        import numpy as np
    except ImportError:
        return None

    if not cell_counts:
        return None

    # min/max 在循环外一次性计算，复用为矩阵填充的偏移基值，
    # 避免在每个 cell 内重复调用（否则整体复杂度为 O(n²)，128 万网格时耗时数小时）。
    xs = [key[0] for key in cell_counts]
    ys = [key[1] for key in cell_counts]
    base_x = min(xs)
    base_y = min(ys)
    width_cells = max(xs) - base_x + 1
    height_cells = max(ys) - base_y + 1
    width_cells = max(width_cells, 1)
    height_cells = max(height_cells, 1)

    matrix = np.zeros((height_cells, width_cells), dtype=float)
    for (cell_x, cell_y), count in cell_counts.items():
        matrix[cell_y - base_y, cell_x - base_x] = count
    return matrix


# 常见中文字体名关键词（按优先级匹配系统已安装字体）。
# 具体字体名靠前（SC 简体优先），宽泛的 "CJK" 靠后兜底，避免先命中 TC/JP 变体。
_CJK_FONT_KEYWORDS = (
    "Source Han Sans SC",
    "Noto Sans SC",
    "Noto Sans CJK SC",
    "SimHei",
    "WenQuanYi",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Serif SC",
    "AR PL UMing CN",
    "Droid Sans Fallback",
    "CJK",
)

# 静态候选字体列表（动态检测未命中时的回退；matplotlib 按序取第一个可用字体）。
_FALLBACK_SANS_SERIF = [
    "SimHei",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
    "Microsoft YaHei",
    "PingFang SC",
    "Source Han Sans SC",
    "AR PL UMing CN",
    "DejaVu Sans",
]


def _find_installed_cjk_font() -> str | None:
    """在 matplotlib 已注册字体中查找一个可用中文字体名，找不到返回 None。"""
    try:
        from matplotlib import font_manager
    except ImportError:
        return None
    try:
        names = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:
        return None
    for keyword in _CJK_FONT_KEYWORDS:
        for name in names:
            if keyword.lower() in name.lower():
                return name
    return None


def _configure_chinese_font() -> None:
    """配置 matplotlib 中文字体（幂等，多次调用安全）。

    优先动态选择系统已安装的中文字体，避免中文标签渲染成方框（tofu）；
    未找到时回退静态候选列表并显式告警，便于定位缺字体环境（如
    celery worker 容器未安装 fonts-noto-cjk）。
    """
    import matplotlib
    import warnings

    matplotlib.rcParams["axes.unicode_minus"] = False
    installed = _find_installed_cjk_font()
    if installed:
        matplotlib.rcParams["font.sans-serif"] = [installed, *_FALLBACK_SANS_SERIF]
    else:
        matplotlib.rcParams["font.sans-serif"] = list(_FALLBACK_SANS_SERIF)
        warnings.warn(
            "未检测到可用的中文字体，地闪密度图中文标签将显示为方框；"
            "请在运行环境安装 fonts-noto-cjk 等中文字体后重试。",
            UserWarning,
            stacklevel=2,
        )


# 公共入口：供其他模块（如 traveling_wave_service 行波波形图）复用同一套中文字体配置。
configure_chinese_font = _configure_chinese_font


def render_density_image(
    strikes: list[dict[str, Any]],
    *,
    grid_size_km: float,
    data_years: float = 1.0,
    title: str | None = None,
) -> bytes:
    """用 matplotlib 渲染地闪密度图（网格热力图），返回 PNG 字节。

    地闪密度 Ng = count / (grid_size_km² × data_years)，单位：次/(km²·年)。
    坐标轴显示经纬度刻度，图中附统计摘要信息。
    matplotlib 不可用时返回 b""（调用方降级为无图）。
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        _configure_chinese_font()
        import matplotlib.pyplot as plt
        from matplotlib.colors import LogNorm
    except ImportError:
        return b""

    if not strikes:
        return b""

    lats = [float(s[STRIKE_LAT]) for s in strikes]
    lons = [float(s[STRIKE_LON]) for s in strikes]
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    center_lat = (min_lat + max_lat) / 2.0
    km_per_lon = safe_km_per_lon(center_lat)
    years = max(float(data_years), 1e-6)

    cell_counts: dict[tuple[int, int], int] = {}
    for s in strikes:
        cell_x = int(math.floor(((float(s[STRIKE_LON]) - min_lon) * km_per_lon) / grid_size_km))
        cell_y = int(math.floor(((float(s[STRIKE_LAT]) - min_lat) * DEGREE_TO_KM) / grid_size_km))
        key = (cell_x, cell_y)
        cell_counts[key] = cell_counts.get(key, 0) + 1

    matrix = build_density_matrix(cell_counts)
    if matrix is None:
        return b""

    # 换算为地闪密度 Ng（次/(km²·年)），替代原始落雷次数
    grid_area_km2 = grid_size_km * grid_size_km
    ng_matrix = matrix / (grid_area_km2 * years)

    # 构建经纬度刻度标签
    xs = [key[0] for key in cell_counts]
    ys = [key[1] for key in cell_counts]
    base_x = min(xs)
    base_y = min(ys)
    width_cells = max(xs) - base_x + 1
    height_cells = max(ys) - base_y + 1

    # 经度刻度：网格中心 → 经度
    lon_ticks = []
    lon_labels = []
    for i in range(width_cells):
        if width_cells <= 10 or i % max(width_cells // 6, 1) == 0:
            km_from_min = (base_x + i + 0.5) * grid_size_km
            lon_val = min_lon + km_from_min / km_per_lon
            lon_ticks.append(i)
            lon_labels.append(f"{lon_val:.2f}")

    # 纬度刻度：网格中心 → 纬度
    lat_ticks = []
    lat_labels = []
    for i in range(height_cells):
        if height_cells <= 10 or i % max(height_cells // 6, 1) == 0:
            km_from_min = (base_y + i + 0.5) * grid_size_km
            lat_val = min_lat + km_from_min / DEGREE_TO_KM
            lat_ticks.append(i)
            lat_labels.append(f"{lat_val:.2f}")

    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(
        ng_matrix,
        origin="lower",
        aspect="auto",
        cmap="YlOrRd",
        interpolation="nearest",
        norm=LogNorm(vmin=1, vmax=ng_matrix.max()),
    )
    ax.set_xlabel("经度 (°E)")
    ax.set_ylabel("纬度 (°N)")
    ax.set_title(title or "雷电流地闪密度分布")
    ax.set_xticks(lon_ticks)
    ax.set_xticklabels(lon_labels, fontsize=8)
    ax.set_yticks(lat_ticks)
    ax.set_yticklabels(lat_labels, fontsize=8)

    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label("地闪密度 Ng (次/(km²·年))")

    # 图内统计摘要信息
    total_strikes = len(strikes)
    area_km2 = grid_area_km2 * max(width_cells, 1) * max(height_cells, 1)
    overall_ng = ng_matrix.sum() * 0  # avoid recomputation
    overall_ng = total_strikes / (area_km2 * years) if area_km2 > 0 and years > 0 else 0.0
    stats_text = (
        f"总落雷数: {total_strikes}\n"
        f"数据年数: {years:.1f}年\n"
        f"整体Ng: {overall_ng:.4f} 次/(km²·年)"
    )
    ax.text(
        0.02, 0.98, stats_text,
        transform=ax.transAxes,
        fontsize=8,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
    )

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# LP 桌面端 Voronoi 分区密度图
#
# 对应反编译的 banjin*.decompiled.py 中「杆塔分组中心 + 中垂线分割」算法：
# 用 scipy.spatial.Voronoi 做相邻分组中心点的中垂线分区（与 LP 桌面端
# make_perp_bisector_deg + split 数学等价，但为原生实现、不引入 shapely）。
# 面积换算契约：area_km2 = abs(area_deg2) * 12321（≈111²）。
# ---------------------------------------------------------------------------
def _lp_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点之间的大圆距离（公里）。lightning_statistics 内就地复制，避免跨模块循环依赖。"""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_lp_voronoi_cells(
    groups: list[dict[str, Any]],
    radius_km: float,
    *,
    padding_deg: float = 0.5,
) -> list[dict[str, Any]]:
    """按 LP 桌面端「杆塔分组中心 + 中垂线(Voronoi)分割」生成每个分组的多边形分区。

    返回 [{"group_id", "center_lat", "center_lon", "area_km2", "polygon":[(lon,lat),...]}, ...]。
    area_km2 = abs(area_deg2) * 12321  （与反编译版一致，1度≈111km）。
    """
    from scipy.spatial import Voronoi
    import numpy as np

    if not groups:
        return []
    pts = np.array([[g["center_lon"], g["center_lat"]] for g in groups], dtype=float)

    # 哨兵点：bbox 外 4 个远点，使所有原始 cell 有限（避免 -1 顶点）
    margin = max(radius_km / 111.0, padding_deg)
    bb = pts.min(axis=0) - margin, pts.max(axis=0) + margin
    sentinels = np.array([
        [bb[0][0], bb[0][1]], [bb[1][0], bb[0][1]],
        [bb[1][0], bb[1][1]], [bb[0][0], bb[1][1]],
    ])
    vor = Voronoi(np.vstack([pts, sentinels]))

    cells = []
    for i, g in enumerate(groups):
        region_idx = vor.point_region[i]
        vert_ids = vor.regions[region_idx]
        if -1 in vert_ids:
            continue  # 理论不应发生（有哨兵），防御跳过
        poly = vor.vertices[vert_ids]  # Nx2 [lon, lat]
        # 鞋带公式求面积（度²）
        x, y = poly[:, 0], poly[:, 1]
        area_deg2 = 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
        cells.append({
            "group_id": g["group_id"],
            "center_lat": g["center_lat"],
            "center_lon": g["center_lon"],
            "area_km2": abs(area_deg2) * 12321,
            "polygon": [(float(lon), float(lat)) for lon, lat in poly],
        })
    return cells


def _compute_lp_ng_by_cell(
    strikes: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    data_years: float,
) -> dict[int, float]:
    """把每条落雷分配到最近的 cell 中心，Ng = count/(cell.area_km2 * years)。"""
    from collections import defaultdict
    if not cells or data_years <= 0:
        return {}
    centers = {c["group_id"]: (c["center_lat"], c["center_lon"]) for c in cells}
    area = {c["group_id"]: max(c["area_km2"], 1e-9) for c in cells}
    cnt: dict[int, int] = defaultdict(int)
    for s in strikes:
        lat, lon = s.get("lat"), s.get("lon")
        if lat is None or lon is None:
            continue
        best = min(centers, key=lambda gid: _lp_haversine_km(lat, lon, centers[gid][0], centers[gid][1]))
        cnt[best] += 1
    return {gid: cnt[gid] / (area[gid] * data_years) for gid in cnt}


def render_lp_density_image(
    strikes: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    *,
    data_years: float,
    radius_km: float,
    title: str | None = None,
) -> bytes:
    """LP 桌面端风格地闪密度分区图：Voronoi cell 按 Ng 着色。matplotlib 不可用返回 b""。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        _configure_chinese_font()
        import matplotlib.pyplot as plt
    except ImportError:
        return b""
    if not cells or not strikes:
        return b""

    ng_map = _compute_lp_ng_by_cell(strikes, cells, data_years)
    max_ng = max(ng_map.values(), default=0.0)

    fig, ax = plt.subplots(figsize=(10, 8))
    for c in cells:
        gid = c["group_id"]
        ng = ng_map.get(gid, 0.0)
        norm = (ng / max_ng) if max_ng > 0 else 0.0
        lons = [p[0] for p in c["polygon"]]
        lats = [p[1] for p in c["polygon"]]
        ax.fill(lons, lats, color=plt.cm.YlOrRd(norm), edgecolor="#666666", linewidth=0.8)
        ax.plot([c["center_lon"]], [c["center_lat"]], "ko", markersize=3)

    ax.set_xlabel("经度 (°E)")
    ax.set_ylabel("纬度 (°N)")
    ax.set_title(title or "雷电流地闪密度分布 - 杆塔分区")
    # 经纬度等比：lon 1度≈111cosφ km（matplotlib ax.set_aspect 数值语义为 dy/dx，
    # 111km 为物理单位换算不应代入；正确值为 1/cosφ，保证纬度/经度单位屏幕等长）
    ax.set_aspect(1.0 / math.cos(math.radians(cells[0]["center_lat"])))

    total_strikes = len(strikes)
    total_area = sum(c["area_km2"] for c in cells)
    overall_ng = (total_strikes / (total_area * data_years)) if total_area * data_years > 0 else 0.0
    ax.text(
        0.02, 0.98,
        f"总落雷数: {total_strikes}\n数据年数: {data_years:.1f}年\n"
        f"整体Ng: {overall_ng:.4f} 次/(km²·年)\n分组数: {len(cells)}",
        transform=ax.transAxes, fontsize=8, verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
    )

    sm = matplotlib.cm.ScalarMappable(cmap="YlOrRd")
    sm.set_array([0, max_ng])
    cbar = fig.colorbar(sm, ax=ax)
    cbar.set_label("地闪密度 Ng (次/(km²·年))")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


def render_along_route_circle_image(
    strikes: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    cells: list[dict[str, Any]],
    *,
    data_years: float,
    radius_km: float,
    title: str | None = None,
) -> bytes:
    """LP 桌面端「沿线圆」地闪密度图：对齐 C# banjin{1,2,3}.exe 分组圆画法。

    每个杆塔分组（group_size 座塔一组）以其中心为圆心、radius_km 为半径画圆，
    圆填充色按该分组 Ng（地闪密度，次/(km²·年)）用 YlOrRd 色阶着色；
    圆心画黑色圆点标记分组中心，落雷点以半透明小点叠加；
    分组中心按线路顺序连线，呈现「沿线一串圆」的视觉效果。

    matplotlib 不可用或输入不足返回 b""。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        _configure_chinese_font()
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle
    except ImportError:
        return b""
    if not groups or not strikes:
        return b""

    # 每个分组的 Ng：落雷分配到最近分组中心 / (圆面积 × 年数)
    from collections import defaultdict
    centers = {g["group_id"]: (g["center_lat"], g["center_lon"]) for g in groups}
    area_km2 = math.pi * (radius_km ** 2)
    cnt: dict[int, int] = defaultdict(int)
    for s in strikes:
        lat, lon = s.get("lat"), s.get("lon")
        if lat is None or lon is None:
            continue
        best = min(centers, key=lambda gid: _lp_haversine_km(lat, lon, centers[gid][0], centers[gid][1]))
        cnt[best] += 1
    ng_map = {gid: cnt[gid] / (area_km2 * max(data_years, 1e-6)) for gid in cnt}
    max_ng = max(ng_map.values(), default=0.0)

    radius_deg = radius_km / DEGREE_TO_KM
    # 经度方向的度/公里按中心纬度修正，保证圆在地理坐标下近似正圆
    center_lat_ref = groups[0]["center_lat"]
    lon_scale = 1.0 / math.cos(math.radians(center_lat_ref))

    fig, ax = plt.subplots(figsize=(12, 8))
    for g in groups:
        gid = g["group_id"]
        ng = ng_map.get(gid, 0.0)
        norm = (ng / max_ng) if max_ng > 0 else 0.0
        circle = Circle(
            (g["center_lon"], g["center_lat"]),
            radius=radius_deg * lon_scale,
            facecolor=plt.cm.YlOrRd(norm),
            edgecolor="#8c8c8c",
            linewidth=0.8,
            alpha=0.85,
            transform=ax.transData,
        )
        ax.add_patch(circle)
        ax.plot(g["center_lon"], g["center_lat"], "ko", markersize=2.5)

    # 分组中心连线（沿线走向）
    sorted_groups = sorted(groups, key=lambda g: g["group_id"])
    ax.plot(
        [g["center_lon"] for g in sorted_groups],
        [g["center_lat"] for g in sorted_groups],
        color="#444444", linewidth=1.2, linestyle="--", alpha=0.6,
    )

    # 落雷点（半透明小点）
    lons = [float(s["lon"]) for s in strikes if s.get("lon") is not None]
    lats = [float(s["lat"]) for s in strikes if s.get("lat") is not None]
    if lons:
        ax.scatter(lons, lats, s=6, c="#1f77b4", alpha=0.35, edgecolors="none", label="落雷点")

    ax.set_xlabel("经度 (°E)")
    ax.set_ylabel("纬度 (°N)")
    ax.set_title(title or "地闪密度分布 - 沿线分组圆")
    ax.set_aspect(1.0 / math.cos(math.radians(center_lat_ref)))
    if lons:
        ax.legend(loc="upper right", fontsize=8)

    total_strikes = len(strikes)
    overall_ng = (total_strikes / (len(groups) * area_km2 * max(data_years, 1e-6))) if groups else 0.0
    ax.text(
        0.02, 0.98,
        f"总落雷数: {total_strikes}\n数据年数: {max(data_years, 1e-6):.1f}年\n"
        f"分组数: {len(groups)}\n圆半径: {radius_km}km\n"
        f"整体Ng: {overall_ng:.4f} 次/(km²·年)",
        transform=ax.transAxes, fontsize=8, verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8),
    )

    sm = matplotlib.cm.ScalarMappable(cmap="YlOrRd")
    sm.set_array([0, max_ng])
    cbar = fig.colorbar(sm, ax=ax)
    cbar.set_label("地闪密度 Ng (次/(km²·年))")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()
