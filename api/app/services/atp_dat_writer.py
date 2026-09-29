"""按 C# 逻辑改写 ATP 导线几何文件（long/short/dahao/xiaohao .dat）。

背景（2026-09-13 排查）：Web 之前从不改写这些 .dat，直接用导入资产里的静态几何
（属于别的塔），导致 .lib（JMARTI 线路模型）几何错误 → 多相仿真数值系统性偏大。

权威依据：
 ① 规格 api/app/services/atp_dat_model/long_short_dat_model.txt
    （形状段：名称 → [导体序号, 偏移, 宽度, 格式]；档距槽的序号是 500/120/20 电压组标识）
 ② C# ComputeLightningProtection.cs:3843-4483（每塔型 MySetValue 取值）
 ③ C# FeatureSetOfATP.SetFeatureValue（写入语义）

写入语义（逐字节核对 C# 的 4 个 .dat 得出）：
 - 导体卡在第 8 行起：文件行 = 导体序号 + 7
 - 档距槽：第 17 行（频率卡），offset 44，宽 8，F2；dahao.dat←大号档距、xiaohao.dat←小号档距
 - 偏移 0-based；值右对齐到宽；格式 F{digits}；去尾随 0（保留小数点）
"""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

_SPEC_PATH = Path(__file__).with_name("atp_dat_model") / "long_short_dat_model.txt"

_CONDUCTOR_LINE_OFFSET = 7      # 导体序号 1 → 文件第 8 行
_SPAN_LINE = 17                 # 档距（频率卡）所在行
_SPAN_OFFSET = 44
_SPAN_WIDTH = 8

_SECTION_MARKERS = (
    "menxing", "ganzi", "guxing", "maotou", "jiubei", "shangzi",
    "sihuita", "zxj", "zx", "zj", "ky", "nz", "vzhiliu", "zhiliu",
)


@dataclass(frozen=True)
class DatSlot:
    conductor: int
    offset: int
    width: int
    digits: int
    is_span: bool = False


def _parse_spec(text: str) -> dict[str, list[tuple[str, DatSlot]]]:
    sections: dict[str, list[tuple[str, DatSlot]]] = {}
    cur: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("</"):
            cur = None
            continue
        if line.startswith("<"):
            cur = line.strip("<>").strip()
            sections.setdefault(cur, [])
            continue
        if cur is None:
            continue
        parts = line.split("#")
        if len(parts) < 6:
            continue
        try:
            conductor = int(parts[0])
            offset = int(parts[1])
            width = int(parts[2])
        except ValueError:
            continue
        m = re.search(r"F(\d+)", parts[3])
        digits = int(m.group(1)) if m else 1
        name = parts[5].strip()
        is_span = "档距" in name          # 档距槽的序号是电压组(500/120/20)，非导体序号
        sections[cur].append((name, DatSlot(conductor, offset, width, digits, is_span)))
    return sections


_CACHE: dict[str, list[tuple[str, DatSlot]]] | None = None


def load_spec() -> dict[str, list[tuple[str, DatSlot]]]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _parse_spec(_SPEC_PATH.read_text(encoding="utf-8"))
    return _CACHE


def _normalize_kind(tower_type: str) -> str:
    t = re.sub(r"[^a-z0-9]", "", (tower_type or "").lower())
    for marker in _SECTION_MARKERS:
        if marker in t:
            return marker
    return ""


def resolve_section(tower_type: str, voltage_kv) -> str:
    kind = _normalize_kind(tower_type)
    if not kind:
        return ""
    sections = load_spec()
    v = str(int(voltage_kv)) if voltage_kv else ""
    if v:
        for name in sections:
            if name.startswith(kind + "-") and v in name.split("-", 1)[1]:
                return name
    return kind if kind in sections else ""


def _conductor_line_offset(lines: list[str]) -> int:
    """推导「导体卡起始行号」（导体 1 所在行）。

    各塔型 .dat 头部行数不同（双回有 2 行 BRANCH，单回只有 1 行），
    因此不能硬编码。统一以 METRIC 行的下一行为导体卡起始；找不到时回退 7
    （历史值，对双回鼓型等成立）。
    """
    for i, ln in enumerate(lines):
        if ln.strip().upper() == "METRIC":
            # 导体卡起始行 = METRIC 行的下一行；本函数返回值用于
            # index = conductor + 返回值 - 1（lines 为 0-based）
            return i + 1
    return 7


def _count_conductor_lines(lines: list[str]) -> int:
    """统计 .dat 的实际导体行数（METRIC 之后 → BLANK CARD ENDING CONDUCTOR 之前）。

    ⚠️ 2026-09-29（sihuitano 无避雷线四回塔修复）：槽位表假定 14 导体
    （12 相 + 2 避雷线），但「无避雷线」变体的 .dat 只有 12 导体。
    按实际导体行数截断槽位，避免避雷线槽位污染频率卡区域。
    """
    seen = 0
    in_metric = False
    for ln in lines:
        up = ln.strip().upper()
        if up == "METRIC":
            in_metric = True
            continue
        if in_metric and "ENDING CONDUCTOR" in up:
            break
        if in_metric and ln.strip():
            seen += 1
    return seen


def _span_block(lines: list[str]) -> list[int]:
    """返回「频率卡」块的 0-based 行号列表（导体卡结束 → 频率卡结束之间）。"""
    start = end = None
    for i, ln in enumerate(lines):
        up = ln.upper()
        if start is None and "ENDING CONDUCTOR" in up:
            start = i + 1
        elif start is not None and "ENDING FREQUENCY" in up:
            end = i
            break
    if start is None or end is None:
        return []
    return [i for i in range(start, end) if lines[i].strip()]


def _fmt(value: float, digits: int, width: int) -> str:
    # ⚠️ 2026-09-20 修复（对拍 C# 发现）：
    # ① 零值不特判 —— C# 对 0 输出 "0."（实测 220 四个塔型 long.dat 的
    #    「中相中距(0值)」槽 = `      0.`），旧实现对零输出 "0.0" → 整行错位。
    # ② 舍入必须走**十进制**四舍五入(round-half-up)，不能直接用二进制浮点格式化：
    #    实测 jiubei 避雷线中距 9.85 → C# 写 "9.9"，而 f"{9.85:.1f}" 得 "9.8"
    #    （9.85 的 float64 实为 9.8499999…）→ 一个字符差异。
    #    改为 Decimal(str(v)) + ROUND_HALF_UP，与 C# ToString("F1") 语义一致。
    txt = str(Decimal(str(float(value))).quantize(Decimal(1).scaleb(-digits),
                                                  rounding=ROUND_HALF_UP))
    if "." in txt:
        txt = txt.rstrip("0")      # C# 去尾零：12.0 → "12."；0.0 → "0."
    return txt.rjust(width)


def rewrite_dat_text(text: str, section: str, values: dict[str, float], *,
                     span_km: float | None = None) -> str:
    """把 values 写进 .dat（几何段 + 可选档距）。行尾原样保留。"""
    slots = load_spec().get(section)
    if not slots:
        raise RuntimeError(f"long_short_dat_model.txt 无塔型段 '{section}'，无法改写 .dat 几何")
    parts = re.split(r"(\r\n|\n)", text)
    lines = [ln.rstrip("\r") for ln in parts[0::2]]

    conductor_offset = _conductor_line_offset(lines)
    # ⚠️ 2026-09-29 修复（sihuitano 无避雷线四回塔）：
    # 槽位表 <sihuita> 假定 14 导体（12 相 + 2 避雷线），但「无避雷线」变体
    # （sihuitano 等资产）的 .dat 只有 12 导体。旧实现把避雷线槽位
    # （导体 13/14）写到频率卡区域 → ATP `fmt: read unexpected character` rc=3。
    # 现按 dat 实际导体行数截断：只写导体号 ≤ 实际数的槽位，
    # 超出的（避雷线）槽位跳过 —— 对 14 导体资产行为不变（无 no-op）。
    actual_conductor_lines = _count_conductor_lines(lines)
    if actual_conductor_lines:
        slots = [(name, s) for name, s in slots if s.conductor <= actual_conductor_lines]

    missing = sorted({n for n, s in slots if not s.is_span and n not in values})
    if missing:
        raise RuntimeError(f"改写 .dat 缺少取值：{missing}（塔型段 {section}）")

    def _write(idx0: int, offset: int, width: int, field: str) -> None:
        if idx0 >= len(lines):
            raise RuntimeError(f".dat 行数不足（需要第 {idx0 + 1} 行，实际 {len(lines)} 行）")
        ln = lines[idx0]
        if len(ln) < offset + width:
            ln = ln.ljust(offset + width)
        lines[idx0] = ln[:offset] + field + ln[offset + width:]

    for name, slot in slots:
        if slot.is_span:
            if span_km is not None:
                # 实测：档距写在「频率卡」块（CONDUCTOR 结束 → FREQUENCY 结束之间）的每一行
                for idx0 in _span_block(lines):
                    _write(idx0, _SPAN_OFFSET, _SPAN_WIDTH, _fmt(span_km, slot.digits, slot.width))
            continue
        _write(slot.conductor + conductor_offset - 1, slot.offset, slot.width,
               _fmt(values[name], slot.digits, slot.width))

    out: list[str] = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if 2 * i + 1 < len(parts):
            out.append(parts[2 * i + 1])
    return "".join(out)


def _guxing(ctx: dict) -> dict[str, float]:
    """guxing（鼓型双回）—— C# ComputeLightningProtection.cs:3911-3980。"""
    return {
        "上相中距(正值)": abs(ctx["sp_upper"]),
        "上相高度": ctx["rehc1"],
        "中相中距(正值)": abs(ctx["sp_middle"]),
        "中相高度": ctx["rehc2"],
        "下相中距(正值)": abs(ctx["sp_lower"]),
        "下相高度": ctx["rehc3"],
        "上相中距(负值)": -abs(ctx["sp_upper"]),
        "中相中距(负值)": -abs(ctx["sp_middle"]),
        "下相中距(负值)": -abs(ctx["sp_lower"]),
        "左避雷线中距(负值)": -abs(ctx["lw_left"]),
        "左避雷线高度": ctx["rehg"],
        "右避雷线中距(正值)": abs(ctx["lw_right"]),
        "右避雷线高度": ctx["rehg"],
    }


def _si_ping_mian(ctx: dict) -> dict[str, float]:
    """猫头/酒杯/干字/门型（单回三相同平面）—— C# ComputeLightningProtection.cs:4117-4166。

    与鼓型同构，差别：feature 名为「左/中/右相」；中相中距由 C# 硬编码为 0。
    高度取渲染后的 REHC1/2/3（= 相高 − 绝缘子串长）。
    """
    return {
        "左相中距(负值)": -abs(ctx["sp_upper"]),
        "左相高度": ctx["rehc1"],
        "中相中距(0值)": 0.0,
        "中相高度": ctx["rehc2"],
        "右相中距(正值)": abs(ctx["sp_lower"]),
        "右相高度": ctx["rehc3"],
        "左避雷线中距(负值)": -abs(ctx["lw_left"]),
        "左避雷线高度": ctx["rehg"],
        "右避雷线中距(正值)": abs(ctx["lw_right"]),
        "右避雷线高度": ctx["rehg"],
    }


def _shangzi(ctx: dict) -> dict[str, float]:
    """上子型（单避雷线）—— C# ComputeLightningProtection.cs:4043-4115。

    相高取「平均高度」= 相高 − 绝缘子 − 1.5；避雷线中距为 0；
    避雷线高度 = |避雷线高 − 1.2|（C# averageHeightBLX = Math.Abs(h - 1.2)）。

    ⚠️ 2026-09-20（对拍 C# 后按 win-csharp #0014 的更正）：C# 模板
    `SettingTxtFile/long_short_dat_model.txt` 的 `<shangzi>` 段**原文**是
      row1 @34 = 中相中距(正值)、row2 @34 = 左相中距(负值)
    而 **LP 自己的规格文件写反了**（曾为 row1=左相(负)/row2=中相(正)）。
    已修正 LP 规格文件去对齐 C# 模板（而非在此处做交换），本函数随之改回**自然映射**：
      row1（中相中距(正值)）← +|物理中相中距|
      row2（左相中距(负值)）← -|物理上相中距|
    高度槽位标签两边一致（row1=左相平均高度、row2=中相平均高度），故高度**不交换**。
    字节结果与修正前完全一致（20/20 不变）。
    """
    ins = float(ctx.get("insulator") or 0.0)
    shield_h = ctx.get("shield_h")
    if shield_h is None:
        shield_h = ctx.get("rehg") or 0.0
    return {
        "中相中距(正值)": abs(ctx["sp_middle"]),
        "左相平均高度": abs(abs(ctx["h_upper"] or 0.0) - ins) - 1.5,
        "左相中距(负值)": -abs(ctx["sp_upper"]),
        "中相平均高度": abs(abs(ctx["h_middle"] or 0.0) - ins) - 1.5,
        "右相中距(正值)": abs(ctx["sp_lower"]),
        "右相平均高度": abs(abs(ctx["h_lower"] or 0.0) - ins) - 1.5,
        "避雷线中距(正值)": 0.0,
        "避雷线平均高度": abs(shield_h - 1.2),
    }


def _avg_h(phase_h, ctx) -> float:
    """C# 平均高度 = |相高 − 绝缘子 − K(电压)|（:1855-1872 / :2161-2191）。"""
    ins = float(ctx.get("insulator") or 0.0)
    k = float(ctx.get("voltage_offset") or 0.0)
    return abs(abs(float(phase_h or 0.0)) - ins - k)


def _sihuita(ctx: dict) -> dict[str, float]:
    """四回型 —— C# :3853-3909（中距 I/III 回为负、II/IV 回为正）。

    规格 <sihuita>：II 回高度沿用 I 回特征名、IV 回沿用 III 回特征名。
    """
    circ = ctx.get("circuits") or []
    out: dict[str, float] = {}
    # ⚠️ 2026-09-20 修复（对拍 C# 时实测 KILL=84 定位）：原实现 src 写成 (0,0,1,1)，
    # 即 I/II 回都取 circ[0]、III/IV 回都取 circ[1] —— 而上下文 `circuits` 是
    # [_circuit_entry(_cg, k) for k in ("I","II","III","IV")] 的**四组**，
    # 于是 12 根导体只剩两组坐标 → 回路 III/IV 与 I/II **几何重合** →
    # ATP 在 LINE CONSTANTS 阶段报
    #   `KILL = 84. Two conductors ... have identical (x,y) geometrical positioning`
    # → 不产出 .pch → sihuita（四回塔）**永远跑不起来**（与引擎 List 容量无关）。
    # 修正为「每回路取自己的那组」：I←0 / II←1 / III←2 / IV←3。
    #
    # ⚠️ 2026-09-20 第二处修复：相高写**原始相高**，不是「平均高度」。
    # 实测对照 C# 侧 sihuita 产物（incoming/win-verify-0042/ev0042/long.dat）：
    #   C#  导体1-3 = -4.8/46.4, -6.1/39.5, -5.2/33.3   （46.4 = 台账原始相高 46.43）
    #   旧 LP        = -4.8/36.8, -6.1/29.9, -5.2/23.7   （36.8 = 46.43 − 绝缘子5 − K4.667）
    # 相高被压低 ~9.7 m 后，回路 III/IV 落到 15.9/11.6/7.8 → LCC 只产出 10 条支路
    # （应为 14）→ work.atp 的 $INCLUDE 要 28 个节点而 .lib 提供不了 → `KILL = 12`。
    # 规格里的槽位标签写的是「平均高度」，但**权威值是原始相高**（标签有误导性）。
    for circ_no, sign, src in (("I", -1, 0), ("II", 1, 1), ("III", -1, 2), ("IV", 1, 3)):
        if len(circ) <= src:
            raise RuntimeError(f"四回型缺少第 {src + 1} 组导线几何，无法改写 .dat")
        c = circ[src]
        for key, label in (("upper", "上相"), ("middle", "中相"), ("lower", "下相")):
            out[f"{circ_no}回线路{label}中距({'负值' if sign < 0 else '正值'})"] = (
                sign * abs(float(c["spacing"].get(key) or 0.0))
            )
            if circ_no in ("I", "III"):
                # ⚠️ 2026-09-20：写**原始相高**（不是 _avg_h）。实测对照 C# 侧 sihuita
                # 产物 long.dat：导体1-3 = -4.8/46.4, -6.1/39.5, -5.2/33.3，
                # 46.4 即台账原始相高；旧实现写 46.43−绝缘子5−K4.667=36.8（错）。
                out[f"{circ_no}回线路{label}平均高度"] = abs(float(c["height"].get(key) or 0.0))
    out["左避雷线中距(负值)"] = -abs(ctx["lw_left"])
    out["避雷线平均高度"] = ctx["rehg"]
    out["右避雷线中距(正值)"] = abs(ctx["lw_right"])
    return out


def _dc(ctx: dict, *, left_label: str, right_label: str, neg_left: bool,
        avg_height: bool) -> dict[str, float]:
    """直流类（2 相）—— C# :4180-4470。

    zj/zx/zxj/ky/nz：写原始相高；zhiliu/vzhiliu：写 |相高 − 绝缘子|（mMinusAbstract）。
    """
    ins = float(ctx.get("insulator") or 0.0)
    lh = ctx["h_left"]
    rh = ctx["h_right"]
    if avg_height:
        lh = abs(abs(float(lh or 0.0)) - ins)
        rh = abs(abs(float(rh or 0.0)) - ins)
    out = {
        f"{left_label}中距({'负值' if neg_left else '正值'})m": (-1 if neg_left else 1) * abs(ctx["sp_left"]),
        f"{left_label}高度m": lh,
        f"{right_label}中距({'正值' if neg_left else '负值'})m": (1 if neg_left else -1) * abs(ctx["sp_right"]),
        f"{right_label}高度m": rh,
        "左避雷线中距(负值)m": -abs(ctx["lw_left"]),
        "左避雷线高度m": ctx["rehg"],
        "右避雷线中距(正值)m": abs(ctx["lw_right"]),
        "右避雷线高度m": ctx["rehg"],
    }
    if avg_height:
        out[f"{left_label}平均高度m"] = lh
        out[f"{right_label}平均高度m"] = rh
        out["避雷线平均高度m"] = abs(float(ctx["rehg"] or 0.0))
    return out


def _zhiliu(ctx: dict) -> dict[str, float]:
    """直流（zhiliu / vzhiliu）—— C# :4362-4470。

    注意与 zj/zx 相反：**左侧取正值、右侧取负值**；含「平均高度」。
    """
    ins = float(ctx.get("insulator") or 0.0)
    lh = abs(abs(float(ctx["h_left"] or 0.0)) - ins)
    rh = abs(abs(float(ctx["h_right"] or 0.0)) - ins)
    return {
        "左相导线中距(正值)m": abs(ctx["sp_left"]),
        "左相导线高度m": ctx["h_left"],
        "左相平均高度m": lh,
        "右相导线中距(负值)m": -abs(ctx["sp_right"]),
        "右相导线高度m": ctx["h_right"],
        "右相平均高度m": rh,
        "左避雷线中距(正值)m": abs(ctx["lw_left"]),
        "避雷线高度m": ctx["rehg"],
        "避雷线平均高度m": abs(float(ctx["rehg"] or 0.0)),
        "右避雷线中距(负值)m": -abs(ctx["lw_right"]),
    }


def build_values(section: str, **ctx) -> dict[str, float]:
    kind = section.split("-", 1)[0]
    if kind == "guxing":
        return _guxing(ctx)
    if kind in {"maotou", "jiubei", "ganzi", "menxing"}:
        return _si_ping_mian(ctx)
    if kind == "shangzi":
        return _shangzi(ctx)
    if kind == "sihuita":
        return _sihuita(ctx)
    if kind in {"zj", "zx", "zxj"}:
        return _dc(ctx, left_label="左相导线", right_label="右相导线",
                   neg_left=True, avg_height=False)
    if kind == "ky":
        return _dc(ctx, left_label="左侧导线", right_label="右侧导线",
                   neg_left=True, avg_height=False)
    if kind == "nz":
        return _dc(ctx, left_label="左侧横担正下方跳线", right_label="右侧横担正下方跳线",
                   neg_left=True, avg_height=False)
    if kind in {"zhiliu", "vzhiliu"}:
        return _zhiliu(ctx)
    raise RuntimeError(
        f"塔型段 '{section}' 的 .dat 几何取值尚未移植（需按 C# ComputeLightningProtection.cs 对应分支实现）；"
        f"为避免静默产出错误几何，此处显式报错"
    )


# ⚠️ 2026-09-20 修复（sihuita 四回塔 .lib 支路数 14→9 的根因）：
# 旧正则要求行首 '-'+数字，但 .pch 里分支号 ≥10 的行写作 '10IN___JOUT__J'（无 '-'），
# 于是 14 根导体只认出 9 条支路 → KARG 只给 9 对节点（18 个），$INCLUDE 要的 28 个节点缺 10 个
# → ATP simulate 阶段 KILL=12「bus name ... unrecognizable ("X0516A")」。
# C# BuildLib_FromPch() 的判据是「行首 '-'」或「第 3 字符起 'IN___'」的**并集** ⇒ 放宽为可选 '-'。
# 安全性（实测 42 个资产 .pch）：非 sihuita 塔型（110/220/500 的 guxing/ganzi/jiubei）dash 数 == 并集数
# （5 或 8），本改动对它们是 no-op；仅 sihuita（14 导体）dash=9 / 并集=14，正是要修的场景。
# ⚠️ 2026-09-29 修复：兼容两种 .pch 节点名格式（实测 36 资产）
#   · 字母版（14 导体 sihuita 等）：-1IN___AOUT__A（IN___A / OUT__A）
#   · 数字版（3 导体 shangzino 无避雷线等）：-1IN_001OUT001（IN_001 / OUT001）
# 旧正则只认字母版 → 数字版 .pch 找不到分支头 → 「pch 中找不到数据起点」。
# 统一模式：-<分支号>IN_<节点名>OUT<节点名>（6 字符，见上）
_BRANCH_HEAD = re.compile(r"^-?\d+(IN_+[A-Z0-9]+?)(OUT[A-Z0-9_]+)")


def _pack_header(card: str, values: list[int]) -> str:
    """按 C# BuildLib_FromPch() 的版式把 KARD/KARG/KBEG/KEND/KTEX 头卡分页写出。

    ⚠️ 2026-09-20 修复（sihuita 四回塔 simulate 报 `lately reading sequential formatted
    internal IO`、rc=3 的根因）：phase_N=14 时每张头卡有 28 个 3 宽字段 = 88 列，
    超过 ATP 卡片的 80 列上限 → ATP 格式化读失败直接退出（.pl4 不产出）。
    C# 侧对 phase_N ≥ 14 做了硬编码分页（ComputeLightningProtection.cs:12037-12093）：
      首行 = 卡名 + 至多 25 个 3 宽字段（= 79 列）
      续行 = 7 宽首字段 + 3 宽后续字段（= 13 列 / 3 值）
    实测（本容器 wine + tpbig.exe）：
      · 88 列头卡 → rc=3「lately reading sequential formatted internal IO」
      · 改成本版式后 → rc=0，推进到 KILL=1「Storage exceeded for EMTP List Number 8」（引擎容量，与 C# 同层）
    字段数 ≤ 25 时不产生续行，输出与旧实现逐字节相同（不影响 5/8 支路的其它塔型）。
    """
    out: list[str] = []
    rest = list(values)
    first = True
    while rest:
        if first:
            head, cap = card, 25          # 4 + 25*3 = 79 列
            first = False
        else:
            head, cap = "", 24            # 7 + 24*3 = 79 列
        chunk, rest = rest[:cap], rest[cap:]
        if head:
            out.append(head + "".join("%3d" % v for v in chunk))
        else:
            out.append("%7d" % chunk[0] + "".join("%3d" % v for v in chunk[1:]))
    return "\n".join(out)


def pch_to_lib(pch_text: str) -> str:
    """把 LCC 输出的 .pch 数据卡转换为 ATP 的 .lib 线路模型库文件。

    ⚠️ 2026-09-17 两次修复（220 鼓型塔 ganzi/jiubei/maotou 全失败 KILL=79 的根因）：
    旧实现 KBEG=(3,n+1)/KEND=(n,n+6) 与 ATP 模板 .lib 的固定格式
    （KBEG 3-9 / KEND 8-14，节点名 6 字符）不匹配 → ATP 解析 $INCLUDE 节点名
    length mismatch → KILL=79、无 work.lis。guxing 恰未触发（缓存/格式碰巧匹配）。

    KARD 规则（C# 样本推导，2026-09-17）：KARD 卡边界 = 各分支头在数据区的
    （0-based）行号 + 2 —— 不能用模板头部（模板 KARD 是别的几何的行号，硬套
    会导致 ATP `fmt: read unexpected character` rc=3）。

    正确格式（对齐 C# 样本，逐字节验证）：
      KARD: 分支头行号+2（与本次 .pch 数据配套）
      KBEG: 每分支 (3, 9)   ← 节点名起列
      KEND: 每分支 (8, 14)  ← 节点名止列（6 字符）
    """
    lines = pch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # ⚠️ 2026-09-29 修复：数据起点兼容数字/字母节点名（-1IN_001 / -1IN___A）
    di = next(
        (i for i, x in enumerate(lines) if _BRANCH_HEAD.match(x)),
        None,
    )
    if di is None:
        raise ValueError("pch 中找不到数据起点 (-1IN___ ...)")
    data = lines[di:]
    while data and not data[-1].strip():
        data.pop()                            # 丢掉尾部空行（C# 不写它们）
    heads = [(i, x) for i, x in enumerate(data) if _BRANCH_HEAD.match(x)]
    if not heads:
        raise ValueError("pch 中找不到分支头")
    nodes = [m.groups() for m in (_BRANCH_HEAD.match(x) for _, x in heads) if m]
    n = len(nodes)
    # KARD = 各分支头行号 + 2（对齐 C#：KARD 值 = 0-based 分支头行号 + 2）
    kard = [v for i, _ in heads for v in (i + 2, i + 2)]
    karg = [v for i in range(1, n + 1) for v in (i, i + n)]
    kbeg = [v for _ in range(n) for v in (3, 9)]
    kend = [v for _ in range(n) for v in (8, 14)]
    ktex = [v for _ in range(n) for v in (1, 1)]
    ins = [a for a, _ in nodes]
    outs = [b for _, b in nodes]
    body = "\n".join(data)
    arg = "ARG, " + ", ".join(ins + outs) + ","
    return (
        _pack_header("KARD", kard) + "\n"
        + _pack_header("KARG", karg) + "\n"
        + _pack_header("KBEG", kbeg) + "\n"
        + _pack_header("KEND", kend) + "\n"
        + _pack_header("KTEX", ktex) + "\n"
        + "/BRANCH\n"
        + body + "\n"
        + "$EOF\n"
        + arg + "\n"
    )
