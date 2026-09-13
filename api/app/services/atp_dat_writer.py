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
    v = float(value)
    if abs(v) < 1e-12:
        # C# 对零值输出 "0.0"（实测 maotou .dat 中相中距），不参与去尾零
        return ("0.0" if digits == 1 else f"{v:.{digits}f}").rjust(width)
    txt = f"{v:.{digits}f}"
    if "." in txt:
        txt = txt.rstrip("0")      # C# 去尾零：12.0 → "12."
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
    """上子型（单避雷线）—— C# ComputeLightningProtection.cs:4079-4113。

    相高取「平均高度」= 相高 − 绝缘子 − 1.5；避雷线中距为 0；
    避雷线高度 = |避雷线高 − 1.2|（C# averageHeightBLX = Math.Abs(h - 1.2)）。
    """
    ins = float(ctx.get("insulator") or 0.0)
    return {
        "左相中距(负值)": -abs(ctx["sp_upper"]),
        "左相平均高度": abs(abs(ctx["h_upper"] or 0.0) - ins) - 1.5,
        "中相中距(正值)": abs(ctx["sp_middle"]),
        "中相平均高度": abs(abs(ctx["h_middle"] or 0.0) - ins) - 1.5,
        "右相中距(正值)": abs(ctx["sp_lower"]),
        "右相平均高度": abs(abs(ctx["h_lower"] or 0.0) - ins) - 1.5,
        "避雷线中距(正值)": 0.0,
        "避雷线平均高度": abs(ctx["rehg"] - 1.2),
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
    for circ_no, sign, src in (("I", -1, 0), ("II", 1, 0), ("III", -1, 1), ("IV", 1, 1)):
        if len(circ) <= src:
            raise RuntimeError(f"四回型缺少第 {src + 1} 组导线几何，无法改写 .dat")
        c = circ[src]
        for key, label in (("upper", "上相"), ("middle", "中相"), ("lower", "下相")):
            out[f"{circ_no}回线路{label}中距({'负值' if sign < 0 else '正值'})"] = (
                sign * abs(float(c["spacing"].get(key) or 0.0))
            )
            if circ_no in ("I", "III"):
                out[f"{circ_no}回线路{label}平均高度"] = _avg_h(c["height"].get(key), ctx)
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


_BRANCH_HEAD = re.compile(r"^-\d+(IN___[A-Z]+)(OUT__[A-Z]+)")


def pch_to_lib(pch_text: str) -> str:
    lines = pch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    di = next((i for i, x in enumerate(lines) if x.startswith("-1IN___")), None)
    if di is None:
        raise ValueError("pch 中找不到数据起点 (-1IN___ ...)")
    data = lines[di:]
    while data and not data[-1].strip():
        data.pop()                            # 丢掉尾部空行（C# 不写它们）
    heads = [(i, x) for i, x in enumerate(data) if _BRANCH_HEAD.match(x)]
    if not heads:
        raise ValueError("pch 中找不到分支头")
    ptrs = [i + 2 for i, _ in heads]          # 行号(1-based)+1
    nodes = [m.groups() for m in (_BRANCH_HEAD.match(x) for _, x in heads) if m]
    n = len(nodes)
    kard = "".join("%3d" % p for p in ptrs)
    kard = "".join("%3d" % v for p in ptrs for v in (p, p))
    karg = "".join("%3d" % v for i in range(1, n + 1) for v in (i, i + n))
    kbeg = "".join("%3d" % v for _ in range(n) for v in (3, n + 1))
    kend = "".join("%3d" % v for _ in range(n) for v in (n, n + 6))
    ktex = "".join("%3d" % v for _ in range(n) for v in (1, 1))
    ins = [a for a, _ in nodes]
    outs = [b for _, b in nodes]
    body = "\n".join(data)
    arg = "ARG, " + ", ".join(ins + outs) + ","
    return (
        "KARD" + kard + "\n"
        + "KARG" + karg + "\n"
        + "KBEG" + kbeg + "\n"
        + "KEND" + kend + "\n"
        + "KTEX" + ktex + "\n"
        + "/BRANCH\n"
        + body + "\n"
        + "$EOF\n"
        + arg + "\n"
    )
