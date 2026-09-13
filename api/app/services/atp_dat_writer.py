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
    txt = f"{float(value):.{digits}f}"
    if "." in txt:
        txt = txt.rstrip("0")
    return txt.rjust(width)


def rewrite_dat_text(text: str, section: str, values: dict[str, float], *,
                     span_km: float | None = None) -> str:
    """把 values 写进 .dat（几何段 + 可选档距）。行尾原样保留。"""
    slots = load_spec().get(section)
    if not slots:
        raise RuntimeError(f"long_short_dat_model.txt 无塔型段 '{section}'，无法改写 .dat 几何")
    parts = re.split(r"(\r\n|\n)", text)
    lines = [ln.rstrip("\r") for ln in parts[0::2]]

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
        _write(slot.conductor + _CONDUCTOR_LINE_OFFSET - 1, slot.offset, slot.width,
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


def build_values(section: str, **ctx) -> dict[str, float]:
    kind = section.split("-", 1)[0]
    if kind == "guxing":
        return _guxing(ctx)
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
