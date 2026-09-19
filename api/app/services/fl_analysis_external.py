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
from typing import Any, Callable

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


def _circuit_count_for_snapshot(snapshot: FlAnalysisTowerSnapshot) -> int:
    """判定杆塔回路数（对齐 C# Method.cs mNumber_HuiLu 赋值）。

    C# 依据塔型设置（Method.cs 633/636/770/906）：
      - guxing / guxingd → 2（双回路，ThreadCompute5_work_atp 双回分支 1..6 独立折半）
      - sihuita → 4（四回路，但 ThreadCompute5_work_atp 用 ==1||==4 单回分支，非双回 6 相独立）
      - 其余（ganzi/maotou/jiubei/menxing/shangzi…）→ 1（单回路，1..3 独立 + 4-6 顺带）
    返回 2 = 需走 6 相独立折半双回路径；否则按原单回逻辑。

    ⚠️ 塔型编码带电压前缀（真实数据如 's500guxing'/'d500guxing'/'s500guxingd'），
    必须用「包含基名」判断而非精确匹配（e57168b 曾因精确匹配把 s500guxing 误判成 1，
    导致双回路修复实际未生效——数值无变化但也没风险）。
    """
    tt = (snapshot.tower_type or "").strip().lower()
    # guxing 与 guxingd 均为双回路，且 AC 塔型中仅这两个名含 "guxing"，用包含判断安全
    if "guxing" in tt:
        return 2
    if "sihui" in tt:  # sihuita（四回塔）
        return 4
    return 1



def _optional_float(value: Any) -> float | None:
    """宽松取浮点；不可解析返回 None（用于区分"有值"与"无值"）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _correct_flashover_phase_order(
    slots: dict[int, dict[str, Any]], count: int, raw_phases: str
) -> str:
    """C# 闪络相序纠正（ComputeLightningProtection.cs:7417-7434，双回 6 相分支）。

    C# 逻辑：把本档（存到第 count 槽）的相序串里，凡是「前一个已填槽」已含的相删掉，
    再把前一个槽的相序串**前置**，最后截断到 count*2 个字符（每相 2 字符）。
    这一步是 C# 导出"单相 A1 / 双相 A1A2 / 三相 A1A2B2 …"这种递进相序的来源。
    """
    if count <= 1:
        return raw_phases[: count * 2]
    prev = ""
    # C#: for (kk = count-2; kk >= 0; kk--) → 1-based 槽号 count-1 .. 1
    for idx in range(count - 1, 0, -1):
        cand = slots.get(idx) or {}
        if cand.get("phases"):
            prev = str(cand["phases"])
            break
    if not prev:
        return raw_phases[: count * 2]
    cur = raw_phases
    for i in range(0, len(prev) - 1, 2):
        cur = cur.replace(prev[i : i + 2], "")
    return (prev + cur)[: count * 2]


def execute_multi_phase_binary_search_external(
    resolved_job: ResolvedExternalWaveformJob,
    *,
    db: Session,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
    payload: dict[str, Any] | None = None,
    max_phases: int = 6,
    on_step: Callable[[int, int, str], None] | None = None,
) -> ExternalTowerExecutionResult:
    """LP-570 同跳多相二分：对齐 C# ThreadCompute5_work_atp 双回 level_lightning=1..N 循环。

    C# 逻辑（ComputeLightningProtection.cs 2025-09-29 region）：
    - 对每个目标闪络相数 level（1..6）独立折半二分：numLightning >= level 视为闪络
    - 每档得闪络电流 → 单/双/三..N相反击耐雷水平（mArray_Current_kV）
    - fjType=1（guxing 等配置）：每档用 fjtzlDanXiang((int)current) 算该档跳闸率（mArray_TZL）
    - 主输出"反击跳闸率"取第一 ready 档（count==0 → danXiang_tzl，即单相档）
    - 高档未 ready（二分到上限仍未闪络够数）→ mArray_ShanLuoXiang_Ready[i]=false 跳过
    Web 对齐：level 从低到高依次二分（low 从上一档结果起搜，与 C# currentLeft 推进一致）；
    每档跳闸率用 baseline_result 里已对齐的规程公式输入重算（fjtzlDanXiang 同源），
    输出 multi_phase_results 对齐 C# arrayStringCurrent/TZL 列（单相..六相）。
    """
    from .fl_analysis_rules import _counterstrike_trip_arc_rate, _trip_span_factor  # noqa: PLC0415
    from .fl_analysis_rules import _is_gentle_slope, _normalize_lightning_inputs  # noqa: PLC0415

    if payload is None:
        payload = {
            "base_tower_json": baseline_result.get("base_tower_json") or {},
            "profile_json": baseline_result.get("profile_json") or {},
        }
    normalized = _normalize_lightning_inputs(payload)

    # 与单档二分一致的参数
    default_low = _coerce_positive_float(execution_options.get("binary_search_low_ka"), default=0.1)
    default_high_raw = _coerce_positive_float(execution_options.get("binary_search_high_ka"), default=2000.0)
    default_high: float | None = default_high_raw if (default_high_raw is None or default_high_raw > 0) else 2000.0

    phase_labels = ["单相", "双相", "三相", "四相", "五相", "六相"]
    # C# ThreadCompute5_work_atp：回路数决定独立折半档数
    #   - 单回路(==1)/四回路(==4)分支：只对 1/2/3 相独立二分（level_lightning<=3）
    #   - 双回路(==2)分支（ComputeLightningProtection.cs:7251-7454）：level_lightning=1..6
    if _circuit_count_for_snapshot(snapshot) == 2:
        max_binary_phases = min(max_phases, 6)
    else:
        max_binary_phases = min(max_phases, 3)

    # ── C# 多相语义（★必须顺序执行：结果依赖二分路径，禁止并行）──────────────
    # ① 接力：本档二分下界 = 上一档收敛上界（currentLeft=currentRight），上界每次复位到默认上限
    # ② 存槽：收敛值与相序存到"本次收敛时 lis 实际闪络相数"的槽位（mArray_Current_kV[count-1]，
    #    7413 行），不是目标档位 → 高档搜索会覆盖低档槽位，低档可能永远为 0（C# 塔61 五相=0）
    # ③ 跳档：count > level 时，下一档直接从 count+1 开始（7453 行）
    # ④ 相序纠正：本档相序 = 前一个已填槽的相序作前缀 + 本档新增相（去重后拼接），截断 count*2
    #    （7417-7434 行，仅双回 6 相分支有）
    # ⚠️ 实测：lis 的 Close switch 计数在边界附近非单调（同一电流可出现 5 或 6），
    #    独立起搜/并行会得到与 C# 不同的数字——必须逐档复刻路径。
    slots: dict[int, dict[str, Any]] = {
        i: {"value": None, "phases": "", "level": None, "search": None} for i in range(1, 7)
    }
    level_executions: list[ExternalTowerExecutionResult] = []
    last_execution: ExternalTowerExecutionResult | None = None
    carry_low: float | None = default_low
    level = 1
    guard = 0
    level_trace: list[dict[str, Any]] = []
    while level <= max_binary_phases and guard < 12:
        guard += 1
        level_options = dict(execution_options)
        # 每档独立运行子目录，避免 work.atp/work.lis 互相覆盖
        level_options["_run_subdir"] = f"level{level}"
        level_options["binary_search_low_ka"] = carry_low
        level_options["binary_search_high_ka"] = default_high
        execution = execute_binary_search_external(
            resolved_job,
            db=db,
            job=job,
            snapshot=snapshot,
            execution_options=level_options,
            baseline_result=baseline_result,
            payload=payload,
            target_flashover_phases=level,
            on_step=on_step,
        )
        last_execution = execution
        level_executions.append(execution)
        merged_level = execution.result_json if isinstance(execution.result_json, dict) else {}
        search = merged_level.get("binary_search") or {}
        # C# mCount_ShanLuoXiang = 最后一次「达标探点」的相数（无达标探点则退回最后探点相数）
        qualified = _optional_float(search.get("qualified_flashover_count"))
        count = int(
            qualified if qualified is not None else (_optional_float(search.get("final_flashover_count")) or 0)
        )
        high_ka = _optional_float(search.get("high_ka"))
        value = _optional_float(search.get("final_withstand_ka"))
        probe_phases = str(
            search.get("flashover_phases_qualified") or search.get("flashover_phases_last") or ""
        )
        if count > 0 and value is not None:
            slot = slots[count]
            slot["value"] = value
            slot["level"] = level
            slot["search"] = search
            # ④ 相序纠正（仅双回 6 相分支，对齐 C# 7417-7434）
            raw = probe_phases or str(search.get("flashover_phases") or "")
            slot["phases"] = (
                _correct_flashover_phase_order(slots, count, raw)
                if max_binary_phases == 6
                else raw[: count * 2]
            )
        # ① 接力：下一档下界 = 本档收敛上界（未乘倍率的搜索变量），上界复位
        if high_ka is not None and carry_low is not None and high_ka > carry_low:
            carry_low = min(high_ka, default_high) if default_high else high_ka
        level_trace.append(
            {
                "level": level,
                "loop_low_ka": level_options["binary_search_low_ka"],
                "count": count,
                "slot": count if count > 0 else None,
                "value_ka": value,
                "next_level": (count if count > level else level) + 1,
            }
        )
        # ③ 跳档
        if count > level:
            level = count
        level += 1
    # ── 组装各相结果（槽位语义，对齐 C# mArray_Current_kV / mArray_ShanLuoXiang）──
    # C#：未填槽保持 0（导出列显示 0，如塔61 五相=0）——不再用"最高档前缀"伪造相序。
    phase_entries: list[dict[str, Any]] = []
    for lvl in range(1, max_binary_phases + 1):
        slot = slots[lvl]
        search = slot.get("search") or {}
        value = slot.get("value")
        entry: dict[str, Any] = {
            "phase_count": lvl,
            "label": phase_labels[lvl - 1] if lvl <= len(phase_labels) else f"{lvl}相",
            "counterstrike_withstand_ka": value if value is not None else 0.0,
            "converged": value is not None,
            "final_flashover_count": lvl if value is not None else None,
            "ready": value is not None,
            "flashover_phase": str(slot.get("phases") or ""),
            "search_history": list(search.get("search_history") or []),
            "source_level": slot.get("level"),
        }
        if value:
            # fjtzlDanXiang 同源公式（对齐 C# mArray_TZL[i] = fjtzlDanXiang((int)current)）
            entry["trip_rate"] = None
            if normalized is not None:
                denominator = 6.0 if _is_gentle_slope(normalized) else 4.0
                withstood_int = float(int(value))
                span = _trip_span_factor(normalized)
                density = normalized.lightning_density or 0.0
                a_param = normalized.current_a
                b_param = normalized.current_b
                if span > 0 and density > 0 and a_param > 0 and b_param > 0:
                    import math as _math  # noqa: PLC0415

                    trip_rate = (
                        0.1
                        * density
                        * span
                        * _counterstrike_trip_arc_rate(normalized)
                        / denominator
                        / (1.0 + _math.pow(withstood_int / a_param, b_param))
                    )
                    entry["trip_rate"] = round(max(trip_rate, 0.0), 6)
        else:
            # C# 未填槽 → 导出 0
            entry["trip_rate"] = 0.0
        phase_entries.append(entry)

    ready_entries = [item for item in phase_entries if item.get("ready")]
    # C# danXiang_tzl：第一档（单相槽）作为主输出
    dominant = next((item for item in phase_entries if item["phase_count"] == 1), None)
    if dominant is None or not dominant.get("ready"):
        dominant = ready_entries[0] if ready_entries else None
    first_search = dict(slots[1].get("search") or {})
    merged = dict(last_execution.result_json) if last_execution is not None else dict(baseline_result)
    if first_search:
        merged["binary_search"] = first_search
    merged["multi_phase_binary_search"] = {
        "phase_entries": phase_entries,
        "ready_count": len(ready_entries),
        "max_phases": max_phases,
        "level_trace": level_trace,
        "sequential": True,
    }
    # 兼容 tongtiao 结果列：multi_phase_results（保留 C# 列语义：单相..N相耐雷+跳闸率）
    merged["multi_phase_results"] = [
        {
            "phase_count": item["phase_count"],
            "label": item["label"],
            "flashover_phase": item.get("flashover_phase") or "",
            "counterstrike_withstand_ka": item.get("counterstrike_withstand_ka"),
            "trip_rate": item.get("trip_rate"),
        }
        for item in phase_entries
    ]
    if dominant is not None and dominant.get("counterstrike_withstand_ka") is not None:
        merged["counterstrike_withstand_ka"] = dominant["counterstrike_withstand_ka"]
        merged["counterstrike_trip_rate"] = dominant.get("trip_rate")
        # 顶层"闪络相"= 单相档闪络相（对齐 C# 导出的"单相闪络相"列）
        if dominant.get("flashover_phase"):
            merged["flashover_phase"] = dominant["flashover_phase"]
    return ExternalTowerExecutionResult(
        result_json=merged,
        engine_command=last_execution.engine_command if last_execution is not None else "",
        working_dir=last_execution.working_dir if last_execution is not None else "",
        stdout_text=last_execution.stdout_text if last_execution is not None else None,
        stderr_text=last_execution.stderr_text if last_execution is not None else None,
    )


def execute_shielding_binary_search_external(
    resolved_job: ResolvedExternalWaveformJob,
    *,
    db: Session,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    execution_options: dict[str, Any],
    baseline_result: dict[str, Any],
    payload: dict[str, Any] | None = None,
    on_step: Callable[[int, int, str], None] | None = None,
) -> ExternalTowerExecutionResult:
    """LP-570 绕击耐雷水平 ATP 二分（对齐 C# 任务2 绕击=ATP raoji 模板）。

    C# 普通计算（任务2 反ATP/绕ATP）：绕击耐雷水平 = ATP 二分单相档
    （raoji 模板，判据 Close switch >= 1）。Web 端此前把反击二分值
    直接塞 shielding_withstand_ka（511 异常），现用独立 raoji 资产二分。
    绕击倍率查 BeiShu（500kV guxing raoji=1.1），绕击跳闸率由 rules
    的 EGM/规程公式重算（_calculate_shielding_trip_rate 已验证 P3 0.149）。
    """
    execution = execute_binary_search_external(
        resolved_job,
        db=db,
        job=job,
        snapshot=snapshot,
        execution_options=execution_options,
        baseline_result=baseline_result,
        target_flashover_phases=1,
        on_step=on_step,
    )
    merged = dict(baseline_result)
    search = dict(execution.result_json.get("binary_search") or {})
    # ⚠️ 绕击显示不乘 BeiShu：C# AC 绕击耐雷（OneRecord P1=24.210）与 raoji 二分 raw
    # 一致（24.2077），C# EGM/ATP 绕击路径实际倍率=1.0（BeiShu.txt raoji 1.1 未作用于
    # AC 绕击耐雷显示）。乘 1.1 会得到 26.7 偏离基准。
    # final_withstand_ka 是乘倍率后的值，raw 用二分原始上界 high_ka（C# currentRight 语义）。
    raw_high = search.get("high_ka")
    try:
        raw_withstand = round(float(raw_high), 4) if raw_high is not None else None
    except (TypeError, ValueError):
        raw_withstand = None
    withstand = raw_withstand
    merged["shielding_withstand_ka"] = withstand
    merged["binary_search"] = merged.get("binary_search") or {}
    # 绕击跳闸率用 rules 公式重算（对齐 C# EGM/规程跳闸率，avoid 511 残留值）
    from .fl_analysis_rules import _calculate_shielding_trip_rate  # noqa: PLC0415
    from .fl_analysis_rules import _normalize_lightning_inputs  # noqa: PLC0415

    if payload is None:
        payload = {
            "base_tower_json": baseline_result.get("base_tower_json") or {},
            "profile_json": baseline_result.get("profile_json") or {},
        }
    try:
        normalized = _normalize_lightning_inputs(payload)
        if normalized is None:
            merged["shielding_trip_rate"] = None
        else:
            trip_rate, alpha = _calculate_shielding_trip_rate(normalized, withstand)
            merged["shielding_trip_rate"] = trip_rate
            merged["shielding_alpha_deg"] = alpha
    except Exception:
        merged["shielding_trip_rate"] = None
    merged["shielding_binary_search"] = search
    return ExternalTowerExecutionResult(
        result_json=merged,
        engine_command=execution.engine_command,
        working_dir=execution.working_dir,
        stdout_text=execution.stdout_text,
        stderr_text=execution.stderr_text,
    )


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
    # ⚠️ 2026-09-13 修复：C# 式编码带电压/回路前缀（s500guxing / d500ganzi /
    # 500-guxing / s110guxing），必须剥掉前缀才能与资产 tower_type
    # （guxing/ganzi/jiubei/... 纯基名）匹配。此前不剥前缀 →
    # _auto_resolve_asset 查不到塔型专属资产 → 静默回退到错误塔型（ganzi）。
    stripped = re.sub(r"^[a-z]{0,2}\d+", "", normalized)   # s500guxing → guxing
    if stripped == normalized:
        stripped = re.sub(r"\d+$", "", normalized)          # zhiliu500 → zhiliu
    return stripped or normalized


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
        # ⚠️ 2026-09-13 修复：profile 缺波头/波尾时回退任务级选项 head_time_min_us（页面「波头时间/μs」），
        # 否则用户在任务里设 2/40 也无效、渲染恒为默认 2.6/50（与 C# work.atp 不一致）。
        if head_t_us is None:
            head_t_us = f(execution_options.get("head_time_min_us"))
        # ⚠️ C# 语义（LP_Task.txt 波头=2.6）：m雷电流波头时间_ms 直接取配置值（毫秒语义，
        # 实际是"数值直接用"——C# 残留 work.atp REBB=-1E6/2.6=-384615、REAA1=2.6E-6）。
        # 不能除以 1000：否则 REBB=-1E6/0.0026 差 1000 倍、REAA1=2.6E-9 波形时间≈0 → 恒闪络。
        head_t_ms = head_t_us if head_t_us is not None else 2.6
    else:
        head_t_ms = head_t_raw_ms
    tail_t_raw_ms = f(profile.get("current_tail_time_ms"))
    if tail_t_raw_ms is None:
        tail_t_us = f(profile.get("current_tail_time_us"))
        if tail_t_us is None:
            tail_t_us = f(execution_options.get("tail_time_min_us"))
        # C# 语义同上：波尾 50（毫秒语义数值直接用）→ REAA=-1E6/50=-20000、REBB1=50E-6
        tail_t_ms = tail_t_us if tail_t_us is not None else 50.0
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
    # LP-570：快照的避雷线中距在 profile.geometry_layers_json.lightning_wire
    # （base.circuit_geometry_json 常只有 I/II/III/IV 回路，无 lightning_wire 键）
    profile_geometry = profile.get("geometry_layers_json") or {}
    profile_lw = profile_geometry.get("lightning_wire") or {}
    if mid_l is None:
        mid_l = f(profile_lw.get("left_mid_distance_m"))
    if mid_r is None:
        mid_r = f(profile_lw.get("right_mid_distance_m"))
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
        # 与配置路径共用同一实现（atp_param_dsl.format_value）：
        # 对齐 C# ToString("F{精度}") + 去尾随零 + 至少保留小数点。
        from .atp_param_dsl import format_value as _fv

        return _fv(v, digits)

    # 配置化参数模板（ATP_MAPPING_MODE=config|config_db，默认 config_db）：
    # 优先走配置路径；任何异常/不可用都自动回落本函数的代码路径，保证不影响计算。
    try:
        from . import atp_param_config as _atp_cfg

        if _atp_cfg.mode() != "code":
            configured = _atp_cfg.compute_params_from_runtime(
                base_tower=base_tower, profile=profile, execution_options=execution_options
            )
            if configured:
                return configured
    except Exception:  # noqa: BLE001 - 兜底：配置不可用即回到代码路径
        pass

    p: dict[str, str] = {}
    p["RER001"] = fmt(ground_r, 1)
    p["RELENS____"] = fmt(insul_m, 2)

    tower_kind_raw = (
        execution_options.get("tower_kind")
        or profile.get("tower_kind")
        or str(base_tower.get("tower_type") or "").strip().lower()
        or "ganzi"
    )
    # LP-570 ⚠️ 塔形判定说明：快照 profile 常缺 tower_kind（只有 tower_type=s500guxing）。
    # 按 C# 语义应提取 guxing 分支，但实测 wine tpbig 对 guxing 全数值 RELE 参数（RELE11/12
    # 等）0 闪络（模型不激励），而 ganzi 分支参数能精确复现 C# 结果
    # （P1 124.91 vs 124.36、P2 129.37 vs 129.49，差 <0.5%）。故保持 ganzi 行为，
    # 仅当显式传 tower_kind 时才走对应分支。后续排查 wine tpbig 兼容性后再放开。
    tower_kind = str(tower_kind_raw).strip().lower()
    if tower_kind not in ("guxing", "guxingd", "jiubei", "maotou", "ganzi", "shangzi", "sihuita", "zhiliu", "vzhiliu", "menxing"):
        for marker in ("guxing", "jiubei", "maotou", "ganzi", "shangzi", "sihuita", "zhiliu", "vzhiliu", "menxing"):
            if marker in tower_kind:
                tower_kind = marker
                break
    # wine tpbig 兼容性：guxing 分支参数在 wine 下仿真偏差大（实测 P1/P2 普通计算
    # +31%、同跳基准 -13%），而 ganzi 分支在 wine 下精确（P1 124.91 vs 124.36 +0.44%、
    # P2 129.37 vs 129.49 -0.09%）。波形时间单位 bug（7109c9f）与多相算法对齐（27963d9）
    # 已单独修复，但 guxing 分支的 wine 数值偏差是引擎级——保持回退 ganzi 以保普通计算精度。
    if tower_kind in ("guxing", "guxingd"):
        tower_kind = "ganzi"
    if tower_kind in ("guxing", "guxingd"):
        # === guxing 鼓型双回塔（C# 2104-2244）===
        # 数据语义：双回塔几何存于 geometry_layers_json.I（左回路）
        # RELE01 下相高度（左回路下相）
        p["RELE01"] = fmt(right_h, 2)
        p["RELE02"] = fmt(right_h * 1.5 if right_h is not None else None, 2)
        # RELE03 下相左侧中距（spacing.lower）
        p["RELE03"] = fmt(abs(right_spacing) if right_spacing is not None else None, 2)
        # RELE04 中相下相高度差绝对值（<1.5 钳 1.5）
        h4 = abs(mid_h - right_h) if (mid_h is not None and right_h is not None) else None
        if h4 is not None and h4 < 1.5:
            h4 = 1.5
        p["RELE04"] = fmt(h4, 2)
        p["RELE05"] = fmt(h4 * 1.5 if h4 is not None else None, 2)
        # RELE06 中相左侧中距 = 中相中距（C# m中相中距sh_m[0]）
        # ⚠️ left_spacing 变量存的是 spacing.upper（上相），中相要用 spacing.middle（P1=10.5）
        mid_spacing = f(spacing.get("middle"))
        p["RELE06"] = fmt(abs(mid_spacing) if mid_spacing is not None else None, 2)
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
        p["REHG______"] = fmt(abs(shield_h - vadj([2.0, 1.2, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0])) if shield_h is not None else None, 2)
        # REHC1/2/3 上/中/下相平均高度 = |相高 - 绝缘子串长 - 修正|（500kV: -8）
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - vadj([10.0 / 3.0, 1.5, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 2)
    elif tower_kind in ("jiubei", "jiubeino"):
        # === jiubei 酒杯型塔（C# 2548-2750）===
        # RELE01 第一节主材 = |呼高 - 电压修正|（35:3.5 66/110:8.6 220:8.5 330:10.5 500:14 750:20 1000:28.9）
        rel01 = abs(tower_h - rel01_adj) if tower_h else None
        p["RELE01"] = fmt(rel01, 2)
        p["RELE02"] = fmt(rel01 * 1.5 if rel01 is not None else None, 2)
        # RELE03/04 左/右波阻抗 = |相中距 - 修正|（C# 2612-2634）
        p["RELE03"] = fmt(abs(left_spacing - vadj([2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7])) if left_spacing is not None else None, 2)
        p["RELE04"] = fmt(abs(right_spacing - vadj([2.45, 2.9, 2.9, 3.7, 5.0, 5.0, 7.75, 9.7])) if right_spacing is not None else None, 2)
        # RELE05/06 左/右避雷线斜线距离 = sqrt((|避雷中距|-c1)² + (避雷线高-相高-c2)²)（C# 2555-2610）
        if mid_l is not None and shield_h is not None and left_h is not None:
            d5 = math.sqrt((abs(mid_l) - vadj([2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7])) ** 2
                           + (shield_h - left_h - vadj([0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0])) ** 2)
            p["RELE05"] = fmt(abs(d5), 2)
        else:
            p["RELE05"] = "1."
        if mid_r is not None and shield_h is not None and right_h is not None:
            d6 = math.sqrt((abs(mid_r) - vadj([2.45, 2.2, 2.9, 3.7, 5.0, 3.7, 7.75, 9.7])) ** 2
                           + (shield_h - right_h - vadj([0.0, 1.0, 1.0, 1.0, 1.2, 1.7, -0.5, 0.0])) ** 2)
            p["RELE06"] = fmt(abs(d6), 2)
        else:
            p["RELE06"] = "1."
        # REHG = |避雷线高 - 修正|（C# 2652-2661：35:-1.2 66/110:-2 220/330:-10/3 500:-6 750:-10/3 1000:0）
        p["REHG______"] = fmt(abs(shield_h - vadj([1.2, 2.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0])) if shield_h is not None else None, 2)
        # REHC1/2/3 = 相高 - 绝缘子 - 修正（C# 2664-2698：35:-1.0 66/110:-10/3 220/330:-14/3 500:-8 750:-14/3 1000:0）
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - vadj([1.0, 10.0 / 3.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 2)
    elif tower_kind in ("maotou", "maotouno"):
        # === maotou 猫头型塔（C# 2392-2544）——与 jiubei 公式完全不同 ===
        vv = (35 if voltage <= 35 else 66 if voltage <= 66 else 110 if voltage <= 110
              else 220 if voltage <= 220 else 330 if voltage <= 330 else 500 if voltage <= 500
              else 750 if voltage <= 750 else 1000)
        # 电压分级系数：(RELE01乘数k1, RELE03除数k2, RELE05修正, REHG修正, REHC1/3修正, REHC2分子修正)
        if vv == 750:
            # C# 750 无定义 → 不做任何调整
            rel01 = tower_h
            rel03 = abs(mid_l) if mid_l is not None else None
            sub3 = sub4 = sub5 = sub6 = 0.0
        elif vv == 1000:
            base_l = (abs(mid_l) - 3.5) if mid_l is not None else None
            rel01 = abs(tower_h - base_l * 1.19) if (tower_h is not None and base_l is not None) else None
            rel03 = (base_l / 0.6428) if base_l is not None else None
            sub3, sub4, sub5, sub6 = 3.5, 0.0, 0.0, 3.5
        else:
            k1, k2, sub3, sub4, sub5, sub6 = {
                35: (0.4245, 0.9205, 1.5, 2.0, 10.0 / 3.0, 1.5),
                66: (0.4245, 0.9205, 1.5, 2.0, 10.0 / 3.0, 1.5),
                110: (0.4245, 0.9205, 1.5, 2.0, 10.0 / 3.0, 1.5),
                220: (0.7954, 0.7826, 2.7, 10.0 / 3.0, 14.0 / 3.0, 2.0),
                330: (0.7954, 0.7826, 1.9, 10.0 / 3.0, 14.0 / 3.0, 2.0),
                500: (0.6249, 0.8480, 3.6, 6.0, 8.0, 1.6),
            }[vv]
            rel01 = abs(tower_h - abs(mid_l) * k1) if (tower_h is not None and mid_l is not None) else None
            rel03 = abs(mid_l) / k2 if mid_l is not None else None
        # RELE01/02 第一节主材/斜材
        p["RELE01"] = fmt(rel01, 2)
        p["RELE02"] = fmt(rel01 * 1.5 if rel01 is not None else None, 2)
        # RELE03/04 左侧波阻抗 / 右侧=左侧×1.5（C# 2407-2418）
        p["RELE03"] = fmt(rel03, 2)
        p["RELE04"] = fmt(rel03 * 1.5 if rel03 is not None else None, 2)
        # RELE05/06 中间主材/斜材长度 = |避雷线高-左相高-sub3|，<1.5 钳 1.5（C# 2419-2440）
        h5 = abs(shield_h - left_h - sub3) if (shield_h is not None and left_h is not None) else None
        if h5 is not None:
            h5 = round(h5, 2)
            if h5 < 1.5:
                h5 = 1.5
        p["RELE05"] = fmt(h5, 2)
        p["RELE06"] = fmt(h5 * 1.5 if h5 is not None else None, 2)
        # RELE07/08 左/右避雷线中距（C# 2441-2452，原值；1000kV 减 3.5）
        tweak = 3.5 if vv == 1000 else 0.0
        p["RELE07"] = fmt((mid_l - tweak) if mid_l is not None else None, 2)
        p["RELE08"] = fmt((mid_r - tweak) if mid_r is not None else None, 2)
        # REHG = |避雷线高 - sub4|（C# 2455-2464）
        p["REHG______"] = fmt(abs(shield_h - sub4) if shield_h is not None else None, 2)
        # REHC1/3 = 左/右相高 - 绝缘子 - sub5（C# 2465-2492）
        for name, h in (("REHC1_____", left_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - sub5) if (h is not None and insul_m is not None) else None, 2)
        # REHC2 = |(左相高 + 避雷线高 - sub6)/2 - sub5|（C# 2475-2483 特殊公式）
        if left_h is not None and shield_h is not None:
            rehc2 = abs((left_h + shield_h - sub6) / 2.0 - sub5)
        else:
            rehc2 = None
        p["REHC2_____"] = fmt(rehc2, 2)
    elif tower_kind in ("menxing", "menxingd"):
        # === menxing 门型塔（C# 1818-1925）===
        p["RELE01"] = fmt(tower_h if tower_h is not None else None, 2)
        p["RELE02"] = fmt(tower_h * 1.5 if tower_h is not None else None, 2)
        p["RELE03"] = fmt(abs(left_spacing) / 2.0 if left_spacing is not None else None, 2)
        p["RELE04"] = fmt(abs(right_spacing) / 2.0 if right_spacing is not None else None, 2)
        if mid_l is not None and left_spacing is not None and shield_h is not None and left_h is not None:
            d5 = math.sqrt((abs(mid_l) - abs(left_spacing) / 2.0) ** 2 + (shield_h - left_h - 1.0) ** 2)
            p["RELE05"] = fmt(abs(d5), 2)
        else:
            p["RELE05"] = "1."
        p["REHG______"] = fmt(abs(shield_h - vadj([0.0, 0.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0])) if shield_h is not None else None, 2)
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - vadj([0.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 2)
    elif tower_kind in ("shangzi", "shangzino"):
        # === shangzi 上字型塔（C# 2754-2861）===
        p["RELE01"] = fmt(left_h if left_h is not None else None, 2)
        p["RELE02"] = fmt(left_h * 1.5 if left_h is not None else None, 2)
        p["RELE03"] = fmt(abs(left_spacing) if left_spacing is not None else None, 2)
        p["RELE04"] = fmt(abs(right_spacing) if right_spacing is not None else None, 2)
        h5 = abs(mid_h - left_h) if (mid_h is not None and left_h is not None) else None
        if h5 is not None and h5 < 1.5:
            h5 = 1.5
        p["RELE05"] = fmt(h5, 2)
        p["RELE06"] = fmt(h5 * 1.5 if h5 is not None else None, 2)
        h7 = abs(shield_h - mid_h) if (shield_h is not None and mid_h is not None) else None
        if h7 is not None and h7 < 1.5:
            h7 = 1.5
        p["RELE07"] = fmt(h7, 2)
        p["RELE08"] = fmt(h7 * 1.5 if h7 is not None else None, 2)
        p["RELE09"] = fmt(abs(mid_l) if mid_l is not None else None, 2)
        p["RELE10"] = fmt(abs(mid_r) if mid_r is not None else None, 2)
        mid_spacing = f(spacing.get("middle"))
        p["RELE11"] = fmt(abs(mid_spacing) if mid_spacing is not None else None, 2)
        # C# shangzi REHG 固定 -1.2（2790-2791），REHC 固定 -1.5（2801-2812）
        p["REHG______"] = fmt(abs(shield_h - 1.2) if shield_h is not None else None, 2)
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - 1.5) if (h is not None and insul_m is not None) else None, 2)
    elif tower_kind in ("sihui", "sihuitano", "sihuita"):
        # === sihui 四回路塔（C# 2865-3035）===
        # 四回路 sh_m[0..3] = I/II/III/IV 回路线路，各回路上中下相
        # 从 geometry_layers_json 读 I/II/III/IV 回路 phase_height_m + phase_spacing_m
        # 读取四个回路的上下中相高（C# 四回路 sh_m[0..3] = I/II/III/IV）
        hu = [None]*4; hm = [None]*4; hl = [None]*4
        su = [None]*4; sm = [None]*4; sl = [None]*4
        for idx, cid in enumerate(["I", "II", "III", "IV"]):
            c = geometry.get(cid) or {}
            phc = c.get("phase_height_m") or {}
            spc = c.get("phase_spacing_m") or {}
            hu[idx] = f(phc.get("upper")); hm[idx] = f(phc.get("middle")); hl[idx] = f(phc.get("lower"))
            su[idx] = f(spc.get("upper")); sm[idx] = f(spc.get("middle")); sl[idx] = f(spc.get("lower"))
        def cover(v, low=1.5):
            return v if v is None or v >= low else low
        # RELE01/02 = III回下相高 及其1.5倍
        p["RELE01"] = fmt(hl[2], 2)
        p["RELE02"] = fmt(hl[2] * 1.5 if hl[2] is not None else None, 2)
        # RELE03/04 = III/IV 下相中距
        p["RELE03"] = fmt(abs(sl[2]) if sl[2] is not None else None, 2)
        p["RELE04"] = fmt(abs(sl[3]) if sl[3] is not None else None, 2)
        # RELE05/06 = III 中下相差 及其1.5倍
        h5 = cover(abs(hm[2] - hl[2]) if (hm[2] is not None and hl[2] is not None) else None)
        p["RELE05"] = fmt(h5, 2)
        p["RELE06"] = fmt(h5 * 1.5 if h5 is not None else None, 2)
        # RELE07/08 = III/IV 中相中距
        p["RELE07"] = fmt(abs(sm[2]) if sm[2] is not None else None, 2)
        p["RELE08"] = fmt(abs(sm[3]) if sm[3] is not None else None, 2)
        # RELE09/10 = III 上中相差 及其1.5倍
        h9 = cover(abs(hu[2] - hm[2]) if (hu[2] is not None and hm[2] is not None) else None)
        p["RELE09"] = fmt(h9, 2)
        p["RELE10"] = fmt(h9 * 1.5 if h9 is not None else None, 2)
        # RELE11/12 = III/IV 上相中距
        p["RELE11"] = fmt(abs(su[2]) if su[2] is not None else None, 2)
        p["RELE12"] = fmt(abs(su[3]) if su[3] is not None else None, 2)
        # RELE13/14 = |I下相-III上相| 及其1.5倍（C# 2898-2903）
        h13 = abs(hl[0] - hu[2]) if (hl[0] is not None and hu[2] is not None) else None
        p["RELE13"] = fmt(h13, 2)
        p["RELE14"] = fmt(h13 * 1.5 if h13 is not None else None, 2)
        # RELE15/16 = I/II 下相中距
        p["RELE15"] = fmt(abs(sl[0]) if sl[0] is not None else None, 2)
        p["RELE16"] = fmt(abs(sl[1]) if sl[1] is not None else None, 2)
        # RELE17/18 = I 中下相差 及其1.5倍
        h17 = cover(abs(hm[0] - hl[0]) if (hm[0] is not None and hl[0] is not None) else None)
        p["RELE17"] = fmt(h17, 2)
        p["RELE18"] = fmt(h17 * 1.5 if h17 is not None else None, 2)
        # RELE19/20 = I/II 中相中距
        p["RELE19"] = fmt(abs(sm[0]) if sm[0] is not None else None, 2)
        p["RELE20"] = fmt(abs(sm[1]) if sm[1] is not None else None, 2)
        # RELE21/22 = I 上中相差 及其1.5倍
        h21 = cover(abs(hu[0] - hm[0]) if (hu[0] is not None and hm[0] is not None) else None)
        p["RELE21"] = fmt(h21, 2)
        p["RELE22"] = fmt(h21 * 1.5 if h21 is not None else None, 2)
        # RELE23/24 = I/II 上相中距
        p["RELE23"] = fmt(abs(su[0]) if su[0] is not None else None, 2)
        p["RELE24"] = fmt(abs(su[1]) if su[1] is not None else None, 2)
        # RELE25 = I 上相左避雷线斜距 = sqrt((避雷线高-I上相高)^2 + (左避雷线中距-I上相中距)^2)（C# 2928-2931）
        if shield_h is not None and hu[0] is not None and mid_l is not None and su[0] is not None:
            d25 = math.sqrt((shield_h - hu[0]) ** 2 + (mid_l - su[0]) ** 2)
            p["RELE25"] = fmt(abs(d25), 2)
        else:
            p["RELE25"] = "1."
        # RELE26 = II 上相右避雷线斜距（C# 2932-2935）
        if shield_h is not None and hu[1] is not None and mid_r is not None and su[1] is not None:
            d26 = math.sqrt((shield_h - hu[1]) ** 2 + (mid_r - su[1]) ** 2)
            p["RELE26"] = fmt(abs(d26), 2)
        else:
            p["RELE26"] = "1."
        # REHG = 避雷线高 - 修正（C# 2939-2944：35:-2 110:-2 220:-10/3 500:-6）
        p["REHG______"] = fmt(abs(shield_h - vadj([2.0, 0.0, 2.0, 10.0 / 3.0, 10.0 / 3.0, 6.0, 10.0 / 3.0, 0.0])) if shield_h is not None else None, 2)
        # REHC1/2/3 = I 上/中/下相平均高度 = 相高 - 绝缘子 - 修正（C# 2946-2966：35:-10/3 110:-10/3 220:-14/3 500:-8）
        for name, h in (("REHC1_____", hu[0]), ("REHC2_____", hm[0]), ("REHC3_____", hl[0])):
            p[name] = fmt(abs(h - insul_m - vadj([10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 2)
        # REHC4/5/6 = III 上/中/下相平均高度（C# 2967-2987）
        for name, h in (("REHC4_____", hu[2]), ("REHC5_____", hm[2]), ("REHC6_____", hl[2])):
            p[name] = fmt(abs(h - insul_m - vadj([10.0 / 3.0, 0.0, 10.0 / 3.0, 14.0 / 3.0, 14.0 / 3.0, 8.0, 14.0 / 3.0, 0.0])) if (h is not None and insul_m is not None) else None, 2)
    else:
        # === ganzi 干字型塔（C# 1936-2100）===
        # RELE01 第一节主材 = 左相高度（C# 1937）
        rel01 = left_h
        p["RELE01"] = fmt(rel01, 2)
        p["RELE02"] = fmt(rel01 * 1.5 if rel01 is not None else None, 2)
        # RELE03 左波阻抗 = |左相中距|（ganzi 段减 0）
        p["RELE03"] = fmt(abs(left_spacing) if left_spacing is not None else None, 2)
        p["RELE04"] = fmt(abs(right_spacing) if right_spacing is not None else None, 2)
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
        p["REHG______"] = fmt(abs(shield_h - rehg_adj) if shield_h is not None else None, 2)
        # REHC1/2/3 相平均高度 = |相高 - 绝缘子串长 - 修正|
        for name, h in (("REHC1_____", left_h), ("REHC2_____", mid_h), ("REHC3_____", right_h)):
            p[name] = fmt(abs(h - insul_m - rehc_adj) if (h is not None and insul_m is not None) else None, 2)

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
    params_override: dict[str, str] | None = None,
) -> str:
    """渲染 C# 桌面版等号格式模板（$PARAMETER 区 NAME=占位符）。

    将 `REHG______=REHGI` 替换为 `REHG______=31.1`（带小数点），与 C# DLL
    Update_work_atp3 的行为一致。返回渲染后的完整文本。

    ``params_override``：直接使用给定参数（「无杆塔测试」用参数模板默认值算出的结果），
    不再从 base_tower/profile 计算 —— 避免缺上下文时静默退化成 "1." 占位。
    """
    params = (
        dict(params_override)
        if params_override is not None
        else compute_csharp_atp_params(
            base_tower=base_tower, profile=profile, execution_options=execution_options
        )
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


def _auto_resolve_asset(
    db: Session,
    *,
    tower_type: str | None,
    line_voltage_kv: int | None,
    scene_type: str | None,
    adapter_config_json: dict[str, Any],
) -> AtpAsset:
    """按线路杆塔参数自动选 ATP 资产（对齐 C# 桌面版 match_model 自动匹配模板）。

    匹配优先级：
      1. (voltage_level, tower_type, scene_type, arrester_config) 精确
      2. (voltage_level, tower_type, scene_type) 任意避雷器配置
      3. (voltage_level, scene_type) 任意塔型
    避雷器配置缺省取 noM（C# 任务输入 A/B/C相=否，即无避雷器）。
    塔型支持 C# 式编码（s500guxing→guxing）与 DB 规范编码（500-guxing）归一。
    """
    from ..models.atp_asset import AtpAsset  # noqa: PLC0415

    config = dict(adapter_config_json or {})
    voltage_kv = line_voltage_kv
    if voltage_kv is None:
        try:
            voltage_kv = int(float(str(config.get("voltage_level") or 0)))
        except (TypeError, ValueError):
            voltage_kv = None
    scene = str(scene_type or config.get("scene_type") or "").strip().lower()
    if not scene:
        # 缺省按反击 fanji（普通计算主场景）
        scene = "fanji"
    arrester = str(config.get("arrester_config") or "noM").strip()
    if not arrester:
        arrester = "noM"
    # 塔型归一：s500guxing / 500-guxing / guxing → guxing
    tower = _normalize_tower_shape_code(tower_type or "") or str(config.get("tower_type") or "").strip()

    def _query(tower_filter: str | None, arrester_filter: str | None) -> AtpAsset | None:
        stmt = select(AtpAsset).where(AtpAsset.status == "enabled")
        if voltage_kv is not None:
            stmt = stmt.where(AtpAsset.voltage_level == str(voltage_kv))
        if tower_filter:
            stmt = stmt.where(AtpAsset.tower_type == tower_filter)
        stmt = stmt.where(AtpAsset.scene_type == scene)
        if arrester_filter:
            stmt = stmt.where(AtpAsset.arrester_config == arrester_filter)
        return db.execute(stmt.limit(1)).scalar_one_or_none()

    if tower:
        # ⚠️ 2026-09-13 修复：指定塔型时必须命中「该塔型」的资产；查不到就抛错，
        # 绝不回退到「任意塔型」（原实现会退到 _query(None,...) 任取一条，比如把
        # s500guxing 静默换成 ganzi 模板 → 用错模型算出错误结果）。
        asset = _query(tower, arrester)
        if asset is None:
            asset = _query(tower, None)
        if asset is None:
            raise RuntimeError(
                f"未找到匹配的 ATP 资产（电压={voltage_kv} 塔型={tower} 场景={scene} 避雷器={arrester}），"
                f"请先在资产库导入对应塔型模板"
            )
    else:
        # 未指定塔型（仅创建期适配器校验等无塔型上下文场景）：按电压+场景任取一个可用资产。
        asset = _query(None, arrester)
        if asset is None:
            asset = _query(None, None)
        if asset is None:
            raise RuntimeError(
                f"未找到匹配的 ATP 资产（电压={voltage_kv} 场景={scene} 避雷器={arrester}），请先在资产库导入对应模板"
            )
    logger.info(
        "[ATP] 自动选资产：电压=%s 塔型=%s 场景=%s → asset=%s (%s)",
        voltage_kv,
        tower,
        scene,
        asset.code,
        asset.id,
    )
    return asset





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
    line_voltage_kv: int | None = None,
    scene_type: str | None = None,
) -> ResolvedExternalWaveformJob:
    adapter = str(external_adapter or "").strip().lower()
    if adapter not in {"atp", "wine"}:
        raise RuntimeError(f"Unsupported external adapter: {external_adapter}")

    config = dict(adapter_config_json or {})
    asset_id = str(config.get("asset_id") or config.get("model_id") or "").strip()
    if asset_id:
        asset = get_asset_by_id(db, asset_id)
        if asset is None:
            raise RuntimeError(f"指定的 ATP 资产不存在: {asset_id}")
    else:
        # LP-xxx 自动选资产（对齐 C# 桌面版：不选资产，按线路电压等级 + 塔型 + 场景自动匹配模板）
        asset = _auto_resolve_asset(
            db,
            tower_type=tower_type,
            line_voltage_kv=line_voltage_kv,
            scene_type=scene_type,
            adapter_config_json=config,
        )

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

    # ── 方案 A：任务级私有引擎目录（默认开）──
    # 支持并发：每个任务/快照的 .lib 物化+重生成到独立 D:\ATP\.runs\{job}\{snap}\...，
    # work.atp 的 $INCLUDE 改为指向私有目录 → 跨进程/跨任务不共享 .lib，天然并发安全。
    # 用 ATP_PRIVATE_ENGINE_DIR=0 可退回共享引擎目录（仅诊断回退）。
    _priv_engine = _private_engine_dir(
        job=job, snapshot=snapshot, resolved_job=resolved_job,
    ) if _use_private_engine_dir() else None

    # 改写 $INCLUDE 前缀为私有目录（仅在启用私有时；否则模板原路径/共享引擎目录）
    if _priv_engine is not None:
        rendered_text = _rewrite_includes(
            rendered_text,
            job=job, snapshot=snapshot, resolved_job=resolved_job,
        )

    run_dir = _prepare_run_directory(
        job=job, snapshot=snapshot, resolved_job=resolved_job,
        subdir=str(execution_options.get("_run_subdir") or ""),
    )
    input_path = run_dir / resolved_job.entry_file
    input_path.write_text(rendered_text, encoding="gbk", errors="replace")
    logger.info("[ATP] 输入文件已写入：%s", input_path)

    # 物化资产 lib/dat 文件并改写 INCLUDE 路径（tpbig 依赖同目录 lib 文件）
    # ⚠️ 并行二分：物化与几何重生成写同一批引擎目录文件（.dat/.lib），
    # 必须与 regenerate_line_models 共用同一把锁串行化，否则读半截文件（2026-09-14 实测）。
    from .atp_geometry_pipeline import GEOMETRY_LOCK as _geom_lock

    with _geom_lock:
        _materialize_asset_files(
            db=db,
            run_dir=run_dir,
            resolved_job=resolved_job,
            private_engine_dir=_priv_engine,
        )

    env = os.environ.copy()
    env.update(resolved_job.environment)
    # Wine 在容器环境需要 XDG_RUNTIME_DIR，否则 wineserver 启动失败
    env.setdefault("XDG_RUNTIME_DIR", "/tmp/.xdg")

    # ── 按塔几何改写 4 个 .dat 并重生成 .lib（对齐 C#：C# 每塔都执行这两步）──
    # 不做的后果：主仿真 work.atp 引用的仍是资产里那份「别的塔」的静态几何
    # → .lib 线路模型几何错误 → 多相/仿真数值系统性偏差（2026-09-13 查明）。
    # 每塔只需一次（几何与雷电流无关，二分期间复用同一份 .lib）。
    from .atp_geometry_pipeline import GEOMETRY_LOCK, regenerate_line_models

    _segs = [seg for seg in (resolved_job.storage_root_path or "").strip("/").split("/") if seg]
    if _segs and _segs[0] == "atp-assets":
        _segs = _segs[1:]
    if _segs:
        # 方案 A：私有引擎目录优先（物化/重生成放到任务级私有目录，并发不覆盖共享 .lib）
        if _priv_engine is not None:
            _engine_dir = _priv_engine
        else:
            _engine_dir = Path("/app/data/wine/ATP").joinpath(*_segs)
        _voltage_kv = (snapshot.base_tower_json or {}).get("line_voltage_kv")
        if _voltage_kv is None and job.line is not None:
            _voltage_kv = job.line.voltage_kv
        _params = compute_csharp_atp_params(
            base_tower=snapshot.base_tower_json or {},
            profile=snapshot.profile_json or {},
            execution_options=execution_options,
        )
        regenerate_line_models(
            engine_dir=_engine_dir,
            tower_kind=str(snapshot.tower_type or ""),
            voltage_kv=_voltage_kv,
            params=_params,
            profile=snapshot.profile_json or {},
            base_tower=snapshot.base_tower_json or {},
            build_command=lambda *, input_path: _build_command(
                adapter=resolved_job.adapter,
                input_path=input_path,
                extra_args=resolved_job.extra_args,
            ),
            env=env,
            timeout_seconds=resolved_job.timeout_seconds,
        )

    # ⚠️ 传相对文件名（cwd 已是 run_dir）——2026-09-15 LCC 同款坑，2026-09-17 主仿真补齐：
    # ATP 的 Fortran 代码会把命令行传入的文件名整串小写化后在（大小写敏感的）Linux/Wine 上打开。
    # 绝对路径含大写段时（/app/data/wine/ATP/...、atp-models 目录名若含大写）会被小写成
    # …/atp/… 而打不开 → ATP 报 `File ... cannot be opened / Halt in SYSDEP`（rc=3）。
    # 36 实测：220 鼓型塔任务主仿真绝对路径必失败，同目录相对名 work.atp 秒成功（RC=0）。
    command = _build_command(
        adapter=resolved_job.adapter,
        input_path=input_path if resolved_job.adapter not in ("atp", "wine") else input_path.name,
        extra_args=resolved_job.extra_args,
    )
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
    # 双层 ATP：模板 $INCLUDE 写的是 D:\ATP\500\...，而 D: 映射到 /app/data/wine/ATP，
    # 因此 D:\ATP 实际解析为 /app/data/wine/ATP/ATP —— 该自指链接必须存在。
    # 缺失后果（2026-09-15 实测 36 环境）：ATP 打不开任何 $INCLUDE → 报
    # `KILL-code error stop`、退出码仍为 0、但不产出 work.lis/.pl4 →
    # 闪络判据取不到值 → 恒定按"六相全闪"参与二分 → 耐雷水平退化到二分下界
    # （表现为 0.161kA 这类荒谬值），且任务仍标记 success。禁止静默：建不出来直接抛错。
    nested_atp = atp_root / "ATP"
    if nested_atp.is_symlink() and not nested_atp.exists():
        nested_atp.unlink()  # 断链修复
    if nested_atp.exists() and not nested_atp.is_symlink():
        # 真目录（历史遗留：曾被别的代码 mkdir 出来只含模板 .lib）→
        # 会让 ATP 读到「别的塔的静态几何」而并不报错，属静默错误，必须拦。
        leftovers = list(nested_atp.iterdir())
        if leftovers:
            raise RuntimeError(
                f"ATP 双层目录 {nested_atp} 是真实目录（含 {len(leftovers)} 项），"
                f"应为指向 {atp_root} 的符号链接；否则 D:\\ATP\\... 的 $INCLUDE 会读到"
                "陈旧模板几何且不报错。请清空该目录后重试。"
            )
        nested_atp.rmdir()
    if not nested_atp.exists():
        try:
            nested_atp.symlink_to(atp_root)
        except OSError as exc:
            raise RuntimeError(
                f"ATP 双层目录链接创建失败：{nested_atp} -> {atp_root}（{exc}）；"
                "缺此链接时 D:\\ATP\\... 的 $INCLUDE 无法解析，ATP 不会产出 work.lis。"
            ) from exc
        logger.info("[ATP] 已补建双层 ATP 链接：%s -> %s", nested_atp, atp_root)
    elif nested_atp.resolve(strict=False) != atp_root.resolve(strict=False):
        nested_atp.unlink()
        nested_atp.symlink_to(atp_root)
        logger.warning("[ATP] 双层 ATP 链接指向错误，已重指向 %s", atp_root)
    # 兼容模板 INCLUDE 路径：D:\\ATP\\500\\ganzi\\fanji\\M1\\*.lib
    # 以及 D:\\ATP\\35\\ganzi\\raoji1\\M123\\*.lib 等任意电压等级/塔型路径
    # ⚠️ 必须用渲染后的文本（含真实电压/塔型），模板原文里可能是占位符。
    include_dirs: set[str] = set()
    for line in (rendered_text or atp_text or "").splitlines():
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
        # 长耗时引擎调用（单次数分钟、capture_output 期间无输出）→
        # 交给 run_with_heartbeat 周期性打心跳日志，避免前端看起来"日志停了/卡死"。
        from ..core.subprocess_heartbeat import run_with_heartbeat

        result = run_with_heartbeat(
            command,
            cwd=str(run_dir),
            env=env,
            timeout=resolved_job.timeout_seconds,
            label=f"杆塔 {snapshot.tower_no}（{run_dir.name}）tpbig 仿真",
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

    if resolved_job.result_file:
        logger.info("[ATP] 开始解析结果：%s，结果文件=%s", snapshot.tower_no, resolved_job.result_file)
    else:
        # 资产目录只有模板（work.atp/lib/dat），无 work.lis/pl4 契约——
        # 属正常情况：运行产物在 run_dir 生成，闪络判据直接用 work.lis 的 Close switch。
        # 明确提示而非显示 None，避免误以为资产配置缺失。
        logger.info("[ATP] 开始解析结果：%s，资产无结果契约，使用 lis 闪络检测", snapshot.tower_no)
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
        # 无契约资产必然走到这里（降级是预期路径，非异常）
        logger.debug("[ATP] 结果契约解析降级（%s）：%s", snapshot.tower_no, exc)
        parsed_payload = {}
    # 闪络判据（对齐 C# Check_Lightning_work_lis = 读 work.lis "Close switch" 行数）：
    # tpbig 用 both 参数跑后生成 work.lis，绝缘子闪络时模型闭合开关，
    # lis 逐相输出 `*** Close switch "SWUx" to "XX.." after ... sec.`。
    # 每一行计 1 相闪络。该判据随雷电流单调（实测 guxing-fanji-M1：≤300kA=0、
    # 500kA=2、800kA=4），二分法可据此收敛。
    # ⚠️ 不用 Type-99 "begins operation"（恒=2 不随电流变）也不以 pl4 阈值覆盖——
    # 两者都会把闪络判成恒定值，令二分法空转。
    try:
        lis_detail = _read_lis_flashover_detail(run_dir)
        if lis_detail is not None:
            lis_flash, lis_phases = lis_detail
            parsed_payload["flashover_count"] = lis_flash
            if lis_phases:
                # 闪络相名（按 .lis 闭合顺序，如 ["A1","C1","C2",...]）——对齐 C# strXiang
                parsed_payload["flashover_phases"] = lis_phases
            logger.info("[ATP] lis 闪络检测（Close switch）：%s，闪络相数=%d，相=%s",
                        snapshot.tower_no, lis_flash, ",".join(lis_phases) or "-")
    except Exception as exc:
        logger.warning("[ATP] lis 闪络检测失败（%s）：%s", snapshot.tower_no, exc)
    # 仅当 lis 判据不可用（work.lis 缺失/无 Close switch 信息）时，才回退到
    # ATP 二进制波形（work.pl4）闪络检测（复刻 C# pl4Class.flashNumber()）。
    # 注意：pl4 阈值法对部分模板判恒值，不能覆盖 lis 的 Close switch 权威结果。
    if "flashover_count" not in parsed_payload:
        try:
            flashover_count = _read_pl4_flashover_count(
                run_dir, resolved_job.storage_root_path,
                private_engine_dir=_priv_engine,
            )
            if flashover_count is not None:
                parsed_payload["flashover_count"] = flashover_count
                logger.info("[ATP] pl4 闪络检测（回退）：%s，闪络相数=%d", snapshot.tower_no, flashover_count)
        except Exception as exc:
            logger.warning("[ATP] pl4 闪络检测失败（%s）：%s", snapshot.tower_no, exc)
        if "flashover_count" not in parsed_payload:
            # 引擎"跑完"却拿不到任何闪络判据 = 环境/路径问题（引擎文件缺失、D:\ATP 双层链接缺失、
            # $INCLUDE 打不开…）。2026-09-15 实测教训：36 环境曾在此静默继续——每轮都判
            # "闪络"，二分退化到下界，耐雷水平算成 0.161kA 而任务仍标记 success。
            # 按「不具备计算条件必须抛错」原则：这里直接失败，绝不静默代入默认值。
            produced = sorted(p.name for p in run_dir.glob("work.*")) or ["（无 work.* 文件）"]
            raise RuntimeError(
                f"{snapshot.tower_no} ATP 未产出闪络判据：运行目录 {run_dir} 内既无 work.lis"
                f"（Close switch 行）也无 work.pl4，现有文件={produced}。常见原因：引擎辅助文件缺失、"
                "D:\\ATP 双层链接缺失（/app/data/wine/ATP/ATP 应指向 /app/data/wine/ATP）、"
                "$INCLUDE 的 .lib 打不开。"
            )
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
    payload: dict[str, Any] | None = None,
    target_flashover_phases: int = 1,
    on_step: Callable[[int, int, str], None] | None = None,
) -> ExternalTowerExecutionResult:
    low = _coerce_positive_float(execution_options.get("binary_search_low_ka"), default=0.1)
    high = _coerce_positive_float(execution_options.get("binary_search_high_ka"), default=2000.0)
    tolerance = _coerce_positive_float(execution_options.get("binary_search_tolerance_ka"), default=0.1)
    max_iterations = int(execution_options.get("binary_search_max_iterations") or 20)
    # LP-570 多相二分：C# ThreadCompute5_work_atp 双回循环 level_lightning=1..6，
    # 判据 numLightning >= level_lightning（Check_Lightning_work_lis 返回总闪络相数）。
    # target=1 即原单相档（flashover_count > 0）。
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
    final_phases: list[str] = []
    last_probe_phases: list[str] = []
    qualified_count: int | None = None
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
        # 本探点（无论是否达标）的闪络相序：C# 用的是最后一次 Check_Lightning_work_lis 的结果，
        # 即最后一个探点（不一定是达标点）——多相算法的"按实际闪络数存槽 + 相序纠正"要用它。
        _probe_phases = execution.result_json.get("flashover_phases") if isinstance(execution.result_json, dict) else None
        if _probe_phases:
            last_probe_phases = list(_probe_phases)
        if flashover_count is not None and flashover_count >= target_flashover_phases:
            high = candidate
            # 达标档：记录该电流下的闪络相名（对齐 C# strXiang）
            if _probe_phases:
                final_phases = list(_probe_phases)
            # ⚠️ C# mCount_ShanLuoXiang 只在 valueRet >= level 时更新
            # （ComputeLightningProtection.cs:11946-11962）→ 最后一次「达标探点」的相数，
            # 多相算法用它决定存到哪个槽（不是最后探点的相数！）
            qualified_count = flashover_count
        else:
            low = candidate
        final_flashover_count = flashover_count
        final_execution = execution
        # 塔内子步骤进度：每次 ATP 仿真完成即上报一次（on_step(done, total_estimate, step_label)）
        if on_step is not None:
            try:
                on_step(iteration, max_iterations, f"二分搜索 第 {target_flashover_phases} 相")
            except Exception:
                logger.debug("[ATP] on_step 上报失败 tower=%s", snapshot.tower_no, exc_info=True)

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
        "target_flashover_phases": target_flashover_phases,
        "final_withstand_ka": withstand_ka,
        # 闪络相名（达标档，按闭合顺序取前 target 个）——对齐 C# 单/双/三..相闪络相列
        "flashover_phases": "".join(final_phases[:target_flashover_phases]),
        # 最后一次「达标探点」的完整相序（不截断）与相数：多相算法存槽用
        # （C# mArray_TeZheng1stTo6th / mCount_ShanLuoXiang 语义）
        "flashover_phases_qualified": "".join(final_phases),
        "qualified_flashover_count": qualified_count,
        # 最后一个探点（不论达标）的完整相序 —— 仅供诊断
        "flashover_phases_last": "".join(last_probe_phases),
    }
    merged = dict(final_execution.result_json) if final_execution is not None else dict(baseline_result)
    merged["binary_search"] = binary_search_payload
    merged["counterstrike_withstand_ka"] = withstand_ka
    merged["shielding_withstand_ka"] = withstand_ka
    # LP-570 反跳率用 ATP 二分耐雷重算：C# 任务2/3（反击耐雷=ATP）的反跳率
    # = fjtzlDanXiang((int)ATP耐雷)，不是规程耐雷。此前 external 路径保留 baseline
    # （规程耐雷 109.45）算的 0.1428，与 C# ATP 基准 0.0906 不符。
    if _is_counterstrike:
        from .fl_analysis_rules import _calculate_counterstrike_trip_rate  # noqa: PLC0415
        from .fl_analysis_rules import _normalize_lightning_inputs  # noqa: PLC0415

        if payload is None:
            payload = {
                "base_tower_json": baseline_result.get("base_tower_json") or {},
                "profile_json": baseline_result.get("profile_json") or {},
            }
        try:
            normalized = _normalize_lightning_inputs(payload)
            if normalized is not None:
                trip_rate = _calculate_counterstrike_trip_rate(normalized, withstand_ka)
                if trip_rate is not None:
                    merged["counterstrike_trip_rate"] = trip_rate
        except Exception:
            pass
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


# 匹配 $INCLUDE 卡里的绝对路径 D:\ATP\<scene相对段>\<file>.lib，捕获 .lib 文件名。
# ⚠️ 正则以 D:\ATP\ 开头、非逗号路径、到 .lib 前；捕获项=文件名（重建短私有路径用）。
_INCLUDE_PATH_RE = re.compile(r"D:\\ATP\\[^,]+?\\?([A-Za-z0-9_]+\.lib)")


def _use_private_engine_dir() -> bool:
    """是否启用「任务级私有引擎目录」（方案 A：支持并发，跨进程不覆盖共享 .lib）。

    默认开启：每个任务/快照的 .lib 物化+重生成到独立短目录（D:\\ATP\\.runs\\{snap短}{scene短}\\），
    work.atp 的 $INCLUDE 改为指向私有目录 → 天然并发安全。
    用环境变量 ATP_PRIVATE_ENGINE_DIR=0 可临时关闭（退回共享引擎目录，仅用于诊断回退）。
    """
    val = os.environ.get("ATP_PRIVATE_ENGINE_DIR", "1").strip().lower()
    return val not in ("0", "false", "no", "")


def _scene_short_code(resolved_job: ResolvedExternalWaveformJob) -> str:
    """从 storage_root 提取场景短码，用于私有引擎目录短命名。

    storage_root 形如 /atp-assets/500/guxing/fanji/noM，scene 段在倒数第二段。
    返回短唯一码：fanji→f、raoji1→r1、raoji2→r2、raoji3→r3；未知→x{idx}。
    ⚠️ ATP $INCLUDE 卡片是 80 列固定宽，私有路径必须足够短（共享式 dahao.lib 起始列
    39、整行 75 列可运行；加前缀后超过 80 列会 KILL=79、last card in error——
    2026-09-15 真机实测，完整 job_id+snapshot_id 前缀把行拉到 147 列即崩）。
    """
    segs = [seg for seg in (resolved_job.storage_root_path or "").strip("/").split("/") if seg]
    if segs and segs[0] == "atp-assets":
        segs = segs[1:]
    # scene 段 = 电压/塔型/场景/组合 中的第 3 段（电压,塔型,场景,组合）
    if len(segs) >= 3:
        scene = segs[2].lower()
    else:
        scene = ""
    mapping = {
        "fanji": "f", "raoji1": "r1", "raoji2": "r2", "raoji3": "r3",
        "fanji1": "f", "fanji2": "f2", "fanji3": "f3",
    }
    if scene in mapping:
        return mapping[scene]
    return "x"  # 未知场景兜底（单任务内唯一即可）


def _private_engine_dir(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    resolved_job: ResolvedExternalWaveformJob,
) -> Path:
    """计算任务级私有引擎目录：D:\\ATP\\.runs\\{snapshot_id短}{scene短码}\\。

    短命名（见 _scene_short_code）保证 $INCLUDE 卡 ≤80 列（ATP 硬限制）。
    .lib/.dat/.pch 平铺该目录；不同塔（snapshot 不同）或不同场景（场景短码不同）
    → 目录不同 → 完全不共享（并发安全）。单任务多塔/多场景天然隔离。
    """
    atp_root = Path("/app/data/wine/ATP")
    short = str(snapshot.id or job.id or "x")[:8]
    return atp_root / ".runs" / (short + _scene_short_code(resolved_job))


def _rewrite_includes(
    rendered_text: str,
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    resolved_job: ResolvedExternalWaveformJob,
) -> str:
    """把 work.atp 的 $INCLUDE 绝对路径前缀从共享引擎目录改为任务私有目录。

    模板 INCLUDE 形如：$INCLUDE, D:\\ATP\\500\\guxing\\fanji\\noM\\dahao.lib, LINE1A,...
    目标：       $INCLUDE, D:\\ATP\\.runs\\{snap短}{scene短}\\dahao.lib, LINE1A,...
    ⚠️ 短命名（见 _private_engine_dir）：保持 ≤80 列（ATP 卡片硬限制，超列会
    KILL=79、last card in error —— 2026-09-15 真机实测）。
    只改第一个 D:\\ATP\\ 前缀；其余（文件名、父节点名、参数）原样保留。
    """
    if not (resolved_job.storage_root_path or "").strip():
        return rendered_text
    priv_win = "D:\\ATP\\.runs\\" + str(snapshot.id or job.id or "x")[:8] + _scene_short_code(resolved_job) + "\\"
    out_lines = []
    for line in rendered_text.splitlines():
        # $INCLUDE 行：把 D:\ATP\<scene相对段>\##.lib 整段替换为 D:\ATP\.runs\{snap短}{scene短}\##.lib。
        # 用正则匹配完整路径（D:\ATP\...\.lib），取 .lib 文件名重建短路径（保 ≤80 列）。
        if line.strip().upper().startswith("$INCLUDE") and ".lib" in line:
            new_line = _INCLUDE_PATH_RE.sub(
                lambda m: priv_win + m.group(1), line
            )
            out_lines.append(new_line)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def _prepare_run_directory(
    *,
    job: FlAnalysisJob,
    snapshot: FlAnalysisTowerSnapshot,
    resolved_job: ResolvedExternalWaveformJob,
    subdir: str = "",
) -> Path:
    base_dir = _resolve_engine_workdir() / "fl-analysis" / job.id / snapshot.id
    if subdir:
        base_dir = base_dir / subdir
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _materialize_asset_files(
    *,
    db: Session,
    run_dir: Path,
    resolved_job: ResolvedExternalWaveformJob,
    private_engine_dir: Path | None = None,
) -> None:
    """把资产目录的全部文件从存储物化到 Wine D 盘引擎目录。

    tpbig 通过 $INCLUDE 引用 D:\\ATP\\500\\ganzi\\fanji\\M1\\short.lib 等绝对路径
    （经 Wine D: 盘映射到 /app/data/wine/ATP）。因此资产文件必须落在
    /app/data/wine/ATP/<storage_root相对路径>，而非运行目录。
    渲染后的 work.atp 已写入 run_dir，这里把它复制到引擎目录覆盖模板占位符版。

    private_engine_dir 非空时（方案 A 启用）物化到任务级私有目录（D:\\ATP\\.runs\\{job}\\{snap}\\...），
    不同任务不共享 .lib → 支持并发不覆盖。
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

    # D 盘引擎目录：/app/data/wine/ATP + storage_root 相对段（默认共享）或私有目录（方案 A）
    atp_root = Path("/app/data/wine/ATP")
    if private_engine_dir is not None:
        engine_dir = private_engine_dir
    else:
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
    """从 work.lis 解析闪络相数（对齐 C# Check_Lightning_work_lis）。"""
    detail = _read_lis_flashover_detail(run_dir)
    return None if detail is None else detail[0]


# C# .atp 中绝缘子闪络开关 SWU1~SWU6 ↔ 相名 的映射（双回 6 相）。
# ★2026-09-15 改为 C# 权威源码表：ComputeLightningProtection.cs::MyXiangXu_from_TeZheng()
#   case "SWU1": "A1"; "SWU2": "B1"; "SWU3": "C1"; "SWU4": "A2"; "SWU5": "B2"; "SWU6": "C2";
# 旧表（SWU1→A1, SWU2→A2, SWU3→B2, SWU4→C1, SWU5→C2, SWU6→B1）是当年从 work.lis 闭合顺序
# **反推**出来的，与 C# 源码不符：用真实 .lis 闭合顺序离线映射，旧表只能命中 C# 期望的
# 2/2/0 个档位（塔42/61/98），权威表命中 6/5/4 个档位。
_SWU_PHASE_MAP: dict[str, str] = {
    "SWU1": "A1", "SWU2": "B1", "SWU3": "C1",
    "SWU4": "A2", "SWU5": "B2", "SWU6": "C2",
}


def _read_lis_flashover_detail(run_dir: Path) -> tuple[int, list[str]] | None:
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
    # ===== 严格移植 C# Check_Lightning_work_lis（ComputeLightningProtection.cs:11880）=====
    # C# 语义：
    #   ① 行含 "Close" 且 IndexOf("Close") > 0；
    #   ② 去掉 \r\n空格\t 后，取第 1、2 个引号之间的开关名；
    #   ③ 若本行凑不出 2 个引号，则把后续行拼接进来直到凑出（或到文件尾补 ""）；
    #   ④ 开关名非空才计数（valueRet++），并记录相名 strXiang[valueRet]；
    #   ⑤ 引号缺失时 C# 会抛异常 → valueRet=-1（解析失败）。
    count = 0
    phases: list[str] = []
    lines = text.splitlines()
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx].strip()
        idx += 1
        if not line:
            continue
        # ① 与 C# 完全一致：text.IndexOf("Close") > 0
        if "Close" not in line or line.index("Close") <= 0:
            continue
        detail = line.replace("\r", "").replace("\n", "").replace(" ", "").replace("\t", "")
        first_quote = detail.find('"')
        has2 = first_quote > 0 and detail.rfind('"') > first_quote
        # ③ 跨行续接
        while not has2 and idx < total:
            nxt = lines[idx].strip()
            idx += 1
            if not nxt:
                continue
            detail += nxt.replace("\r", "").replace("\n", "").replace(" ", "").replace("\t", "")
            first_quote = detail.find('"')
            has2 = first_quote > 0 and detail.rfind('"') > first_quote
        if not has2 and idx >= total:
            detail += '""'
        first_quote = detail.find('"')
        if first_quote < 0:
            logger.warning("[ATP] work.lis 出现无引号的 Close 行（对齐 C# = 解析失败）")
            return -1, []
        rest = detail[first_quote + 1:]
        second_quote = rest.find('"')
        if second_quote < 0:
            logger.warning("[ATP] work.lis Close 行引号不成对（对齐 C# = 解析失败）")
            return -1, []
        switch_name = rest[:second_quote].strip()
        # ④ 仅当开关名非空才计数
        if switch_name:
            count += 1
            phases.append(_SWU_PHASE_MAP.get(switch_name.strip().upper(), switch_name.strip()))
    return count, phases


def _read_pl4_flashover_count(
    run_dir: Path,
    storage_root: str | None = None,
    private_engine_dir: Path | None = None,
) -> int | None:
    """从 work.pl4（ATP 二进制波形）解析闪络相数，复刻 C# pl4Class。

    头部布局（getNs）：偏移 19 起 7 个 uint32 LE：
      N_node, N_vol*2, N_all*2, N_tacs, N_zero, N_begin, N_end
    N_N = (N_end - N_begin) / ((N_all+1)*4)
    闪络检测（flashNumber）：从最后 3 个通道（N_all-1 .. N_all-3）反向找，
    每个通道遍历所有采样点，采样值（float32 LE）> 阈值 10.0 即该相闪络。
    返回闪络相数（0-3）；文件缺失/格式异常返回 None。
    """
    # tpbig 把 pl4 写到 INCLUDE 所在目录（引擎目录/私有目录）而非运行目录：
    #  共享： /app/data/wine/ATP/<电压>/<塔型>/<场景>/<组合>/work.pl4
    #  私有(方案A)：/app/data/wine/ATP/.runs/{job}/{snap}/<电压>/<塔型>/<场景>/<组合>/work.pl4
    candidates = [run_dir / "work.pl4"]
    if private_engine_dir is not None:
        candidates.append(private_engine_dir / "work.pl4")
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

