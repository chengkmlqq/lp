"""风电场地闪密度统计 —— 纯函数算法层。

口径严格对齐核心程序 ``地闪密度/density.py``（**不复用** ``lightning_statistics``
的地闪密度算法、色标与分级）：

1. DMS → 十进制度：``d + m/60 + s/3600``，兼容 ``121°11'18.34"`` 合并格式；
2. 统计范围：风机经/纬度 min/max 四周各外扩 ``margin_deg``（默认 0.01°）；
3. 网格：``grid_step_deg`` 固定步长，``arange(min, max+step, step)`` 含终点，
   经纬度独立分箱（等价于 ``numpy.histogram2d``）；
4. 记录过滤：只保留落在范围内的记录，不做 CG/IC 类型筛选；
5. 密度：网格计数 ÷ 统计年限；
6. 渲染：灰 ``#D3D3D3`` → 蓝 ``#0000FF`` → 黄 ``#FFFF00`` → 红 ``#FF0000``
   线性色带，``origin="lower"``、``aspect="auto"``、``interpolation="bilinear"``、
   ``extent`` 取网格边界。

本模块只做纯计算，不读写数据库、不依赖 FastAPI，便于单元测试逐格对拍。
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

# 与 density.py 一致的默认参数
DEFAULT_GRID_STEP_DEG = 0.01
DEFAULT_MARGIN_DEG = 0.01
DEFAULT_DATA_YEARS = 6.0
# 单边网格数上限：超过即拒绝（避免前端表格与出图不可用）
MAX_GRID_AXIS = 500
# density.py 的灰→蓝→黄→红线性色带
COLOR_STOPS = ("#D3D3D3", "#0000FF", "#FFFF00", "#FF0000")

# 核心程序按「1° = 100 km」近似（见 dishan_tongji.py），故 0.01° 网格 = 1 km²
DEG_KM_APPROX = 100.0

LON_HEADERS = {"longitude", "lon", "经度"}
LAT_HEADERS = {"latitude", "lat", "纬度"}
TIME_HEADERS = {"datetime", "time", "date", "时间", "时刻", "日期", "发生时间", "inputtime"}

_DMS_SYMBOL_RE = re.compile(r"[°′'\"”″]")
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


class WindLightningDensityError(ValueError):
    """算法输入不合法（调用方转 400 并给出明确提示）。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class TurbinePoint:
    seq: int
    turbine_no: str
    lon: float
    lat: float


@dataclass(slots=True)
class TurbineParseResult:
    points: list[TurbinePoint] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LightningParseResult:
    lat: np.ndarray
    lon: np.ndarray
    total_rows: int
    valid_rows: int
    skipped_rows: int
    detected_years: list[int] = field(default_factory=list)

    @property
    def inferred_years(self) -> int | None:
        """按实际覆盖年份推断统计年限（max - min + 1）；无法推断返回 None。"""
        if not self.detected_years:
            return None
        span = max(self.detected_years) - min(self.detected_years) + 1
        if span <= 0 or span > 100:
            return None
        return span


@dataclass(slots=True)
class BoundingBox:
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float

    def as_dict(self) -> dict[str, float]:
        return {
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
        }

    def contains(self, lon: float, lat: float) -> bool:
        return (
            self.min_lon <= lon <= self.max_lon
            and self.min_lat <= lat <= self.max_lat
        )


# ---------------------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------------------
def decode_text_bytes(content: bytes) -> str:
    """按 UTF-8(BOM) → GBK → latin-1 顺序解码（核心程序源数据多为 GBK/UTF-8）。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


def dms_to_decimal(deg: float, minute: float, second: float) -> float:
    """度分秒 → 十进制度，与 density.py 的 ``d + m/60 + s/3600`` 完全一致。"""
    return float(deg) + float(minute) / 60.0 + float(second) / 3600.0


def parse_dms_compact(value: Any) -> tuple[float, float, float] | None:
    """从 ``121 11 18.339516`` / ``121°11'18.34"`` 等写法中提取 (度, 分, 秒)。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = _DMS_SYMBOL_RE.sub(" ", text)
    for letter in ("N", "E", "S", "W", "n", "e", "s", "w"):
        text = text.replace(letter, " ")
    numbers = re.findall(r"-?\d+\.?\d*", text)
    if len(numbers) < 3:
        return None
    try:
        return float(numbers[0]), float(numbers[1]), float(numbers[2])
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        result = float(value)
        return result if math.isfinite(result) else None
    text = str(value).strip()
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        parts = parse_dms_compact(text)
        if parts is None:
            return None
        result = dms_to_decimal(*parts)
    return result if math.isfinite(result) else None


def _coord_from_text(value: Any) -> float | None:
    """Excel 单元格可能是数字，也可能是 ``121°11'18.34"`` 文本。"""
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return _to_float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        parts = parse_dms_compact(text)
        if parts is None:
            return None
        return dms_to_decimal(*parts)


# ---------------------------------------------------------------------------
# 风机点位解析
# ---------------------------------------------------------------------------
def parse_turbine_file(content: bytes, filename: str) -> TurbineParseResult:
    """按扩展名分派：``.xlsx/.xlsm`` 走 Excel，其余按 11 列空白分隔文本处理。"""
    suffix = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if suffix in {"xlsx", "xlsm"}:
        return parse_turbine_excel(content)
    return parse_turbine_txt(content)


def parse_turbine_txt(content: bytes) -> TurbineParseResult:
    """解析 ``file_2.txt`` 原格式：11 列空白分隔，前 6 列为经纬度度分秒。

    兼容性：
    - 首行若为表头（含非数字）自动跳过；
    - 少于 6 列时，若前 2 列可解析为十进制度则按 ``经度 纬度`` 处理。
    """
    text = decode_text_bytes(content)
    result = TurbineParseResult()
    seq = 0
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        columns = re.split(r"[\s,;]+", line)
        if line_no == 1 and not _looks_numeric(columns[0]):
            continue  # 表头行
        seq += 1
        lon: float | None = None
        lat: float | None = None
        if len(columns) >= 6:
            try:
                lon = dms_to_decimal(float(columns[0]), float(columns[1]), float(columns[2]))
                lat = dms_to_decimal(float(columns[3]), float(columns[4]), float(columns[5]))
            except ValueError:
                lon = lat = None
        elif len(columns) >= 2:
            lon = _to_float(columns[0])
            lat = _to_float(columns[1])

        if lon is None or lat is None or not _valid_lonlat(lon, lat):
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {line_no} 行风机坐标无法识别，已跳过")
            continue
        result.points.append(
            TurbinePoint(seq=len(result.points) + 1, turbine_no=str(seq), lon=lon, lat=lat)
        )

    if not result.points:
        raise WindLightningDensityError(
            "风机文件未解析出任何有效点位（需 11 列格式，前 6 列为经纬度度分秒）"
        )
    return result


def parse_turbine_excel(content: bytes) -> TurbineParseResult:
    """解析 Excel 风机表（列名映射：十进制度或度分秒两套写法）。"""
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise WindLightningDensityError("读取 Excel 需要 openpyxl 依赖") from exc

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - 统一转业务错误
        raise WindLightningDensityError("Excel 文件无法打开，请确认格式为 .xlsx") from exc

    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration as exc:
        raise WindLightningDensityError("Excel 文件为空") from exc

    index = _build_excel_index(header)
    if index["lon_dec"] is None and index["lon_dms"] is None:
        raise WindLightningDensityError(
            "Excel 缺少经度列（支持「经度/lon/longitude」或「经度度/经度分/经度秒」）"
        )
    if index["lat_dec"] is None and index["lat_dms"] is None:
        raise WindLightningDensityError(
            "Excel 缺少纬度列（支持「纬度/lat/latitude」或「纬度度/纬度分/纬度秒」）"
        )

    result = TurbineParseResult()
    seq = 0
    for row_no, row in enumerate(rows, start=2):
        if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        seq += 1
        lon = _excel_coord(row, index["lon_dec"], index["lon_dms"])
        lat = _excel_coord(row, index["lat_dec"], index["lat_dms"])
        if lon is None or lat is None or not _valid_lonlat(lon, lat):
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {row_no} 行风机坐标无法识别，已跳过")
            continue
        turbine_no = ""
        if index["no"] is not None and index["no"] < len(row):
            raw_no = row[index["no"]]
            turbine_no = "" if raw_no is None else str(raw_no).strip()
        result.points.append(
            TurbinePoint(
                seq=len(result.points) + 1,
                turbine_no=turbine_no or str(seq),
                lon=lon,
                lat=lat,
            )
        )

    if not result.points:
        raise WindLightningDensityError("Excel 未解析出任何有效风机点位")
    return result


def _normalize_header(value: Any) -> str:
    return re.sub(r"[\s_\-()（）]", "", str(value or "")).lower()


def _build_excel_index(header: Sequence[Any]) -> dict[str, Any]:
    """列名映射：十进制度（经度/lon）与度分秒（经度度/经度分/经度秒）两套写法。"""
    normalized = [_normalize_header(cell) for cell in header]

    def find(candidates: Iterable[str]) -> int | None:
        wanted = {_normalize_header(item) for item in candidates}
        for position, name in enumerate(normalized):
            if name in wanted:
                return position
        return None

    def find_dms(axis_cn: str, axis_en: str) -> tuple[int, int, int] | None:
        deg = find([f"{axis_cn}度", f"{axis_cn}d", f"{axis_cn}deg", f"{axis_en}d", f"{axis_en}deg", f"{axis_en}degree"])
        minute = find([f"{axis_cn}分", f"{axis_cn}m", f"{axis_cn}min", f"{axis_en}m", f"{axis_en}min", f"{axis_en}minute"])
        second = find([f"{axis_cn}秒", f"{axis_cn}s", f"{axis_cn}sec", f"{axis_en}s", f"{axis_en}sec", f"{axis_en}second"])
        if deg is not None and minute is not None and second is not None:
            return deg, minute, second
        return None

    return {
        "lon_dec": find(["经度", "lon", "longitude", "lng"]),
        "lat_dec": find(["纬度", "lat", "latitude"]),
        "lon_dms": find_dms("经度", "lon"),
        "lat_dms": find_dms("纬度", "lat"),
        "no": find(["风机编号", "机位号", "机组编号", "turbine_no", "turbineno", "编号", "no", "name"]),
    }


def _excel_coord(
    row: Sequence[Any],
    decimal_index: int | None,
    dms_index: tuple[int, int, int] | None,
) -> float | None:
    if dms_index is not None:
        deg_i, min_i, sec_i = dms_index
        if max(deg_i, min_i, sec_i) < len(row):
            try:
                return dms_to_decimal(
                    float(row[deg_i] or 0), float(row[min_i] or 0), float(row[sec_i] or 0)
                )
            except (TypeError, ValueError):
                return None
    if decimal_index is not None and decimal_index < len(row):
        return _coord_from_text(row[decimal_index])
    return None


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _valid_lonlat(lon: float, lat: float) -> bool:
    return -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0


# ---------------------------------------------------------------------------
# 雷电定位 CSV 解析
# ---------------------------------------------------------------------------
def parse_lightning_csv(content: bytes) -> LightningParseResult:
    """解析雷电定位 CSV（至少含 ``LONGITUDE`` / ``LATITUDE`` 两列）。

    只保留坐标可解析的记录；不做 CG/IC 类型筛选（与 density.py 一致）。
    """
    text = decode_text_bytes(content)
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise WindLightningDensityError("雷电 CSV 为空") from exc

    lon_index = _find_column(header, LON_HEADERS)
    lat_index = _find_column(header, LAT_HEADERS)
    if lon_index is None or lat_index is None:
        raise WindLightningDensityError(
            "雷电 CSV 缺少 LONGITUDE / LATITUDE 列，无法统计"
        )
    time_index = _find_column(header, TIME_HEADERS, exclude={lon_index, lat_index})

    lats: list[float] = []
    lons: list[float] = []
    years: set[int] = set()
    total = 0
    skipped = 0
    for row in reader:
        if not row or all(not str(cell).strip() for cell in row):
            continue
        total += 1
        if max(lon_index, lat_index) >= len(row):
            skipped += 1
            continue
        lon = _to_float(row[lon_index])
        lat = _to_float(row[lat_index])
        if lon is None or lat is None or not _valid_lonlat(lon, lat):
            skipped += 1
            continue
        lons.append(lon)
        lats.append(lat)
        if time_index is not None and time_index < len(row):
            match = _YEAR_RE.search(str(row[time_index]))
            if match:
                years.add(int(match.group(1)))

    if not lons:
        raise WindLightningDensityError("雷电 CSV 未解析出任何有效坐标记录，无法统计")

    return LightningParseResult(
        lat=np.asarray(lats, dtype=float),
        lon=np.asarray(lons, dtype=float),
        total_rows=total,
        valid_rows=len(lons),
        skipped_rows=skipped,
        detected_years=sorted(years),
    )


def _find_column(
    header: Sequence[Any],
    candidates: set[str],
    exclude: set[int] | None = None,
) -> int | None:
    exclude = exclude or set()
    for position, cell in enumerate(header):
        if position in exclude:
            continue
        name = str(cell or "").strip().strip('"').lower()
        if name in candidates:
            return position
    return None


# ---------------------------------------------------------------------------
# 范围、网格与统计
# ---------------------------------------------------------------------------
def compute_bbox(points: Sequence[TurbinePoint], margin_deg: float) -> BoundingBox:
    """风机经/纬度 min/max 四周各外扩 ``margin_deg``。"""
    if not points:
        raise WindLightningDensityError("风机点位为空，无法确定统计范围")
    if margin_deg < 0:
        raise WindLightningDensityError("外扩边距不能为负数")
    lons = [p.lon for p in points]
    lats = [p.lat for p in points]
    return BoundingBox(
        min_lon=min(lons) - margin_deg,
        max_lon=max(lons) + margin_deg,
        min_lat=min(lats) - margin_deg,
        max_lat=max(lats) + margin_deg,
    )


def build_bins(bbox: BoundingBox, step_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """``np.arange(min, max + step, step)`` 含终点，与 density.py 完全一致。"""
    if step_deg <= 0:
        raise WindLightningDensityError("网格步长必须大于 0")
    lon_bins = np.arange(bbox.min_lon, bbox.max_lon + step_deg, step_deg)
    lat_bins = np.arange(bbox.min_lat, bbox.max_lat + step_deg, step_deg)
    return lon_bins, lat_bins


def grid_shape(lon_bins: np.ndarray, lat_bins: np.ndarray) -> tuple[int, int]:
    """返回 (x_count 经度列数, y_count 纬度行数)。"""
    return max(len(lon_bins) - 1, 0), max(len(lat_bins) - 1, 0)


def validate_grid(bbox: BoundingBox, step_deg: float) -> tuple[int, int]:
    """校验网格规模，返回 (x_count, y_count)；超限抛业务错误。"""
    lon_bins, lat_bins = build_bins(bbox, step_deg)
    x_count, y_count = grid_shape(lon_bins, lat_bins)
    if x_count <= 0 or y_count <= 0:
        raise WindLightningDensityError("网格行列数不足，请检查风机范围与网格步长")
    if x_count > MAX_GRID_AXIS or y_count > MAX_GRID_AXIS:
        raise WindLightningDensityError(
            f"网格数 {x_count}×{y_count} 超过单边 {MAX_GRID_AXIS} 的上限，请增大网格步长或缩小范围"
        )
    return x_count, y_count


def cell_area_km2(step_deg: float) -> float:
    """单个网格面积（km²）：核心程序按 1° = 100 km 近似，0.01° → 1 km²。"""
    return (float(step_deg) * DEG_KM_APPROX) ** 2


def filter_in_range(
    lon: np.ndarray, lat: np.ndarray, bbox: BoundingBox
) -> tuple[np.ndarray, np.ndarray, int]:
    """只保留落在统计范围内的记录，返回 (lon, lat, 范围内条数)。"""
    mask = (
        (lon >= bbox.min_lon)
        & (lon <= bbox.max_lon)
        & (lat >= bbox.min_lat)
        & (lat <= bbox.max_lat)
    )
    return lon[mask], lat[mask], int(mask.sum())


def histogram2d(
    lon: np.ndarray, lat: np.ndarray, lon_bins: np.ndarray, lat_bins: np.ndarray
) -> np.ndarray:
    """落雷计数矩阵（行=y 纬度，列=x 经度），等价 ``np.histogram2d``。"""
    counts, _, _ = np.histogram2d(lat, lon, bins=[lat_bins, lon_bins])
    return counts


def density_from_counts(
    counts: np.ndarray, *, data_years: float, step_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """计数矩阵 → (次/(格·年), 次/(km²·年))。"""
    years = float(data_years) if data_years and data_years > 0 else DEFAULT_DATA_YEARS
    per_cell = counts.astype(float) / years
    per_km2 = per_cell / max(cell_area_km2(step_deg), 1e-12)
    return per_cell, per_km2


def cell_index(value: float, edges: np.ndarray) -> int:
    """数值 → 网格下标（与 ``np.histogram2d`` 的 ``[left, right)`` 含右端闭区间一致）。"""
    position = int(np.searchsorted(edges, value, side="right")) - 1
    last = len(edges) - 2
    if position < 0:
        return 0
    if position > last:
        return last
    return position


def build_cells(
    counts: np.ndarray,
    lon_bins: np.ndarray,
    lat_bins: np.ndarray,
    *,
    data_years: float,
    step_deg: float,
    turbine_counts: dict[tuple[int, int], int] | None = None,
) -> list[dict[str, Any]]:
    """把计数矩阵展开为网格明细。

    只返回「有落雷或有风机」的网格，避免 500×500 时写入 25 万行空值；
    完整矩阵可随时由 counts 重建（出图与逐格校验走矩阵本身）。
    """
    per_cell, per_km2 = density_from_counts(
        counts, data_years=data_years, step_deg=step_deg
    )
    turbine_counts = turbine_counts or {}
    rows: list[dict[str, Any]] = []
    y_count, x_count = counts.shape
    for i in range(x_count):
        for j in range(y_count):
            strike_count = int(counts[j, i])
            turbine_count = int(turbine_counts.get((i, j), 0))
            if strike_count == 0 and turbine_count == 0:
                continue
            min_lon = float(lon_bins[i])
            max_lon = float(lon_bins[i + 1])
            min_lat = float(lat_bins[j])
            max_lat = float(lat_bins[j + 1])
            rows.append(
                {
                    "cell_i": i,
                    "cell_j": j,
                    "center_lon": (min_lon + max_lon) / 2.0,
                    "center_lat": (min_lat + max_lat) / 2.0,
                    "min_lon": min_lon,
                    "max_lon": max_lon,
                    "min_lat": min_lat,
                    "max_lat": max_lat,
                    "strike_count": strike_count,
                    "density_per_cell_year": float(per_cell[j, i]),
                    "density_per_km2_year": float(per_km2[j, i]),
                    "turbine_count": turbine_count,
                }
            )
    return rows


def assign_turbines(
    points: Sequence[TurbinePoint],
    lon_bins: np.ndarray,
    lat_bins: np.ndarray,
    per_km2: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int], int]]:
    """风机 → 所在网格下标与网格密度；返回 (明细, 每格风机数)。"""
    rows: list[dict[str, Any]] = []
    turbine_counts: dict[tuple[int, int], int] = {}
    for point in points:
        i = cell_index(point.lon, lon_bins)
        j = cell_index(point.lat, lat_bins)
        turbine_counts[(i, j)] = turbine_counts.get((i, j), 0) + 1
        rows.append(
            {
                "seq": point.seq,
                "turbine_no": point.turbine_no,
                "lon": point.lon,
                "lat": point.lat,
                "cell_i": i,
                "cell_j": j,
                "cell_density": float(per_km2[j, i]),
            }
        )
    return rows, turbine_counts


def compute_stats(
    counts: np.ndarray,
    *,
    data_years: float,
    step_deg: float,
    total_records: int,
    valid_records: int,
    skipped_records: int,
    turbine_count: int,
    years_source: str,
) -> dict[str, Any]:
    """批次统计卡数据（整体/峰值密度、面积、年限来源等）。"""
    x_count, y_count = counts.shape[1], counts.shape[0]
    area = x_count * y_count * cell_area_km2(step_deg)
    per_cell, per_km2 = density_from_counts(
        counts, data_years=data_years, step_deg=step_deg
    )
    total_strikes = int(counts.sum())
    overall = float(total_strikes / (data_years * area)) if area > 0 else 0.0
    if counts.size and total_strikes > 0:
        flat_index = int(np.argmax(per_km2))
        peak_j, peak_i = divmod(flat_index, x_count)
        peak = float(per_km2[peak_j, peak_i])
    else:
        peak, peak_i, peak_j = 0.0, -1, -1
    return {
        "turbine_count": turbine_count,
        "total_records": total_records,
        "valid_records": valid_records,
        "skipped_records": skipped_records,
        "in_range_strikes": valid_records,
        "total_strikes": total_strikes,
        "grid_x_count": x_count,
        "grid_y_count": y_count,
        "cell_count": x_count * y_count,
        "cell_area_km2": cell_area_km2(step_deg),
        "area_km2": area,
        "data_years": data_years,
        "years_source": years_source,
        "overall_density": overall,
        "peak_density": peak,
        "peak_cell_i": peak_i,
        "peak_cell_j": peak_j,
        "non_empty_cells": int(np.count_nonzero(per_cell > 0)),
    }


# ---------------------------------------------------------------------------
# 核心程序文件（file_3 / file_4）
# ---------------------------------------------------------------------------
def core_grid(bbox: BoundingBox, step_deg: float) -> dict[str, float | int]:
    """核心程序风电场研究区域网格（与 file_1.txt 口径一致）。

    ``fengji_bianhao.py`` 的网格编号以**整度**为原点：``start_lon = int(119.34…) = 119``、
    ``x_count = (int(max_lon) + 1 - start_lon) / step``。样例 ``file_1.txt`` 的
    ``119 / 25 / 100 / 100`` 正是该口径的结果，故这里保持一致，保证导出的 grid_id
    与既有核心程序逐行对应。
    """
    start_lon = float(int(bbox.min_lon))
    start_lat = float(int(bbox.min_lat))
    if step_deg <= 0:
        raise WindLightningDensityError("网格步长必须大于 0")
    x_count = int(round((int(bbox.max_lon) + 1 - start_lon) / step_deg))
    y_count = int(round((int(bbox.max_lat) + 1 - start_lat) / step_deg))
    if x_count <= 0 or y_count <= 0:
        raise WindLightningDensityError("核心程序网格行列数计算异常，请检查风机范围")
    return {
        "start_lon": start_lon,
        "start_lat": start_lat,
        "x_count": x_count,
        "y_count": y_count,
        "step_deg": float(step_deg),
    }


def core_bins(grid: dict[str, float | int]) -> tuple[np.ndarray, np.ndarray]:
    """核心程序网格边界（整度起点 + 固定步长的等距坐标）。"""
    step = float(grid["step_deg"])
    x_count = int(grid["x_count"])
    y_count = int(grid["y_count"])
    start_lon = float(grid["start_lon"])
    start_lat = float(grid["start_lat"])
    lon_edges = start_lon + np.arange(x_count + 1) * step
    lat_edges = start_lat + np.arange(y_count + 1) * step
    return lon_edges, lat_edges


def core_density_matrix(
    lon: np.ndarray,
    lat: np.ndarray,
    grid: dict[str, float | int],
    data_years: float,
) -> np.ndarray:
    """研究区域网格上的密度矩阵（次/(km²·年)），与 ``dishan_tongji.py`` 口径一致。"""
    lon_edges, lat_edges = core_bins(grid)
    counts, _, _ = np.histogram2d(lat, lon, bins=[lat_edges, lon_edges])
    per_cell, per_km2 = density_from_counts(
        counts, data_years=data_years, step_deg=float(grid["step_deg"])
    )
    return per_km2


def core_grid_id(lon: float, lat: float, grid: dict[str, float | int]) -> tuple[int, int, int]:
    """风机 → (grid_id, i, j)，与 ``fengji_bianhao.py`` 完全一致（先 round 6 位再取整）。"""
    x_count = int(grid["x_count"])
    lon0 = int(float(grid["start_lon"]) * 100)
    lat0 = int(float(grid["start_lat"]) * 100)
    i = int(round(float(lon), 6) * 100) - lon0
    j = int(round(float(lat), 6) * 100) - lat0
    return j * x_count + i + 1, i, j


def build_core_files(
    turbines: Sequence[dict[str, Any]],
    grid: dict[str, float | int],
    core_density: np.ndarray,
) -> tuple[list[str], list[str]]:
    """生成 ``file_3.txt`` / ``file_4.txt`` 的行内容。

    - file_3：``grid_id  0 0.2 0.2 0.2 0.2 0.1 0.1``，``grid_id = j * x_count + i + 1``，
      ``i = int(lon*100) - int(start_lon*100)``、``j = int(lat*100) - int(start_lat*100)``
      （与 ``fengji_bianhao.py`` 一致）；
    - file_4：与 file_3 的 grid_id 逐行对应的该网格密度（次/(km²·年)），
      与核心程序 ``Nl`` 口径一致。
    """
    y_count, x_count = core_density.shape
    file3: list[str] = []
    file4: list[str] = []
    for turbine in turbines:
        grid_id, i, j = core_grid_id(float(turbine["lon"]), float(turbine["lat"]), grid)
        density = (
            float(core_density[j, i]) if 0 <= i < x_count and 0 <= j < y_count else 0.0
        )
        file3.append(f"{grid_id}\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n")
        file4.append(f"{density}\n")
    if len(file3) != len(file4):
        raise WindLightningDensityError("file_3 与 file_4 行数不一致，已中止导出")
    return file3, file4


# ---------------------------------------------------------------------------
# 出图
# ---------------------------------------------------------------------------
def build_colormap():  # type: ignore[no-untyped-def]
    """灰 → 蓝 → 黄 → 红 线性色带（density.py 同款 4 个色标，256 级）。"""
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("gray_blue_yellow_red", list(COLOR_STOPS), N=256)


def _safe_title(title: str, fallback: str = "Wind Farm") -> str:
    ascii_title = "".join(ch for ch in (title or "") if ord(ch) < 128).strip()
    return ascii_title or fallback


def render_density_png(
    matrix: np.ndarray,
    *,
    lon_bins: np.ndarray,
    lat_bins: np.ndarray,
    title: str,
    colorbar_label: str,
    interpolation: str = "bilinear",
) -> bytes:
    """按 density.py 的渲染参数输出 PNG 字节。

    ``origin="lower"``、``aspect="auto"``、``extent`` 取网格边界、线性色带。
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    if interpolation not in {"bilinear", "nearest"}:
        interpolation = "bilinear"

    extent = [
        float(lon_bins.min()),
        float(lon_bins.max()),
        float(lat_bins.min()),
        float(lat_bins.max()),
    ]
    figure = plt.figure(figsize=(9, 7))
    try:
        axis = figure.add_subplot(1, 1, 1)
        image = axis.imshow(
            matrix,
            origin="lower",
            extent=extent,
            aspect="auto",
            cmap=build_colormap(),
            interpolation=interpolation,
        )
        figure.colorbar(image, ax=axis, label=colorbar_label)
        axis.set_xlabel("Longitude (°)")
        axis.set_ylabel("Latitude (°)")
        axis.set_title(_safe_title(title, fallback="Wind Farm Ground Flash Density"))
        figure.tight_layout()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(figure)


def render_batch_png(
    *,
    counts: np.ndarray,
    lon_bins: np.ndarray,
    lat_bins: np.ndarray,
    data_years: float,
    step_deg: float,
    title: str,
    unit: str = "km2",
    interpolation: str = "bilinear",
) -> bytes:
    """按单位（per cell / per km²）渲染密度图。"""
    per_cell, per_km2 = density_from_counts(
        counts, data_years=data_years, step_deg=step_deg
    )
    if unit == "cell":
        matrix = per_cell
        label = "Ground Flash Density (count / (cell·year))"
    else:
        matrix = per_km2
        label = "Ground Flash Density (count / (km²·year))"
    return render_density_png(
        matrix,
        lon_bins=lon_bins,
        lat_bins=lat_bins,
        title=title,
        colorbar_label=label,
        interpolation=interpolation,
    )


def matrix_from_cells(
    cells: Sequence[dict[str, Any]], x_count: int, y_count: int
) -> np.ndarray:
    """由网格明细（只存非空格）重建完整计数矩阵，用于重新出图。"""
    matrix = np.zeros((y_count, x_count), dtype=float)
    for cell in cells:
        i = int(cell["cell_i"])
        j = int(cell["cell_j"])
        if 0 <= i < x_count and 0 <= j < y_count:
            matrix[j, i] = float(cell["strike_count"])
    return matrix
