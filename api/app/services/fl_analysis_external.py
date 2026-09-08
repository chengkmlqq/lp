from __future__ import annotations

import json
import logging
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# C# 桌面版倍率表（BeiShu.txt，2025-11-20 执行目录 SettingTxtFile/BeiShu.txt 实测）：
# - 反击 fanji：除 35kV guxing/guxingd=0.7 外，全部 1.0（含 500kV guxing）
# - 绕击 raoji：110/220/500kV 且塔型∈{menxing,ganzi,guxing,guxingd,maotou,jiubei} 取 1.1；
#   sihuita 35/110/220 取 1.1；shangzi 与直流塔型恒 1.0；其余 1.0
# 注意：MyConst.cs 默认 mBeiShu_fanji=0.7 会被 LoadFromSettingFile_BeiShu 覆盖，
# 不能拿默认常量当最终倍率（曾因此误把 ATP 500kV fanji 输出 ×0.7，系统性低 30%）。
_CSHARP_BEISHU_RAOJI_110_220_500 = {"menxing", "ganzi", "guxing", "guxingd", "maotou", "jiubei"}


def csharp_beishu_multiplier(*, tower_kind: str, voltage_kv: int | None, is_counterstrike: bool) -> float:
    """按 C# BeiShu.txt 查显示倍率（mBeiShu_fanji / mBeiShu_raoji）。"""
    kind = str(tower_kind or "").strip().lower()
    voltage = int(voltage_kv) if voltage_kv else 0
    if is_counterstrike:
        # fanji：仅 35kV 鼓型（guxing/guxingd）取 0.7，其余 1.0
        if voltage <= 35 and kind in ("guxing", "guxingd"):
            return 0.7
        return 1.0
    # raoji
    if kind == "sihuita":
        return 1.1 if voltage in (35, 110, 220) else 1.0
    if voltage in (110, 220, 500) and kind in _CSHARP_BEISHU_RAOJI_110_220_500:
        return 1.1
    return 1.0

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.atp_asset import AtpAsset
from ..models.base import utcnow
from ..models.fl_analysis import FlAnalysisJob, FlAnalysisTowerSnapshot
from .atp_asset_service import (
    _normalize_optional_str,
    _normalize_relative_path,
    _resolve_engine_workdir,
    _resolve_mount,
    _resolve_native_engine_executable,
    _resolve_timeout,
    _resolve_wine_engine_executable,
    _truncate_output,
    _walk_storage_tree,
)
from .storage_driver import (
    StorageDriverError,
    build_storage_driver,
    normalize_virtual_path,
)

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([^{}]+?)\s*}}")


def _normalize_tower_shape_code(value: str) -> str:
    """规范化塔型编码用于资产子目录名（LP-560）。

    C# 式塔型编码如 d500shangzi/s500guxing/zhiliu500 仅含字母数字；
    中文「直线/耐张」或空值返回空串，调用方回退到资产根目录模板。
    """
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]", "", value.lower())
    if not normalized or not re.search(r"[a-z]", normalized):
        return ""
    return normalized


# ---------------------------------------------------------------------------
# C# 桌面版 work.atp 参数计算（参照 lp-knowledge V1_Invoke_CircuitLightningProtection_Base
# / ComputeLightningProtection.cs 的 500kV 公式）。
# work.atp 的 $PARAMETER 区是 NAME=占位符 格式（如 REHG______=REHGI），必须逐参数
# 替换为「带小数点」的数值，否则 tpbig 报 TACS/JTOKEN 错误。
# ---------------------------------------------------------------------------
CSHARP_PARAM_ORDER = [
    "RER001", "RELENS____",
    "RELE01", "RELE02", "RELE03", "RELE04", "RELE05", "RELE06",
    "RELE07", "RELE08", "RELE09", "RELE10",
    "REHG______", "REHC1_____", "REHC2_____", "REHC3_____",
    "REIGAN____", "REIAMP____", "HIAMP_____",
    "REAA______", "REBB______", "REAA1_____", "REBB1_____",
    "REHSUR____", "REHSLO____", "REHHEI____",
]


def _as_float(value: Any) -> float | None:
    """宽松转 float，None/空/非法返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_csharp_atp_params(*, base_tower: dict[str, Any], profile: dict[str, Any],
                             execution_options: dict[str, Any]) -> dict[str, str]:
    """按 C# 桌面版公式计算 work.atp $PARAMETER 全部参数值。

    公式对齐 ComputeLightningProtection.cs 的 ganzi/maotou/jiubei/guxing 塔型分支
    （各电压等级 mDYDJ 分级修正）。返回 {参数名: 字符串值}，值统一带小数点。
    """
    import math

    def f(v):
        return _as_float(v)

    insul_mm = f(profile.get("insulator_length_m"))
    insul_m = insul_mm / 1000.0 if insul_mm and insul_mm > 100 else insul_mm
    shield_h = f(profile.get("shield_wire_height_m"))
    # 二分法迭代电流优先（kA）；profile.current_a 仅作初值
    current_ka = f(execution_options.get("binary_search_current_ka")) or f(profile.get("current_a")) or 0.0
    head_t_raw_ms = f(profile.get("current_head_time_ms"))
    if head_t_raw_ms is None:
        head_t_us = f(profile.get("current_head_time_us"))
        # C# 桌面版默认波头 2.6ms（LP_Task.txt）
        head_t_ms = head_t_us / 1000.0 if head_t_us is not None else 2.6
    else:
        head_t_ms = head_t_raw_ms
    tail_t_raw_ms = f(profile.get("current_tail_time_ms"))
    if tail_t_raw_ms is None:
        tail_t_us = f(profile.get("current_tail_time_us"))
        # C# 桌面版默认波尾 50ms（LP_Task.txt）
        tail_t_ms = tail_t_us / 1000.0 if tail_t_us is not None else 50.0
    else:
        tail_t_ms = tail_t_raw_ms
    ground_r = f(base_tower.get("ground_resistance_ohm"))

    cg = base_tower.get("circuit_geometry_json") or {}
    lightning_wire = cg.get("lightning_wire") or {}
    mid_l = f(lightning_wire.get("left_mid_distance_m"))
    mid_r = f(lightning_wire.get("right_mid_distance_m"))
    if mid_l is None:
        mid_l = f(cg.get("left_mid_distance_m"))
    if mid_r is None:
        mid_r = f(cg.get("right_mid_distance_m"))
    tower_h = f(cg.get("tower_height_m")) or f(profile.get("call_height_m"))

    geometry = profile.get("geometry_layers_json") or {}
    layer_i = geometry.get("I") or {}
    ph = layer_i.get("phase_height_m") or {}
    spacing = layer_i.get("phase_spacing_m") or {}
    left_h = f(ph.get("upper"))
    mid_h = f(ph.get("middle"))
    right_h = f(ph.get("lower"))
    left_spacing = f(spacing.get("upper"))
    right_spacing = f(spacing.get("lower"))
    voltage = f(base_tower.get("line_voltage_kv")) or 500.0

    # 电压分级 → C# switch(mDYDJ) 修正量（ganzi 段 2005-2048）
    def vadj(series):
        if voltage <= 35: return series[0]
        if voltage <= 66: return series[1]
        if voltage <= 110: return series[2]
        if voltage <= 220: return series[3]
        if voltage <= 330: return series[4]
        if voltage <= 500: return series[5]
        if voltage <= 750: return series[6]
        return series[7]

    rehg_adj = vadj([2.0, 1.2, 2.0, 10.0 / 3.0, 10.0 / 3.0, 8.0, 10.0 / 3.0, 0.0])   # REHG 避雷线平均高度修正
    rehc_adj = vadj([10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 6.0, 14.0 / 3.0, 0.0])  # REHC1/2/3 相高修正
    rel01_adj = vadj([3.5, 8.6, 8.6, 8.5, 10.5, 14.0, 20.0, 28.9])  # RELE01 呼高修正（ganzi 2637-2645）

    def fmt(v, digits=2):
        if v is None:
            return "1."
        try:
            return f"{float(v):.{digits}f}"
        except (TypeError, ValueError):
            return "1."

    p: dict[str, str] = {}
    p["RER001"] = fmt(ground_r, 1)
    p["RELENS____"] = fmt(insul_m, 2)

    tower_kind = str(execution_options.get("tower_kind") or profile.get("tower_kind") or "ganzi").strip().lower()
    if tower_kind in ("guxing", "guxingd"):
        # === guxing 鼓型双回塔（C# 2104-2244）===
        # 数据语义：双回塔几何存于 geometry_layers_json.I（左回路）
        # RELE01 下相高度（左回路下相）
        p["RELE01"] = fmt(right_h, 1)
        p["RELE02"] = fmt(right_h * 1.5 if right_h is not None else None, 1)
        # RELE03 下相左侧中距（spacing.lower）
        p["RELE03"] = fmt(abs(right_spacing) if right_spacing is not None else None, 1)
        # RELE04 中相下相高度差绝对值（<1.5 钳 1.5）
        h4 = abs(mid_h - right_h) if (mid_h is not None and right_h is not None) else None
        if h4 is not None and h4 < 1.5:
            h4 = 1.5
        p["RELE04"] = fmt(h4, 2)
        p["RELE05"] = fmt(h4 * 1.5 if h4 is not None else None, 2)
        # RELE06 中相左侧中距（spacing.middle）
        p["RELE06"] = fmt(abs(left_spacing) if left_spacing is not None else None, 1)
        # RELE07 上相中相高度差绝对值（<1.5 钳 1.5）
        h7 = abs(left_h - mid_h) if (left_h is not None and mid_h is not None) else None
        if h7 is not None and h7 < 1.5:
            h7 = 1.5
        p["RELE07"] = fmt(h7, 2)
        p["RELE08"] = fmt(h7 * 1.5 if h7 is not None else None, 2)
        # RELE09 上相左侧中距
        p["RELE09"] = fmt(abs(left_spacing) if left_spacing is not None else None, 2)
        # RELE10 避雷线上相高度差绝对值（<1.5 钳 1.5）
        h10 = abs(shield_h - left_h) if (shield_h is not None and left_h is not None) else None
        if h10 is not None and h10 < 1.5:
            h10 = 1.5
        p["RELE10"] = fmt(h10, 2)
        # RELE11 一点五倍RELE10
        p["RELE11"] = fmt(h10 * 1.5 if h10 is not None else None, 2)
        # RELE12 左避雷线中距
        p["RELE12"] = fmt(abs(mid_l) if mid_l is not None else None, 2)
        # REHG 避雷线平均高度 = |避雷线高度 - 修正|（500kV: -6）
        p["REHG______"] = fmt(abs(shield_h - vadj([2.0, 1.2, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0])) if shield_h is not None else None, 1)
        # REHC1/2/3 上/中/下相平均高度 = |相高 - 绝缘子串长 - 修正|（500kV: -8）
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - vadj([10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 1)
    elif tower_kind in ("jiubei", "maotou"):
        # === jiubei 酒杯型塔（C# 2548-2750）===
        # RELE01 第一节主材 = |呼高 - 电压修正|（500kV: -14）
        rel01 = abs(tower_h - rel01_adj) if tower_h else None
        p["RELE01"] = fmt(rel01, 1)
        p["RELE02"] = fmt(rel01 * 1.5 if rel01 is not None else None, 1)
        # RELE03 左波阻抗 = |左相中距 - 修正|（500kV: -5）
        p["RELE03"] = fmt(abs(left_spacing - vadj([2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7])) if left_spacing is not None else None, 1)
        p["RELE04"] = fmt(abs(right_spacing - vadj([2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7])) if right_spacing is not None else None, 1)
        # RELE05 左避雷线斜线距离 = sqrt(|左中距-修正|² + (避雷线高-左相高-修正)²)
        if mid_l is not None and shield_h is not None and left_h is not None:
            d5 = math.sqrt((abs(mid_l) - vadj([2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7])) ** 2
                           + (shield_h - left_h - vadj([0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0])) ** 2)
            p["RELE05"] = fmt(abs(d5), 2)
        else:
            p["RELE05"] = "1."
        # RELE06 右避雷线斜线距离
        if mid_r is not None and shield_h is not None and right_h is not None:
            d6 = math.sqrt((abs(mid_r) - vadj([2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7])) ** 2
                           + (shield_h - right_h - vadj([0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0])) ** 2)
            p["RELE06"] = fmt(abs(d6), 2)
        else:
            p["RELE06"] = "1."
        # RELE07 左避雷线中距、RELE08 右避雷线中距
        p["RELE07"] = fmt(abs(mid_l) if mid_l is not None else None, 2)
        p["RELE08"] = fmt(abs(mid_r) if mid_r is not None else None, 2)
        p["RELE09"] = "1."
        p["RELE10"] = "1."
        p["REHG______"] = fmt(abs(shield_h - rehg_adj) if shield_h is not None else None, 1)
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - rehc_adj) if (h is not None and insul_m is not None) else None, 1)
    else:
        # === ganzi 干字型塔（C# 1936-2100）===
        # RELE01 第一节主材 = 左相高度（C# 1937）
        rel01 = left_h
        p["RELE01"] = fmt(rel01, 1)
        p["RELE02"] = fmt(rel01 * 1.5 if rel01 is not None else None, 1)
        # RELE03 左波阻抗 = |左相中距|（ganzi 段减 0）
        p["RELE03"] = fmt(abs(left_spacing) if left_spacing is not None else None, 1)
        p["RELE04"] = fmt(abs(right_spacing) if right_spacing is not None else None, 1)
        # RELE05 中相左相高度差（<1.5 钳到 1.5）
        h5 = abs(mid_h - left_h) if (mid_h is not None and left_h is not None) else None
        if h5 is not None and h5 < 1.5:
            h5 = 1.5
        p["RELE05"] = fmt(h5, 2)
        p["RELE06"] = fmt(h5 * 1.5 if h5 is not None else None, 2)
        # RELE07 避雷线高度与中相高度之差（<1.5 钳到 1.5）
        h7 = abs(shield_h - mid_h) if (shield_h is not None and mid_h is not None) else None
        if h7 is not None and h7 < 1.5:
            h7 = 1.5
        p["RELE07"] = fmt(h7, 2)
        p["RELE08"] = fmt(h7 * 1.5 if h7 is not None else None, 2)
        # RELE09/10 左/右避雷线中距绝对值（C# 1996/2000）
        # 优先用 circuit_geometry.lightning_wire 中距；缺失时用保护角推导 x = h*tan(alpha) 回退
        angle_l = f(profile.get("protection_angle_left_deg"))
        angle_r = f(profile.get("protection_angle_right_deg"))
        if mid_l is None and angle_l is not None and shield_h:
            mid_l = shield_h * math.tan(math.radians(angle_l))
        if mid_r is None and angle_r is not None and shield_h:
            mid_r = shield_h * math.tan(math.radians(angle_r))
        p["RELE09"] = fmt(abs(mid_l) if mid_l is not None else None, 2)
        p["RELE10"] = fmt(abs(mid_r) if mid_r is not None else None, 2)

        # REHG 避雷线平均高度 = |避雷线高度 - 修正|
        p["REHG______"] = fmt(abs(shield_h - rehg_adj) if shield_h is not None else None, 1)
        # REHC1/2/3 相平均高度 = |相高 - 绝缘子串长 - 修正|
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - rehc_adj) if (h is not None and insul_m is not None) else None, 1)

    # 雷电流幅值（C# 2052-2056）：current_ka(kA) → REIGAN=|c|/1000? 不——current_ka 已是 kA
    # C# current 单位 A：REIGAN=|current|/1000(kA)、REIAMP=-|current|(A)、HIAMP=-|current|*0.5(A)
    # 我们 current_ka 单位 kA：REIGAN=current_ka(kA)、REIAMP=-current_ka*1000(A)、HIAMP=-current_ka*500(A)
    p["REIGAN____"] = fmt(abs(current_ka), 1)
    p["REIAMP____"] = fmt(-abs(current_ka) * 1000.0, 1)
    p["HIAMP_____"] = fmt(-abs(current_ka) * 1000.0 * 0.5, 1)

    # 雷电流波形参数（C# 2058-2065）：REAA/REBB 衰减率(s^-1)=-1E6/时间ms；REAA1/REBB1 时间(s)=ms*1E-6
    # 格式：REAA/REBB 用 {0,10:F1}，REAA1/REBB1 用 {0,10:F7}（work_atp_model.txt）
    if head_t_ms is not None and head_t_ms > 0:
        p["REBB______"] = fmt(-1.0E6 / head_t_ms, 1)
        p["REAA1_____"] = fmt(head_t_ms * 1.0E-6, 7)
    else:
        p["REBB______"] = "1."
        p["REAA1_____"] = "1."
    if tail_t_ms is not None and tail_t_ms > 0:
        p["REAA______"] = fmt(-1.0E6 / tail_t_ms, 1)
        p["REBB1_____"] = fmt(tail_t_ms * 1.0E-6, 7)
    else:
        p["REAA______"] = "1."
        p["REBB1_____"] = "1."

    # 波形种类（C# 2066-2087 switch）：1 Heidler(INPhei) 2 双斜角(INPslo) 3 双指数(INPsur)
    wf = int(f(profile.get("current_type")) or 1)
    if wf == 2:
        p["REHHEI____"] = "0."
        p["REHSLO____"] = "1."
        p["REHSUR____"] = "0."
    elif wf == 3:
        p["REHHEI____"] = "0."
        p["REHSLO____"] = "0."
        p["REHSUR____"] = "1."
    else:
        p["REHHEI____"] = "1."
        p["REHSLO____"] = "0."
        p["REHSUR____"] = "0."
    return p


_CSHARP_EQUALS_PARAM_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*([A-Za-z0-9_]+)\s*$")


def _looks_like_csharp_equality_template(template: str) -> bool:
    """检测模板是否为 C# 等号占位符格式（$PARAMETER 区 NAME=NAMEI 行）。

    特征：存在形如 `RER001=RER001I` / `REHG______=REHGI` 的等号行，
    且等号右侧是字母数字下划线（占位符）而非数字。返回 True 时走 C# 渲染。
    """
    sample = 0
    for line in template.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        name, sep, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue
        # 右侧是数字（含小数点/科学计数）→ 已渲染或非占位符
        if re.fullmatch(r"[-+]?\d*\.?\d+([eE][-+]?\d+)?", value):
            continue
        # 右侧是字母开头占位符（REHGI / RER001I / RELENSI ...）
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value):
            sample += 1
            if sample >= 2:
                return True
    return False


def render_csharp_equality_template(
    template: str,
    *,
    base_tower: dict[str, Any],
    profile: dict[str, Any],
    execution_options: dict[str, Any],
) -> str:
    """渲染 C# 桌面版等号格式模板（$PARAMETER 区 NAME=占位符）。

    将 `REHG______=REHGI` 替换为 `REHG______=31.1`（带小数点），与 C# DLL
    Update_work_atp3 的行为一致。返回渲染后的完整文本。
    """
    params = compute_csharp_atp_params(
        base_tower=base_tower, profile=profile, execution_options=execution_options
    )
    lines = template.splitlines(keepends=True)
    rendered: list[str] = []
    for line in lines:
        match = _CSHARP_EQUALS_PARAM_RE.match(line.rstrip("\r\n"))
        if match and match.group(1) in params:
            new_line = f"{match.group(1)}={params[match.group(1)]}"
            if line.endswith("\r\n"):
                new_line += "\r\n"
            elif line.endswith("\n"):
                new_line += "\n"
            rendered.append(new_line)
        else:
            rendered.append(line)
    return "".join(rendered)


DEFAULT_JSON_MARKERS = ("FL_ANALYSIS_RESULT_BEGIN", "FL_ANALYSIS_RESULT_END")
LEGACY_RESULT_KEY_MAP = {
    "反击耐雷水平": "counterstrike_withstand_ka",
    "反击跳闸率": "counterstrike_trip_rate",
    "绕击耐雷水平": "shielding_withstand_ka",
    "绕击跳闸率": "shielding_trip_rate",
    "雷击风险等级": "risk_grade",
    "风险等级": "risk_grade",
    "单相闪络相": "flashover_phase",
    "闪络相": "flashover_phase",
    "主导相组": "dominant_phase_set",
    "同跳跳闸率": "counterstrike_trip_rate",
}
NUMERIC_RESULT_KEYS = {
    "counterstrike_withstand_ka",
    "counterstrike_trip_rate",
    "shielding_withstand_ka",
    "shielding_trip_rate",
    "score",
    "risk_grade",
}


def get_asset_by_id(db: Session, asset_id: str) -> AtpAsset | None:
    """Get ATP asset by ID."""
    return db.execute(select(AtpAsset).where(AtpAsset.id == asset_id)).scalar_one_or_none()





@dataclass(slots=True)
class ResolvedExternalWaveformJob:
    adapter: str
    asset: AtpAsset
    entry_file: str
    result_file: str | None
    storage_mount_code: str
    storage_root_path: str
    atp_text: str
    timeout_seconds: int
    extra_args: list[str]
    environment: dict[str, str]
    contract: dict[str, Any]
    parameter_bindings: dict[str, Any]


@dataclass(slots=True)
class ExternalTowerExecutionResult:
    result_json: dict[str, Any]
    engine_command: str
    working_dir: str
    stdout_text: str | None
    stderr_text: str | None





def _resolve_asset_worktree(
    db: Session,
    *,
    asset: AtpAsset,
    tower_type: str | None = None,
) -> dict[str, Any]:
    """Resolve an executable file tree directly from the asset's own storage.

    Assets are created by uploading files straight into the asset root
    (``/atp-assets/<code>``). This helper walks that root and auto-detects
    the entry ``.atp`` file.

    LP-560：支持按塔型编码细分 —— 优先查找 ``<root>/<塔型编码>/work.atp``，
    找不到时回退资产根目录 ``<root>/work.atp``（兼容旧布局）。

    Returns a dict compatible with the run payload::

        {
            "entry_file": str,
            "result_file": str | None,
            "storage_mount_code": str,
            "storage_root_path": str,
            "atp_text": str,
            "manifest": dict,
            "warnings": list[str],
        }
    """
    mount_code = _normalize_optional_str(asset.storage_mount_code) or "main"
    root_path = normalize_virtual_path(
        _normalize_optional_str(asset.storage_root_path) or f"/atp-assets/{asset.code.strip()}"
    )
    mount = _resolve_mount(db, mount_code)
    driver = build_storage_driver(mount.backend, mount)

    search_roots = [root_path]
    shape_code = _normalize_tower_shape_code(str(tower_type or "").strip())
    if shape_code:
        search_roots.insert(0, normalize_virtual_path(f"{root_path.rstrip('/')}/{shape_code}"))

    tree = None
    root = root_path
    for candidate_root in search_roots:
        try:
            tree = _walk_storage_tree(driver, candidate_root)
        except HTTPException:
            continue
        if tree is not None and any(path.lower().endswith(".atp") for path in tree.file_paths):
            root = candidate_root
            break

    if tree is None:
        raise RuntimeError(
            f"ATP 资产缺少可执行模板文件: {asset.code}（{root_path} 无可用文件）"
        )

    atp_files = sorted(path for path in tree.file_paths if path.lower().endswith(".atp"))
    entry_file = "work.atp" if "work.atp" in tree.file_paths else (atp_files[0] if atp_files else None)
    if entry_file is None:
        raise RuntimeError(f"ATP 资产缺少可执行模板文件: {asset.code}（{root} 未找到 work.atp 或 .atp 文件）")

    warnings: list[str] = []
    result_file = _normalize_relative_path(
        next(
            (path for path in ("work.lis", "work.pl4") if path in tree.file_paths),
            None,
        )
    )

    entry_path = normalize_virtual_path(f"{root.rstrip('/')}/{entry_file}")
    try:
        read_result = driver.read_file(entry_path)
    except (HTTPException, StorageDriverError) as exc:
        raise RuntimeError(f"ATP 资产缺少可执行模板: {asset.code}（{entry_file}）") from exc
    atp_text = read_result.content.decode("utf-8", errors="replace")
    if not atp_text.strip():
        raise RuntimeError(f"ATP 资产缺少可执行模板: {asset.code}（{entry_file}）")

    manifest = {
        "file_count": len(tree.files),
        "directory_count": len(tree.directories),
        "max_depth": tree.max_depth,
        "detected_entry_file": entry_file,
        "detected_root": root,
        "sample_files": [path for path in sorted(tree.file_paths)[:20]],
        "storage_mount_code": mount.code,
        "storage_root_path": root,
    }
    return {
        "entry_file": entry_file,
        "result_file": result_file,
        "storage_mount_code": mount.code,
        "storage_root_path": root,
        "atp_text": atp_text,
        "manifest": manifest,
        "warnings": warnings,
    }


def resolve_external_waveform_job(
    db: Session,
    *,
    external_adapter: str,
    adapter_config_json: dict[str, Any],
    tower_type: str | None = None,
) -> ResolvedExternalWaveformJob:
    adapter = str(external_adapter or "").strip().lower()
    if adapter not in {"atp", "wine"}:
        raise RuntimeError(f"Unsupported external adapter: {external_adapter}")

    config = dict(adapter_config_json or {})
    asset_id = str(config.get("asset_id") or config.get("model_id") or "").strip()
    if not asset_id:
        raise RuntimeError("外部 ATP/Wine 任务缺少 adapter_config_json.asset_id")

    asset = get_asset_by_id(db, asset_id)
    if asset is None:
        raise RuntimeError(f"指定的 ATP 资产不存在: {asset_id}")

    worktree = _resolve_asset_worktree(db, asset=asset, tower_type=tower_type)
    atp_text = worktree["atp_text"]
    entry_file = worktree["entry_file"]
    result_file = worktree["result_file"]
    storage_mount_code = worktree["storage_mount_code"]
    storage_root_path = worktree["storage_root_path"]
    manifest_contract = _read_object(worktree.get("manifest", {}).get("fl_analysis"))

    adapter_contract = {
        key: value
        for key, value in config.items()
        if key
        in {
            "result_file",
            "result_format",
            "result_labels",
            "result_json_pointer",
            "result_key_map",
            "stdout_json_markers",
        }
    }
    parameter_bindings = {
        **_read_object(manifest_contract.get("parameter_bindings")),
        **_read_object(config.get("parameter_bindings")),
    }
    # Some ATP templates use fixed parameter names like REHG______=28.8.
    # If parameter_bindings also contains REHGI, the template renderer will
    # replace the REHGI token with the string "REHG______", breaking the
    # assignment. Drop REHGI from bindings so the template's fixed value wins.
    parameter_bindings.pop("REHGI", None)
    contract = {
        **manifest_contract,
        **adapter_contract,
    }
    contract["parameter_bindings"] = parameter_bindings

    timeout_seconds = _resolve_timeout(_coerce_positive_int(config.get("timeout_seconds")))
    extra_args = [str(item).strip() for item in list(config.get("extra_args") or []) if str(item).strip()]
    environment = {
        str(key): str(value)
        for key, value in _read_object(config.get("environment")).items()
        if str(key).strip()
    }
    return ResolvedExternalWaveformJob(
        adapter=adapter,
        asset=asset,
        entry_file=entry_file,
        result_file=result_file,
        storage_mount_code=storage_mount_code,
        storage_root_path=storage_root_path,
        atp_text=atp_text,
        timeout_seconds=timeout_seconds,
        extra_args=extra_args,
        environment=environment,
        contract=contract,
        parameter_bindings=parameter_bindings,
    )


def render_atp_template(
    template: str,
    *,
    context: dict[str, Any],
    parameter_bindings: dict[str, Any] | None = None,
) -> str:
    bindings = parameter_bindings or {}

    def replace_placeholder(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        return _render_placeholder(expression, context=context, parameter_bindings=bindings)

    return PLACEHOLDER_PATTERN.sub(replace_placeholder, template)


def execute_external_waveform_tower_analysis(
    resolved_job: ResolvedExternalWaveformJob,
    *,
    db: Session,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> ExternalTowerExecutionResult:
    context = _build_template_context(
        job=job,
        snapshot=snapshot,
        execution_options=execution_options,
        baseline_result=baseline_result,
    )
    atp_text = resolved_job.atp_text
    parameter_bindings = {
        **_read_object(resolved_job.parameter_bindings),
        **_build_method_parameter_bindings(execution_options),
    }
    parameter_bindings.pop("REHGI", None)
    logger.info(
        "[ATP] 开始执行外部波形分析：job=%s, 杆塔=%s(%s), 模型=%s, 适配器=%s",
        job.id,
        snapshot.tower_no,
        snapshot.id,
        resolved_job.asset.code,
        resolved_job.adapter,
    )

    rendered_text = render_atp_template(
        atp_text,
        context=context,
        parameter_bindings=parameter_bindings,
    )
    # C# 桌面版等号格式模板（$PARAMETER 区 NAME=占位符）支持：
    # 检测到等号占位符（如 REHG______=REHGI）时，按 C# 公式逐参数替换为带小数点的数值，
    # 否则 tpbig 会报 TACS/JTOKEN 错误。
    if _looks_like_csharp_equality_template(rendered_text):
        rendered_text = render_csharp_equality_template(
            rendered_text,
            base_tower=snapshot.base_tower_json or {},
            profile=snapshot.profile_json or {},
            execution_options=execution_options,
        )
    logger.info("[ATP] 模板渲染完成，输入文件大小=%d 字节", len(rendered_text))

    run_dir = _prepare_run_directory(job=job, snapshot=snapshot, resolved_job=resolved_job)
    input_path = run_dir / resolved_job.entry_file
    input_path.write_text(rendered_text, encoding="gbk", errors="replace")
    logger.info("[ATP] 输入文件已写入：%s", input_path)

    # 物化资产 lib/dat 文件并改写 INCLUDE 路径（tpbig 依赖同目录 lib 文件）
    _materialize_asset_files(
        db=db,
        run_dir=run_dir,
        resolved_job=resolved_job,
    )

    command = _build_command(
        adapter=resolved_job.adapter,
        input_path=input_path,
        extra_args=resolved_job.extra_args,
    )
    env = os.environ.copy()
    env.update(resolved_job.environment)
    # Wine 在容器环境需要 XDG_RUNTIME_DIR，否则 wineserver 启动失败
    env.setdefault("XDG_RUNTIME_DIR", "/tmp/.xdg")
    logger.info("[ATP] 执行命令：%s，工作目录：%s", " ".join(command), run_dir)
    # 同时输出到 stderr，确保 docker logs 可见
    print(f"[ATP][STDOUT] 执行命令：{' '.join(command)}，工作目录：{run_dir}", file=sys.stdout, flush=True)

    # 持久化修复：Wine 配置初始化 + d 盘映射 + startup 文件
    wine_prefix = os.environ.get("WINEPREFIX") or str(Path(os.path.expanduser("~")) / ".wine")
    wine_profile = Path(wine_prefix)
    wine_dosdevices = wine_profile / "dosdevices"
    wine_dosdevices.mkdir(parents=True, exist_ok=True)
    # /tmp 是 Wine wineserver 必需的，缺失时自动创建
    Path("/tmp").mkdir(parents=True, exist_ok=True)
    atp_root = Path("/app/data/wine/ATP")
    d_drive = wine_dosdevices / "d:"
    if not d_drive.exists() or not d_drive.is_symlink():
        if d_drive.exists() or d_drive.is_symlink():
            d_drive.unlink()
        d_drive.symlink_to(atp_root)
    # 兼容模板 INCLUDE 路径：D:\\ATP\\500\\ganzi\\fanji\\M1\\*.lib
    # 以及 D:\\ATP\\35\\ganzi\\raoji1\\M123\\*.lib 等任意电压等级/塔型路径
    include_dirs: set[str] = set()
    for line in (atp_text or "").splitlines():
        if not line.strip().upper().startswith("$INCLUDE"):
            continue
        raw_path = line.split(",", 1)[1].strip() if "," in line else ""
        raw_path = raw_path.strip().split()[0].strip("$ ") if raw_path else ""
        if raw_path:
            dir_path = str(Path(raw_path).parent)
            include_dirs.add(dir_path)
    for include_dir in include_dirs:
        native_dir = Path(include_dir.replace("D:", "/app/data/wine/ATP").replace("\\", "/"))
        native_dir.mkdir(parents=True, exist_ok=True)
        for lib_name in ("short.lib", "dahao.lib", "long.lib", "xiaohao.lib"):
            target = native_dir / lib_name
            if target.exists():
                continue
            # 优先从同模板目录 symlink
            for template_dir in atp_root.glob("templates/*"):
                src = template_dir / lib_name
                if src.exists():
                    try:
                        target.symlink_to(src.resolve())
                    except OSError:
                        pass
                    break
    # 确保运行目录有 startup，ATP 启动必需
    startup_src = atp_root / "startup"
    startup_dst = run_dir / "startup"
    if startup_src.exists() and not startup_dst.exists():
        startup_dst.write_bytes(startup_src.read_bytes())

    try:
        result = subprocess.run(
            command,
            cwd=str(run_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=resolved_job.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("[ATP] 执行超时：%s，超时时间=%ds", snapshot.tower_no, resolved_job.timeout_seconds)
        print(f"[ATP][TIMEOUT] 杆塔 {snapshot.tower_no} 超时，超时时间={resolved_job.timeout_seconds}s", file=sys.stdout, flush=True)
        raise RuntimeError(
            f"{snapshot.tower_no} 外部 ATP/Wine 执行超时（{resolved_job.timeout_seconds}s）"
        ) from exc
    except OSError as exc:
        logger.error("[ATP] 启动失败：%s，错误=%s", snapshot.tower_no, exc)
        print(f"[ATP][ERROR] 杆塔 {snapshot.tower_no} 启动失败: {exc}", file=sys.stdout, flush=True)
        raise RuntimeError(f"{snapshot.tower_no} 外部 ATP/Wine 启动失败: {exc}") from exc

    logger.info(
        "[ATP] 执行完成：%s，退出码=%d",
        snapshot.tower_no,
        result.returncode,
    )
    print(f"[ATP] 执行完成：{snapshot.tower_no}，退出码={result.returncode}", file=sys.stdout, flush=True)
    stdout_text = _truncate_output(result.stdout)
    stderr_text = _truncate_output(result.stderr) or ""
    if stdout_text:
        logger.debug("[ATP] 标准输出（%s 前200行）：\n%s", snapshot.tower_no, stdout_text[:2000])
        print(f"[ATP][STDOUT] {snapshot.tower_no}:\n{stdout_text[:500]}", file=sys.stdout, flush=True)
    if stderr_text:
        logger.debug("[ATP] 错误输出（%s 前200行）：\n%s", snapshot.tower_no, stderr_text[:2000])
        print(f"[ATP][STDERR] {snapshot.tower_no}:\n{stderr_text[:500]}", file=sys.stdout, flush=True)

    if result.returncode != 0:
        logger.error("[ATP] 执行失败：%s，退出码=%d，stderr=%s", snapshot.tower_no, result.returncode, stderr_text[:500])
        raise RuntimeError(
            f"{snapshot.tower_no} 外部 ATP/Wine 执行失败，退出码 {result.returncode}"
        )

    logger.info("[ATP] 开始解析结果：%s，期望结果文件=%s", snapshot.tower_no, resolved_job.result_file)
    # ATP 模板无结果契约时（result_file=None 且 stdout 为 tpbig 文本日志），
    # 解析会失败；此时降级为 pl4 闪络检测结果，保证二分法可运行。
    try:
        parsed_payload = _read_external_result_payload(
            contract=resolved_job.contract,
            stdout_text=result.stdout,
            run_dir=run_dir,
            result_file=resolved_job.result_file,
        )
    except Exception as exc:
        logger.warning("[ATP] 结果契约解析失败（%s），降级为 pl4 闪络检测：%s", snapshot.tower_no, exc)
        parsed_payload = {}
    # 闪络判据（对齐 C# Check_Lightning_work_lis = 读 work.lis "Close switch" 行数）：
    # tpbig 用 both 参数跑后生成 work.lis，绝缘子闪络时模型闭合开关，
    # lis 逐相输出 `*** Close switch "SWUx" to "XX.." after ... sec.`。
    # 每一行计 1 相闪络。该判据随雷电流单调（实测 guxing-fanji-M1：≤300kA=0、
    # 500kA=2、800kA=4），二分法可据此收敛。
    # ⚠️ 不用 Type-99 "begins operation"（恒=2 不随电流变）也不以 pl4 阈值覆盖——
    # 两者都会把闪络判成恒定值，令二分法空转。
    try:
        lis_flash = _read_lis_flashover(run_dir)
        if lis_flash is not None:
            parsed_payload["flashover_count"] = lis_flash
            logger.info("[ATP] lis 闪络检测（Close switch）：%s，闪络相数=%d", snapshot.tower_no, lis_flash)
    except Exception as exc:
        logger.warning("[ATP] lis 闪络检测失败（%s）：%s", snapshot.tower_no, exc)
    # 仅当 lis 判据不可用（work.lis 缺失/无 Close switch 信息）时，才回退到
    # ATP 二进制波形（work.pl4）闪络检测（复刻 C# pl4Class.flashNumber()）。
    # 注意：pl4 阈值法对部分模板判恒值，不能覆盖 lis 的 Close switch 权威结果。
    if "flashover_count" not in parsed_payload:
        try:
            flashover_count = _read_pl4_flashover_count(run_dir, resolved_job.storage_root_path)
            if flashover_count is not None:
                parsed_payload["flashover_count"] = flashover_count
                logger.info("[ATP] pl4 闪络检测（回退）：%s，闪络相数=%d", snapshot.tower_no, flashover_count)
        except Exception as exc:
            logger.warning("[ATP] pl4 闪络检测失败（%s）：%s", snapshot.tower_no, exc)
    logger.info("[ATP] 结果解析完成：%s，payload_keys=%s", snapshot.tower_no, list(parsed_payload.keys())[:10])
    merged_result = _merge_external_result(
        baseline_result=baseline_result,
        external_payload=parsed_payload,
        resolved_job=resolved_job,
        engine_command=" ".join(command),
        working_dir=str(run_dir),
    )
    return ExternalTowerExecutionResult(
        result_json=merged_result,
        engine_command=" ".join(command),
        working_dir=str(run_dir),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
    )


def execute_binary_search_external(
    resolved_job: ResolvedExternalWaveformJob,
    *,
    db: Session,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> ExternalTowerExecutionResult:
    low = _coerce_positive_float(execution_options.get("binary_search_low_ka"), default=0.1)
    high = _coerce_positive_float(execution_options.get("binary_search_high_ka"), default=2000.0)
    tolerance = _coerce_positive_float(execution_options.get("binary_search_tolerance_ka"), default=0.1)
    max_iterations = int(execution_options.get("binary_search_max_iterations") or 20)
    # 显示倍率对齐 C# BeiShu.txt（ComputeLightningProtection.cs:6685 × mBeiShu_fanji/raoji）。
    # ⚠️ 不能硬编码 0.7：MyConst 默认 mBeiShu_fanji=0.7 会被 BeiShu.txt 覆盖，
    #    500kV fanji 实际为 1.0（仅 35kV guxing 为 0.7）；raoji 500kV 多数塔型为 1.1。
    #    从资产 scene_type 判断反击/绕击，从 asset.tower_type+voltage_level 查倍率表。
    _asset_scene = ""
    try:
        _asset_scene = str(getattr(resolved_job.asset, "scene_type", "") or "").strip().lower()
    except Exception:
        _asset_scene = ""
    _stroke = (execution_options.get("stroke_mode") or "").strip().lower()
    _is_counterstrike = _asset_scene.startswith("fanji") or _stroke in {"反击", "counterstrike"}
    _asset_tower_kind = ""
    _asset_voltage = None
    try:
        _asset_tower_kind = str(getattr(resolved_job.asset, "tower_type", "") or "").strip().lower()
    except Exception:
        _asset_tower_kind = _asset_tower_kind
    try:
        _v = getattr(resolved_job.asset, "voltage_level", None)
        if _v is not None:
            _asset_voltage = int(float(str(_v)))
    except (TypeError, ValueError):
        _asset_voltage = None
    multiplier = csharp_beishu_multiplier(
        tower_kind=_asset_tower_kind,
        voltage_kv=_asset_voltage,
        is_counterstrike=_is_counterstrike,
    )
    if low is None or high is None or tolerance is None or low < 0 or high <= 0 or tolerance <= 0:
        raise RuntimeError("二分迭代参数无效：电流上下限与精度阈值必须为正数")
    if high <= low:
        raise RuntimeError("二分迭代参数无效：上限电流必须大于下限电流")

    search_history: list[dict[str, Any]] = []
    iteration = 0
    final_flashover_count: int | None = None
    final_execution: ExternalTowerExecutionResult | None = None

    while (high - low) >= tolerance and iteration < max_iterations:
        iteration += 1
        candidate = (low + high) / 2
        adjusted_execution_options = _with_binary_search_current(execution_options, current_ka=candidate)
        execution = execute_external_waveform_tower_analysis(
            resolved_job,
            db=db,
            job=job,
            snapshot=snapshot,
            execution_options=adjusted_execution_options,
            baseline_result=baseline_result,
        )
        flashover_count = _coerce_flashover_count(execution.result_json)
        search_history.append(
            {
                "iteration": iteration,
                "current_ka": candidate,
                "flashover_count": flashover_count,
                "low": low,
                "high": high,
            }
        )
        if flashover_count > 0:
            high = candidate
        else:
            low = candidate
        final_flashover_count = flashover_count
        final_execution = execution

    # C# 桌面版：折半收敛后 current = currentRight（闪络边界高值），
    # showCurrent_kV = |currentRight|/1000 * mBeiShu（ComputeLightningProtection.cs:6685）。
    # 故 withstand = high(对应 currentRight) × multiplier（kA）。⚠️ 勿用 max(min(high*多,high),low)
    # ——low 是未乘倍率的原始下界，会把结果钳回未乘倍率值、抵消 multiplier（实测 P1=269.86×0.7=188.9
    # 却被钳回 269.8）。直接 high*multiplier 即与 C# 一致。
    withstand_ka = round(high * multiplier, 4)
    binary_search_payload = {
        "low_ka": low,
        "high_ka": high,
        "tolerance_ka": tolerance,
        "max_iterations": max_iterations,
        "multiplier": multiplier,
        "iteration_count": iteration,
        "search_history": search_history,
        "converged": (high - low) < tolerance,
        "final_flashover_count": final_flashover_count,
        "final_withstand_ka": withstand_ka,
    }
    merged = dict(final_execution.result_json) if final_execution is not None else dict(baseline_result)
    merged["binary_search"] = binary_search_payload
    merged["counterstrike_withstand_ka"] = withstand_ka
    merged["shielding_withstand_ka"] = withstand_ka
    return ExternalTowerExecutionResult(
        result_json=merged,
        engine_command=final_execution.engine_command if final_execution is not None else "",
        working_dir=final_execution.working_dir if final_execution is not None else "",
        stdout_text=final_execution.stdout_text if final_execution is not None else None,
        stderr_text=final_execution.stderr_text if final_execution is not None else None,
    )


def _with_binary_search_current(execution_options: dict[str, Any], *, current_ka: float) -> dict[str, Any]:
    updated = dict(execution_options)
    updated["binary_search_current_ka"] = current_ka
    return updated


def _coerce_flashover_count(result_json: dict[str, Any]) -> int:
    for key in {"flashover_count", "闪络相数"}:
        if key in result_json:
            return _coerce_positive_int(result_json.get(key)) or 0
    flashover_phase = result_json.get("flashover_phase")
    if isinstance(flashover_phase, str) and flashover_phase.strip():
        return max(1, len([item for item in flashover_phase.split(",") if str(item).strip()]))
    return 0


def _coerce_positive_float(value: Any, *, default: float) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _build_template_context(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "job": {
            "id": job.id,
            "job_name": job.job_name,
            "job_type": job.job_type,
            "external_adapter": job.external_adapter,
        },
        "snapshot": {
            "id": snapshot.id,
            "seq_no": snapshot.seq_no,
            "tower_no": snapshot.tower_no,
            "tower_model": snapshot.tower_model,
            "tower_type": snapshot.tower_type,
            "longitude": snapshot.longitude,
            "latitude": snapshot.latitude,
            "altitude_m": snapshot.altitude_m,
            "terrain": snapshot.terrain,
        },
        "base_tower": snapshot.base_tower_json or {},
        "profile": snapshot.profile_json or {},
        "execution_options": execution_options,
        "workflow": baseline_result.get("workflow") or {},
        "baseline_result": baseline_result,
    }


def _prepare_run_directory(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    resolved_job: ResolvedExternalWaveformJob,
) -> Path:
    base_dir = _resolve_engine_workdir() / "fl-analysis" / job.id / snapshot.id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _materialize_asset_files(
    *,
    db: Session,
    run_dir: Path,
    resolved_job: ResolvedExternalWaveformJob,
) -> None:
    """把资产目录的全部文件从存储物化到 Wine D 盘引擎目录。

    tpbig 通过 $INCLUDE 引用 D:\\ATP\\500\\ganzi\\fanji\\M1\\short.lib 等绝对路径
    （经 Wine D: 盘映射到 /app/data/wine/ATP）。因此资产文件必须落在
    /app/data/wine/ATP/<storage_root相对路径>，而非运行目录。
    渲染后的 work.atp 已写入 run_dir，这里把它复制到引擎目录覆盖模板占位符版。
    """
    from .atp_asset_service import _resolve_mount, _build_driver_or_400

    storage_root = resolved_job.storage_root_path or ""
    if not storage_root:
        return
    mount = _resolve_mount(db, resolved_job.storage_mount_code or "main")
    driver = _build_driver_or_400(mount)
    try:
        tree = _walk_storage_tree(driver, storage_root)
    except Exception:
        logger.warning("[ATP] 资产文件物化失败：无法枚举 %s", storage_root, exc_info=True)
        return

    # D 盘引擎目录：/app/data/wine/ATP + storage_root 相对段
    atp_root = Path("/app/data/wine/ATP")
    rel_segments = [seg for seg in storage_root.strip("/").split("/") if seg]
    # storage_root 形如 /atp-assets/500/ganzi/fanji/M1 → 取 atp-assets 之后的段
    if rel_segments and rel_segments[0] == "atp-assets":
        rel_segments = rel_segments[1:]
    engine_dir = atp_root.joinpath(*rel_segments) if rel_segments else atp_root
    engine_dir.mkdir(parents=True, exist_ok=True)

    for item in tree.files:
        rel = item.path
        rel_path = rel[len(storage_root):].lstrip("/")
        if not rel_path or "\\" in rel_path:
            continue
        target = engine_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            read_result = driver.read_file(item.path)
            content = read_result.content if hasattr(read_result, "content") else read_result
            target.write_bytes(content)
        except Exception as exc:
            logger.warning("[ATP] 物化文件失败 %s：%s", rel_path, exc)

    # 渲染后的 work.atp 复制到引擎目录（覆盖模板占位符版）
    entry_target = engine_dir / resolved_job.entry_file
    rendered_atp = run_dir / resolved_job.entry_file
    if rendered_atp.is_file():
        entry_target.write_bytes(rendered_atp.read_bytes())
        logger.info("[ATP] 资产文件已物化到引擎目录 %s，work.atp 渲染版已覆盖", engine_dir)

    # startup 是 tpbig 运行必需（缺少时报 "Attempt to connect disk file startup has failed"）
    startup_src = atp_root / "startup"
    startup_dst = engine_dir / "startup"
    if startup_src.exists() and not startup_dst.exists():
        startup_dst.write_bytes(startup_src.read_bytes())
        logger.info("[ATP] startup 已复制到引擎目录 %s", engine_dir)


def _build_command(*, adapter: str, input_path: Path, extra_args: list[str]) -> list[str]:
    if adapter in ("wine", "atp"):
        wine_binary, engine_path, error = _resolve_wine_engine_executable()
        if error or not wine_binary or not engine_path:
            raise RuntimeError(error or "Wine ATP engine unavailable")
        # C# 桌面版调用参数：tpbig both <path> s -r —— both 模式先生成稳态再时域，
        # 同时输出 work.lis（闪络判据 Type-99 动作需要）与 work.pl4。
        # extra_args 若已含 both 则不重复追加。
        if "both" not in (str(a).strip() for a in extra_args):
            return [wine_binary, engine_path, "both", str(input_path), "s", "-r", *extra_args]
        return [wine_binary, engine_path, str(input_path), *extra_args]

    engine_path, error = _resolve_native_engine_executable()
    if error or not engine_path:
        raise RuntimeError(error or "Native ATP engine unavailable")
    return [engine_path, str(input_path), *extra_args]


def _render_placeholder(
    expression: str,
    *,
    context: dict[str, Any],
    parameter_bindings: dict[str, Any],
) -> str:
    if expression in parameter_bindings:
        return _render_bound_placeholder(parameter_bindings[expression], context=context, name=expression)

    path, spec, width, default, required = _parse_inline_expression(expression)
    value = _read_path(context, path)
    return _stringify_value(
        value,
        format_spec=spec,
        width=width,
        default=default,
        required=required,
        name=expression,
    )


def _render_bound_placeholder(binding: Any, *, context: dict[str, Any], name: str) -> str:
    if isinstance(binding, str):
        path, spec, width, default, required = _parse_inline_expression(binding)
        value = _read_path(context, path)
        return _stringify_value(
            value,
            format_spec=spec,
            width=width,
            default=default,
            required=required,
            name=name,
        )

    mapping = _read_object(binding)
    path = str(mapping.get("path") or mapping.get("source") or "").strip()
    if not path:
        raise RuntimeError(f"ATP 模板绑定缺少 path/source: {name}")
    value = _read_path(context, path)
    return _stringify_value(
        value,
        format_spec=str(mapping.get("format") or "").strip() or None,
        width=_coerce_positive_int(mapping.get("width")),
        default=mapping.get("default"),
        required=bool(mapping.get("required", "default" not in mapping)),
        name=name,
    )


def _parse_inline_expression(expression: str) -> tuple[str, str | None, int | None, Any, bool]:
    parts = [part.strip() for part in expression.split("|")]
    path = parts[0]
    spec = parts[1] if len(parts) > 1 and parts[1] else None
    width = _coerce_positive_int(parts[2]) if len(parts) > 2 and parts[2] else None
    if len(parts) > 3:
        return path, spec, width, parts[3], False
    return path, spec, width, None, True


def _stringify_value(
    value: Any,
    *,
    format_spec: str | None,
    width: int | None,
    default: Any,
    required: bool,
    name: str,
) -> str:
    if value is None:
        if required:
            raise RuntimeError(f"ATP 模板占位符缺少取值: {name}")
        text = "" if default is None else str(default)
        return text.rjust(width) if width else text

    text: str
    if format_spec:
        text = _format_value(value, format_spec)
    elif isinstance(value, bool):
        text = "1" if value else "0"
    else:
        text = str(value)
    return text.rjust(width) if width else text


def _format_value(value: Any, format_spec: str) -> str:
    numeric_value = float(value)
    normalized_spec = format_spec.strip()
    if normalized_spec.startswith("F"):
        precision = abs(int(normalized_spec[1:] or "0"))
        text = f"{numeric_value:.{precision}f}"
        if precision > 0:
            text = text.rstrip("0").rstrip(".")
        elif "." not in text:
            text = f"{text}."
        return text
    if normalized_spec.startswith("E"):
        precision = abs(int(normalized_spec[1:] or "0"))
        return f"{numeric_value:.{precision}E}"
    return format(value, normalized_spec)


def _read_lis_flashover(run_dir: Path) -> int | None:
    """从 work.lis（tpbig both 模式日志）解析闪络相数。

    判据对齐 C# Check_Lightning_work_lis（ComputeLightningProtection.cs:11880）：
    绝缘子闪络时模型闭合开关，tpbig 在 lis 中逐相输出行为：
        *** Close switch  "SWU2  "  to  "XX0078"  after  1.71000000E-06  sec.
    每出现一行 `Close switch "X" to "Y"` 计 1 相闪络（valueRet++）。
    C# 用该 counts 作为折半法二分判据：numLightning >= level_lightning 视为闪络。

    ⚠️ 历史误判：曾用 "Type-99 v-i ... begins operation"（非线性电阻进入
    非线性段）作为判据——实测该标记在任何电流下都恒定出现（=2），不随雷电流
    变化，二分法会判定"恒有闪络"而无法收敛。正确判据是 "Close switch"，实测
    （500kV-guxing-fanji-M1 模板）随电流单调：50~300kA=0、500kA=2、800kA=4。

    返回闪络相数（0=无闪络）；文件缺失返回 None。
    """
    lis_path = run_dir / "work.lis"
    if not lis_path.is_file():
        return None
    try:
        raw = lis_path.read_bytes()
        text = raw.decode("gbk", errors="replace")
    except Exception:
        return None
    if not text.strip():
        return None
    count = 0
    for line in text.splitlines():
        # C# Check_Lightning_work_lis: text.IndexOf("Close") > 0
        if "Close" in line and line.index("Close") > 0:
            count += 1
    return count


def _read_pl4_flashover_count(run_dir: Path, storage_root: str | None = None) -> int | None:
    """从 work.pl4（ATP 二进制波形）解析闪络相数，复刻 C# pl4Class。

    头部布局（getNs）：偏移 19 起 7 个 uint32 LE：
      N_node, N_vol*2, N_all*2, N_tacs, N_zero, N_begin, N_end
    N_N = (N_end - N_begin) / ((N_all+1)*4)
    闪络检测（flashNumber）：从最后 3 个通道（N_all-1 .. N_all-3）反向找，
    每个通道遍历所有采样点，采样值（float32 LE）> 阈值 10.0 即该相闪络。
    返回闪络相数（0-3）；文件缺失/格式异常返回 None。
    """
    # tpbig 把 pl4 写到 INCLUDE 所在目录（引擎目录）而非运行目录：
    # /app/data/wine/ATP/<电压>/<塔型>/<场景>/<组合>/work.pl4
    candidates = [run_dir / "work.pl4"]
    if storage_root:
        rel_segments = [seg for seg in storage_root.strip("/").split("/") if seg]
        if rel_segments and rel_segments[0] == "atp-assets":
            rel_segments = rel_segments[1:]
        if rel_segments:
            candidates.append(Path("/app/data/wine/ATP").joinpath(*rel_segments) / "work.pl4")
    pl4_path = None
    for cand in candidates:
        if cand.is_file() and cand.stat().st_size > 60:
            pl4_path = cand
            break
    if pl4_path is None:
        return None
    data = pl4_path.read_bytes()
    if len(data) < 19 + 28:
        return None
    def u32(offset: int) -> int:
        return int.from_bytes(data[offset:offset + 4], "little", signed=False)

    N_node = u32(19)
    N_vol = u32(19 + 4) // 2
    N_all = u32(19 + 8) // 2
    N_begin = u32(19 + 20)
    N_end = u32(19 + 24)
    if N_node > 300 or N_all < 1:
        return None
    step_bytes = (N_all + 1) * 4
    if step_bytes <= 0:
        return None
    N_N = (N_end - N_begin) // step_bytes
    if N_N <= 0:
        return None

    threshold = 10.0
    flash_count = 0
    # 最后 3 个通道（跳过时间列 + 最后 3 个通道）
    for channel in range(N_all - 1, max(N_all - 4, -1), -1):
        flashed = False
        for i in range(N_N):
            offset = N_begin - 1 + step_bytes * i + (channel + 1) * 4
            if offset + 4 > len(data):
                break
            sample = struct.unpack("<f", data[offset:offset + 4])[0]
            if sample > threshold:
                flashed = True
                break
        if flashed:
            flash_count += 1
    return flash_count


def _read_external_result_payload(
    *,
    contract: dict[str, Any],
    stdout_text: str,
    run_dir: Path,
    result_file: str | None = None,
) -> dict[str, Any]:
    resolved_result_file = result_file or str(contract.get("result_file") or "").strip() or None
    source_text: str
    if resolved_result_file:
        result_path = (run_dir / resolved_result_file).resolve(strict=False)
        if not result_path.is_relative_to(run_dir.resolve(strict=False)):
            raise RuntimeError(f"外部结果文件越界: {resolved_result_file}")
        if result_path.exists():
            source_text = result_path.read_text(encoding="utf-8", errors="replace")
        else:
            # 结果文件未生成，回退到 stdout（某些 ATP 模板输出到 stdout 而非文件）
            source_text = stdout_text or ""
            if not source_text:
                raise RuntimeError(f"外部 ATP/Wine 未生成结果文件且无 stdout: {resolved_result_file}")
    else:
        source_text = stdout_text

    payload = _parse_external_payload(source_text, contract)
    pointer = str(contract.get("result_json_pointer") or "").strip()
    if pointer:
        pointed = _read_path({"payload": payload}, f"payload.{pointer}")
        if not isinstance(pointed, dict):
            raise RuntimeError(f"外部结果指针无效: {pointer}")
        payload = pointed
    if not isinstance(payload, dict):
        raise RuntimeError("外部 ATP/Wine 结果不是 JSON 对象")
    return _normalize_external_result_payload(payload, _read_object(contract.get("result_key_map")))


def _parse_external_payload(source_text: str, contract: dict[str, Any]) -> dict[str, Any]:
    labels = [str(item).strip() for item in list(contract.get("result_labels") or []) if str(item).strip()]
    if labels:
        values = [item.strip() for item in re.split(r"[|\r\n]+", source_text) if item.strip()]
        return {
            label: _coerce_scalar(values[index]) if index < len(values) else None
            for index, label in enumerate(labels)
        }

    result_format = str(contract.get("result_format") or "").strip().lower()
    if result_format in {"key_value", "kv", "text"}:
        return _parse_key_value_text(source_text)

    markers = contract.get("stdout_json_markers")
    if isinstance(markers, list) and len(markers) == 2:
        candidate = _extract_marked_json(source_text, str(markers[0]), str(markers[1]))
        if candidate is not None:
            return json.loads(candidate)

    candidate = source_text.strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return json.loads(candidate)

    marked_json = _extract_marked_json(source_text, *DEFAULT_JSON_MARKERS)
    if marked_json is not None:
        return json.loads(marked_json)

    raise RuntimeError("外部 ATP/Wine 结果无法解析为 JSON")


def _parse_key_value_text(source_text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in source_text.splitlines():
        text = line.strip()
        if not text:
            continue
        if "=" in text:
            key, value = text.split("=", 1)
        elif ":" in text:
            key, value = text.split(":", 1)
        else:
            continue
        result[key.strip()] = _coerce_scalar(value.strip())
    return result


def _extract_marked_json(source_text: str, start_marker: str, end_marker: str) -> str | None:
    start_index = source_text.find(start_marker)
    if start_index < 0:
        return None
    start_index += len(start_marker)
    end_index = source_text.find(end_marker, start_index)
    if end_index < 0:
        return None
    return source_text[start_index:end_index].strip()


def _normalize_external_result_payload(
    payload: dict[str, Any],
    result_key_map: dict[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = str(result_key_map.get(raw_key) or raw_key).strip()
        key = LEGACY_RESULT_KEY_MAP.get(key, key)
        value = raw_value
        if key in NUMERIC_RESULT_KEYS:
            value = _coerce_scalar(raw_value)
        normalized[key] = value

    risk_level = normalized.get("risk_level")
    if isinstance(risk_level, (int, float)) and "risk_grade" not in normalized:
        normalized["risk_grade"] = int(risk_level)
        normalized["risk_level"] = _risk_level_from_grade(int(risk_level))
    if "risk_level" not in normalized and "risk_grade" in normalized:
        grade = _coerce_positive_int(normalized.get("risk_grade")) or 1
        normalized["risk_grade"] = grade
        normalized["risk_level"] = _risk_level_from_grade(grade)
    return normalized


def _merge_external_result(
    *,
    baseline_result: dict[str, Any],
    external_payload: dict[str, Any],
    resolved_job: ResolvedExternalWaveformJob,
    engine_command: str,
    working_dir: str,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(baseline_result)
    workflow = {
        **_read_object(baseline_result.get("workflow")),
        **_read_object(external_payload.get("workflow")),
    }
    if workflow:
        merged["workflow"] = workflow
    for key, value in external_payload.items():
        if key == "workflow" and isinstance(value, dict):
            continue
        merged[key] = value

    if merged.get("selected_case") is None and baseline_result.get("selected_case") is not None:
        merged["selected_case"] = baseline_result.get("selected_case")
    if merged.get("summary_text") is None and baseline_result.get("summary_text") is not None:
        merged["summary_text"] = baseline_result.get("summary_text")
    if merged.get("cause_analysis") is None and baseline_result.get("cause_analysis") is not None:
        merged["cause_analysis"] = baseline_result.get("cause_analysis")
    if merged.get("mitigation_recommendation") is None and baseline_result.get("mitigation_recommendation") is not None:
        merged["mitigation_recommendation"] = baseline_result.get("mitigation_recommendation")

    external_execution = {
        "adapter_status": "executed",
        "adapter": resolved_job.adapter,
        "asset_id": resolved_job.asset.id,
        "asset_code": resolved_job.asset.code,
        "asset_name": resolved_job.asset.name,
        "entry_file": resolved_job.entry_file,
        "result_file": resolved_job.result_file,
        "storage_mount_code": resolved_job.storage_mount_code,
        "storage_root_path": resolved_job.storage_root_path,
        "engine_command": engine_command,
        "working_dir": working_dir,
        "executed_at": utcnow().isoformat(),
    }
    merged["external_execution"] = external_execution
    merged["external_result_json"] = external_payload
    return merged


def _read_path(context: dict[str, Any], path: str) -> Any:
    current: Any = context
    for segment in [item for item in path.split(".") if item]:
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return None
    return current


def _read_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _coerce_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_scalar(value: Any) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value

    text = str(value).strip()
    if not text:
        return text
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if any(char in text for char in {".", "e", "E"}):
            return float(text)
        return int(text)
    except ValueError:
        return text


def _build_method_parameter_bindings(execution_options: dict[str, Any]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    fanji_method = str(execution_options.get("fanji_naleishuiping_method") or "").strip().lower()
    raoji_method = str(execution_options.get("raoji_naleishuiping_method") or "").strip().lower()
    if fanji_method == "atp":
        bindings["REHGF"] = {"path": "execution_options.fanji_naleishuiping_method", "default": "ATP"}
    if raoji_method == "atp":
        bindings["REHRF"] = {"path": "execution_options.raoji_naleishuiping_method", "default": "ATP"}

    fanji_tzl = str(execution_options.get("fanji_tzl_method") or "").strip().lower()
    raoji_tzl = str(execution_options.get("raoji_tzl_method") or "").strip().lower()
    if fanji_tzl == "egm":
        bindings["CAL_MODE"] = {"path": "execution_options.fanji_tzl_method", "default": "EGM"}
    if raoji_tzl == "egm":
        bindings["CAL_MODE"] = {"path": "execution_options.raoji_tzl_method", "default": "EGM"}

    include_tower_ids = execution_options.get("selected_tower_ids") or execution_options.get("include_tower_ids")
    if isinstance(include_tower_ids, list) and include_tower_ids:
        bindings["INCLUDE_TOWER_IDS"] = ",".join(str(item).strip() for item in include_tower_ids if str(item).strip())
    return bindings


def _risk_level_from_grade(grade: int) -> str:
    if grade >= 3:
        return "high"
    if grade == 2:
        return "medium"
    return "low"

