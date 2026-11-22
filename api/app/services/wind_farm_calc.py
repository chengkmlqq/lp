"""风电场计算 —— 纯函数内核（预检 + 输出解析 + 规则重算）。

核心程序 ``FengLiFangLei-10.exe`` 视为黑盒：本模块只做「启动前把输入校验到位」和
「结束后把 GBK 输出解析成结构化结果」，不改动 exe 的代码与算法。

- 输入：数据准备模块（LP-33）产出的 ``file_1.txt`` ~ ``file_4.txt`` + ``P0.abc``；
- 输出：``file_out.txt``（GBK/GB18030）6 列 —— 序号、十进制经度、十进制纬度、
  计算值 V、风险等级（罗马数字 I–IV）、停运建议文本。

风险等级由后端按 ``V`` 与 ``file_1`` 第 2 行的 ``S`` 重新计算，停运建议按 GBK 文本
归一化成状态码并使用本模块的规范文案；GBK 原文保留在 ``raw_line`` 仅作对照。
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Any

INPUT_FILE_NAMES = ("file_1.txt", "file_2.txt", "file_3.txt", "file_4.txt", "P0.abc")
MAX_TURBINES = 100
MAX_GRID_AXIS = 100
MAX_CIRCUIT_NO = 100
# 核心程序按 150 个雷电流档位逐档扫描（用于把 stdout 的 "I = " 行数估算为进度）
CURRENT_LEVELS = 150

RISK_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}
SUGGESTION_TEXT_BY_CODE = {
    1: "无",
    2: "停运",
    3: "停运(集电线)",
    4: "停运(风电场)",
}

_SPLIT_RE = re.compile(r"[\t ]+")
_PROGRESS_RE = re.compile(r"\bI\s*=\s*[-+]?\d+(?:\.\d+)?", re.IGNORECASE)


class WindFarmCalcError(ValueError):
    """预检 / 解析失败，api 层统一映射为 400 或任务失败。"""


@dataclass(slots=True)
class File1Params:
    n: int
    s: float
    start_lon: float
    start_lat: float
    nx: int
    ny: int


@dataclass(slots=True)
class PreflightReport:
    ok: bool = False
    params: File1Params | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    grid_rows: int = 0

    def as_dict(self) -> dict[str, Any]:
        params = None
        if self.params is not None:
            params = {
                "n": self.params.n,
                "s": self.params.s,
                "start_lon": self.params.start_lon,
                "start_lat": self.params.start_lat,
                "nx": self.params.nx,
                "ny": self.params.ny,
            }
        return {
            "ok": self.ok,
            "params": params,
            "checks": self.checks,
            "errors": self.errors,
            "grid_rows": self.grid_rows,
        }


@dataclass(slots=True)
class TurbineCalcRow:
    seq: int
    lon: float
    lat: float
    value_v: float
    risk_level: int
    suggestion_code: int
    suggestion_text: str
    parsed_risk_level: int | None
    raw_line: str


@dataclass(slots=True)
class FileOutParseResult:
    rows: list[TurbineCalcRow] = field(default_factory=list)
    risk_mismatch_count: int = 0
    raw_text: str = ""


def _check(
    code: str, label: str, passed: bool, message: str, level: str | None = None
) -> dict[str, Any]:
    check: dict[str, Any] = {
        "code": code,
        "label": label,
        "passed": bool(passed),
        "message": message,
    }
    if level is not None:
        check["level"] = level
    return check


def _nonblank_lines(content: bytes) -> list[str]:
    text = content.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_file1(content: bytes) -> File1Params:
    """解析 6 行 ``N / S / 起始经度 / 起始纬度 / 经向网格数 / 纬向网格数``。"""
    lines = _nonblank_lines(content)
    if len(lines) < 6:
        raise WindFarmCalcError(f"file_1.txt 需要 6 个参数，实际只有 {len(lines)} 行")
    try:
        n = int(float(lines[0]))
        s = float(lines[1])
        start_lon = float(lines[2])
        start_lat = float(lines[3])
        nx = int(float(lines[4]))
        ny = int(float(lines[5]))
    except (TypeError, ValueError) as exc:
        raise WindFarmCalcError(f"file_1.txt 参数不是合法数值：{exc}") from exc
    return File1Params(
        n=n, s=s, start_lon=start_lon, start_lat=start_lat, nx=nx, ny=ny
    )


def _parse_grid_id(line: str) -> int:
    parts = _SPLIT_RE.split(line.strip())
    if not parts or not parts[0]:
        raise WindFarmCalcError("file_3.txt 存在空首列")
    try:
        return int(float(parts[0]))
    except ValueError as exc:
        raise WindFarmCalcError(f"file_3.txt 网格编号不是整数：{line!r}") from exc


def _parse_circuit_no(line: str) -> int:
    parts = _SPLIT_RE.split(line.strip())
    if len(parts) < 11:
        raise WindFarmCalcError(f"file_2.txt 每行需要 11 列，实际 {len(parts)} 列：{line!r}")
    try:
        return int(float(parts[10]))
    except ValueError as exc:
        raise WindFarmCalcError(f"file_2.txt 回路号不是整数：{line!r}") from exc


def _validate_p0abc(content: bytes, *, nx: int, ny: int) -> dict[str, int]:
    """按头部 w/h 校验字节数，并要求头部与 file_1 的 nx/ny 一致。"""
    if len(content) < 12:
        raise WindFarmCalcError("P0.abc 字节数不足 12，头部损坏")
    left, right, bottom, top, width, height = struct.unpack(">6H", content[:12])
    expected = 12 + width * height * 2
    if len(content) != expected:
        raise WindFarmCalcError(
            f"P0.abc 字节数 {len(content)} 与头部 w*h 推得 {expected} 不一致"
        )
    if width != nx or height != ny:
        raise WindFarmCalcError(
            f"P0.abc 头部网格 {width}x{height} 与 file_1 的 {nx}x{ny} 不一致"
        )
    return {
        "left": left,
        "right": right,
        "bottom": bottom,
        "top": top,
        "width": width,
        "height": height,
        "byte_size": len(content),
    }


def preflight(files: dict[str, bytes]) -> PreflightReport:
    """启动 Wine 前必须完成的完整性 / 边界校验，任一失败直接 fail。"""
    report = PreflightReport()

    for name in INPUT_FILE_NAMES:
        content = files.get(name)
        ok = isinstance(content, (bytes, bytearray)) and len(content) > 0
        report.checks.append(
            _check(
                f"file.{name}",
                f"{name} 存在且非空",
                ok,
                "已就绪" if ok else "文件缺失或为空",
            )
        )
        if not ok:
            report.errors.append(f"{name} 缺失或为空")
    if report.errors:
        return report

    try:
        params = parse_file1(files["file_1.txt"])
    except WindFarmCalcError as exc:
        report.checks.append(_check("file1.parse", "file_1.txt 可解析", False, str(exc)))
        report.errors.append(str(exc))
        return report
    report.params = params
    report.checks.append(
        _check("file1.parse", "file_1.txt 可解析", True, f"N={params.n}, S={params.s}")
    )

    if not (1 <= params.n <= MAX_TURBINES):
        report.errors.append(f"风机数 N={params.n} 不在 1–{MAX_TURBINES} 之间")
    report.checks.append(
        _check(
            "file1.n",
            f"风机数 N 在 1–{MAX_TURBINES}",
            1 <= params.n <= MAX_TURBINES,
            f"N={params.n}",
        )
    )
    s_ok = params.s > 0 and params.s == params.s and abs(params.s) != float("inf")
    report.checks.append(
        _check("file1.s", "风险基准 S 为正数", s_ok, f"S={params.s}")
    )
    if not s_ok:
        report.errors.append(f"风险基准 S={params.s} 非法")
    grid_ok = 1 <= params.nx <= MAX_GRID_AXIS and 1 <= params.ny <= MAX_GRID_AXIS
    report.checks.append(
        _check(
            "file1.grid",
            f"网格数在 1–{MAX_GRID_AXIS}",
            grid_ok,
            f"nx={params.nx}, ny={params.ny}",
        )
    )
    if not grid_ok:
        report.errors.append(f"网格数 {params.nx}x{params.ny} 越界")
    if report.errors:
        return report

    # N 与 file_2 / file_3 / file_4 行数：核心程序只取前 N 行，故行数 ≥ N 即可
    lines_by_file = {name: _nonblank_lines(files[name]) for name in ("file_2.txt", "file_3.txt", "file_4.txt")}
    for name, lines in lines_by_file.items():
        ok = len(lines) >= params.n
        report.checks.append(
            _check(
                f"count.{name}",
                f"{name} 行数 ≥ N（核心程序仅取前 N 行）",
                ok,
                f"行数={len(lines)}, N={params.n}",
            )
        )
        if not ok:
            report.errors.append(f"{name} 行数 {len(lines)} 少于 N={params.n}")
        elif len(lines) > params.n:
            report.checks.append(
                _check(
                    f"count.extra.{name}",
                    f"{name} 多余行（仅提示）",
                    True,
                    f"文件行数 {len(lines)} > N={params.n}，仅使用前 {params.n} 行",
                    level="warning",
                )
            )
    if report.errors:
        return report

    # file_3 网格编号 [1, nx*ny]：核心程序只处理前 N 台，只校验前 N 行
    max_grid_id = params.nx * params.ny
    grid_ids: list[int] = []
    try:
        grid_ids = [_parse_grid_id(line) for line in lines_by_file["file_3.txt"][:params.n]]
        grid_ok = all(1 <= grid_id <= max_grid_id for grid_id in grid_ids)
        message = "全部在范围内" if grid_ok else f"网格编号越界（合法 1–{max_grid_id}）"
    except WindFarmCalcError as exc:
        grid_ok = False
        message = str(exc)
    report.grid_rows = len(grid_ids)
    report.checks.append(
        _check("file3.grid_id", f"网格编号在 1–{max_grid_id}", grid_ok, message)
    )
    if not grid_ok:
        report.errors.append(message)

    # file_2 回路号 [1, 100]（核心程序直接当数组下标）：只校验前 N 行
    try:
        circuits = [_parse_circuit_no(line) for line in lines_by_file["file_2.txt"][:params.n]]
        circuit_ok = all(1 <= circuit <= MAX_CIRCUIT_NO for circuit in circuits)
        message = "全部在范围内" if circuit_ok else f"存在越界回路号（合法 1–{MAX_CIRCUIT_NO}）"
    except WindFarmCalcError as exc:
        circuit_ok = False
        message = str(exc)
    report.checks.append(
        _check(
            "file2.circuit",
            f"回路号在 1–{MAX_CIRCUIT_NO}",
            circuit_ok,
            message,
        )
    )
    if not circuit_ok:
        report.errors.append(message)

    # P0.abc 字节数 = 12 + w*h*2
    try:
        header = _validate_p0abc(files["P0.abc"], nx=params.nx, ny=params.ny)
        p0_ok = True
        message = f"头部 {header['width']}x{header['height']}，{header['byte_size']} 字节"
    except WindFarmCalcError as exc:
        p0_ok = False
        message = str(exc)
    report.checks.append(_check("p0abc.size", "P0.abc 字节数与头部一致", p0_ok, message))
    if not p0_ok:
        report.errors.append(message)

    report.ok = not report.errors
    return report


def decode_file_out(content: bytes) -> str:
    """GBK/GB18030 解码，UTF-8 仅作兜底（兼容测试构造的样例）。"""
    for encoding in ("gbk", "gb18030", "utf-8-sig", "utf-8"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("gb18030", errors="replace")


def classify_risk(value_v: float, s: float) -> int:
    """V ≤ 0.5S→I；0.5S < V ≤ S→II；S < V ≤ 1.5S→III；V > 1.5S→IV。"""
    if s <= 0 or s != s or abs(s) == float("inf"):
        raise WindFarmCalcError(f"风险基准 S={s} 非法，无法计算风险等级")
    if value_v <= 0.5 * s:
        return 1
    if value_v <= s:
        return 2
    if value_v <= 1.5 * s:
        return 3
    return 4


def parse_risk_level(text: str) -> int | None:
    """把罗马数字 I–IV（或阿拉伯数字 1–4）解析为 1–4；无法识别返回 None。"""
    normalized = (text or "").strip().upper().strip(".")
    mapping = {"I": 1, "II": 2, "III": 3, "IV": 4, "1": 1, "2": 2, "3": 3, "4": 4}
    return mapping.get(normalized)


def classify_suggestion(text: str) -> int:
    """把 GBK 停运建议文本归一化为状态码 1–4。"""
    normalized = (text or "").strip()
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = re.sub(r"\s+", "", normalized)
    if not normalized:
        return 1
    if normalized in {"1", "2", "3", "4"}:
        return int(normalized)
    if "风电场" in normalized or "全场" in normalized:
        return 4
    if "集电线" in normalized or "集电" in normalized:
        return 3
    if "停运" in normalized:
        return 2
    return 1


def suggestion_text(code: int) -> str:
    return SUGGESTION_TEXT_BY_CODE.get(code, SUGGESTION_TEXT_BY_CODE[1])


def count_progress_marks(line: str) -> int:
    """统计一行 stdout 中的 ``I = `` 进度标记数量（程序每个雷电流档位打印一次）。"""
    return len(_PROGRESS_RE.findall(line))


def parse_file_out(
    content: bytes, *, s: float, expected_n: int
) -> FileOutParseResult:
    """解析 GBK 输出并按规则重算风险等级 / 建议文案，校验行数等于 N。"""
    text = decode_file_out(content)
    result = FileOutParseResult(raw_text=text)
    seqs: set[int] = set()
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        parts = _SPLIT_RE.split(stripped)
        if len(parts) < 5:
            continue
        try:
            seq = int(float(parts[0]))
        except ValueError:
            # 跳过可能存在的表头行
            continue
        try:
            lon = float(parts[1])
            lat = float(parts[2])
            value_v = float(parts[3])
        except ValueError as exc:
            raise WindFarmCalcError(f"file_out.txt 数值列解析失败：{stripped!r}") from exc
        parsed_risk = parse_risk_level(parts[4])
        suggestion = " ".join(parts[5:]) if len(parts) > 5 else ""
        level = classify_risk(value_v, s)
        code = classify_suggestion(suggestion)
        if parsed_risk is not None and parsed_risk != level:
            result.risk_mismatch_count += 1
        result.rows.append(
            TurbineCalcRow(
                seq=seq,
                lon=lon,
                lat=lat,
                value_v=value_v,
                risk_level=level,
                suggestion_code=code,
                suggestion_text=suggestion_text(code),
                parsed_risk_level=parsed_risk,
                raw_line=stripped,
            )
        )
        seqs.add(seq)

    if len(result.rows) != expected_n:
        raise WindFarmCalcError(
            f"file_out.txt 结果行数 {len(result.rows)} 与 file_1 的 N={expected_n} 不一致"
        )
    if len(seqs) != expected_n or seqs != set(range(1, expected_n + 1)):
        raise WindFarmCalcError(
            f"file_out.txt 序号异常：应为 1..{expected_n}，实际 {sorted(seqs)[:10]}..."
        )
    return result
