"""work.atp 仿真步长（dT）自适应适配器。

背景（2026-11-04 35kV 上字塔 12 塔实测）：塔模型横臂/塔身按分布参数支路
（LINEZT 型，Z=150~200Ω、v=2.5E8 m/s）建模，0.8m 短横臂的波行程时间仅 3.2ns；
模板 dT=5ns > 3.2ns 时 ATP 引擎 KILL=29 拒跑。C# 桌面版靠可选的
Setting/NoRelease_work.txt（内容 ``dT:Tmax`` 两个整数）人工覆写，且引擎拒跑后
不校验产物、静默输出假结果（实测假上限 2000kA）。本模块改为全自动：

1. 扫描渲染后 work.atp 的 /BRANCH 段，识别分布参数支路行
   （形如 ``-1XX0106XX0139   150. 2.5E8RELE01 1 0``，波速 v∈[1e7,3e8]）；
2. 波速/长度字段是 $PARAMETER 变量名（ATPDraw 导出形态
   ``-1XX0005XX0120   ZRE02_VRE___RELE03 1 0``）→ 查同文件 $PARAMETER 段
   真实值（渲染后已含最终几何值）；是数值 → 直接使用；
3. 取全模型最小波行程时间 t_min = min(len/v)；
4. dT_new = t_min / SAFETY_FACTOR，且只收窄不放宽（不超过模板原 dT）；
5. dT_new < MIN_DT → 抛 AtpDataError（存在病态短支路，须人工核查几何参数）。

不触碰 Tmax/Xopt/Copt/Epsiln（与 C# Update_work_atp4 只改 dT 列一致）。
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# C# Update_work_atp4 定位 dT 行用的同一特征串
_DT_FEATURE = "C  dT  >< Tmax >"
# 安全系数：dT 必须严格小于最短支路行程时间，取一半留余量
SAFETY_FACTOR = 2.0
# dT 硬下限：低于此值说明模型存在病态短支路（亚厘米级），判为数据错误
MIN_DT = 2e-10  # 0.2 ns
# 分布参数支路波速合理区间（m/s）。架空线/塔材 1e8~3e8；电缆约 1~2e8。
_V_MIN, _V_MAX = 1e7, 3e8


class AtpDataError(RuntimeError):
    """模型数据导致 dT 无法安全适配（病态短支路等）。"""


@dataclass
class DistributedLine:
    """一条分布参数支路的行程时间信息。"""

    line_no: int          # work.atp 中的行号（1-based）
    node_a: str
    node_b: str
    impedance: float      # Z（Ω）
    velocity: float       # v（m/s）
    length: float         # 长度（m）
    length_source: str    # "param:RELE01" 或 "literal"
    travel_time: float    # 行程时间（秒）
    velocity_source: str = "literal"  # "param:VRE___" 或 "literal"


@dataclass
class AdaptResult:
    """adapt_deltat 的结果。"""

    atp_text: str
    changed: bool
    original_dt: float | None = None
    new_dt: float | None = None
    t_min: float | None = None
    lines: list[DistributedLine] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # 无法解析的支路说明
    notes: list[str] = field(default_factory=list)


_FLOAT = r"\d+(?:\.\d*)?(?:[Ee][+-]?\d+)?|\.\d+(?:[Ee][+-]?\d+)?"
# 波速专用窄正则：指数最多 2 位（架空线/塔材 1E8~2.5E8），避免把紧贴的
# 数值长度吞进指数（"2.5E80.4" 应解析为 v=2.5E8 + len=0.4 而非 v=2.5E80）
_V_RE = re.compile(r"\d+(?:\.\d+)?[Ee][+-]?\d{1,2}")
# 分布参数支路行：模型码 -1/-2/-3 开头（-1 无损单相分布参数；塔模型只用 -1）
_LINE_RE = re.compile(rf"^-?[123](?P<na>[A-Za-z0-9#]{{1,8}})(?P<nb>[A-Za-z0-9#]{{1,8}})")
_VALUE_RE = re.compile(_FLOAT)
# $PARAMETER 变量名（ATPDraw 按 6 列右补下划线，如 VRE___ / ZRE01_）
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# ATP 固定格式单字段列宽：A/B/Leng 各占 6 列，粘连时按此切块
_ATOM_MAX = 8
_FIELD_WIDTHS = (6, 5, 4, 7, 8)


def _parse_float(token: str) -> float:
    return float(token.replace("E", "e").replace("e+", "e+"))


def _extract_param_values(atp_text: str) -> dict[str, float]:
    """解析 $PARAMETER 段的 NAME=VALUE（渲染后值均为最终数值）。"""
    values: dict[str, float] = {}
    lines = atp_text.splitlines()
    in_param = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.upper().startswith("$PARAMETER"):
            in_param = True
            continue
        if in_param and stripped.upper().startswith("BLANK"):
            break
        if not in_param or "=" not in stripped:
            continue
        name, _, val = stripped.partition("=")
        name = name.strip().upper()
        val = val.strip()
        if not name or not val:
            continue
        try:
            values[name] = _parse_float(val)
        except ValueError:
            continue
    return values


def _scan_branch_section(atp_text: str) -> tuple[int, int]:
    """返回 /BRANCH 段（不含首尾标记行）的 (start, end) 行号区间。"""
    lines = atp_text.splitlines()
    start = end = -1
    for i, raw in enumerate(lines):
        stripped = raw.strip().upper()
        if start < 0 and stripped.startswith("/BRANCH"):
            start = i + 1
            continue
        if start >= 0 and stripped.startswith("BLANK") and "BRANCH" in stripped:
            end = i
            break
    if start < 0:
        return -1, -1
    return start, (end if end > 0 else len(lines))


def _try_split_velocity(token: str, trailing: str = "") -> tuple[str, str] | None:
    """拆分被吞并的"波速+数值长度"token（如 "2.5E80" + ".4" → ("2.5E8", "0.4"））。

    ATP 卡片里数值长度紧贴波速时（无分隔列），token 正则会把长度的数字吞进
    指数（残余小数部分落在 token 之外，由 trailing 传入）。按波速指数惯例取
    1~2 位逐一尝试：拆出的 v 须落在合理区间、剩余部分须可解析为正数。
    返回 (v_token, len_token) 或 None。
    """
    head = re.match(r"(\d+(?:\.\d+)?)([Ee][+-]?)(\d+)", token)
    if not head:
        return None
    mant, sign, digits = head.group(1), head.group(2), head.group(3)
    for exp_len in (1, 2):
        if len(digits) <= exp_len:
            continue
        v_token = f"{mant}{sign}{digits[:exp_len]}"
        len_candidate = digits[exp_len:] + trailing
        try:
            v_val = _parse_float(v_token)
        except ValueError:
            continue
        if not (_V_MIN <= v_val <= _V_MAX):
            continue
        len_m = re.match(_FLOAT, len_candidate)
        if not len_m:
            continue
        try:
            if _parse_float(len_m.group(0)) > 0:
                return v_token, len_m.group(0)
        except ValueError:
            continue
    return None


def _param_index(param_values: dict[str, float]) -> dict[str, float]:
    """$PARAMETER 名归一化索引：去掉 ATP 列位填充用的尾随下划线。

    卡片与 $PARAMETER 段可能用不同补位形态（``VRE___`` / ``VRE`` / ``ZRE01_``），
    统一 rstrip('_') 后比对。
    """
    return {name.rstrip("_").upper(): value for name, value in param_values.items()}


def _lookup_param(
    token: str, param_values: dict[str, float], index: dict[str, float]
) -> float | None:
    """按原形态或去尾随下划线的形态查 $PARAMETER 值。"""
    value = param_values.get(token.upper())
    if value is None:
        value = index.get(token.rstrip("_").upper())
    return value


def _find_param_velocity(
    body: str,
    start: int,
    param_values: dict[str, float],
    index: dict[str, float] | None = None,
) -> tuple[float, int, int] | None:
    """在卡片的 A/B 字段区找变量名形态的波速，返回 (v, token_start, token_end)。

    ATPDraw 导出的塔模型把 A/B/Leng 三个字段整体写成变量名且**紧贴无空格**，
    如 ``-1XX0005XX0120   ZRE02_VRE___RELE03 1 0``。ATP 固定格式里每个字段占
    6 列，所以先按列宽切块再逐块查 $PARAMETER；行内没有数值可供 ``_VALUE_RE``
    识别，不回查参数段就必然 0 命中。``start`` 取节点名之后，避免把 ``XX0137``
    这类节点标识当成变量。
    """
    if not param_values:
        return None
    index = index if index is not None else _param_index(param_values)
    for m in _IDENT_RE.finditer(body, start):
        tok = m.group(0)
        # 单字段（未与相邻字段粘连）：整串直接查表
        if len(tok) <= _ATOM_MAX:
            value = _lookup_param(tok, param_values, index)
            if value is not None and _V_MIN <= value <= _V_MAX:
                return value, m.start(), m.end()
            continue
        # 多字段粘连：按 ATP 列位宽度整块切分
        for width in _FIELD_WIDTHS:
            if len(tok) % width:
                continue
            for off in range(0, len(tok), width):
                value = _lookup_param(tok[off : off + width], param_values, index)
                if value is not None and _V_MIN <= value <= _V_MAX:
                    return value, m.start() + off, m.start() + off + width
        # 列宽不规范时的滑动窗口兜底
        for off in range(0, len(tok) - _ATOM_MAX + 1):
            value = _lookup_param(
                tok[off : off + _ATOM_MAX], param_values, index
            )
            if value is not None and _V_MIN <= value <= _V_MAX:
                return value, m.start() + off, m.start() + off + _ATOM_MAX
    return None


def analyze_distributed_lines(
    atp_text: str, *, params: dict[str, float] | None = None
) -> tuple[list[DistributedLine], list[str]]:
    """扫描 /BRANCH 段的分布参数支路，返回（支路列表, 跳过说明列表）。"""
    param_values = params if params is not None else _extract_param_values(atp_text)
    param_idx = _param_index(param_values)
    result: list[DistributedLine] = []
    skipped: list[str] = []
    start, end = _scan_branch_section(atp_text)
    if start < 0:
        return result, skipped
    lines = atp_text.splitlines()
    for idx in range(start, min(end, len(lines))):
        raw = lines[idx]
        stripped = raw.rstrip()
        if not stripped.strip():
            continue
        head = _LINE_RE.match(stripped.strip())
        if not head:
            continue
        node_a, node_b = head.group("na"), head.group("nb")
        body = stripped.strip()

        # 在行内找波速 v：指数形数值且落在 [1e7, 3e8]；
        # 波速被紧贴的数值长度吞并（"2.5E80.4"）时用拆分回退
        velocity = 0.0
        velocity_source = "literal"
        v_start = v_end = -1
        pre_len_token: str | None = None  # 拆分回退时预先确定的长度 token
        for m in _VALUE_RE.finditer(body):
            tok = m.group(0)
            try:
                val = _parse_float(tok)
            except ValueError:
                continue
            if _V_MIN <= val <= _V_MAX:
                velocity, v_start, v_end = val, m.start(), m.end()
                break
            if val > _V_MAX:
                split = _try_split_velocity(tok, body[m.end():])
                if split is not None:
                    v_token, pre_len_token = split
                    velocity = _parse_float(v_token)
                    v_hit = re.match(r".*?" + re.escape(v_token), body)
                    v_start, v_end = (v_hit.start(), v_hit.end()) if v_hit else (
                        m.start(), m.end()
                    )
                    break
        if v_start < 0:
            # 波速写成 $PARAMETER 变量名（ATPDraw 导出：
            # "-1XX0005XX0120   ZRE02_VRE___RELE03 1 0"），行内无可识别数值。
            # ⚠️ 2026-11-13 750kV/66kV/35kV 共 12 个任务实测：此处原为静默
            # continue 且不记 skipped，整族模板 t_min 恒为空、dT 不收窄，
            # 日志还误报「未发现分布参数支路」，兜底形同虚设 → 引擎 KILL=29。
            found = _find_param_velocity(
                body, head.end(), param_values, param_idx
            ) if stripped.startswith("-1") else None
            if found is None:
                if stripped.startswith("-1"):
                    skipped.append(
                        f"行{idx + 1} {node_a}-{node_b}：波速字段既非数值也非可解析变量"
                    )
                continue  # 非分布参数行（-2/-3 等卡片类型）
            velocity, v_start, v_end = found
            velocity_source = f"param:{body[v_start:v_end]}"
        v_pos = v_end

        # 波速之后紧跟长度字段：变量名（如 RELE01）或数值；
        # 拆分回退时长度 token 已在波速 token 内确定
        if pre_len_token is not None:
            len_token = pre_len_token
        else:
            # ⚠️ 2026-11-11 66-maotou 实测教训：长度字段与波速之间常有空格
            # （"-1XX0121XX0173  200. 2.5E8    .5 1 0"，0.5m→行程 2ns）。
            # 不 lstrip 时 re.match 撞上空格必失败，该行被静默跳过 →
            # t_min 虚高 → dT 不收窄 → 引擎 KILL=29 拒跑。
            rest = body[v_pos:].lstrip()
            len_m = re.match(r"([A-Za-z_][A-Za-z_0-9]{1,9}|%s)" % _FLOAT, rest)
            if not len_m:
                skipped.append(f"行{idx + 1} {node_a}-{node_b}：波速后无法解析长度字段")
                continue
            len_token = len_m.group(1)
        length: float | None = None
        source = "literal"
        try:
            length = _parse_float(len_token)
        except ValueError:
            name = len_token.upper()
            if name in param_values:
                length = param_values[name]
                source = f"param:{name}"
            elif name.rstrip("_") in param_idx:
                length = param_idx[name.rstrip("_")]
                source = f"param:{name}"
        if length is None or length <= 0 or not math.isfinite(length):
            skipped.append(
                f"行{idx + 1} {node_a}-{node_b}：长度 {len_token} 无法解析或非正"
            )
            continue
        # 波阻抗（波速之前的最后一个数值），解析失败不阻断
        imp = 0.0
        for vm in _VALUE_RE.finditer(body[:v_start]):
            imp = _parse_float(vm.group(0))
        result.append(
            DistributedLine(
                line_no=idx + 1,
                node_a=node_a,
                node_b=node_b,
                impedance=imp,
                velocity=velocity,
                length=length,
                length_source=source,
                travel_time=length / velocity,
                velocity_source=velocity_source,
            )
        )
    return result, skipped


def _format_dt(dt: float) -> str:
    """把 dT 格式化为 ATP 数值形态（如 2.E-9 / 1.6E-9 / 8.E-10）。"""
    s = f"{dt:.2E}"                       # 8.00E-10
    mant, _, exp = s.partition("E")
    # 指数去前导零（-09 → -9；-10 保持 -10）
    exp = exp[0] + (exp[1:].lstrip("0") or "0")
    # 尾数去尾零但保留小数点前的形态（1.60 → 1.6；8.00 → 8.）
    mant = mant.rstrip("0").rstrip(".")
    if "." not in mant:
        mant += "."                        # 2E-9 → 2.E-9（模板形态）
    return f"{mant}E{exp}"


def _parse_dt_line(line: str) -> tuple[float, float] | None:
    """解析 dT 数值行，返回 (dT, Tmax)。"""
    tokens = line.split()
    if len(tokens) < 2:
        return None
    try:
        return _parse_float(tokens[0]), _parse_float(tokens[1])
    except ValueError:
        return None


def adapt_deltat(
    atp_text: str,
    *,
    safety_factor: float = SAFETY_FACTOR,
    min_dt: float = MIN_DT,
) -> AdaptResult:
    """对渲染后的 work.atp 做步长自适应，必要时收窄 dT。

    只收窄不放宽；不改动 Tmax 及后续列。结构异常（找不到 dT 行等）降级为
    notes 并原样返回——引擎侧现有 lis 致命行提取会兜底，不能因解析缺陷阻断任务。
    """
    res = AdaptResult(atp_text=atp_text, changed=False)
    lines = atp_text.splitlines()

    # 1) 定位 dT 行（C# 同款特征串 + 数值行）
    feat_idx = next(
        (i for i, l in enumerate(lines) if _DT_FEATURE in l), -1
    )
    if feat_idx < 0 or feat_idx + 1 >= len(lines):
        res.notes.append("未找到 dT 特征行，跳过自适应（引擎侧 lis 校验兜底）")
        return res
    parsed = _parse_dt_line(lines[feat_idx + 1])
    if parsed is None:
        res.notes.append("dT 数值行解析失败，跳过自适应")
        return res
    res.original_dt = parsed[0]

    # 2) 扫描分布参数支路
    res.lines, res.skipped = analyze_distributed_lines(atp_text)
    for note in res.skipped:
        res.notes.append(note)
    if not res.lines:
        res.notes.append("未发现分布参数支路，无需适配")
        return res
    var_count = sum(1 for l in res.lines if l.velocity_source.startswith("param"))
    if var_count:
        res.notes.append(
            f"其中 {var_count}/{len(res.lines)} 条支路波速取自 $PARAMETER 变量"
        )

    t_min = min(l.travel_time for l in res.lines)
    res.t_min = t_min
    dt_target = t_min / safety_factor
    if dt_target < min_dt:
        worst = min(res.lines, key=lambda l: l.travel_time)
        raise AtpDataError(
            f"分布参数支路 {worst.node_a}-{worst.node_b}（长度 {worst.length:g} m，"
            f"来源 {worst.length_source}）行程时间 {worst.travel_time * 1e9:.2f} ns，"
            f"所需 dT={dt_target * 1e9:.3f} ns 低于硬下限 {min_dt * 1e9:.1f} ns，"
            "疑似病态短支路，请核查杆塔几何参数"
        )

    if dt_target >= res.original_dt:
        res.notes.append(
            f"最小行程时间 {t_min * 1e9:.2f} ns ≥ 原dT {res.original_dt * 1e9:g} ns，无需收窄"
        )
        return res

    # 3) 改写 dT 数值行第一个字段（右对齐保持原列结构，Tmax 及后续列不动）
    new_dt = dt_target
    token = _format_dt(new_dt)
    row = lines[feat_idx + 1]
    # 原 dT 字段从行首到第一个空白（如 "   5.E-9" 占 8 列）
    m = re.match(r"\s*\S+", row)
    field_width = m.end() if m else 8
    padded = token.rjust(field_width)[:field_width]
    lines[feat_idx + 1] = padded + row[field_width:]
    res.atp_text = "\n".join(lines) + ("\n" if atp_text.endswith("\n") else "")
    res.changed = True
    res.new_dt = new_dt
    return res
