"""风电场网格公共内核 —— 纯函数，不依赖 FastAPI / 数据库。

被「风电场数据准备」(LP-33) 与「风电场地闪密度统计」(LP-32) 共同复用，
保证两处对同一批点位算出的逐格计数一致。

编号口径（严格对齐核心程序 ``FengLiFangLei-10.exe``）：

1. 内部只用 ``(i, j)`` 定位：``i = floor((lon - lon0)/ddeg)``、
   ``j = floor((lat - lat0)/ddeg)``；写 ``file_3`` 时才 ``grid_id = j*nx + i + 1``。
   **禁止**用 0 起的 ``row*nx+col`` 去匹配 1 起编号（会让 58 台里 56 台取到东邻格）。
2. 取整必须用 ``floor``，不能用 ``astype(int)``：负值会被截断到 0，
   导致研究区西/南侧越界记录误入第 0 列。这里对浮点误差加极小容差后再 floor，
   并用整数分度做兜底（0.01° 网格等价于「百分度整数差」）。
3. 起始坐标必须是 0.01° 的整数倍（P0.abc 头部把坐标×100 存为 2 字节整数）。
4. ``nx/ny ≤ 100``（核心程序 ``NMAX=100``）。
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

# 核心程序固定口径
DEFAULT_DDEG = 0.01
MAX_GRID_AXIS = 100
DATA_YEARS = 6
# 坐标×100 的对齐容差（度）
ALIGN_TOL = 1e-7
# floor 的浮点容差（度）：约 0.1 mm，远小于一个网格
FLOOR_EPS = 1e-9

LON_HEADERS = {"longitude", "lon", "lng", "经度"}
LAT_HEADERS = {"latitude", "lat", "纬度"}
TIME_HEADERS = {"datetime", "time", "date", "时间", "时刻", "日期", "发生时间", "inputtime"}
TYPE_HEADERS = {"type", "kind", "类型", "雷电流类型", "闪击类型"}

_DMS_SYMBOL_RE = re.compile(r"[°′'\"”″]")
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


class WindGridError(ValueError):
    """输入不合法（调用方转 400 并给出明确文案）。"""


# ---------------------------------------------------------------------------
# 通用解析
# ---------------------------------------------------------------------------
def decode_text_bytes(content: bytes) -> str:
    """UTF-8(BOM) → GBK → latin-1 顺序解码（源数据多为 GBK/UTF-8）。"""
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("latin-1", errors="replace")


def dms_to_decimal(deg: float, minute: float, second: float) -> float:
    """度分秒 → 十进制度：``d + m/60 + s/3600``。"""
    return float(deg) + float(minute) / 60.0 + float(second) / 3600.0


def decimal_to_dms(value: float, *, seconds_decimals: int = 6) -> tuple[int, int, float]:
    """十进制度 → (度, 分, 秒)，带进位，避免秒出现 60。"""
    sign = -1 if value < 0 else 1
    absolute = abs(float(value))
    deg = int(absolute)
    remainder = (absolute - deg) * 60.0
    minute = int(remainder)
    second = round((remainder - minute) * 60.0, seconds_decimals)
    if second >= 60.0:
        second -= 60.0
        minute += 1
    if minute >= 60:
        minute -= 60
        deg += 1
    return sign * deg, minute, second


def parse_dms_compact(value: Any) -> tuple[float, float, float] | None:
    """从 ``121 11 18.339516`` / ``121°11'18.34"`` / ``121°11'18.34"E`` 提取 (度,分,秒)。"""
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


def to_float(value: Any) -> float | None:
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


def _valid_lonlat(lon: float, lat: float) -> bool:
    return -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class TurbinePoint:
    seq: int
    turbine_no: str
    lon: float
    lat: float
    lon_dms: tuple[float, float, float]
    lat_dms: tuple[float, float, float]
    input_elev: float = 0.0
    height: float = 0.0
    blade: float = 0.0
    motion: int = 1
    circuit: int = 1


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
    type_distribution: dict[str, int] = field(default_factory=dict)

    @property
    def time_span(self) -> str:
        if not self.detected_years:
            return "未识别到时间列"
        first, last = min(self.detected_years), max(self.detected_years)
        return str(first) if first == last else f"{first}–{last}"


# ---------------------------------------------------------------------------
# 风机文件解析（file_2.txt / Excel，三种 DMS 写法）
# ---------------------------------------------------------------------------
def _extra_fields(columns: Sequence[str], start: int) -> tuple[float, float, float, int, int]:
    """读取“输入高程/风机高度/叶片长度/动静状态/回路号”，缺失给默认值。"""
    values: list[float | None] = []
    for offset in range(5):
        index = start + offset
        values.append(to_float(columns[index]) if index < len(columns) else None)

    def number(index: int, default: float) -> float:
        value = values[index]
        return value if value is not None else default

    return (
        number(0, 0.0),  # 输入高程（会被 P0.abc 覆盖，仅占位）
        number(1, 0.0),  # 风机高度
        number(2, 0.0),  # 叶片长度
        int(number(3, 1)),  # 动静状态
        int(number(4, 1)),  # 回路号
    )


def _valid_dms_parts(parts: tuple[float, float, float]) -> bool:
    """分/秒必须落在 0–60，避免把十进制度的 7 列误判成 DMS 分列。"""
    _, minute, second = parts
    return 0.0 <= minute < 60.0 and 0.0 <= second < 60.0


def _parse_turbine_columns(
    columns: Sequence[str],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float, int, int]] | None:
    """返回 (lon_dms, lat_dms, 附加字段)，无法解析返回 None。

    支持三种写法：
    - DMS 分列：``经度度 经度分 经度秒 纬度度 纬度分 纬度秒 ...``（file_2 原格式）；
    - DMS 合并：``121°11'18.34" 25°23'34.78" ...``；
    - 十进制度：``121.188 25.393 ...``。
    """
    # 1) DMS 分列（前 6 列都能按数字解析）
    if len(columns) >= 6:
        try:
            lon_tuple = (float(columns[0]), float(columns[1]), float(columns[2]))
            lat_tuple = (float(columns[3]), float(columns[4]), float(columns[5]))
        except ValueError:
            lon_tuple = lat_tuple = None  # type: ignore[assignment]
        if (
            lon_tuple is not None
            and lat_tuple is not None
            and _valid_dms_parts(lon_tuple)
            and _valid_dms_parts(lat_tuple)
        ):
            return lon_tuple, lat_tuple, _extra_fields(columns, 6)

    # 2) DMS 合并（单列写全度分秒）
    if len(columns) >= 2:
        lon_tuple = parse_dms_compact(columns[0])
        lat_tuple = parse_dms_compact(columns[1])
        if lon_tuple is not None and lat_tuple is not None and columns[0] and columns[1]:
            try:
                float(columns[0])
                float(columns[1])
                # 纯数字（十进制）不走此分支
                lon_tuple = None
            except ValueError:
                pass
        if (
            lon_tuple is not None
            and lat_tuple is not None
            and _valid_dms_parts(lon_tuple)
            and _valid_dms_parts(lat_tuple)
        ):
            return lon_tuple, lat_tuple, _extra_fields(columns, 2)

    # 3) 十进制度
    if len(columns) >= 2:
        lon = to_float(columns[0])
        lat = to_float(columns[1])
        if lon is not None and lat is not None:
            lon_dms = decimal_to_dms(lon)
            lat_dms = decimal_to_dms(lat)
            return (
                (float(lon_dms[0]), float(lon_dms[1]), float(lon_dms[2])),
                (float(lat_dms[0]), float(lat_dms[1]), float(lat_dms[2])),
                _extra_fields(columns, 2),
            )
    return None


def parse_turbine_file(content: bytes, filename: str) -> TurbineParseResult:
    """按扩展名分派：``.xlsx/.xlsm`` 走 Excel，其余按文本解析。"""
    suffix = (
        (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    )
    if suffix in {"xlsx", "xlsm"}:
        return parse_turbine_excel(content)
    return parse_turbine_txt(content)


def _make_point(
    seq: int,
    turbine_no: str,
    lon_tuple: tuple[float, float, float],
    lat_tuple: tuple[float, float, float],
    extra: tuple[float, float, float, int, int],
) -> TurbinePoint | None:
    lon = dms_to_decimal(*lon_tuple)
    lat = dms_to_decimal(*lat_tuple)
    if not _valid_lonlat(lon, lat):
        return None
    return TurbinePoint(
        seq=seq,
        turbine_no=turbine_no or str(seq),
        lon=lon,
        lat=lat,
        lon_dms=lon_tuple,
        lat_dms=lat_tuple,
        input_elev=extra[0],
        height=extra[1],
        blade=extra[2],
        motion=extra[3],
        circuit=extra[4],
    )


def parse_turbine_txt(content: bytes) -> TurbineParseResult:
    """解析风机文本（11 列空白/逗号/分号分隔，兼容合并 DMS 与十进制）。"""
    text = decode_text_bytes(content)
    result = TurbineParseResult()
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        columns = re.split(r"[\s,;]+", line)
        if line_no == 1 and _parse_turbine_columns(columns) is None:
            continue  # 表头
        parsed = _parse_turbine_columns(columns)
        if parsed is None:
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {line_no} 行风机坐标无法识别，已跳过")
            continue
        lon_tuple, lat_tuple, extra = parsed
        point = _make_point(
            len(result.points) + 1, str(len(result.points) + 1), lon_tuple, lat_tuple, extra
        )
        if point is None:
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {line_no} 行风机坐标越界，已跳过")
            continue
        result.points.append(point)

    if not result.points:
        raise WindGridError("风机文件未解析出任何有效点位（需 11 列 / DMS 合并 / 十进制格式）")
    return result


def _normalize_header(value: Any) -> str:
    return re.sub(r"[\s_\-()（）]", "", str(value or "")).lower()


def _build_excel_index(header: Sequence[Any]) -> dict[str, Any]:
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
        "lon_compact": find(["经度dms", "经度度分秒", "londms", "lonlat"]),
        "lat_compact": find(["纬度dms", "纬度度分秒", "latdms"]),
        "no": find(["风机编号", "机位号", "机组编号", "turbine_no", "turbineno", "编号", "no", "name"]),
        "elev": find(["输入高程", "高程", "elevation", "elev"]),
        "height": find(["风机高度", "离地高度", "轮毂高度", "高度", "height", "hubheight"]),
        "blade": find(["叶片长度", "叶长", "blade", "bladelength"]),
        "motion": find(["动静状态", "状态", "motion", "status"]),
        "circuit": find(["回路号", "回路", "circuit", "circuitno"]),
    }


def _excel_value(
    row: Sequence[Any],
    index: int | None,
    *,
    dms: tuple[int, int, int] | None = None,
    compact: int | None = None,
) -> tuple[float, float, float] | float | None:
    if dms is not None and max(dms) < len(row):
        try:
            return (
                float(row[dms[0]] or 0),
                float(row[dms[1]] or 0),
                float(row[dms[2]] or 0),
            )
        except (TypeError, ValueError):
            return None
    if compact is not None and compact < len(row):
        return parse_dms_compact(row[compact])
    if index is not None and index < len(row):
        return to_float(row[index])
    return None


def parse_turbine_excel(content: bytes) -> TurbineParseResult:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise WindGridError("读取 Excel 需要 openpyxl 依赖") from exc

    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise WindGridError("Excel 文件无法打开，请确认格式为 .xlsx") from exc

    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    try:
        header = next(rows)
    except StopIteration as exc:
        raise WindGridError("Excel 文件为空") from exc

    index = _build_excel_index(header)
    if not any(
        index[key] is not None
        for key in ("lon_dec", "lon_dms", "lon_compact")
    ):
        raise WindGridError("Excel 缺少经度列（经度 / 经度度分秒 / 十进制）")

    result = TurbineParseResult()
    for row_no, row in enumerate(rows, start=2):
        if row is None or all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        lon_raw = _excel_value(row, index["lon_dec"], dms=index["lon_dms"], compact=index["lon_compact"])
        lat_raw = _excel_value(row, index["lat_dec"], dms=index["lat_dms"], compact=index["lat_compact"])
        if isinstance(lon_raw, tuple) and isinstance(lat_raw, tuple):
            lon_tuple, lat_tuple = lon_raw, lat_raw
        elif isinstance(lon_raw, (int, float)) and isinstance(lat_raw, (int, float)):
            lon_dms = decimal_to_dms(float(lon_raw))
            lat_dms = decimal_to_dms(float(lat_raw))
            lon_tuple = (float(lon_dms[0]), float(lon_dms[1]), float(lon_dms[2]))
            lat_tuple = (float(lat_dms[0]), float(lat_dms[1]), float(lat_dms[2]))
        else:
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {row_no} 行风机坐标无法识别，已跳过")
            continue

        def field_value(key: str, default: float) -> float:
            position = index[key]
            if position is None or position >= len(row):
                return default
            value = to_float(row[position])
            return default if value is None else value

        extra: tuple[float, float, float, int, int] = (
            field_value("elev", 0.0),
            field_value("height", 0.0),
            field_value("blade", 0.0),
            int(field_value("motion", 1)),
            int(field_value("circuit", 1)),
        )
        turbine_no = ""
        no_index = index["no"]
        if no_index is not None and no_index < len(row) and row[no_index] is not None:
            turbine_no = str(row[no_index]).strip()
        point = _make_point(len(result.points) + 1, turbine_no, lon_tuple, lat_tuple, extra)
        if point is None:
            result.skipped += 1
            if len(result.warnings) < 20:
                result.warnings.append(f"第 {row_no} 行风机坐标越界，已跳过")
            continue
        result.points.append(point)

    if not result.points:
        raise WindGridError("Excel 未解析出任何有效风机点位")
    return result


# ---------------------------------------------------------------------------
# 雷电定位 CSV 解析
# ---------------------------------------------------------------------------
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


def parse_lightning_csv(content: bytes) -> LightningParseResult:
    """解析雷电定位 CSV（至少含经纬度列），不做 CG/IC/NB 筛选。"""
    text = decode_text_bytes(content)
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise WindGridError("雷电 CSV 为空") from exc

    lon_index = _find_column(header, LON_HEADERS)
    lat_index = _find_column(header, LAT_HEADERS)
    if lon_index is None or lat_index is None:
        raise WindGridError("雷电 CSV 缺少 LONGITUDE / LATITUDE 列，无法统计")
    time_index = _find_column(header, TIME_HEADERS, exclude={lon_index, lat_index})
    type_index = _find_column(header, TYPE_HEADERS, exclude={lon_index, lat_index})

    lons: list[float] = []
    lats: list[float] = []
    years: set[int] = set()
    types: Counter[str] = Counter()
    total = 0
    skipped = 0
    for row in reader:
        if not row or all(not str(cell).strip() for cell in row):
            continue
        total += 1
        if max(lon_index, lat_index) >= len(row):
            skipped += 1
            continue
        lon = to_float(row[lon_index])
        lat = to_float(row[lat_index])
        if lon is None or lat is None or not _valid_lonlat(lon, lat):
            skipped += 1
            continue
        lons.append(lon)
        lats.append(lat)
        if time_index is not None and time_index < len(row):
            match = _YEAR_RE.search(str(row[time_index]))
            if match:
                years.add(int(match.group(1)))
        if type_index is not None and type_index < len(row):
            label = str(row[type_index]).strip().upper() or "UNKNOWN"
            types[label] += 1

    if not lons:
        raise WindGridError("雷电 CSV 未解析出任何有效坐标记录，无法统计")

    return LightningParseResult(
        lat=np.asarray(lats, dtype=float),
        lon=np.asarray(lons, dtype=float),
        total_rows=total,
        valid_rows=len(lons),
        skipped_rows=skipped,
        detected_years=sorted(years),
        type_distribution=dict(types),
    )


# ---------------------------------------------------------------------------
# 网格校验、编号与聚合
# ---------------------------------------------------------------------------
def is_aligned(value: float, ddeg: float = DEFAULT_DDEG) -> bool:
    """坐标是否为 0.01°（ddeg）的整数倍。"""
    scaled = float(value) / float(ddeg)
    return abs(scaled - round(scaled)) <= ALIGN_TOL / float(ddeg)


def validate_grid(
    start_lon: float,
    start_lat: float,
    nx: int,
    ny: int,
    ddeg: float = DEFAULT_DDEG,
) -> None:
    """区域硬约束：0.01° 对齐、行列数 1..100、步长 > 0。"""
    if not (math.isfinite(start_lon) and math.isfinite(start_lat)):
        raise WindGridError("起始经纬度必须为有限数值")
    if ddeg <= 0:
        raise WindGridError("网格步长必须大于 0")
    if not is_aligned(start_lon, ddeg) or not is_aligned(start_lat, ddeg):
        raise WindGridError(
            f"起始经纬度必须是 {ddeg:.2f}° 的整数倍（例如 119.34、25.23）；"
            "P0.abc 头部以坐标×100 存为 2 字节整数"
        )
    for label, value in (("经向网格数 nx", nx), ("纬向网格数 ny", ny)):
        if int(value) != value or value < 1 or value > MAX_GRID_AXIS:
            raise WindGridError(f"{label} 必须在 1–{MAX_GRID_AXIS} 之间（核心程序 NMAX=100）")


def grid_cell(
    lon: float,
    lat: float,
    start_lon: float,
    start_lat: float,
    nx: int,
    ny: int,
    ddeg: float = DEFAULT_DDEG,
) -> tuple[int, int, int, bool]:
    """点位 → ``(i, j, grid_id, in_scope)``。

    ``i = floor((lon-lon0)/ddeg)``、``j = floor((lat-lat0)/ddeg)``（含浮点容差），
    ``grid_id = j*nx + i + 1``。越界（i/j 不在 0..nx-1/0..ny-1）时
    ``in_scope=False``，grid_id 仍按公式给出但不代表有效网格。
    """
    i = int(math.floor((float(lon) - float(start_lon)) / float(ddeg) + FLOOR_EPS))
    j = int(math.floor((float(lat) - float(start_lat)) / float(ddeg) + FLOOR_EPS))
    in_scope = 0 <= i < nx and 0 <= j < ny
    return i, j, j * nx + i + 1, in_scope


def grid_cells_vectorized(
    lon: np.ndarray,
    lat: np.ndarray,
    start_lon: float,
    start_lat: float,
    nx: int,
    ny: int,
    ddeg: float = DEFAULT_DDEG,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """向量化版本，返回 (i, j, mask)，供 10 万条记录聚合使用。"""
    i = np.floor((lon - start_lon) / float(ddeg) + FLOOR_EPS).astype(np.int64)
    j = np.floor((lat - start_lat) / float(ddeg) + FLOOR_EPS).astype(np.int64)
    mask = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
    return i, j, mask


def aggregate_flashes(
    lon: np.ndarray,
    lat: np.ndarray,
    start_lon: float,
    start_lat: float,
    nx: int,
    ny: int,
    ddeg: float = DEFAULT_DDEG,
) -> tuple[np.ndarray, int, int]:
    """逐格落雷计数矩阵（行=j 纬度，列=i 经度），返回 (counts, 范围内条数, 越界条数)。"""
    counts = np.zeros((ny, nx), dtype=np.int64)
    i, j, mask = grid_cells_vectorized(
        np.asarray(lon, dtype=float),
        np.asarray(lat, dtype=float),
        start_lon,
        start_lat,
        nx,
        ny,
        ddeg,
    )
    np.add.at(counts, (j[mask], i[mask]), 1)
    return counts, int(mask.sum()), int((~mask).sum())
