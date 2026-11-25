"""单风机计算 —— 纯函数内核（参数校验 / params.json 构造 / CSV 解析 / 曲线生成）。

MATLAB 编译产物（main_angle.exe + run_main_angle.sh）视为黑盒：本模块不实现也不改
算法的任何公式或积分步长，只负责与产物的文件接口对接：
- 输入：任务工作目录下 params.json
- 输出：results/failure_rate_by_theta.csv（表头 Theta_deg,FailureRate,FailureRate_pct）
严格遵循 issue LP-36 §二「原程序行为」作为算法契约。
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from typing import Any

DEFAULT_HUB_HEIGHT = 105.5
DEFAULT_RECEPTOR_RADII = [53.6, 63.6, 73.6, 78.6, 82.6]
DEFAULT_START_CURRENT = 1.0
DEFAULT_ANGLE_LIST = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
MAX_ANGLE_COUNT = 36

# golden case（默认参数下 12 角度逐项失效率，误差 ≤1e-9；均值如下）。
# 用作回归基准与 CSV 解析自校验，不参与运行时计算。
GOLDEN_FAILURE_RATES = [
    0.00622877556642743,
    0.00630627791810152,
    0.00652826327652078,
    0.00683634573238524,
    0.0071449149389087,
    0.00737805722869206,
    0.00746396580010588,
    0.00737904070704741,
    0.00714485503401852,
    0.00683454583833169,
    0.00652839719423753,
    0.00630859970252665,
]
GOLDEN_ANGLES = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
GOLDEN_MEAN = 0.006840169911441951

CSV_HEADER = ["Theta_deg", "FailureRate", "FailureRate_pct"]

# 请求角度与 CSV 行角度的匹配容差（deg）。CSV 由 %g 输出，正常误差远小于此值。
ANGLE_MATCH_TOLERANCE = 1e-6


class WindTurbineCalcError(ValueError):
    """参数校验或结果解析失败。"""


@dataclass
class ValidationResult:
    ok: bool
    params: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)


def validate_params(
    *,
    hub_height: float,
    receptor_radii: list[float],
    blade_length: float | None,
    start_current: float,
    angle_list: list[float],
) -> ValidationResult:
    """提交前校验，规则严格对齐 issue LP-36 §四。"""
    errors: list[str] = []
    radii = [float(r) for r in receptor_radii]
    if not radii:
        errors.append("接闪器径向位置 r_list 不能为空")
    elif any(not math.isfinite(r) or r <= 0 for r in radii):
        errors.append("接闪器径向位置必须为正的有限数值")
    elif any(b <= a for a, b in zip(radii, radii[1:])):
        errors.append("接闪器径向位置必须严格递增")

    R = float(blade_length) if blade_length is not None else (max(radii) if radii else 0.0)
    if not math.isfinite(R) or R <= 0:
        errors.append("叶片长度 R 必须大于 0")
    elif radii and any(r > R for r in radii):
        errors.append("接闪器径向位置 r 不能大于叶片长度 R")

    if not math.isfinite(float(hub_height)) or float(hub_height) <= 0:
        errors.append("轮毂高度 h 必须大于 0")
    if not math.isfinite(float(start_current)) or float(start_current) <= 0:
        errors.append("起始雷电流 Ic 必须大于 0")

    angles = [float(a) for a in angle_list]
    if not angles:
        errors.append("旋转角列表不能为空")
    elif len(angles) > MAX_ANGLE_COUNT:
        errors.append(f"旋转角数量不能超过 {MAX_ANGLE_COUNT}")
    elif any(not math.isfinite(a) for a in angles):
        errors.append("旋转角必须为有限数值")

    params = {
        "hub_height": float(hub_height),
        "receptor_radii": radii,
        "blade_length": R,
        "start_current": float(start_current),
        "angle_list": angles,
    }
    return ValidationResult(ok=not errors, params=params if not errors else None, errors=errors)


def build_params_json(params: dict[str, Any]) -> bytes:
    """构造编译产物接口约定的 params.json（UTF-8，缩进便于人工核对）。"""
    import json

    payload = {
        "hub_height": params["hub_height"],
        "receptor_radii": params["receptor_radii"],
        "blade_length": params["blade_length"],
        "start_current": params["start_current"],
        "angle_list": params["angle_list"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


@dataclass
class ParsedRow:
    theta_deg: float
    failure_rate: float
    failure_rate_pct: float


@dataclass
class ParsedCsv:
    rows: list[ParsedRow]
    all_rows: list[ParsedRow]
    mean_failure_rate: float
    min_failure_rate: float
    max_failure_rate: float
    min_failure_rate_theta: float
    max_failure_rate_theta: float

    @property
    def has_unrequested_rows(self) -> bool:
        """CSV 是否含有请求角度之外的行（历史编译产物会写死 0–110° 全角度）。"""
        return len(self.all_rows) > len(self.rows)


def select_rows_for_angles(
    rows: list[ParsedRow],
    angle_list: list[float],
    *,
    tolerance: float = ANGLE_MATCH_TOLERANCE,
) -> tuple[list[ParsedRow], list[float]]:
    """按请求角度挑出 CSV 对应行，返回 (匹配行, 缺失角度)。

    引擎可能返回整条 0–110° 曲线（历史编译产物无视 params.json 的 angle_list），
    统计与曲线一律以用户请求的角度为准，避免展示未请求角度的峰值。
    """
    selected: list[ParsedRow] = []
    missing: list[float] = []
    used: set[int] = set()
    targets: list[float] = []
    for angle in angle_list:
        target = float(angle)
        # 请求里重复的角度只统计一次，避免同一行被落库两次
        if any(abs(target - seen) <= tolerance for seen in targets):
            continue
        targets.append(target)
        match = next(
            (
                index
                for index, row in enumerate(rows)
                if index not in used and abs(row.theta_deg - target) <= tolerance
            ),
            None,
        )
        if match is None:
            missing.append(target)
        else:
            used.add(match)
            selected.append(rows[match])
    return selected, missing


def parse_failure_rate_csv(raw: bytes, *, angle_list: list[float] | None = None) -> ParsedCsv:
    """解析 results/failure_rate_by_theta.csv。

    兼容 UTF-8 BOM、表头大小写、额外空白列；仅接受三列核心字段。
    传入 ``angle_list`` 时，统计口径只取请求角度对应的行（``all_rows`` 保留原始全量行）。
    """
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows: list[ParsedRow] = []
    for line in reader:
        if not line or all(not c.strip() for c in line):
            continue
        cells = [c.strip() for c in line]
        if cells[0].lower().replace(" ", "_") in {"theta_deg", "theta", "angle", "角度"}:
            continue
        if len(cells) < 2:
            raise WindTurbineCalcError(f"CSV 行字段不足：{line}")
        try:
            theta = float(cells[0])
            rate = float(cells[1])
            pct = float(cells[2]) if len(cells) > 2 and cells[2] else rate * 100.0
        except (ValueError, IndexError) as exc:
            raise WindTurbineCalcError(f"CSV 数值解析失败：{line}") from exc
        if not (math.isfinite(theta) and math.isfinite(rate)):
            raise WindTurbineCalcError(f"CSV 出现非有限数值：{line}")
        rows.append(ParsedRow(theta_deg=theta, failure_rate=rate, failure_rate_pct=pct))
    if not rows:
        raise WindTurbineCalcError("failure_rate_by_theta.csv 无有效数据行")
    stat_rows = rows
    if angle_list:
        selected, missing = select_rows_for_angles(rows, angle_list)
        if missing:
            returned = ", ".join(f"{r.theta_deg:g}" for r in rows[:36])
            missing_text = ", ".join(f"{angle:g}" for angle in missing)
            raise WindTurbineCalcError(
                f"引擎返回的角度与请求不一致，缺少请求角度 {missing_text}°；"
                f"CSV 实际返回角度 {returned}°。请确认编译产物是否按 params.json 的 angle_list 计算"
            )
        stat_rows = selected
    rates = [r.failure_rate for r in stat_rows]
    min_row = min(stat_rows, key=lambda r: r.failure_rate)
    max_row = max(stat_rows, key=lambda r: r.failure_rate)
    return ParsedCsv(
        rows=stat_rows,
        all_rows=rows,
        mean_failure_rate=sum(rates) / len(rates),
        min_failure_rate=min_row.failure_rate,
        max_failure_rate=max_row.failure_rate,
        min_failure_rate_theta=min_row.theta_deg,
        max_failure_rate_theta=max_row.theta_deg,
    )


def golden_csv_bytes() -> bytes:
    """生成 golden case 的 CSV 字节，供离线对拍/测试使用。"""
    lines = [",".join(CSV_HEADER)]
    for theta, rate in zip(GOLDEN_ANGLES, GOLDEN_FAILURE_RATES):
        lines.append(f"{theta:g},{rate:.17g},{rate * 100.0:.17g}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _pick_chart_font() -> tuple[str | None, bool]:
    """返回 (字体名, 是否支持中文)。无 CJK 字体时改用英文标签，避免方块字。"""
    try:
        import matplotlib.font_manager as fm

        names = {f.name for f in fm.fontManager.ttflist}
    except Exception:  # pragma: no cover
        return None, False
    for candidate in ("Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "WenQuanYi Zen Hei", "PingFang SC"):
        if candidate in names:
            return candidate, True
    return None, False


def render_chart_png(parsed: ParsedCsv, *, title: str = "单风机屏蔽失效率") -> bytes:
    """用 matplotlib（Agg 后端）按 CSV 生成失效率-旋转角曲线 PNG。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    font, has_cjk = _pick_chart_font()
    if font:
        plt.rcParams["font.sans-serif"] = [font]
    plt.rcParams["axes.unicode_minus"] = False

    x = [r.theta_deg for r in parsed.rows]
    y = [r.failure_rate for r in parsed.rows]

    fig, ax = plt.subplots(figsize=(9, 5.2))
    ax.plot(x, y, marker="o", linewidth=2, color="#1f77b4")
    if len(x) > 1:
        ax.fill_between(x, y, min(y) * 0.9, color="#1f77b4", alpha=0.12)
    else:
        # 单角度任务只有一个点：留出横向余量，避免点贴在坐标轴边缘
        ax.set_xlim(x[0] - 10, x[0] + 10)
    ax.set_title(title if has_cjk else "Failure Rate vs Rotation Angle")
    ax.set_xlabel("旋转角 (deg)" if has_cjk else "Rotation angle (deg)")
    ax.set_ylabel("屏蔽失效率" if has_cjk else "Shielding failure rate")
    ax.grid(True, linestyle="--", alpha=0.4)
    note = "注：角度击距公式在 0–90° 拟合，其余姿态为外推" if has_cjk else "Note: angle formula fitted for 0-90 deg; extrapolated beyond"
    ax.annotate(note, xy=(0.5, 0.01), xycoords="axes fraction", ha="center", fontsize=8, color="#888")
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=140)
    plt.close(fig)
    return buffer.getvalue()
