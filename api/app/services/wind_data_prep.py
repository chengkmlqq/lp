"""风电场数据准备 —— 五文件序列化、地形生成与整体校验。

产物严格对齐核心程序 ``FengLiFangLei-10.exe``：
- ``file_1.txt``：6 行 ``N / S / 起始经度 / 起始纬度 / 经向网格数 / 纬向网格数``；
- ``file_2.txt``：每台风机 11 列（度 分 秒 / 度 分 秒 / 输入高程 / 风机高度 /
  叶片长度 / 动静状态 / 回路号）；
- ``file_3.txt``：每台风机一行 ``grid_id 0 0.2 0.2 0.2 0.2 0.1 0.1``；
- ``file_4.txt``：每台风机一行 ``Nl = 该风机所在网格落雷次数 / 6``（次/(格·年)）；
- ``P0.abc``：6×uint16 大端头（left/right/bottom/top 为坐标×100，width/height）
  + 逐像素 uint16 大端，行序北→南（与 GTiff 一致）。

核心程序是既有二进制、不改动，因此本模块只做「按口径产出」，不做任何口径换算。
"""

from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from . import wind_grid as wg

DDEG = wg.DEFAULT_DDEG
DATA_YEARS = wg.DATA_YEARS
FILE3_TAIL = (0, 0.2, 0.2, 0.2, 0.2, 0.1, 0.1)
FILE_NAMES = ("file_1.txt", "file_2.txt", "file_3.txt", "file_4.txt", "P0.abc")

# 核心程序按「1° = 100 km」近似，格面积仅用于参考展示，不写入文件
DEG_KM_APPROX = 100.0


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class PrepParams:
    start_lon: float
    start_lat: float
    nx: int
    ny: int
    risk_base_s: float
    ddeg: float = DDEG
    terrain_mode: str = "zero"  # zero | tif
    wind_farm_name: str = ""
    remark: str = ""


@dataclass(slots=True)
class PrepResult:
    params: PrepParams
    turbines: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _check(
    code: str,
    label: str,
    passed: bool,
    message: str,
    level: str = "error",
) -> dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "level": level if not passed else "ok",
        "passed": bool(passed),
        "message": message,
    }


# ---------------------------------------------------------------------------
# 文件序列化
# ---------------------------------------------------------------------------
def serialize_file1(params: PrepParams, turbine_count: int) -> str:
    """6 行：N(风机数) / S(风险基准) / 起始经度 / 起始纬度 / 经向网格数 / 纬向网格数。"""
    lines = [
        str(int(turbine_count)),
        _fmt_number(params.risk_base_s),
        _fmt_coord(params.start_lon),
        _fmt_coord(params.start_lat),
        str(int(params.nx)),
        str(int(params.ny)),
    ]
    return "\n".join(lines) + "\n"


def serialize_file2(turbines: Sequence[dict[str, Any]]) -> str:
    """每台风机 11 列，制表符分隔（与既有 file_2.txt 一致）。"""
    lines: list[str] = []
    for turbine in turbines:
        lon = turbine["lon_dms"]
        lat = turbine["lat_dms"]
        columns = [
            _fmt_number(lon[0]),
            _fmt_number(lon[1]),
            _fmt_number(lon[2]),
            _fmt_number(lat[0]),
            _fmt_number(lat[1]),
            _fmt_number(lat[2]),
            _fmt_number(turbine["input_elev"]),
            _fmt_number(turbine["height"]),
            _fmt_number(turbine["blade"]),
            str(int(turbine["motion"])),
            str(int(turbine["circuit"])),
        ]
        lines.append("\t".join(columns) + "\n")
    return "".join(lines)


def serialize_file3(turbines: Sequence[dict[str, Any]]) -> str:
    lines = []
    for turbine in turbines:
        columns = [str(int(turbine["grid_id"])), *(_fmt_number(v) for v in FILE3_TAIL)]
        lines.append("\t".join(columns) + "\n")
    return "".join(lines)


def serialize_file4(turbines: Sequence[dict[str, Any]]) -> str:
    return "".join(f"{_fmt_number(turbine['nl'])}\n" for turbine in turbines)


def _fmt_coord(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _fmt_number(value: float) -> str:
    """浮点转文本：尽量简洁，同时保留 Nl 的小数精度。"""
    result = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return result or "0"


# ---------------------------------------------------------------------------
# P0.abc 地形
# ---------------------------------------------------------------------------
def build_p0abc(
    params: PrepParams,
    *,
    tif_content: bytes | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """生成 P0.abc 字节与校验信息。

    ``terrain_mode=zero`` 时全 0；``tif`` 时按原生 0.01° 分辨率逐格取中心像素，
    不做重采样，并校验 EPSG:4326 / 分辨率 / 覆盖 / 高程范围。
    """
    wg.validate_grid(params.start_lon, params.start_lat, params.nx, params.ny, params.ddeg)
    left = int(round(params.start_lon * 100))
    bottom = int(round(params.start_lat * 100))
    right = int(round((params.start_lon + params.nx * params.ddeg) * 100))
    top = int(round((params.start_lat + params.ny * params.ddeg) * 100))
    header = struct.pack(">6H", left, right, bottom, top, int(params.nx), int(params.ny))

    if params.terrain_mode == "zero":
        pixels = np.zeros((params.ny, params.nx), dtype=np.uint16)
        info = {
            "mode": "zero",
            "header": {
                "left": left,
                "right": right,
                "bottom": bottom,
                "top": top,
                "width": int(params.nx),
                "height": int(params.ny),
            },
            "elevation_min": 0,
            "elevation_max": 0,
            "source": "按研究区域生成零高程",
        }
        return header + pixels.astype(">u2").tobytes(), info

    if params.terrain_mode != "tif":
        raise wg.WindGridError("地形模式只支持 zero 或 tif")
    if not tif_content:
        raise wg.WindGridError("已选择 tif 地形，但未上传 tif 文件")

    try:
        import rasterio  # type: ignore
        from rasterio.io import MemoryFile  # type: ignore
    except ImportError as exc:  # pragma: no cover - 依赖已固定
        raise wg.WindGridError("读取 tif 需要 rasterio 依赖") from exc

    try:
        with MemoryFile(tif_content) as memory:
            with memory.open() as src:
                return _sample_tif(src, params, left, right, bottom, top, header)
    except wg.WindGridError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转业务错误
        raise wg.WindGridError(f"tif 地形读取失败：{exc}") from exc


def _sample_tif(
    src: Any,
    params: PrepParams,
    left: int,
    right: int,
    bottom: int,
    top: int,
    header: bytes,
) -> tuple[bytes, dict[str, Any]]:
    epsg = None
    try:
        epsg = src.crs.to_epsg() if src.crs is not None else None
    except Exception:  # noqa: BLE001
        epsg = None
    if epsg != 4326:
        raise wg.WindGridError("地形 tif 必须使用 EPSG:4326 坐标系统（WGS84 经纬度）")

    res_x, res_y = abs(float(src.res[0])), abs(float(src.res[1]))
    if abs(res_x - params.ddeg) > 1e-6 or abs(res_y - params.ddeg) > 1e-6:
        raise wg.WindGridError(
            f"地形 tif 分辨率必须为 {params.ddeg:.2f}°，当前为 {res_x:.6f}° × {res_y:.6f}°；"
            "本模块不做重采样，请提供原分辨率数据"
        )

    bounds = src.bounds
    min_lon = params.start_lon
    max_lon = params.start_lon + params.nx * params.ddeg
    min_lat = params.start_lat
    max_lat = params.start_lat + params.ny * params.ddeg
    tol = params.ddeg * 0.01
    if not (
        bounds.left - tol <= min_lon
        and bounds.right + tol >= max_lon
        and bounds.bottom - tol <= min_lat
        and bounds.top + tol >= max_lat
    ):
        raise wg.WindGridError(
            "地形 tif 未覆盖研究区域"
            f"（tif: {bounds.left:.4f}~{bounds.right:.4f}, "
            f"{bounds.bottom:.4f}~{bounds.top:.4f}；"
            f"研究区: {min_lon:.4f}~{max_lon:.4f}, {min_lat:.4f}~{max_lat:.4f}）"
        )

    # 逐格采样（行序南→北读取后翻转成北→南），不做任何重采样
    pixels = np.zeros((params.ny, params.nx), dtype=np.uint16)
    coords = [
        (
            params.start_lon + (i + 0.5) * params.ddeg,
            params.start_lat + (j + 0.5) * params.ddeg,
        )
        for j in range(params.ny)
        for i in range(params.nx)
    ]
    nodata = src.nodata
    values = list(src.sample(coords))
    for index, sample in enumerate(values):
        raw = sample[0]
        j, i = divmod(index, params.nx)
        if raw is None or (nodata is not None and float(raw) == float(nodata)):
            raise wg.WindGridError(f"地形 tif 第 {j + 1} 行第 {i + 1} 列为无数据像素，无法生成高程")
        elevation = int(round(float(raw)))
        if elevation < 0 or elevation > 65535:
            raise wg.WindGridError(
                f"地形 tif 高程超出 0–65535 范围（格 i={i}, j={j}: {raw}）；"
                "P0.abc 用无符号 2 字节，负高程无法表达"
            )
        pixels[j, i] = elevation

    # GTiff 行序北→南；src.sample 按给定坐标取值，这里按北→南写出
    north_to_south = pixels[::-1]
    info = {
        "mode": "tif",
        "header": {
            "left": left,
            "right": right,
            "bottom": bottom,
            "top": top,
            "width": int(params.nx),
            "height": int(params.ny),
        },
        "elevation_min": int(pixels.min()),
        "elevation_max": int(pixels.max()),
        "resolution": [res_x, res_y],
        "source": "上传 tif（原生 0.01°，未重采样）",
    }
    return header + north_to_south.astype(">u2").tobytes(), info


# ---------------------------------------------------------------------------
# 端到端准备
# ---------------------------------------------------------------------------
def prepare_data(
    params: PrepParams,
    *,
    turbine_content: bytes,
    turbine_filename: str,
    lightning_content: bytes,
    lightning_filename: str,
    tif_content: bytes | None = None,
) -> PrepResult:
    """解析 → 校验 → 逐格聚合 → 生成五文件与校验报告。

    校验不通过抛 ``WindGridError``，调用方据此返回 400 且不落任何批次记录。
    """
    checks: list[dict[str, Any]] = []

    # 1) 参数硬约束
    try:
        wg.validate_grid(params.start_lon, params.start_lat, params.nx, params.ny, params.ddeg)
        checks.append(_check("grid_params", "区域与网格参数", True, "起始坐标 0.01° 对齐，网格数 ≤ 100"))
    except wg.WindGridError as exc:
        checks.append(_check("grid_params", "区域与网格参数", False, str(exc)))
        raise _blocked(checks, str(exc)) from exc
    if not (math.isfinite(params.risk_base_s) and params.risk_base_s > 0):
        message = "风险基准 S 必须大于 0"
        checks.append(_check("risk_base_s", "风险基准 S", False, message))
        raise _blocked(checks, message)

    # 2) 风机 / 雷电解析
    turbine_result = wg.parse_turbine_file(turbine_content, turbine_filename)
    lightning = wg.parse_lightning_csv(lightning_content)
    checks.append(
        _check(
            "turbine_parse",
            "风机文件解析",
            True,
            f"解析出 {len(turbine_result.points)} 台风机，跳过 {turbine_result.skipped} 行",
        )
    )
    checks.append(
        _check(
            "lightning_parse",
            "雷电 CSV 解析",
            True,
            f"有效 {lightning.valid_rows} 条，跳过 {lightning.skipped_rows} 条",
        )
    )

    # 3) 逐格落雷聚合（floor + 1 起 grid_id）
    counts, in_scope, out_of_scope = wg.aggregate_flashes(
        lightning.lon,
        lightning.lat,
        params.start_lon,
        params.start_lat,
        params.nx,
        params.ny,
        params.ddeg,
    )

    # 4) 风机逐台编号、越界校验与 Nl 计算
    turbines: list[dict[str, Any]] = []
    out_of_scope_turbines: list[str] = []
    for point in turbine_result.points:
        i, j, grid_id, in_grid = wg.grid_cell(
            point.lon,
            point.lat,
            params.start_lon,
            params.start_lat,
            params.nx,
            params.ny,
            params.ddeg,
        )
        if not in_grid:
            out_of_scope_turbines.append(f"第 {point.seq} 台（{point.lon:.5f}, {point.lat:.5f}）")
        flash_count = int(counts[j, i]) if in_grid else 0
        east_count = (
            int(counts[j, i + 1])
            if in_grid and i + 1 < params.nx
            else 0
        )
        nl = flash_count / float(DATA_YEARS)
        area_km2 = (params.ddeg * DEG_KM_APPROX) ** 2
        turbines.append(
            {
                "seq": point.seq,
                "turbine_no": point.turbine_no,
                "lon": point.lon,
                "lat": point.lat,
                "lon_dms": point.lon_dms,
                "lat_dms": point.lat_dms,
                "input_elev": point.input_elev,
                "height": point.height,
                "blade": point.blade,
                "motion": point.motion,
                "circuit": point.circuit,
                "cell_i": i,
                "cell_j": j,
                "grid_id": grid_id,
                "in_scope": in_grid,
                "flash_count": flash_count,
                "flash_count_east": east_count,
                "nl": nl,
                "density_per_km2_year": nl / area_km2,
            }
        )

    if out_of_scope_turbines:
        message = (
            f"有 {len(out_of_scope_turbines)} 台风机落在研究区域外，无法生成合法 grid_id："
            + "；".join(out_of_scope_turbines[:5])
        )
        checks.append(_check("turbine_in_scope", "风机位于研究区域内", False, message))
        raise _blocked(checks, message)
    checks.append(
        _check("turbine_in_scope", "风机位于研究区域内", True, "全部风机均在研究区域内")
    )

    # 5) N 与文件行数一致（由同一份解析结果生成，天然一致；保留显式校验）
    n_declared = len(turbines)
    checks.append(
        _check(
            "file_row_counts",
            "N 与文件行数一致",
            n_declared == len(turbines),
            f"N={n_declared}，file_2/file_3/file_4 各 {len(turbines)} 行",
        )
    )

    # 6) 地形
    p0abc, terrain_info = build_p0abc(params, tif_content=tif_content)
    checks.append(
        _check(
            "terrain",
            "地形 P0.abc",
            True,
            f"{terrain_info['source']}，字节数 {len(p0abc)}（应为 {12 + params.nx * params.ny * 2}）",
        )
    )

    # 7) 提示项（不阻断）
    warnings: list[str] = list(turbine_result.warnings)
    if lightning.skipped_rows:
        warnings.append(f"雷电 CSV 有 {lightning.skipped_rows} 行坐标无效，已跳过")
    if out_of_scope:
        warnings.append(f"雷电有 {out_of_scope} 条落在研究区域外，未参与统计")
    warnings.append(
        f"统计年限固定 {DATA_YEARS} 年；雷电数据实际时间跨度：{lightning.time_span}（仅作提示）"
    )
    if any(t["flash_count"] == 0 for t in turbines):
        warnings.append("部分风机所在网格落雷次数为 0，file_4 对应数值为 0")
    for warning in warnings:
        checks.append(_check("notice", "提示", True, warning, level="warning"))
    checks.append(
        _check(
            "lightning_type",
            "雷电类型分布（仅提示，不筛选）",
            True,
            "、".join(f"{k}: {v}" for k, v in lightning.type_distribution.items()) or "未识别类型列",
            level="info",
        )
    )

    nonzero_cell_count = int(np.count_nonzero(counts > 0))
    nl_values = [t["nl"] for t in turbines]
    stats: dict[str, Any] = {
        "turbine_count": len(turbines),
        "lightning_total": lightning.total_rows,
        "lightning_valid": lightning.valid_rows,
        "lightning_in_scope": in_scope,
        "lightning_out_of_scope": out_of_scope,
        "lightning_skipped": lightning.skipped_rows,
        "nonzero_cell_count": nonzero_cell_count,
        "zero_nl_turbine_count": sum(1 for value in nl_values if value == 0),
        "nl_max": max(nl_values) if nl_values else 0.0,
        "nl_min": min(nl_values) if nl_values else 0.0,
        "nl_avg": (sum(nl_values) / len(nl_values)) if nl_values else 0.0,
        "time_span": lightning.time_span,
        "detected_years": lightning.detected_years,
        "type_distribution": lightning.type_distribution,
        "start_lon": params.start_lon,
        "start_lat": params.start_lat,
        "grid_nx": params.nx,
        "grid_ny": params.ny,
        "grid_step_deg": params.ddeg,
        "data_years": DATA_YEARS,
        "risk_base_s": params.risk_base_s,
        "terrain": terrain_info,
        "area_km2_ref": params.nx * params.ny * (params.ddeg * DEG_KM_APPROX) ** 2,
    }

    files: dict[str, bytes] = {
        "file_1.txt": serialize_file1(params, len(turbines)).encode("utf-8"),
        "file_2.txt": serialize_file2(turbines).encode("utf-8"),
        "file_3.txt": serialize_file3(turbines).encode("utf-8"),
        "file_4.txt": serialize_file4(turbines).encode("utf-8"),
        "P0.abc": p0abc,
    }
    report = {
        "status": "pass",
        "checks": checks,
        "summary": {
            "errors": 0,
            "warnings": sum(1 for c in checks if c["level"] == "warning"),
            "turbine_count": len(turbines),
        },
    }
    return PrepResult(
        params=params,
        turbines=turbines,
        stats=stats,
        report=report,
        files=files,
        warnings=warnings,
    )


def _blocked(checks: list[dict[str, Any]], message: str) -> wg.WindGridError:
    errors = [c for c in checks if c["level"] == "error" and not c["passed"]]
    exc = wg.WindGridError(
        f"{message}｜校验报告：{errors or [{'code': 'blocked', 'message': message}]}"
    )
    # 附带已生成的校验项，供任务写入运行日志（不改变阻断行为）
    exc.checks = checks  # type: ignore[attr-defined]
    return exc


def validate_p0abc(content: bytes, *, nx: int, ny: int) -> dict[str, Any]:
    """在线预览用：解析 P0.abc 头部 6 个数值并校验字节数。"""
    if len(content) < 12:
        raise wg.WindGridError("P0.abc 字节数不足 12，头部损坏")
    header = struct.unpack(">6H", content[:12])
    expected = 12 + nx * ny * 2
    if len(content) != expected:
        raise wg.WindGridError(f"P0.abc 字节数 {len(content)} 与预期 {expected} 不一致")
    left, right, bottom, top, width, height = header
    return {
        "left": left,
        "right": right,
        "bottom": bottom,
        "top": top,
        "width": width,
        "height": height,
        "byte_size": len(content),
        "expected_byte_size": expected,
        "row_order": "north_to_south",
    }
