"""work.atp 里「C# 运行期计算并写回」的槽位改写（对齐 C#）。

C# 在调用 tpbig **之前**会把一批运行期算出的值刷进 work.atp
（`ThreadCompute5_work_atp()` → `Update_work_atp1(strPath+"work.atp", mSet_WorkAtp_Feature, 0)`，
ComputeLightningProtection.cs:6128）。这些值**不是资产数据**，未跑过的资产保持模板原值，
所以「文件里的值不能当权威，公式才是权威」。

本模块补两个此前 LP 缺失的槽位：

1. **`11K0` = 耦合系数 k0（几何系数）**  —— C# `fetch_CouplingCoefficient()`（:11484-11668）
   · 规格（SettingTxtFile/work_atp_model.txt）：`11K0      #10#10#{0,10:F2}#ioType1#耦合系数k0#`
     ⇒ 偏移 10、宽 10、F2、右对齐
   · 公式：
       y1 = 避雷线高度 − 2/3·避雷线弧垂         x1 = 右避雷线中距
       y2 = y1                                   x2 = −|左避雷线中距|
       y3 = ha − 2/3·导线弧垂 − 绝缘子串长        x3/ha = 相导线中距/高度（见 _phase_x3_ha）
       d31=hypot(x1−x3, y1−y3)  D31=hypot(x1−x3, y1+y3)
       d32=hypot(x2−x3, y2−y3)  D32=hypot(x2−x3, y2+y3)
       d12=hypot(x2−x1, y2−y1)  D12=hypot(x2−x1, y2+y1)
       z11=ln(2·y1/rk)  z12=ln(D12/d12)  z31=ln(D31/d31)  z32=ln(D32/d32)   (rk=0.0055)
       k0 = (z31+z32)/(z11+z12)          ← 写进 11K0
       k  = k1·k0                        （k1=电晕系数，本模块不写，供参考）
       guxingd（双回单 66）特例：x1=x2=0 且 k0 = z31/z11
   · 逐塔型不同（220kV 实测）：ganzi 0.38 / guxing 0.35 / jiubei 0.27 / maotou 0.24
     —— 所以**不能把模板的 0.25 改成 0.38**（那只修好 ganzi），必须算。

2. **`14XXSS` = 电源电角度** —— C# :1906-1916 / 读参 :1655（单回 IDin19）
   · 规则：`electricAngle = 电角度(角度制) − 90`；A/B/C = 该值 / 该值−120 / 该值−240
   · 资产模板原值为 `空 / -120 / -240`（= 电角度 0 时未减 90），C# 实跑写 `-90/-210/-330`。
   · 三相整体旋转 90°（1/4 工频周期）会改变雷击注入时刻的相电压 → 足以翻转闪络相。
"""

from __future__ import annotations

import math
from typing import Any, Mapping

RK = 0.0055
"""地线半径（分裂导线取几何均距），C# 常量，不随电压变。"""

# 电压分档：(避雷线弧垂 m, 导线弧垂 m, 电晕系数 k1)
_VOLTAGE_PROFILE = {
    35: (1.1, 1.8, 1.15),
    66: (1.1, 1.8, 1.15),
    110: (2.8, 5.3, 1.20),
    220: (7.0, 12.0, 1.25),
}
_VOLTAGE_PROFILE_HIGH = (9.5, 12.0, 1.28)   # ≥500kV 及直流

_K0_SLOT = ("11K0", 10, 10, 2)              # 名称、偏移、宽、F2
# ⚠️ 2026-09-20 修复：偏移原写成 34（错 2 列）。实测 C# 产物：
#   14XXSS2A …第3字段「-90.」落在第 36..39 列、14XXSS2B「-120.」落在第 35..39 列
#   ⇒ 字段 = 偏移 32、宽 8、右对齐。ATP 是**固定列格式**，错 2 列会被读成别的值，
#     实测导致 220/ganzi 的闪络相由 C1(SWU3) 翻成 B1(SWU2)。
_ANGLE_OFFSET, _ANGLE_WIDTH = 32, 8
_ANGLE_SLOTS = ("14XXSS2A", "14XXSS1A", "14XXSS2B", "14XXSS1B", "14XXSS2C", "14XXSS1C")

_DOUBLE_CIRCUIT = {"guxing", "guxingd", "sihuita", "sihuitano", "guxingno"}
_GUXINGD = {"guxingd"}


def _voltage_profile(voltage_kv: float, is_dc: bool) -> tuple[float, float, float]:
    if is_dc:
        return _VOLTAGE_PROFILE_HIGH
    v = int(voltage_kv)
    if v in _VOLTAGE_PROFILE:
        return _VOLTAGE_PROFILE[v]
    return _VOLTAGE_PROFILE_HIGH


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_sequence(phase_sequence: Any) -> list[str]:
    """把相序规整成 ['A','B','C'] 形式的 3 字母表。

    兼容三种输入：`"BCA"`、`["B","C","A"]`、`["BCA"]`（case.json 的 `raw.相序.相序` 形态）。
    """
    if not phase_sequence:
        return ["A", "B", "C"]
    raw = phase_sequence[0] if isinstance(phase_sequence, (list, tuple)) and phase_sequence else phase_sequence
    letters = [c for c in str(raw).strip().upper() if c in ("A", "B", "C")]
    return letters if len(letters) >= 3 else ["A", "B", "C"]


def _phase_x3_ha(
    tower_kind: str, geometry: Mapping[str, Any], phase_sequence: list[str] | None = None
) -> tuple[float | None, float | None]:
    """取 (x3, ha)：单回/直流取**物理上相**；双回/四回取**物理上相**（C# :11560-11613 的 switch）。

    C# 双回用 `m上相中距sh_m[0]` / `m上相高度sh_m[0]`，单回用 `m左相导线中距_m` /
    `m左相导线高度_m` —— 而 `m左相导线中距_m ≡ m上相中距`（win-csharp #0010 核实），
    所以两种情况**都取物理上相**。
    ⚠️ 台账「上/中/下」三列承载的是 A/B/C 相值，物理上相 = 台账列[相序[0]]，
    必须先按相序重排（否则 guxing(BCA) 会取错，实测 k0 0.169 vs C# 0.35）。
    """
    from .atp_phase_sequence import permute_layer

    seq = _normalize_sequence(phase_sequence)
    layer = permute_layer(geometry, seq)
    spacing = (layer or {}).get("phase_spacing_m") or {}
    height = (layer or {}).get("phase_height_m") or {}
    return _f(spacing.get("upper")), _f(height.get("upper"))


def coupling_k0(
    *,
    tower_kind: str,
    voltage_kv: float,
    shield_wire_height_m: float | None,
    left_mid_distance_m: float | None,
    right_mid_distance_m: float | None,
    insulator_length_m: float | None,
    phase_geometry: Mapping[str, Any],
    is_dc: bool = False,
    phase_sequence: list[str] | None = None,
) -> float | None:
    """算几何耦合系数 k0（= C# `fetch_CouplingCoefficient()` 的 `k0`）。取不到输入返回 None。"""
    if (
        shield_wire_height_m is None
        or left_mid_distance_m is None
        or right_mid_distance_m is None
        or insulator_length_m is None
    ):
        return None
    x3, ha = _phase_x3_ha(tower_kind, phase_geometry, phase_sequence)
    if x3 is None or ha is None:
        return None

    # ⚠️ 单位防御：绝缘子串长必须是**米**。杆塔 profile 里存的是毫米（1142.85），
    # 调用方需自行 /1000；此处对明显是毫米的值直接报错，避免静默算出错误 k0。
    if insulator_length_m > 20.0:
        raise ValueError(
            f"coupling_k0 的 insulator_length_m 需要「米」，收到 {insulator_length_m}（疑似毫米）。"
            "请调用方按 profile.insulator_length_m / 1000 转换。"
        )

    blx_vertical, dx_vertical, _k1 = _voltage_profile(voltage_kv, is_dc)
    y1 = shield_wire_height_m - blx_vertical * 2.0 / 3.0
    x1 = right_mid_distance_m
    x2 = -abs(left_mid_distance_m)
    y2 = y1
    y3 = ha - dx_vertical * 2.0 / 3.0 - insulator_length_m
    if y1 <= 0:
        return None

    if tower_kind in _GUXINGD:
        x1 = 0.0
        x2 = 0.0

    d31 = math.hypot(x1 - x3, y1 - y3)
    d31i = math.hypot(x1 - x3, y1 + y3)
    d32 = math.hypot(x2 - x3, y2 - y3)
    d32i = math.hypot(x2 - x3, y2 + y3)
    d12 = math.hypot(x2 - x1, y2 - y1)
    d12i = math.hypot(x2 - x1, y2 + y1)
    if min(d31, d31i, d32, d32i, d12) <= 0:
        return None

    z11 = math.log(2.0 * y1 / RK)
    z12 = math.log(d12i / d12)
    z31 = math.log(d31i / d31)
    z32 = math.log(d32i / d32)
    if tower_kind in _GUXINGD:
        return z31 / z11 if z11 else None
    denom = z11 + z12
    if math.isclose(denom, 0.0, abs_tol=1e-12):
        return None
    return (z31 + z32) / denom


def _write_slot(line: str, offset: int, width: int, digits: int, value: float) -> str:
    """按「右对齐、去尾零、F{digits}」写槽位（C# FeatureSetOfATP 语义）。"""
    from .atp_dat_writer import _fmt  # 复用同一套槽位格式化（.dat 侧已验证）

    field = _fmt(value, digits, width)
    padded = line.ljust(offset + width)
    return padded[:offset] + field + padded[offset + width:]


def rewrite_coupling_k0(text: str, k0: float | None) -> tuple[str, bool]:
    """把 k0 写进 `11K0` 槽位。返回 (新文本, 是否改写)。"""
    if k0 is None:
        return text, False
    name, offset, width, digits = _K0_SLOT
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(name):
            lines[i] = _write_slot(line, offset, width, digits, k0)
            return "\n".join(lines), True
    return text, False


def rewrite_electric_angle(text: str, angle_deg: float | None) -> tuple[str, bool]:
    """按 C# 规则写 `14XXSS` 三相电角度：A=angle−90、B=angle−210、C=angle−330。"""
    if angle_deg is None:
        return text, False
    base = float(angle_deg) - 90.0
    values = {
        "14XXSS2A": base, "14XXSS1A": base,
        "14XXSS2B": base - 120.0, "14XXSS1B": base - 120.0,
        "14XXSS2C": base - 240.0, "14XXSS1C": base - 240.0,
    }
    lines = text.split("\n")
    changed = False
    for i, line in enumerate(lines):
        for slot, value in values.items():
            if line.startswith(slot):
                lines[i] = _write_slot(line, _ANGLE_OFFSET, _ANGLE_WIDTH, 1, value)
                changed = True
                break
    return ("\n".join(lines), True) if changed else (text, False)
