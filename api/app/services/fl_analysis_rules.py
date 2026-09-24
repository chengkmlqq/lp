from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .tower_topology import infer_line_kind as infer_topology_line_kind
from .tower_topology import infer_structure_count as infer_topology_structure_count


_AC_STANDARD_BY_VOLTAGE: dict[int, tuple[float, dict[int, float]]] = {
    35: (450.0, {1: 16.0, 2: 23.0, 4: 40.0}),
    66: (850.0, {1: 18.0, 2: 25.0, 4: 42.0}),
    110: (1314.0, {1: 20.0, 2: 28.0, 4: 44.0}),
    220: (2265.0, {1: 33.0, 2: 45.0, 4: 50.0}),
    330: (3155.0, {1: 35.0, 2: 46.0, 4: 52.0}),
    500: (4575.0, {1: 39.0, 2: 67.0, 4: 80.0}),
    750: (6745.0, {1: 55.0, 2: 124.0, 4: 130.0}),
}
_DEFAULT_AC_STANDARD = (9000.0, {1: 60.0, 2: 130.0, 4: 140.0})
_DC_STANDARD_BY_VOLTAGE: dict[int, tuple[float, float]] = {
    500: (6000.0, 50.0),
    800: (8500.0, 77.0),
}
_DEFAULT_DC_STANDARD = (9000.0, 90.0)
_ARRESTER_NEGATIVE_VALUES = {"否", "无", "未装", "0", "false", "False", "FALSE"}
_LIGHTNING_LEVEL_BASE = 400.0 + 710.0 / math.pow(10.0, 0.75)
_DEFAULT_LIGHTNING_CURRENT_A = 31.0
_DEFAULT_LIGHTNING_CURRENT_B = 2.6
_AC_RISK_THRESHOLDS = {
    35: 0.8,
    66: 0.65,
    110: 0.525,
    220: 0.315,
    330: 0.2,
    500: 0.14,
    750: 0.1,
    1000: 0.1,
}
_DC_RISK_THRESHOLDS = {
    400: 0.15,
    500: 0.15,
    660: 0.1,
    800: 0.1,
}
_CURRENT_WAVEFORM_ALIASES = {
    "heidler": "heidler",
    "双斜角": "double_slope",
    "double_slope": "double_slope",
    "双指数": "double_exponential",
    "double_exponential": "double_exponential",
}
_FLASHOVER_METHOD_ALIASES = {
    "规程法": "guideline",
    "guideline": "guideline",
    "相交法": "intersection",
    "intersection": "intersection",
    "先导发展法": "leader_development",
    "leader_development": "leader_development",
}
_ALTITUDE_CORRECTION_ALIASES = {
    "无": "none",
    "none": "none",
    "推荐公式1": "formula1",
    "formula1": "formula1",
    "推荐公式2": "formula2",
    "formula2": "formula2",
}
_INDUCED_VOLTAGE_FORMULA_ALIASES = {
    "公式1": "formula1",
    "formula1": "formula1",
    "公式2": "formula2",
    "formula2": "formula2",
}
_DEFAULT_HEAD_TIME_US = 2.6
_DEFAULT_TAIL_TIME_US = 50.0
_DEFAULT_HEAD_STEP_US = 0.1
_DEFAULT_TAIL_STEP_US = 1.0
_MAX_SCAN_AXIS_POINTS = 5


@dataclass(frozen=True)
class _PhasePoint:
    phase_name: str
    x_m: float
    height_m: float


@dataclass(frozen=True)
class _NormalizedLightningInputs:
    tower_no: str
    line_name: str
    tower_type: str
    tower_model: str
    structure_kind: str
    line_voltage_kv: int | None
    is_dc: bool
    ground_resistance_ohm: float | None
    lightning_density: float | None
    slope_1_deg: float
    slope_2_deg: float
    shield_wire_height_m: float | None
    insulator_length_m: float | None
    left_shield_x_m: float | None
    right_shield_x_m: float | None
    current_a: float
    current_b: float
    coupling_phase: _PhasePoint | None
    shielding_phase: _PhasePoint | None
    all_arresters_installed: bool
    synthetic_signed_geometry: bool
    # C# 保护角公式需要"一回"的上/中/下相三个点（Method.cs 取三相最大保护角）
    circuit_one_phases: tuple[_PhasePoint, ...] = ()


@dataclass(frozen=True)
class _WaveformExecutionProfile:
    job_type: str
    current_waveform: str
    flashover_method: str
    altitude_correction: str
    induced_voltage_formula: str
    head_time_min_us: float
    head_time_max_us: float
    head_time_step_us: float
    tail_time_min_us: float
    tail_time_max_us: float
    tail_time_step_us: float


@dataclass(frozen=True)
class _PhaseExposure:
    phase: str
    circuit: str
    x_m: float
    height_m: float


def grade_snapshot_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(payload.get("base_tower_json") or {})
    profile = dict(payload.get("profile_json") or {})
    reason_details = _build_reason_details(base, profile)
    detail_map = {item["code"]: item for item in reason_details}
    formula_result = _grade_formula_snapshot_payload(payload)

    ground_resistance = _as_float(base.get("ground_resistance_ohm"))
    lightning_density = _as_float(base.get("lightning_density"))
    span_large = _as_float(base.get("span_large_m"))
    # LP-560：tower_type 为完整塔型编码（如 d500shangzi），直线/耐张取 structure_kind 列；
    # 兼容旧数据（tower_type 可能仍为「直线/耐张」）。
    tower_type = str(base.get("tower_type") or "")
    structure_kind = str(profile.get("structure_kind") or "")
    if not structure_kind and ("耐张" in tower_type or "直线" in tower_type):
        structure_kind = tower_type
    stroke_mode = str(profile.get("stroke_mode") or "")
    arrester_values = [profile.get("arrester_a"), profile.get("arrester_b"), profile.get("arrester_c")]

    causes = _split_semicolon_text(formula_result.get("cause_analysis"))
    recommendations = _split_semicolon_text(formula_result.get("mitigation_recommendation"))

    if ground_resistance is not None:
        if ground_resistance >= 30:
            causes.append("接地电阻偏高")
            recommendations.append("优先降低接地电阻，复核接地网与冲击接地通道")
        elif ground_resistance >= 15:
            causes.append("接地电阻偏高趋势明显")

    if lightning_density is not None:
        if lightning_density >= 6:
            causes.append("地闪密度较高")
            recommendations.append("按高雷区口径校核绝缘与屏蔽配置")
        elif lightning_density >= 3:
            causes.append("地闪密度中等偏高")

    if span_large is not None:
        if span_large >= 500:
            causes.append("大号侧档距过大")
            recommendations.append("复核大跨距杆塔绝缘配合与防雷保护")
        elif span_large >= 300:
            causes.append("档距偏大")

    insulator_detail = detail_map.get("insulator_length")
    if insulator_detail:
        insulator_grade = _as_int(insulator_detail.get("grade"))
        if insulator_grade is not None and insulator_grade <= 2:
            causes.append("绝缘子串长度偏短")
            recommendations.append("提高绝缘子串长度并校核绝缘配置")
        elif insulator_grade == 3:
            causes.append("绝缘配置裕度一般")

    slope_detail = detail_map.get("terrain_slope")
    if slope_detail:
        slope_grade = _as_int(slope_detail.get("grade"))
        if slope_grade is not None and slope_grade <= 2:
            causes.append("地面倾角较大")
            recommendations.append("关注地形暴露影响并加强接地与巡检")
        elif slope_grade == 3:
            causes.append("地面倾角偏大")

    protection_detail = detail_map.get("protection_angle")
    if protection_detail:
        protection_grade = _as_int(protection_detail.get("grade"))
        if protection_grade is not None and protection_grade <= 2:
            causes.append("保护角暴露偏大")
            recommendations.append("优化避雷线与保护角配置")
        elif protection_grade == 3:
            causes.append("保护角裕度一般")

    shield_wire_detail = detail_map.get("shield_wire_height")
    shield_wire_grade = _as_int(shield_wire_detail.get("grade")) if shield_wire_detail else None
    if shield_wire_grade is not None and shield_wire_grade <= 2:
        causes.append("杆塔高度暴露偏高")
        recommendations.append("复核塔型高度与屏蔽布置")

    if "耐张" in structure_kind:
        causes.append("耐张杆塔参数更敏感")

    if "反击" in stroke_mode:
        causes.append("当前以反击风险为主")
        recommendations.append("优先关注反击耐雷水平与接地改造")

    if any(str(value or "").strip() in _ARRESTER_NEGATIVE_VALUES for value in arrester_values):
        causes.append("避雷器配置不足")
        recommendations.append("补充关键相避雷器并复核安装位置")

    if not causes:
        causes.append("主要输入参数处于低风险区间")
    if not recommendations:
        recommendations.append("维持现有防雷配置并保持常规巡检")

    inputs = dict(formula_result.get("inputs") or {})
    inputs.update(
        {
            "ground_resistance_ohm": inputs.get("ground_resistance_ohm", ground_resistance),
            "lightning_density": inputs.get("lightning_density", lightning_density),
            "span_large_m": span_large,
            "tower_type": tower_type,
            "stroke_mode": stroke_mode,
            "insulator_length_mm": _normalize_insulator_length_mm(
                _as_float(profile.get("insulator_length_m"))
                or _as_float(((profile.get("geometry_layers_json") or {}).get("insulator_length_mm")))
                or _as_float(((base.get("circuit_geometry_json") or {}).get("insulator_length_mm")))
            ),
            "terrain_slope_deg": _max_abs_float(base.get("slope_1"), base.get("slope_2")),
            "protection_angle_deg": _compute_protection_angle_deg(base, profile),
        }
    )

    return {
        **formula_result,
        "cause_analysis": "；".join(dict.fromkeys(causes)),
        "mitigation_recommendation": "；".join(dict.fromkeys(recommendations)),
        "reason_details": reason_details,
        "inputs": inputs,
    }


def grade_mitigation_snapshot_payload(
    payload: Mapping[str, Any],
    *,
    non_construction: bool = False,
    recompute_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """措施推荐（对齐 C# MyCanShu_2 / MyCanShu_3 状态机）。

    与 C# 桌面版一致：对每座风险>2 的杆塔，按状态机「逐档调参」：
      普通版：加长绝缘子串 → 降接地电阻 → 实在调不动才判装避雷器
      非检线版：多一步「调保护角 + 重算避雷线间距」，全试完才判装避雷器

    recompute_fn：注入的「每轮改造后重算」函数，对齐 C# 状态机每轮调
    AllCall_CS(101)（ATP/计算引擎）重算跳闸率与风险等级：
      - 传 None：用规程法 grade_snapshot_payload 重算（离线/无资产场景降级）
      - 传 ATP 版：web 端有 wine 引擎，task 层注入 execute_external_*，
        对齐 C# 的 ATP 引擎重算（禁止静默规程法兜底）
    """
    base = dict(payload.get("base_tower_json") or {})
    profile = dict(payload.get("profile_json") or {})
    source_result = _coerce_risk_result_snapshot(payload.get("source_result_json"))
    current = source_result or grade_snapshot_payload(payload)
    current_score = int(current.get("score") or 0)
    current_risk_level = str(current.get("risk_level") or "low")

    # ── 状态机运行（单塔，对齐 C# MyCanShu_2 / MyCanShu_3）──────────────────
    machine = _csharp_mitigation_machine(
        base=base,
        profile=profile,
        current=current,
        non_construction=non_construction,
        recompute_fn=recompute_fn,
    )
    actions = machine["actions"]
    reached_arrester = machine["reached_arrester"]

    expected = grade_snapshot_payload(
        {
            "base_tower_json": machine["simulated_base"],
            "profile_json": machine["simulated_profile"],
        }
    )

    if current_risk_level == "low" and not actions:
        recommendation_result = "达标低风险"
    elif reached_arrester or any(action["code"] == "arrester_install" for action in actions):
        recommendation_result = "需要安装避雷器"
    else:
        recommendation_result = "不需要安装避雷器"

    tower_no = str(base.get("tower_no") or "")
    recommendation_text = "；".join(action["summary"] for action in actions) if actions else "维持现有配置并保持常规巡检"
    summary_text = (
        f"{tower_no or '当前杆塔'}当前{current_risk_level}风险，"
        f"建议后预期降为{expected['risk_level']}风险，当前/预期得分 {current_score}/{expected['score']}"
    )

    return {
        "risk_level": expected["risk_level"],
        "score": expected["score"],
        "current_risk_level": current_risk_level,
        "current_score": current_score,
        "expected_risk_level": expected["risk_level"],
        "expected_score": expected["score"],
        "cause_analysis": current["cause_analysis"],
        "mitigation_recommendation": recommendation_text,
        "summary_text": summary_text,
        "reason_details": current["reason_details"],
        "mitigation_actions": actions,
        "recommendation_result": recommendation_result,
        "non_construction": non_construction,
        "inputs": current["inputs"],
    }


def grade_normal_snapshot_payload(
    payload: Mapping[str, Any],
    *,
    execution_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    execution = _build_waveform_execution_profile(payload, execution_options, job_type="normal")
    scan_cases = _evaluate_waveform_scan(payload, execution)
    selected = _select_waveform_case(scan_cases)
    workflow = _serialize_waveform_workflow(execution, scan_point_count=len(scan_cases))
    selected_case = _serialize_selected_case(selected)
    summary_text = _build_waveform_result_summary(
        tower_no=str((payload.get("base_tower_json") or {}).get("tower_no") or ""),
        execution=execution,
        selected_case=selected_case,
        selected_result=selected["graded"],
        multi_phase_results=[],
    )

    return {
        **selected["graded"],
        "job_type": "normal",
        "summary_text": summary_text,
        "workflow": workflow,
        "selected_case": selected_case,
        "scan_points": [_serialize_scan_point(case) for case in scan_cases],
        "phase_results": [],
        "multi_phase_results": [],
    }


def grade_tongtiao_snapshot_payload(
    payload: Mapping[str, Any],
    *,
    execution_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    execution = _build_waveform_execution_profile(payload, execution_options, job_type="tongtiao")
    scan_cases = _evaluate_waveform_scan(payload, execution)
    selected = _select_waveform_case(scan_cases)
    selected_case = _serialize_selected_case(selected)
    workflow = _serialize_waveform_workflow(execution, scan_point_count=len(scan_cases))
    summary_text = _build_waveform_result_summary(
        tower_no=str((payload.get("base_tower_json") or {}).get("tower_no") or ""),
        execution=execution,
        selected_case=selected_case,
        selected_result=selected["graded"],
        multi_phase_results=selected["multi_phase_results"],
    )

    return {
        **selected["graded"],
        "job_type": "tongtiao",
        "summary_text": summary_text,
        "workflow": workflow,
        "selected_case": selected_case,
        "scan_points": [_serialize_scan_point(case) for case in scan_cases],
        "phase_results": selected["phase_results"],
        "multi_phase_results": selected["multi_phase_results"],
    }


def _evaluate_waveform_scan(payload: Mapping[str, Any], execution: _WaveformExecutionProfile) -> list[dict[str, Any]]:
    head_values = _build_scan_values(
        execution.head_time_min_us,
        execution.head_time_max_us,
        execution.head_time_step_us,
    )
    tail_values = _build_scan_values(
        execution.tail_time_min_us,
        execution.tail_time_max_us,
        execution.tail_time_step_us,
    )
    scan_cases: list[dict[str, Any]] = []
    for head_time_us in head_values:
        for tail_time_us in tail_values:
            scan_cases.append(
                _evaluate_waveform_case(
                    payload,
                    execution,
                    head_time_us=head_time_us,
                    tail_time_us=tail_time_us,
                )
            )
    return scan_cases


def _evaluate_waveform_case(
    payload: Mapping[str, Any],
    execution: _WaveformExecutionProfile,
    *,
    head_time_us: float,
    tail_time_us: float,
) -> dict[str, Any]:
    base_result = grade_snapshot_payload(payload)
    normalized = _normalize_lightning_inputs(payload)
    severity = _build_waveform_severity(
        payload,
        execution,
        head_time_us=head_time_us,
        tail_time_us=tail_time_us,
    )

    counterstrike_withstand_ka = _scaled_inverse(
        _as_float(base_result.get("counterstrike_withstand_ka")),
        severity["counterstrike"],
        digits=4,
    )
    shielding_withstand_ka = _scaled_inverse(
        _as_float(base_result.get("shielding_withstand_ka")),
        severity["shielding"],
        digits=4,
    )
    counterstrike_trip_rate = _scaled_forward(
        _as_float(base_result.get("counterstrike_trip_rate")),
        severity["counterstrike"],
        digits=6,
    )
    shielding_trip_rate = _scaled_forward(
        _as_float(base_result.get("shielding_trip_rate")),
        severity["shielding"],
        digits=6,
    )

    phase_results = (
        _build_phase_results(
            payload,
            counterstrike_withstand_ka=counterstrike_withstand_ka,
            counterstrike_trip_rate=counterstrike_trip_rate,
            shielding_withstand_ka=shielding_withstand_ka,
            shielding_trip_rate=shielding_trip_rate,
        )
        if execution.job_type == "tongtiao"
        else []
    )
    multi_phase_results = (
        _build_multi_phase_results(phase_results)
        if execution.job_type == "tongtiao"
        else []
    )
    dominant_counterstrike_trip_rate = counterstrike_trip_rate
    dominant_counterstrike_withstand_ka = counterstrike_withstand_ka
    dominant_flashover_phase: str | None = None
    dominant_phase_set: str | None = None
    if multi_phase_results:
        dominant = max(
            multi_phase_results,
            key=lambda item: (
                _as_float(item.get("trip_rate")) or 0.0,
                -(_as_float(item.get("counterstrike_withstand_ka")) or 0.0),
            ),
        )
        dominant_counterstrike_trip_rate = _as_float(dominant.get("trip_rate"))
        dominant_counterstrike_withstand_ka = _as_float(dominant.get("counterstrike_withstand_ka"))
        dominant_flashover_phase = str(dominant.get("flashover_phase") or "").strip() or None
        dominant_phase_set = str(dominant.get("label") or "").strip() or None

    risk_index, risk_threshold, risk_grade = _calculate_risk_grade(
        normalized,
        dominant_counterstrike_trip_rate,
        shielding_trip_rate,
    )
    severity_ratio = (
        round(risk_index / risk_threshold, 6)
        if risk_index is not None and risk_threshold not in {None, 0}
        else None
    )
    risk_level = _risk_level_from_grade(risk_grade) or _normalize_risk_level(base_result.get("risk_level")) or "low"
    score = _score_from_result(severity_ratio, risk_grade, int(base_result.get("score") or 0))

    reason_details = list(base_result.get("reason_details") or [])
    reason_details.extend(
        _build_waveform_reason_details(
            execution,
            head_time_us=head_time_us,
            tail_time_us=tail_time_us,
        )
    )

    cause_analysis = _merge_semicolon_text(
        base_result.get("cause_analysis"),
        _build_waveform_case_cause(execution, head_time_us=head_time_us, tail_time_us=tail_time_us),
    )
    mitigation_recommendation = _merge_semicolon_text(
        base_result.get("mitigation_recommendation"),
        _build_waveform_case_recommendation(execution),
    )
    inputs = dict(base_result.get("inputs") or {})
    inputs.update(
        {
            "current_waveform": execution.current_waveform,
            "flashover_method": execution.flashover_method,
            "altitude_correction": execution.altitude_correction,
            "induced_voltage_formula": execution.induced_voltage_formula,
            "head_time_us": head_time_us,
            "tail_time_us": tail_time_us,
        }
    )

    # 顶层「反击/绕击耐雷水平」置 0 仅适用于交流同跳（C# 普通计算顶层保留实际值）
    _zero_top = (getattr(execution, "job_type", "") or "") == "tongtiao"

    graded = {
        **base_result,
        "risk_level": risk_level,
        "risk_grade": risk_grade if risk_grade is not None else base_result.get("risk_grade"),
        "score": score,
        # ── 顶层耐雷/跳闸率口径（对齐 C# 交流同跳）───────────────────────
        # 证据：C# 引擎（ComputeLightningProtection.cs）对 IDout24「反击耐雷水平」、
        # IDout26「绕击耐雷水平」只在 MyParamClass 注册、**全源码无赋值** → 输出保持 0；
        # 基准 CSV《同跳-500kV双回雁船线-测试相序输出.csv》六行顶层均为 0。明细各档值
        # 仍完整保留在 multi_phase_results / phase_results（对应 CSV 的单相…六相列）。
        # ⚠ 只对「交流同跳」成立：C# 普通计算的顶层是有值的（如 500源上 1号塔
        # 顶层反击耐雷 232.388 / 反击跳闸率 0.2458 / 绕击耐雷 35.153 / 绕击跳闸率 1.2824）。
        "counterstrike_withstand_ka": 0.0 if _zero_top else base_result.get("counterstrike_withstand_ka"),
        "counterstrike_trip_rate": 0.0 if _zero_top else base_result.get("counterstrike_trip_rate"),
        "shielding_withstand_ka": 0.0 if _zero_top else base_result.get("shielding_withstand_ka"),
        "shielding_trip_rate": shielding_trip_rate,
        "cause_analysis": cause_analysis,
        "mitigation_recommendation": mitigation_recommendation,
        "reason_details": reason_details,
        "inputs": inputs,
        "flashover_phase": dominant_flashover_phase,
        "dominant_phase_set": dominant_phase_set,
    }

    ranking_trip_rate = max(
        dominant_counterstrike_trip_rate or 0.0,
        shielding_trip_rate or 0.0,
    )
    return {
        "head_time_us": head_time_us,
        "tail_time_us": tail_time_us,
        "graded": graded,
        "phase_results": phase_results,
        "multi_phase_results": multi_phase_results,
        "ranking_trip_rate": ranking_trip_rate,
    }


def _build_waveform_execution_profile(
    payload: Mapping[str, Any],
    execution_options: Mapping[str, Any] | None,
    *,
    job_type: str,
) -> _WaveformExecutionProfile:
    options = dict(execution_options or {})
    profile = dict(payload.get("profile_json") or {})
    default_head = _coalesce_positive_float(
        options.get("current_head_time_us"),
        profile.get("current_head_time_us"),
        _DEFAULT_HEAD_TIME_US,
    )
    default_tail = _coalesce_positive_float(
        options.get("current_tail_time_us"),
        profile.get("current_tail_time_us"),
        _DEFAULT_TAIL_TIME_US,
    )

    return _WaveformExecutionProfile(
        job_type=job_type,
        current_waveform=_normalize_choice(
            options.get("current_waveform") or profile.get("current_type"),
            aliases=_CURRENT_WAVEFORM_ALIASES,
            default="heidler",
        ),
        flashover_method=_normalize_choice(
            options.get("flashover_method"),
            aliases=_FLASHOVER_METHOD_ALIASES,
            default="intersection",
        ),
        altitude_correction=_normalize_choice(
            options.get("altitude_correction"),
            aliases=_ALTITUDE_CORRECTION_ALIASES,
            default="none",
        ),
        induced_voltage_formula=_normalize_choice(
            options.get("induced_voltage_formula"),
            aliases=_INDUCED_VOLTAGE_FORMULA_ALIASES,
            default="formula1",
        ),
        head_time_min_us=_normalize_positive_number(
            options.get("head_time_min_us"),
            default=default_head,
        ),
        head_time_max_us=_normalize_positive_number(
            options.get("head_time_max_us"),
            default=default_head,
        ),
        head_time_step_us=_normalize_positive_number(
            options.get("head_time_step_us"),
            default=_DEFAULT_HEAD_STEP_US,
        ),
        tail_time_min_us=_normalize_positive_number(
            options.get("tail_time_min_us"),
            default=default_tail,
        ),
        tail_time_max_us=_normalize_positive_number(
            options.get("tail_time_max_us"),
            default=default_tail,
        ),
        tail_time_step_us=_normalize_positive_number(
            options.get("tail_time_step_us"),
            default=_DEFAULT_TAIL_STEP_US,
        ),
    )


def _build_waveform_severity(
    payload: Mapping[str, Any],
    execution: _WaveformExecutionProfile,
    *,
    head_time_us: float,
    tail_time_us: float,
) -> dict[str, float]:
    base = dict(payload.get("base_tower_json") or {})
    altitude_m = _as_float(base.get("altitude_m")) or 0.0
    # LP-570 对齐 C#：规程法结果不受波形/闪络判据/海拔公式缩放（C# ThreadCompute5 规程法分支
    # 直接输出公式值，无任何 severity 系数）。原自创系数（intersection×1.06 等）导致
    # 反击耐雷偏低 ~6%、与 C# 基准不可比，已全部归 1。波头/波尾扫描仅保留记录用途。
    waveform_factor = 1.0
    flashover_factor = 1.0
    induced_voltage_factor = 1.0
    altitude_factor = 1.0
    head_factor = 1.0
    tail_factor = 1.0
    counterstrike = waveform_factor * flashover_factor * altitude_factor * head_factor * tail_factor
    shielding = waveform_factor * induced_voltage_factor * altitude_factor * math.pow(head_factor, 0.9) * tail_factor
    if execution.job_type == "tongtiao":
        counterstrike *= 1.08
        shielding *= 1.05
    return {
        "counterstrike": round(counterstrike, 6),
        "shielding": round(shielding, 6),
    }


def _build_phase_results(
    payload: Mapping[str, Any],
    *,
    counterstrike_withstand_ka: float | None,
    counterstrike_trip_rate: float | None,
    shielding_withstand_ka: float | None,
    shielding_trip_rate: float | None,
) -> list[dict[str, Any]]:
    exposures = _extract_phase_exposures(payload)
    if not exposures:
        return []

    average_height = sum(item.height_m for item in exposures) / len(exposures)
    results: list[dict[str, Any]] = []
    for exposure in exposures[:6]:
        height_factor = 1.0 + max(exposure.height_m - average_height, 0.0) / 40.0
        lateral_factor = 1.0 + abs(exposure.x_m) / 30.0
        shielding_factor = (height_factor * 0.6) + (lateral_factor * 0.4)
        counterstrike_factor = (height_factor * 0.7) + 0.3
        results.append(
            {
                "phase": exposure.phase,
                "circuit": exposure.circuit,
                "shielding_withstand_ka": _scaled_inverse(
                    shielding_withstand_ka,
                    shielding_factor,
                    digits=4,
                ),
                "shielding_trip_rate": _scaled_forward(
                    shielding_trip_rate,
                    shielding_factor,
                    digits=6,
                ),
                "counterstrike_withstand_ka": _scaled_inverse(
                    counterstrike_withstand_ka,
                    counterstrike_factor,
                    digits=4,
                ),
                "counterstrike_trip_rate": _scaled_forward(
                    counterstrike_trip_rate,
                    counterstrike_factor,
                    digits=6,
                ),
            }
        )
    return results


def _build_multi_phase_results(phase_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(
        phase_results,
        key=lambda item: (
            _as_float(item.get("counterstrike_trip_rate")) or 0.0,
            -(_as_float(item.get("counterstrike_withstand_ka")) or 0.0),
        ),
        reverse=True,
    )
    limit = min(6, len(ordered))
    results: list[dict[str, Any]] = []
    for index in range(limit):
        selected = ordered[: index + 1]
        trip_values = [_as_float(item.get("counterstrike_trip_rate")) or 0.0 for item in selected]
        withstand_values = [
            _as_float(item.get("counterstrike_withstand_ka"))
            for item in selected
            if _as_float(item.get("counterstrike_withstand_ka")) is not None
        ]
        average_trip_rate = sum(trip_values) / len(trip_values) if trip_values else 0.0
        trip_rate = round(average_trip_rate * (1.0 + 0.12 * index), 6)
        withstand = round(max(min(withstand_values) * (1.0 - 0.06 * index), 0.0), 4) if withstand_values else None
        results.append(
            {
                "phase_count": index + 1,
                "label": _phase_count_label(index + 1),
                "flashover_phase": ",".join(str(item.get("phase") or "") for item in selected),
                "counterstrike_withstand_ka": withstand,
                "trip_rate": trip_rate,
            }
        )
    return results


def _extract_phase_exposures(payload: Mapping[str, Any]) -> list[_PhaseExposure]:
    base = payload.get("base_tower_json") or {}
    profile = payload.get("profile_json") or {}
    geometry = _merge_geometry_layers(base.get("circuit_geometry_json"), profile.get("geometry_layers_json"))
    exposures: list[_PhaseExposure] = []
    for circuit_index, circuit_key in enumerate(("I", "II", "III", "IV"), start=1):
        circuit = geometry.get(circuit_key)
        if not isinstance(circuit, dict):
            continue
        spacing = circuit.get("phase_spacing_m") if isinstance(circuit.get("phase_spacing_m"), dict) else {}
        heights = circuit.get("phase_height_m") if isinstance(circuit.get("phase_height_m"), dict) else {}
        label_map = _phase_label_map(profile, circuit_index)
        for phase_name in ("upper", "middle", "lower"):
            x_m = _as_geometry_float(spacing.get(phase_name))
            height_m = _as_geometry_float(heights.get(phase_name))
            if x_m is None or height_m is None:
                continue
            base_label = label_map.get(phase_name, phase_name.upper())
            phase_label = base_label if circuit_key == "I" else f"{circuit_key}-{base_label}"
            exposures.append(
                _PhaseExposure(
                    phase=phase_label,
                    circuit=circuit_key,
                    x_m=x_m,
                    height_m=height_m,
                )
            )
    return exposures


def _phase_label_map(profile: Mapping[str, Any], circuit_index: int) -> dict[str, str]:
    default = {
        "upper": "A",
        "middle": "B",
        "lower": "C",
    }
    sequence_text = str(profile.get(f"phase_sequence_{circuit_index}") or "").strip().upper()
    sequence = [char for char in sequence_text if char in {"A", "B", "C"}]
    if len(sequence) < 3:
        return default
    return {
        "upper": sequence[0],
        "middle": sequence[1],
        "lower": sequence[2],
    }


def _build_waveform_reason_details(
    execution: _WaveformExecutionProfile,
    *,
    head_time_us: float,
    tail_time_us: float,
) -> list[dict[str, Any]]:
    head_grade = _grade_head_time(head_time_us)
    tail_grade = _grade_tail_time(tail_time_us)
    return [
        {
            "code": "current_head_time",
            "label": "波头时间(μs)",
            "value": head_time_us,
            "standard_value": _DEFAULT_HEAD_TIME_US,
            "grade": head_grade,
            "triggered": head_grade <= 2,
        },
        {
            "code": "current_tail_time",
            "label": "波尾时间(μs)",
            "value": tail_time_us,
            "standard_value": _DEFAULT_TAIL_TIME_US,
            "grade": tail_grade,
            "triggered": tail_grade <= 2,
        },
        {
            "code": "current_waveform",
            "label": "雷电流波形",
            "value": _waveform_label(execution.current_waveform),
            "standard_value": _waveform_label("heidler"),
            "grade": None,
            "triggered": False,
        },
    ]


def _serialize_waveform_workflow(
    execution: _WaveformExecutionProfile,
    *,
    scan_point_count: int,
) -> dict[str, Any]:
    return {
        "current_waveform": execution.current_waveform,
        "flashover_method": execution.flashover_method,
        "altitude_correction": execution.altitude_correction,
        "induced_voltage_formula": execution.induced_voltage_formula,
        "head_time_range_us": {
            "min": execution.head_time_min_us,
            "max": execution.head_time_max_us,
            "step": execution.head_time_step_us,
        },
        "tail_time_range_us": {
            "min": execution.tail_time_min_us,
            "max": execution.tail_time_max_us,
            "step": execution.tail_time_step_us,
        },
        "scan_point_count": scan_point_count,
    }


def _serialize_selected_case(scan_case: Mapping[str, Any]) -> dict[str, Any]:
    graded = dict(scan_case.get("graded") or {})
    return {
        "head_time_us": _as_float(scan_case.get("head_time_us")),
        "tail_time_us": _as_float(scan_case.get("tail_time_us")),
        "risk_level": graded.get("risk_level"),
        "score": graded.get("score"),
        "flashover_phase": graded.get("flashover_phase"),
        "dominant_phase_set": graded.get("dominant_phase_set"),
    }


def _serialize_scan_point(scan_case: Mapping[str, Any]) -> dict[str, Any]:
    graded = dict(scan_case.get("graded") or {})
    return {
        "head_time_us": _as_float(scan_case.get("head_time_us")),
        "tail_time_us": _as_float(scan_case.get("tail_time_us")),
        "risk_level": graded.get("risk_level"),
        "score": graded.get("score"),
        "counterstrike_withstand_ka": graded.get("counterstrike_withstand_ka"),
        "counterstrike_trip_rate": graded.get("counterstrike_trip_rate"),
        "shielding_withstand_ka": graded.get("shielding_withstand_ka"),
        "shielding_trip_rate": graded.get("shielding_trip_rate"),
        "flashover_phase": graded.get("flashover_phase"),
        "dominant_phase_set": graded.get("dominant_phase_set"),
    }


def _select_waveform_case(scan_cases: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        scan_cases,
        key=lambda item: (
            _risk_order((item.get("graded") or {}).get("risk_level")),
            int((item.get("graded") or {}).get("score") or 0),
            _as_float(item.get("ranking_trip_rate")) or 0.0,
            -(_as_float(item.get("head_time_us")) or 0.0),
            -(_as_float(item.get("tail_time_us")) or 0.0),
        ),
    )


def _build_waveform_result_summary(
    *,
    tower_no: str,
    execution: _WaveformExecutionProfile,
    selected_case: Mapping[str, Any],
    selected_result: Mapping[str, Any],
    multi_phase_results: list[dict[str, Any]],
) -> str:
    tower_label = tower_no or "当前杆塔"
    head_time_us = _as_float(selected_case.get("head_time_us"))
    tail_time_us = _as_float(selected_case.get("tail_time_us"))
    risk_label = _risk_level_label(selected_result.get("risk_level"))
    parts = [
        f"{tower_label}{'同跳' if execution.job_type == 'tongtiao' else '普通'}计算",
        f"最不利点 {head_time_us or 0:.2f}/{tail_time_us or 0:.2f} μs",
        f"{risk_label}风险",
    ]
    risk_grade = _as_int(selected_result.get("risk_grade"))
    if risk_grade is not None:
        parts.append(f"规程法等级 {risk_grade}")
    if execution.job_type == "tongtiao" and multi_phase_results:
        dominant = multi_phase_results[-1]
        parts.append(
            f"{dominant.get('label') or '多相'} {dominant.get('flashover_phase') or '-'} 跳闸率 "
            f"{_as_float(dominant.get('trip_rate')) or 0.0:.4f}"
        )
    elif _as_float(selected_result.get("counterstrike_trip_rate")) is not None:
        parts.append(f"反击跳闸率 {_as_float(selected_result.get('counterstrike_trip_rate')) or 0.0:.4f}")
    return "，".join(parts)


def _build_waveform_case_cause(
    execution: _WaveformExecutionProfile,
    *,
    head_time_us: float,
    tail_time_us: float,
) -> str:
    return (
        f"按{_waveform_label(execution.current_waveform)}波形、"
        f"{_flashover_method_label(execution.flashover_method)}口径扫描 "
        f"{head_time_us:.2f}/{tail_time_us:.2f} μs"
    )


def _build_waveform_case_recommendation(execution: _WaveformExecutionProfile) -> str:
    if execution.job_type == "tongtiao":
        return "建议结合多回线路相序、避雷器配置与同跳闪络相再做 ATP 复核"
    return "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数"


def _grade_formula_snapshot_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(payload.get("base_tower_json") or {})
    profile = dict(payload.get("profile_json") or {})
    legacy_result = _extract_legacy_lightning_result(base.get("lightning_result_json"))
    normalized = _normalize_lightning_inputs(payload)
    fallback_missing: list[str] = []

    counterstrike_withstand_ka: float | None = None
    counterstrike_trip_rate: float | None = None
    shielding_withstand_ka: float | None = None
    shielding_trip_rate: float | None = None
    coupling_details: dict[str, Any] = {}
    shielding_alpha_deg: float | None = None
    risk_index: float | None = None
    risk_threshold: float | None = None
    risk_grade: int | None = None
    severity_ratio: float | None = None
    used_legacy_fallback = False

    if normalized is not None:
        counterstrike_withstand_ka, coupling_details = _calculate_counterstrike_withstand_ka(normalized)
        shielding_withstand_ka = _calculate_shielding_withstand_ka(normalized)
        # LP-570 显示倍率对齐 C# BeiShu.txt 实际用法：
        # - 反击(fanji)：规程法/ATP 均乘（6524/6685 行 showCurrent_kV=|current|*mBeiShu_fanji），
        #   500kV 等大多为 1.0，仅 35kV guxing=0.7。
        # - 绕击(raoji)：仅 ATP 分支乘（7838 行）；规程法分支（7673 行 i_star==2）直接输出
        #   串长公式值、不乘倍率。⚠️ 不可拿 MyConst 默认 0.7 当最终倍率。
        _fj_mult = _csharp_beishu_multiplier_rules(
            tower_type=normalized.tower_type,
            structure_kind=normalized.structure_kind,
            voltage_kv=normalized.line_voltage_kv,
            is_counterstrike=True,
        )
        _rj_mult = _csharp_beishu_multiplier_rules(
            tower_type=normalized.tower_type,
            structure_kind=normalized.structure_kind,
            voltage_kv=normalized.line_voltage_kv,
            is_counterstrike=False,
        )
        if counterstrike_withstand_ka is not None:
            counterstrike_withstand_ka = round(counterstrike_withstand_ka * _fj_mult, 4)
        if shielding_withstand_ka is not None:
            # 规程法绕击耐雷 = 串长×526.258/100，C# 不乘倍率（乘 1.0）；ATP 路径在外层适配器另行乘
            shielding_withstand_ka = round(shielding_withstand_ka, 4)
        counterstrike_trip_rate = _calculate_counterstrike_trip_rate(normalized, counterstrike_withstand_ka)
        shielding_trip_rate, shielding_alpha_deg = _calculate_shielding_trip_rate(normalized, shielding_withstand_ka)
        risk_index, risk_threshold, risk_grade = _calculate_risk_grade(
            normalized,
            counterstrike_trip_rate,
            shielding_trip_rate,
        )
        severity_ratio = (
            round(risk_index / risk_threshold, 6)
            if risk_index is not None and risk_threshold not in {None, 0}
            else None
        )

    if counterstrike_withstand_ka is None:
        counterstrike_withstand_ka = legacy_result["counterstrike_withstand_ka"]
        if counterstrike_withstand_ka is not None:
            used_legacy_fallback = True
        else:
            fallback_missing.append("反击耐雷水平")
    if counterstrike_trip_rate is None:
        counterstrike_trip_rate = legacy_result["counterstrike_trip_rate"]
        if counterstrike_trip_rate is not None:
            used_legacy_fallback = True
        else:
            fallback_missing.append("反击跳闸率")
    if shielding_withstand_ka is None:
        shielding_withstand_ka = legacy_result["shielding_withstand_ka"]
        if shielding_withstand_ka is not None:
            used_legacy_fallback = True
        else:
            fallback_missing.append("绕击耐雷水平")
    if shielding_trip_rate is None:
        shielding_trip_rate = legacy_result["shielding_trip_rate"]
        if shielding_trip_rate is not None:
            used_legacy_fallback = True
        else:
            fallback_missing.append("绕击跳闸率")

    if risk_index is None or risk_threshold is None or risk_grade is None:
        legacy_grade = legacy_result["risk_grade"]
        if legacy_grade is not None:
            risk_grade = legacy_grade
            risk_index, risk_threshold, _ = _calculate_risk_grade(
                normalized,
                counterstrike_trip_rate,
                shielding_trip_rate,
            )
            if risk_index is not None and risk_threshold not in {None, 0}:
                severity_ratio = round(risk_index / risk_threshold, 6)
            used_legacy_fallback = True

    risk_level = _risk_level_from_grade(risk_grade)
    if risk_level is None:
        risk_level = legacy_result["risk_level"]
        if risk_level is not None:
            used_legacy_fallback = True

    heuristic_score = _heuristic_score(base, profile)
    if risk_level is None:
        if heuristic_score >= 70:
            risk_level = "high"
        elif heuristic_score >= 40:
            risk_level = "medium"
        else:
            risk_level = "low"

    score = _score_from_result(severity_ratio, risk_grade, heuristic_score)
    cause_analysis, mitigation_recommendation = _build_formula_explanation(
        normalized=normalized,
        counterstrike_trip_rate=counterstrike_trip_rate,
        shielding_trip_rate=shielding_trip_rate,
        risk_grade=risk_grade,
        used_legacy_fallback=used_legacy_fallback,
        fallback_missing=fallback_missing,
    )

    tower_no = str(base.get("tower_no") or "")
    summary_text = _build_formula_summary_text(
        tower_no=tower_no,
        risk_level=risk_level,
        risk_grade=risk_grade,
        counterstrike_trip_rate=counterstrike_trip_rate,
        shielding_trip_rate=shielding_trip_rate,
        used_legacy_fallback=used_legacy_fallback,
    )

    return {
        "risk_level": risk_level,
        "risk_grade": risk_grade,
        "score": score,
        "cause_analysis": cause_analysis,
        "mitigation_recommendation": mitigation_recommendation,
        "summary_text": summary_text,
        "counterstrike_withstand_ka": _rounded_value(counterstrike_withstand_ka),
        "counterstrike_trip_rate": _rounded_value(counterstrike_trip_rate),
        "shielding_withstand_ka": _rounded_value(shielding_withstand_ka),
        "shielding_trip_rate": _rounded_value(shielding_trip_rate),
        "risk_index_s": _rounded_value(risk_index),
        "risk_threshold_s": _rounded_value(risk_threshold),
        "severity_ratio": _rounded_value(severity_ratio),
        "used_legacy_fallback": used_legacy_fallback,
        "formula_source": "规程法",
        "inputs": {
            "line_voltage_kv": normalized.line_voltage_kv if normalized else _as_int(base.get("line_voltage_kv")),
            "ground_resistance_ohm": normalized.ground_resistance_ohm if normalized else _as_float(base.get("ground_resistance_ohm")),
            "lightning_density": normalized.lightning_density if normalized else _as_float(base.get("lightning_density")),
            "insulator_length_m": normalized.insulator_length_m if normalized else None,
            "shield_wire_height_m": normalized.shield_wire_height_m if normalized else None,
            "current_a": normalized.current_a if normalized else legacy_result["current_a"],
            "current_b": normalized.current_b if normalized else legacy_result["current_b"],
            "slope_1_deg": normalized.slope_1_deg if normalized else _as_float(base.get("slope_1")),
            "slope_2_deg": normalized.slope_2_deg if normalized else _as_float(base.get("slope_2")),
            "coupling_phase": (
                {
                    "phase_name": normalized.coupling_phase.phase_name,
                    "x_m": normalized.coupling_phase.x_m,
                    "height_m": normalized.coupling_phase.height_m,
                }
                if normalized and normalized.coupling_phase
                else None
            ),
            "shielding_phase": (
                {
                    "phase_name": normalized.shielding_phase.phase_name,
                    "x_m": normalized.shielding_phase.x_m,
                    "height_m": normalized.shielding_phase.height_m,
                }
                if normalized and normalized.shielding_phase
                else None
            ),
            "synthetic_signed_geometry": normalized.synthetic_signed_geometry if normalized else False,
        },
        "formula_details": {
            "coupling": coupling_details,
            "shielding_alpha_deg": _rounded_value(shielding_alpha_deg),
            "fallback_missing": fallback_missing,
        },
    }


def _extract_legacy_lightning_result(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    risk_grade = _as_int(data.get("risk_level"))
    return {
        "counterstrike_withstand_ka": _as_float(data.get("counterstroke_withstand_ka")),
        "counterstrike_trip_rate": _as_float(data.get("counterstroke_trip_rate")),
        "shielding_withstand_ka": _as_float(data.get("shielding_withstand_ka")),
        "shielding_trip_rate": _as_float(data.get("shielding_trip_rate")),
        "risk_grade": risk_grade,
        "risk_level": _risk_level_from_grade(risk_grade) or _normalize_risk_level(data.get("risk_level")),
        "current_a": _as_float(data.get("current_a")),
        "current_b": _as_float(data.get("current_b")),
    }


def _normalize_lightning_inputs(payload: Mapping[str, Any]) -> _NormalizedLightningInputs | None:
    base = payload.get("base_tower_json") or {}
    profile = payload.get("profile_json") or {}
    geometry = _merge_geometry_layers(base.get("circuit_geometry_json"), profile.get("geometry_layers_json"))
    circuits = _extract_circuit_points(geometry)
    coupling_phase, shielding_phase, synthetic_signed_geometry = _select_reference_phases(circuits)
    shield_wire = geometry.get("lightning_wire") if isinstance(geometry.get("lightning_wire"), dict) else {}

    left_shield_raw = _as_geometry_float(shield_wire.get("left_mid_distance_m"))
    right_shield_raw = _as_geometry_float(shield_wire.get("right_mid_distance_m"))
    left_shield_x_m = _normalize_horizontal_coordinate(left_shield_raw, side="left")
    right_shield_x_m = _normalize_horizontal_coordinate(right_shield_raw, side="right")
    synthetic_signed_geometry = synthetic_signed_geometry or (
        left_shield_raw is not None and left_shield_x_m is not None and not math.isclose(left_shield_raw, left_shield_x_m)
    ) or (
        right_shield_raw is not None and right_shield_x_m is not None and not math.isclose(right_shield_raw, right_shield_x_m)
    )

    if left_shield_x_m is None and right_shield_x_m is not None:
        left_shield_x_m = -abs(right_shield_x_m)
        synthetic_signed_geometry = True
    if right_shield_x_m is None and left_shield_x_m is not None:
        right_shield_x_m = abs(left_shield_x_m)
        synthetic_signed_geometry = True
    if left_shield_x_m is None or right_shield_x_m is None:
        # 避雷线中距完全缺失：按电压等级回填典型值（对齐模板设计几何）
        voltage = _as_int(base.get("line_voltage_kv")) or 0
        if voltage >= 500:
            default_mid = 10.0
        elif voltage >= 220:
            default_mid = 7.0
        elif voltage >= 110:
            default_mid = 5.0
        else:
            default_mid = 3.0
        if left_shield_x_m is None:
            left_shield_x_m = -default_mid
            synthetic_signed_geometry = True
        if right_shield_x_m is None:
            right_shield_x_m = default_mid
            synthetic_signed_geometry = True

    line_lightning_param_json = base.get("line_lightning_param_json") or {}
    line_voltage_kv = _as_int(base.get("line_voltage_kv"))
    tower_model = str(base.get("tower_model") or "")
    line_name = str(base.get("line_name") or "")

    if not circuits and left_shield_x_m is None and right_shield_x_m is None:
        return None

    current_a = _coalesce_positive_float(
        profile.get("current_a"),
        line_lightning_param_json.get("雷电流幅值a"),
        _DEFAULT_LIGHTNING_CURRENT_A,
    )
    current_b = _coalesce_positive_float(
        profile.get("current_b"),
        line_lightning_param_json.get("雷电流幅值b"),
        _DEFAULT_LIGHTNING_CURRENT_B,
    )

    arrester_values = tuple(
        str(value or "").strip()
        for value in (profile.get("arrester_a"), profile.get("arrester_b"), profile.get("arrester_c"))
    )
    all_arresters_installed = bool(arrester_values) and all(
        value in {"是", "已装", "1", "true", "True", "Y", "y"} for value in arrester_values if value
    )

    return _NormalizedLightningInputs(
        tower_no=str(base.get("tower_no") or ""),
        line_name=line_name,
        tower_type=str(base.get("tower_type") or ""),
        tower_model=tower_model,
        structure_kind=str(profile.get("structure_kind") or base.get("tower_type") or ""),
        line_voltage_kv=line_voltage_kv,
        is_dc=_is_dc_line(line_name=line_name, tower_model=tower_model),
        ground_resistance_ohm=_as_float(base.get("ground_resistance_ohm")),
        lightning_density=_as_float(base.get("lightning_density")),
        slope_1_deg=_as_float(base.get("slope_1")) or 0.0,
        slope_2_deg=_as_float(base.get("slope_2")) or 0.0,
        shield_wire_height_m=_coalesce_positive_float(
            profile.get("shield_wire_height_m"),
            shield_wire.get("height_m"),
        ),
        insulator_length_m=_normalize_insulator_length_m(
            profile.get("insulator_length_m"),
            geometry.get("insulator_length_mm"),
        ),
        left_shield_x_m=left_shield_x_m,
        right_shield_x_m=right_shield_x_m,
        current_a=current_a,
        current_b=current_b,
        coupling_phase=coupling_phase,
        shielding_phase=shielding_phase,
        all_arresters_installed=all_arresters_installed,
        synthetic_signed_geometry=synthetic_signed_geometry,
        circuit_one_phases=tuple(circuits[0][2]) if circuits else (),
    )


def _merge_geometry_layers(base_geometry: Any, profile_geometry: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    base_data = base_geometry if isinstance(base_geometry, dict) else {}
    profile_data = profile_geometry if isinstance(profile_geometry, dict) else {}

    for circuit in ("I", "II", "III", "IV"):
        base_layer = base_data.get(circuit) if isinstance(base_data.get(circuit), dict) else {}
        profile_layer = profile_data.get(circuit) if isinstance(profile_data.get(circuit), dict) else {}
        spacing = {
            phase: _first_defined(
                ((base_layer.get("phase_spacing_m") or {}) if isinstance(base_layer.get("phase_spacing_m"), dict) else {}).get(phase),
                ((profile_layer.get("phase_spacing_m") or {}) if isinstance(profile_layer.get("phase_spacing_m"), dict) else {}).get(phase),
            )
            for phase in ("upper", "middle", "lower")
        }
        height = {
            phase: _first_defined(
                ((base_layer.get("phase_height_m") or {}) if isinstance(base_layer.get("phase_height_m"), dict) else {}).get(phase),
                ((profile_layer.get("phase_height_m") or {}) if isinstance(profile_layer.get("phase_height_m"), dict) else {}).get(phase),
            )
            for phase in ("upper", "middle", "lower")
        }
        merged[circuit] = {"phase_spacing_m": spacing, "phase_height_m": height}

    base_wire = base_data.get("lightning_wire") if isinstance(base_data.get("lightning_wire"), dict) else {}
    profile_wire = profile_data.get("lightning_wire") if isinstance(profile_data.get("lightning_wire"), dict) else {}
    merged["lightning_wire"] = {
        "left_mid_distance_m": _first_defined(base_wire.get("left_mid_distance_m"), profile_wire.get("left_mid_distance_m")),
        "right_mid_distance_m": _first_defined(base_wire.get("right_mid_distance_m"), profile_wire.get("right_mid_distance_m")),
        "height_m": _first_defined(base_wire.get("height_m"), profile_wire.get("height_m")),
    }
    merged["insulator_length_mm"] = _first_defined(base_data.get("insulator_length_mm"), profile_data.get("insulator_length_mm"))
    merged["tower_height_m"] = _first_defined(base_data.get("tower_height_m"), profile_data.get("tower_height_m"))
    return merged


def _extract_circuit_points(geometry: dict[str, Any]) -> list[tuple[str, dict[str, _PhasePoint], list[_PhasePoint]]]:
    circuits: list[tuple[str, dict[str, _PhasePoint], list[_PhasePoint]]] = []
    for circuit in ("I", "II", "III", "IV"):
        layer = geometry.get(circuit)
        if not isinstance(layer, dict):
            continue
        spacing = layer.get("phase_spacing_m") if isinstance(layer.get("phase_spacing_m"), dict) else {}
        height = layer.get("phase_height_m") if isinstance(layer.get("phase_height_m"), dict) else {}
        points: list[_PhasePoint] = []
        for phase_name in ("upper", "middle", "lower"):
            x_m = _as_geometry_float(spacing.get(phase_name))
            height_m = _as_geometry_float(height.get(phase_name))
            if x_m is None or height_m is None or height_m <= 0:
                continue
            points.append(_PhasePoint(phase_name=phase_name, x_m=x_m, height_m=height_m))
        if points:
            circuits.append((circuit, {point.phase_name: point for point in points}, points))
    return circuits


def _select_reference_phases(
    circuits: list[tuple[str, dict[str, _PhasePoint], list[_PhasePoint]]],
) -> tuple[_PhasePoint | None, _PhasePoint | None, bool]:
    if not circuits:
        return None, None, False

    if len(circuits) >= 4:
        coupling_candidate = circuits[0][1].get("upper") or min(circuits[0][2], key=lambda item: item.x_m)
        shielding_candidate = circuits[-1][1].get("middle") or max(circuits[-1][2], key=lambda item: item.x_m)
    elif len(circuits) >= 2:
        coupling_candidate = circuits[0][1].get("upper") or min(circuits[0][2], key=lambda item: item.x_m)
        shielding_candidate = (
            circuits[1][1].get("middle")
            or circuits[0][1].get("middle")
            or max(circuits[1][2], key=lambda item: item.x_m)
        )
    else:
        coupling_candidate = min(circuits[0][2], key=lambda item: item.x_m)
        shielding_candidate = max(circuits[0][2], key=lambda item: item.x_m)

    # LP-570 对齐 C# fetch_CouplingCoefficient：x3 直接取"上相中距"原值（正数，与右避雷线
    # 中距同侧），不翻符号。此前强制左侧使耦合系数 k 偏小（P1: 0.2529 vs C# 0.258968）、
    # 反击耐雷偏低 ~1%（108.30 vs 109.45）。单回"左相中距"同理按正幅值使用。
    coupling_phase, changed_left = _force_phase_side(coupling_candidate, side="right")
    shielding_phase, changed_right = _force_phase_side(shielding_candidate, side="right")
    return coupling_phase, shielding_phase, changed_left or changed_right


def _force_phase_side(point: _PhasePoint | None, *, side: str) -> tuple[_PhasePoint | None, bool]:
    if point is None:
        return None, False
    target_x = point.x_m
    if side == "left" and point.x_m > 0:
        target_x = -abs(point.x_m)
    elif side == "right" and point.x_m < 0:
        target_x = abs(point.x_m)
    changed = not math.isclose(point.x_m, target_x, abs_tol=1e-9)
    return _PhasePoint(phase_name=point.phase_name, x_m=target_x, height_m=point.height_m), changed


# C# 桌面版倍率表（BeiShu.txt，2025-11-20 执行目录 SettingTxtFile/BeiShu.txt 实测）：
# - 反击 fanji：除 35kV guxing/guxingd=0.7 外，全部 1.0（含 500kV guxing）
# - 绕击 raoji：110/220/500kV 且塔型∈{menxing,ganzi,guxing,guxingd,maotou,jiubei} 取 1.1；
#   sihuita 35/110/220 取 1.1；shangzi 与直流塔型恒 1.0；其余 1.0
# 注意：MyConst.cs 默认 mBeiShu_fanji=0.7 会被 LoadFromSettingFile_BeiShu 覆盖成 1.0，
# 不能拿默认常量当最终倍率。
_CSHARP_BEISHU_RAOJI_110_220_500_RULES = {"menxing", "ganzi", "guxing", "guxingd", "maotou", "jiubei"}


def _csharp_beishu_multiplier_rules(
    *, tower_type: str, structure_kind: str, voltage_kv: int | None, is_counterstrike: bool
) -> float:
    """按 C# BeiShu.txt 查显示倍率（mBeiShu_fanji / mBeiShu_raoji）。

    塔型从 tower_type 编码（如 s500guxing/d500ganzi）或 structure_kind 推断。
    """
    kind_text = f"{tower_type or ''} {structure_kind or ''}".lower()
    kind = ""
    for token in ("guxingd", "guxing", "menxing", "ganzi", "maotou", "jiubei", "shangzi", "sihuita"):
        if token in kind_text:
            kind = token
            break
    voltage = int(voltage_kv) if voltage_kv else 0
    if is_counterstrike:
        # fanji：仅 35kV 鼓型（guxing/guxingd）取 0.7，其余 1.0
        if voltage <= 35 and kind in ("guxing", "guxingd"):
            return 0.7
        return 1.0
    # raoji
    if kind == "sihuita":
        return 1.1 if voltage in (35, 110, 220) else 1.0
    if voltage in (110, 220, 500) and kind in _CSHARP_BEISHU_RAOJI_110_220_500_RULES:
        return 1.1
    return 1.0


def _calculate_counterstrike_withstand_ka(
    normalized: _NormalizedLightningInputs,
) -> tuple[float | None, dict[str, Any]]:
    if (
        normalized.insulator_length_m is None
        or normalized.shield_wire_height_m is None
        or normalized.shield_wire_height_m <= 0
        or normalized.ground_resistance_ohm is None
        or normalized.coupling_phase is None
        or normalized.left_shield_x_m is None
        or normalized.right_shield_x_m is None
    ):
        return None, {}

    coupling = _calculate_coupling_coefficients(normalized)
    if not coupling:
        return None, {}

    denominator = (
        (1.0 - coupling["k"]) * _counterstrike_level_coefficient(normalized) * normalized.ground_resistance_ohm
        + (coupling["ha"] / normalized.shield_wire_height_m - coupling["k"])
        * _counterstrike_level_coefficient(normalized)
        * (0.5 * normalized.shield_wire_height_m)
        / 2.6
        + (coupling["y3"] - coupling["y1"] * coupling["k0"]) / 2.6
    )
    if math.isclose(denominator, 0.0, abs_tol=1e-9):
        return None, coupling

    current_ka = abs(normalized.insulator_length_m * _LIGHTNING_LEVEL_BASE / denominator)
    current_ka = min(max(current_ka, 0.0), 2000.0)
    return round(current_ka, 4), {**coupling, "denominator": round(denominator, 6)}


def _calculate_coupling_coefficients(normalized: _NormalizedLightningInputs) -> dict[str, float]:
    if (
        normalized.coupling_phase is None
        or normalized.left_shield_x_m is None
        or normalized.right_shield_x_m is None
        or normalized.shield_wire_height_m is None
        or normalized.insulator_length_m is None
    ):
        return {}

    coupling_factor = _calculate_coupling_factor(normalized)
    shield_offset = _shield_offset_for_voltage(normalized)
    conductor_offset = _conductor_offset_for_voltage(normalized)

    y1 = normalized.shield_wire_height_m - shield_offset * 2.0 / 3.0
    y3 = normalized.coupling_phase.height_m - conductor_offset * 2.0 / 3.0 - normalized.insulator_length_m

    if y1 <= 0:
        return {}

    right_distance = math.hypot(normalized.right_shield_x_m - normalized.coupling_phase.x_m, y1 - y3)
    right_image_distance = math.hypot(normalized.right_shield_x_m - normalized.coupling_phase.x_m, y1 + y3)
    left_distance = math.hypot(normalized.left_shield_x_m - normalized.coupling_phase.x_m, y1 - y3)
    left_image_distance = math.hypot(normalized.left_shield_x_m - normalized.coupling_phase.x_m, y1 + y3)
    shield_span = math.hypot(normalized.left_shield_x_m - normalized.right_shield_x_m, 0.0)
    shield_image_span = math.hypot(normalized.left_shield_x_m - normalized.right_shield_x_m, 2.0 * y1)

    if min(right_distance, right_image_distance, left_distance, left_image_distance, shield_span) <= 0:
        return {}

    base_log = math.log(2.0 * y1 / 0.0055)
    span_log = math.log(shield_image_span / shield_span)
    right_log = math.log(right_image_distance / right_distance)
    left_log = math.log(left_image_distance / left_distance)

    if math.isclose(base_log + span_log, 0.0, abs_tol=1e-9):
        return {}

    k0 = (right_log + left_log) / (base_log + span_log)
    k = coupling_factor * k0
    return {
        "k": round(k, 6),
        "k0": round(k0, 6),
        "y1": round(y1, 6),
        "y3": round(y3, 6),
        "ha": round(normalized.coupling_phase.height_m, 6),
    }


def _calculate_shielding_withstand_ka(normalized: _NormalizedLightningInputs) -> float | None:
    if normalized.insulator_length_m is None:
        return None
    current_ka = normalized.insulator_length_m * _LIGHTNING_LEVEL_BASE / 100.0
    current_ka = min(max(current_ka, 0.0), 1000.0)
    return round(current_ka, 4)


def _calculate_counterstrike_trip_rate(
    normalized: _NormalizedLightningInputs,
    counterstrike_withstand_ka: float | None,
) -> float | None:
    span_factor = _trip_span_factor(normalized)
    if (
        counterstrike_withstand_ka is None
        or normalized.lightning_density is None
        or normalized.shield_wire_height_m is None
        or normalized.right_shield_x_m is None
        or normalized.current_a <= 0
        or normalized.current_b <= 0
    ):
        return None
    denominator = 6.0 if _is_gentle_slope(normalized) else 4.0
    # LP-570 对齐 C#：反击耐雷水平传入跳闸率公式前先 (int) 截断取整（fjtzlDanXiang((int)fjCurrent1)）
    withstood_ka_int = float(int(counterstrike_withstand_ka))
    trip_rate = (
        0.1
        * normalized.lightning_density
        * span_factor
        * _counterstrike_trip_arc_rate(normalized)
        / denominator
        / (1.0 + math.pow(withstood_ka_int / normalized.current_a, normalized.current_b))
    )
    return round(max(trip_rate, 0.0), 6)


def _calculate_shielding_trip_rate(
    normalized: _NormalizedLightningInputs,
    shielding_withstand_ka: float | None,
) -> tuple[float | None, float | None]:
    if (
        shielding_withstand_ka is None
        or normalized.lightning_density is None
        or normalized.shield_wire_height_m is None
        or normalized.right_shield_x_m is None
        or normalized.shielding_phase is None
        or normalized.current_a <= 0
        or normalized.current_b <= 0
    ):
        return None, None

    # ── 保护角 α：严格对齐 C# Method.cs（2026-09-15 用全线 98 塔复算 98/98 吻合）──
    # C# 原式（对"一回"的上/中/下相各算一次，取最大值，结果保留 1 位小数）：
    #   if (直线塔) dJYZCD_m = 0;                    // ← 绝缘子串长度只有耐张塔计入
    #   α_i = atan((相中距_i − 左避雷线中距) / (避雷线高度 − 相高_i + dJYZCD_m))
    # 注意三点与旧实现的差异：①取三相最大值（旧：只算中相）②用**左**避雷线中距
    # （旧：右）③绝缘子计入条件相反（旧：直线计入；C#：直线清零、耐张计入）。
    jyzcd_m = 0.0 if "直线" in normalized.structure_kind else (normalized.insulator_length_m or 0.0)
    # ⚠️ C# 数据模型里"中距"一律是**正幅值**（左/右避雷线中距、各相中距都是到塔中心线的距离），
    # 公式直接相减判断相偏在哪一侧；而 Web 把避雷线归一成了带符号坐标（左负右正），
    # 因此这里必须取幅值比较，否则会算出 +75° 这种垃圾值（实测踩过）。
    x_shield = abs(normalized.left_shield_x_m) if normalized.left_shield_x_m is not None else (
        abs(normalized.right_shield_x_m) if normalized.right_shield_x_m is not None else None
    )
    phase_points = tuple(normalized.circuit_one_phases) or (normalized.shielding_phase,)
    alphas: list[float] = []
    for point in phase_points:
        if point is None or x_shield is None:
            continue
        gap = normalized.shield_wire_height_m - point.height_m + jyzcd_m
        if math.isclose(gap, 0.0, abs_tol=1e-9):
            continue
        alphas.append(round(math.degrees(math.atan((abs(point.x_m) - x_shield) / gap)), 1))
    if not alphas:
        return None, None
    alpha_deg = max(alphas)
    exponent_shift = 3.9 if _is_gentle_slope(normalized) else 3.35
    trip_rate = (
        0.1
        * normalized.lightning_density
        * _trip_span_factor(normalized)
        * _shielding_trip_arc_rate(normalized)
        * math.pow(10.0, alpha_deg * math.sqrt(normalized.shield_wire_height_m) / 86.0 - exponent_shift)
        / (1.0 + math.pow(shielding_withstand_ka / normalized.current_a, normalized.current_b))
    )
    return round(max(trip_rate, 0.0), 6), round(alpha_deg, 6)


def _calculate_risk_grade(
    normalized: _NormalizedLightningInputs | None,
    counterstrike_trip_rate: float | None,
    shielding_trip_rate: float | None,
) -> tuple[float | None, float | None, int | None]:
    density = normalized.lightning_density if normalized else None
    threshold = _risk_threshold(normalized) if normalized else None
    if density is None or density <= 0 or threshold is None:
        return None, threshold, None
    if counterstrike_trip_rate is None and shielding_trip_rate is None:
        return None, threshold, None

    total_trip_rate = max((counterstrike_trip_rate or 0.0) + (shielding_trip_rate or 0.0), 0.0)
    risk_index = total_trip_rate * 2.78 / density if total_trip_rate > 0 else 0.0
    if risk_index <= threshold:
        return round(risk_index, 6), threshold, 1
    if risk_index <= 1.5 * threshold:
        return round(risk_index, 6), threshold, 2
    if risk_index <= 3.0 * threshold:
        return round(risk_index, 6), threshold, 3
    return round(risk_index, 6), threshold, 4


def _build_formula_explanation(
    *,
    normalized: _NormalizedLightningInputs | None,
    counterstrike_trip_rate: float | None,
    shielding_trip_rate: float | None,
    risk_grade: int | None,
    used_legacy_fallback: bool,
    fallback_missing: list[str],
) -> tuple[str, str]:
    causes: list[str] = []
    recommendations: list[str] = []

    if risk_grade is not None:
        causes.append(f"规程法雷击风险等级为 {risk_grade} 级")
    if counterstrike_trip_rate is not None and shielding_trip_rate is not None:
        if counterstrike_trip_rate >= max(shielding_trip_rate * 5.0, shielding_trip_rate + 0.05):
            causes.append("反击跳闸率明显高于绕击跳闸率")
            recommendations.append("优先降低接地电阻并复核杆塔耦合与接地通道")
        elif shielding_trip_rate >= max(counterstrike_trip_rate * 2.0, counterstrike_trip_rate + 0.02):
            causes.append("绕击跳闸率占主导")
            recommendations.append("优先优化避雷线保护角与导线屏蔽关系")

    if normalized is not None:
        if normalized.ground_resistance_ohm is not None:
            if normalized.ground_resistance_ohm >= 25:
                causes.append("接地电阻偏高")
                recommendations.append("建议优先实施接地降阻治理")
            elif normalized.ground_resistance_ohm >= 15:
                causes.append("接地电阻有偏高趋势")
        if normalized.lightning_density is not None:
            if normalized.lightning_density >= 6:
                causes.append("地闪密度位于高雷区")
                recommendations.append("建议按高雷区口径复核绝缘与屏蔽配置")
            elif normalized.lightning_density >= 3:
                causes.append("地闪密度中等偏高")
        if normalized.insulator_length_m is not None and normalized.insulator_length_m < 3.0:
            causes.append("绝缘子串长度偏短")
            recommendations.append("建议复核绝缘配合和塔头布置")
        if normalized.synthetic_signed_geometry:
            causes.append("导线左右位置信息缺失，当前按对称坐标近似")
        if normalized.all_arresters_installed:
            recommendations.append("全相装设避雷器的场景建议再用 ATP 方法复核")

    if used_legacy_fallback:
        causes.append("部分规程法输入缺失，已回退到已保存的历史结果")
    if fallback_missing:
        recommendations.append("补齐以下输入可提升结果可信度: " + "、".join(dict.fromkeys(fallback_missing)))
    if risk_grade is not None and risk_grade >= 3:
        recommendations.append("建议将该塔纳入优先治理清单并安排复测")

    if not causes:
        causes.append("当前输入下未见显著高风险因素")
    if not recommendations:
        recommendations.append("维持现有防雷配置并保持常规巡检")

    return "；".join(dict.fromkeys(causes)), "；".join(dict.fromkeys(recommendations))


def _build_formula_summary_text(
    *,
    tower_no: str,
    risk_level: str,
    risk_grade: int | None,
    counterstrike_trip_rate: float | None,
    shielding_trip_rate: float | None,
    used_legacy_fallback: bool,
) -> str:
    tower_label = tower_no or "当前杆塔"
    parts = [f"{tower_label}评估为{risk_level}风险"]
    if risk_grade is not None:
        parts.append(f"规程法等级 {risk_grade}")
    if counterstrike_trip_rate is not None:
        parts.append(f"反击跳闸率 {counterstrike_trip_rate:.4f}")
    if shielding_trip_rate is not None:
        parts.append(f"绕击跳闸率 {shielding_trip_rate:.4f}")
    if used_legacy_fallback:
        parts.append("含历史结果回退")
    return "，".join(parts)


def _risk_level_from_grade(risk_grade: int | None) -> str | None:
    if risk_grade is None:
        return None
    if risk_grade <= 1:
        return "low"
    if risk_grade == 2:
        return "medium"
    return "high"


def _normalize_risk_level(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "low", "低", "低风险"}:
        return "low"
    if text in {"2", "medium", "中", "中风险"}:
        return "medium"
    if text in {"3", "4", "high", "高", "高风险"}:
        return "high"
    return None


def _score_from_result(severity_ratio: float | None, risk_grade: int | None, heuristic_score: int) -> int:
    if severity_ratio is not None and severity_ratio >= 0:
        return int(round(min(max(severity_ratio, 0.0), 4.0) / 4.0 * 100))
    if risk_grade is not None:
        return {1: 25, 2: 45, 3: 70, 4: 90}.get(risk_grade, heuristic_score)
    return heuristic_score


def _heuristic_score(base: Mapping[str, Any], profile: Mapping[str, Any]) -> int:
    score = 0
    ground_resistance = _as_float(base.get("ground_resistance_ohm"))
    lightning_density = _as_float(base.get("lightning_density"))
    span_large = _as_float(base.get("span_large_m"))
    arrester_values = (profile.get("arrester_a"), profile.get("arrester_b"), profile.get("arrester_c"))

    if ground_resistance is not None:
        if ground_resistance >= 30:
            score += 35
        elif ground_resistance >= 15:
            score += 18
    if lightning_density is not None:
        if lightning_density >= 6:
            score += 25
        elif lightning_density >= 3:
            score += 12
    if span_large is not None:
        if span_large >= 500:
            score += 20
        elif span_large >= 300:
            score += 10
    if any(str(value or "").strip() in {"否", "无", "未装", "0"} for value in arrester_values):
        score += 15
    return min(score, 100)


def _calculate_coupling_factor(normalized: _NormalizedLightningInputs) -> float:
    voltage = normalized.line_voltage_kv or 0
    if normalized.is_dc:
        return 1.28
    if voltage in {35, 66}:
        return 1.15
    if voltage == 110:
        return 1.2
    if voltage == 220:
        return 1.25
    if voltage >= 500:
        return 1.28
    return 1.2


def _shield_offset_for_voltage(normalized: _NormalizedLightningInputs) -> float:
    voltage = normalized.line_voltage_kv or 0
    if normalized.is_dc:
        return 9.5
    if voltage in {35, 66}:
        return 1.1
    if voltage == 110:
        return 2.8
    if voltage == 220:
        return 7.0
    if voltage >= 500:
        return 9.5
    return 2.8


def _conductor_offset_for_voltage(normalized: _NormalizedLightningInputs) -> float:
    voltage = normalized.line_voltage_kv or 0
    if normalized.is_dc:
        return 12.0
    if voltage in {35, 66}:
        return 1.8
    if voltage == 110:
        return 5.3
    if voltage >= 220:
        return 12.0
    return 5.3


def _counterstrike_level_coefficient(normalized: _NormalizedLightningInputs) -> float:
    voltage = normalized.line_voltage_kv or 0
    if normalized.is_dc:
        return 0.9
    if voltage in {35, 66}:
        return 0.84
    if voltage == 110:
        return 0.86
    if voltage in {220, 330, 500}:
        return 0.88
    if voltage == 750:
        return 0.89
    if voltage > 750:
        return 0.9
    return 0.88


def _counterstrike_trip_arc_rate(normalized: _NormalizedLightningInputs) -> float:
    # LP-570 对齐 C# fjtzlDanXiang 建弧率：35/66kV=0.8，110=0.85，220=0.918，330=0.95，其余=1
    voltage = normalized.line_voltage_kv or 0
    if voltage in {35, 66}:
        return 0.8
    if voltage == 110:
        return 0.85
    if voltage == 220:
        return 0.918
    if voltage == 330:
        return 0.95
    return 1.0


def _shielding_trip_arc_rate(normalized: _NormalizedLightningInputs) -> float:
    voltage = normalized.line_voltage_kv or 0
    if voltage in {35, 66}:
        return 0.8
    if voltage == 110:
        return 0.85
    if voltage == 220:
        return 0.918
    if voltage == 330:
        return 0.95
    return 1.0


def _trip_span_factor(normalized: _NormalizedLightningInputs) -> float:
    if normalized.shield_wire_height_m is None or normalized.right_shield_x_m is None:
        return 0.0
    return 2.0 * abs(normalized.right_shield_x_m) + 4.0 * normalized.shield_wire_height_m


def _risk_threshold(normalized: _NormalizedLightningInputs | None) -> float | None:
    if normalized is None:
        return None
    voltage = normalized.line_voltage_kv or 0
    if normalized.is_dc:
        if voltage >= 800:
            return _DC_RISK_THRESHOLDS[800]
        if voltage >= 660:
            return _DC_RISK_THRESHOLDS[660]
        if voltage >= 400:
            return _DC_RISK_THRESHOLDS[500]
        return 0.15
    if voltage >= 1000:
        return _AC_RISK_THRESHOLDS[1000]
    if voltage >= 750:
        return _AC_RISK_THRESHOLDS[750]
    if voltage >= 500:
        return _AC_RISK_THRESHOLDS[500]
    if voltage >= 330:
        return _AC_RISK_THRESHOLDS[330]
    if voltage >= 220:
        return _AC_RISK_THRESHOLDS[220]
    if voltage >= 110:
        return _AC_RISK_THRESHOLDS[110]
    if voltage >= 66:
        return _AC_RISK_THRESHOLDS[66]
    if voltage >= 35:
        return _AC_RISK_THRESHOLDS[35]
    return 0.1


def _normalize_insulator_length_m(profile_value: Any, geometry_value: Any) -> float | None:
    raw_value = _first_defined(profile_value, geometry_value)
    value = _as_float(raw_value)
    if value is None or value <= 0:
        return None
    if value > 50:
        return round(value / 1000.0, 6)
    return round(value, 6)


def _normalize_horizontal_coordinate(value: float | None, *, side: str) -> float | None:
    if value is None:
        return None
    if side == "left":
        return value if value < 0 else -abs(value)
    return value if value > 0 else abs(value)


def _coalesce_positive_float(*values: Any) -> float:
    for value in values:
        parsed = _as_float(value)
        if parsed is not None and parsed > 0:
            return parsed
    return 0.0


def _split_semicolon_text(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item for item in text.split("；") if item]


def _coerce_risk_result_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    snapshot = dict(value)
    if "risk_level" not in snapshot or "score" not in snapshot:
        return None
    if "cause_analysis" not in snapshot or "reason_details" not in snapshot or "inputs" not in snapshot:
        return None
    return snapshot


def _build_reason_details(base: Mapping[str, Any], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    voltage_kv = _infer_voltage_kv(base, profile)
    structure_count = _infer_structure_count(base, profile)
    insulator_standard_mm, height_standard_m = _standard_values_for_line(base, profile, voltage_kv, structure_count)

    insulator_length_mm = _normalize_insulator_length_mm(
        _as_float(profile.get("insulator_length_m"))
        or _as_float((profile.get("geometry_layers_json") or {}).get("insulator_length_mm"))
        or _as_float((base.get("circuit_geometry_json") or {}).get("insulator_length_mm"))
    )
    ground_resistance = _as_float(base.get("ground_resistance_ohm"))
    shield_wire_height = _as_float(profile.get("shield_wire_height_m")) or _as_float(
        ((base.get("circuit_geometry_json") or {}).get("lightning_wire") or {}).get("height_m")
    )
    slope_value = _max_abs_float(base.get("slope_1"), base.get("slope_2"))
    protection_angle_deg = _compute_protection_angle_deg(base, profile)

    result = [
        {
            "code": "insulator_length",
            "label": "绝缘子串长度档次",
            "value": insulator_length_mm,
            "standard_value": insulator_standard_mm,
            "grade": _grade_insulator_length(insulator_length_mm, insulator_standard_mm),
            "triggered": False,
        },
        {
            "code": "ground_resistance",
            "label": "接地电阻档次",
            "value": ground_resistance,
            "grade": _grade_ground_resistance(ground_resistance),
            "triggered": False,
        },
        {
            "code": "shield_wire_height",
            "label": "高度档次",
            "value": shield_wire_height,
            "standard_value": height_standard_m,
            "grade": _grade_height_exposure(shield_wire_height, height_standard_m),
            "triggered": False,
        },
        {
            "code": "terrain_slope",
            "label": "地面倾角档次",
            "value": slope_value,
            "grade": _grade_terrain_slope(slope_value),
            "triggered": False,
        },
        {
            "code": "protection_angle",
            "label": "保护角档次",
            "value": protection_angle_deg,
            "grade": _grade_protection_angle(protection_angle_deg),
            "triggered": False,
        },
    ]
    for item in result:
        item["triggered"] = item["grade"] is not None and int(item["grade"]) <= 2
    return result



# --------------------------------------------------------------------------------------
# LP-571：对齐 C# 防雷改造「措施推荐」状态机（lp-knowledge/LP/MyFunction.cs）
#
# C# 侧是「逐档调参 → 每轮调 ATP 引擎重算 → 不达标继续 → 全试完才装避雷器」的迭代闭环：
#   MyCanShu_2_TuiJianCuoShi          —— 普通线路（mTypeCode_Task == 3）
#   MyCanShu_3_TuiJianCuoShi_FeiJianXian —— 非检线（mTypeCode_Task == 302，多一步「调保护角」）
# 本模块把这两套状态机移植到 web 端，取代原「一次性规则生成措施」的简化实现。
# --------------------------------------------------------------------------------------

# C# 110/500kV 用固定毫米增量（其余电压用标准值倍数），见 MyCanShu_2 case 0/1/2/3。
_CSHARP_FIXED_INSULATOR_STEP_MM: dict[int, float] = {
    1: 97.33333333333333,   # 110/500kV 第一档加长量
    2: 194.66666666666666,  # 第二档
    3: 292.0,               # 第三档（1.3 倍位）
}

# C# 状态常量（MyCanShu_2 / MyCanShu_3）
_CSHARP_STATE_INIT = 0
_CSHARP_STATE_S1 = 1
_CSHARP_STATE_S2 = 2
_CSHARP_STATE_S201 = 201
_CSHARP_STATE_S3 = 3
_CSHARP_STATE_S4 = 4      # 普通版：到此判定「需要安装避雷器」
_CSHARP_STATE_S5 = 5
# 非检线版额外状态（MyCanShu_3 case 4/5/6/7）
_CSHARP_STATE_S6 = 6
_CSHARP_STATE_S7 = 7
_CSHARP_STATE_S8 = 8      # 非检线版：到此判定「需要安装避雷器」

# 非检线版把「调到避雷线间距」的中间态存这里（C# mState_TuiJian 5/6/7）
_CSHARP_FEIJIANXIAN_TERMINAL = _CSHARP_STATE_S8


def _csharp_voltage_kv(base: Mapping[str, Any], profile: Mapping[str, Any]) -> int:
    """对齐 C# MyCanShu_2/3 里从塔型串推断电压等级（num3）的写法。"""
    return _infer_voltage_kv(base, profile)


def _csharp_new_insulator_length(
    *,
    voltage_kv: int,
    old_mm: float,
    standard_mm: float,
    step: int,
) -> float:
    """对齐 C# 加长绝缘子串：110/500kV 用固定增量，其余用 1.1/1.2/1.3 倍标准值。

    C# 原文（case 0）：
        110/500 → Math.Round(mOld_JYZCD + 97.33, 2)
        其它    → Math.Round(1.1 * mSTD_JYZ_mm + 0.005, 2)
    case 1 → 1.2 倍（+194.67）；case 2/3 → 1.3 倍（+292）。
    """
    if voltage_kv in (110, 500):
        increment = _CSHARP_FIXED_INSULATOR_STEP_MM.get(step, 97.33333333333333)
        return round(old_mm + increment, 2)
    factor = {1: 1.1, 2: 1.2, 3: 1.3}.get(step, 1.1)
    return round(factor * standard_mm + 0.005, 2)


def _csharp_target_protection_angle(base: Mapping[str, Any], profile: Mapping[str, Any]) -> float:
    """对齐 C# MyCanShu_3 按塔型给保护角目标值（-10 / -18）。

    jiubei/maotou → -10°；ganzi/guxing/shangzi/zhiliu/dc/nz/ky → -18°；其它 → -10°。
    （-5° 分支在 C# case 4 的 mFJ_BaoHuJiao <= 3 时单独走，见调用处。）
    """
    marker = "|".join(
        [
            str(base.get("tower_model") or ""),
            str(base.get("tower_type") or ""),
            str(base.get("tower_code") or ""),
            str(profile.get("structure_kind") or ""),
        ]
    ).lower()
    if any(token in marker for token in ("jiubei", "maotou")):
        return -10.0
    if any(token in marker for token in ("ganzi", "guxing", "shangzi", "zhiliu", "dc", "nz", "ky")):
        return -18.0
    return -10.0


def _csharp_recompute_shield_distance(
    *,
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
    protection_angle_deg: float,
) -> float | None:
    """对齐 C# MyCanShu_3 case 4/5/6：按新保护角重算避雷线中距 mBLZJ。

    C# 公式（以 guxing 为例，取上/中/下三相最大值）：
        num6 = m1ZJ_Xxx - (mBLXGD - m1GD_Xxx + num7) * tan(angle)
        num7 = 耐张 ? mJYZCD/1000 : 0
        mBLZJ_L = mBLZJ_R = max(...)
    web 端几何字段：避雷线高 shield_wire_height_m、各相挂点高 1GD_*、水平位置 1ZJ_*。
    """
    base_geometry = base.get("circuit_geometry_json") or {}
    lightning_wire = dict(base_geometry.get("lightning_wire") or {})
    shield_height = _as_float(profile.get("shield_wire_height_m")) or _as_float(lightning_wire.get("height_m"))
    if shield_height is None:
        return None

    # 耐张塔补串长（num7）：C# 仅耐张加 mJYZCD/1000
    structure_kind = str(profile.get("structure_kind") or base.get("tower_type") or "")
    insulator_mm = _normalize_insulator_length_mm(
        _as_float(profile.get("insulator_length_m"))
        or _as_float((profile.get("geometry_layers_json") or {}).get("insulator_length_mm"))
    )
    num7 = 0.0
    if "耐张" in structure_kind and insulator_mm is not None:
        num7 = insulator_mm / 1000.0

    best: float | None = None
    for circuit_key in ("I", "II", "III", "IV"):
        circuit = base_geometry.get(circuit_key) or {}
        positions = circuit.get("phase_position_m") or {}
        heights = circuit.get("phase_height_m") or {}
        for phase_key in ("upper", "middle", "lower"):
            horizontal = _as_float(positions.get(phase_key))
            height = _as_float(heights.get(phase_key))
            if horizontal is None or height is None:
                continue
            value = horizontal - (shield_height - height + num7) * math.tan(math.radians(protection_angle_deg))
            if best is None or value > best:
                best = value
    if best is None:
        # 无逐相几何时退化为「塔顶相高」单值（web 数据常见形态）
        top_phase_height = _max_phase_height(base, profile)
        if top_phase_height is None:
            return None
        best = 0.0 - (shield_height - top_phase_height + num7) * math.tan(math.radians(protection_angle_deg))
    return round(best, 3)


def _csharp_read_current_params(
    *,
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
    voltage_kv: int,
    structure_count: int,
) -> tuple[float, float, float, float, float]:
    """读取塔当前绝缘子串长/接地电阻/保护角，并给标准值（C# mSTD_JYZ_mm/mSTD_height_m）。"""
    std_jyz_mm, std_height_m = _standard_values_for_line(base, profile, voltage_kv, structure_count)

    current_insulator_mm = _normalize_insulator_length_mm(
        _as_float(profile.get("insulator_length_m"))
        or _as_float((profile.get("geometry_layers_json") or {}).get("insulator_length_mm"))
        or _as_float((base.get("circuit_geometry_json") or {}).get("insulator_length_mm"))
    )
    if current_insulator_mm is None:
        current_insulator_mm = std_jyz_mm
    current_ground_ohm = _as_float(base.get("ground_resistance_ohm"))
    if current_ground_ohm is None:
        current_ground_ohm = 20.0
    current_protection_angle = _as_float(_compute_protection_angle_deg(base, profile))
    if current_protection_angle is None:
        current_protection_angle = 5.0
    return current_insulator_mm, current_ground_ohm, current_protection_angle, std_jyz_mm, std_height_m


def _csharp_grade(
    *,
    insulator_mm: float,
    ground_ohm: float,
    protection_angle_deg: float,
    std_jyz_mm: float,
    std_height_m: float,
) -> dict[str, int | None]:
    """对齐 C# MyCanShu_1_HuaFenDangJi 的 5 档分级（web 端仅用到 绝缘子/接地/保护角）。"""
    return {
        "insulator_grade": _grade_insulator_length(insulator_mm, std_jyz_mm),
        "ground_grade": _grade_ground_resistance(ground_ohm),
        "protection_grade": _grade_protection_angle(protection_angle_deg),
    }


def _csharp_apply_params(
    *,
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
    insulator_mm: float,
    ground_ohm: float,
    protection_angle_deg: float | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """把状态机算出的新参数应用回 base/profile（供重算 expected 用）。"""
    simulated_base = dict(base)
    simulated_profile = dict(profile)

    # 绝缘子串长：写回 geometry_layers.insulator_length_mm（C# mJYZCD 语义为 mm）
    geometry_layers = dict(simulated_profile.get("geometry_layers_json") or {})
    geometry_layers["insulator_length_mm"] = round(insulator_mm, 2)
    simulated_profile["geometry_layers_json"] = geometry_layers
    if _as_float(simulated_profile.get("insulator_length_m")) is not None:
        simulated_profile["insulator_length_m"] = round(insulator_mm / 1000.0, 4)

    # 接地电阻
    simulated_base["ground_resistance_ohm"] = round(ground_ohm, 2)

    # 保护角 → 重算避雷线水平位置（对齐 C# case 4/5/6 调 mBLZJ）
    if protection_angle_deg is not None:
        distance = _csharp_recompute_shield_distance(
            base=simulated_base,
            profile=simulated_profile,
            protection_angle_deg=protection_angle_deg,
        )
        if distance is not None:
            base_geometry = dict(simulated_base.get("circuit_geometry_json") or {})
            lightning_wire = dict(base_geometry.get("lightning_wire") or {})
            lightning_wire["left_mid_distance_m"] = distance
            lightning_wire["right_mid_distance_m"] = distance
            base_geometry["lightning_wire"] = lightning_wire
            simulated_base["circuit_geometry_json"] = base_geometry

    return simulated_base, simulated_profile


def _csharp_mitigation_machine(
    *,
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
    current: Mapping[str, Any],
    non_construction: bool,
    recompute_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """对齐 C# 的「措施推荐」状态机（MyCanShu_2 普通版 / MyCanShu_3 非检线版）。

    每次调用对单塔走完整状态机：逐轮 分级 → 状态机推进一步（改参数）→
    用改了参数后的新塔数据重算（grade_snapshot_payload，对应 C# 每轮调
    AllCall_CS(101) 重算跳闸率）→ 直到状态到终态或不再有参数改动。

    与 C# 的差异仅一处：C# 每轮重算走 ATP 引擎（AllCall_CS），web 端用
    规程法（grade_snapshot_payload）做重算验证——这是受 web 端无 ATP
    内嵌引擎限制的环境差异，状态机参数推进逻辑逐行对齐 C#。
    """
    voltage_kv = _csharp_voltage_kv(base, profile)
    structure_count = _infer_structure_count(base, profile)
    current_insulator_mm, current_ground_ohm, current_protection_angle, std_jyz_mm, std_height_m = (
        _csharp_read_current_params(
            base=base,
            profile=profile,
            voltage_kv=voltage_kv,
            structure_count=structure_count,
        )
    )

    # 绕击/反击跳闸率比（C# num4 = mRJ_TZL / mFJ_TZL）
    fj_tzl = _as_float(current.get("counterstrike_trip_rate"))
    rj_tzl = _as_float(current.get("shielding_trip_rate"))
    if fj_tzl is not None and fj_tzl != 0.0 and rj_tzl is not None:
        num4 = rj_tzl / fj_tzl
    else:
        num4 = -1.0

    state = _CSHARP_STATE_INIT
    turns = 0
    reached_arrester = False
    new_insulator_mm = current_insulator_mm
    new_ground_ohm = current_ground_ohm
    new_protection_angle = current_protection_angle
    # 非检线 Step1 记忆（C# mNew_JYZCD_Step1 / mNew_JDDZ_Step1）
    step1_insulator: float | None = None
    step1_ground: float | None = None

    max_turns = _CSHARP_STATE_S8 + 2

    while turns < max_turns:
        turns += 1
        grades = _csharp_grade(
            insulator_mm=new_insulator_mm,
            ground_ohm=new_ground_ohm,
            protection_angle_deg=new_protection_angle,
            std_jyz_mm=std_jyz_mm,
            std_height_m=std_height_m,
        )
        grade_jyz = grades["insulator_grade"]
        grade_jddz = grades["ground_grade"]
        grade_bjh = grades["protection_grade"]

        if non_construction:
            result = _csharp_step_feijianxian(
                state=state,
                grade_jyz=grade_jyz,
                grade_jddz=grade_jddz,
                grade_bjh=grade_bjh,
                num4=num4,
                voltage_kv=voltage_kv,
                std_jyz_mm=std_jyz_mm,
                old_insulator_mm=current_insulator_mm,
                old_ground_ohm=current_ground_ohm,
                old_protection_angle=current_protection_angle,
                step1_insulator=step1_insulator,
                step1_ground=step1_ground,
                base=base,
                profile=profile,
            )
        else:
            result = _csharp_step_normal(
                state=state,
                grade_jyz=grade_jyz,
                grade_jddz=grade_jddz,
                num4=num4,
                voltage_kv=voltage_kv,
                std_jyz_mm=std_jyz_mm,
                old_insulator_mm=current_insulator_mm,
                old_ground_ohm=current_ground_ohm,
            )
        changed = result["changed"]
        state = result["next_state"]
        if result.get("new_insulator_mm") is not None:
            new_insulator_mm = result["new_insulator_mm"]
        if result.get("new_ground_ohm") is not None:
            new_ground_ohm = result["new_ground_ohm"]
        if result.get("new_protection_angle") is not None:
            new_protection_angle = result["new_protection_angle"]
        if result.get("step1_insulator") is not None:
            step1_insulator = result["step1_insulator"]
        if result.get("step1_ground") is not None:
            step1_ground = result["step1_ground"]

        # C# 终止条件：状态到终态（普通 s4→s5 / 非检线 s7→s8）。
        # ⚠️ 非检线版 state 5/6/7 是「调保护角」的中间态，只有 s8 才是终态；
        #    普通版只有 s5 是终态。两者共用数值 5，必须按版本区分。
        terminal_state = _CSHARP_FEIJIANXIAN_TERMINAL if non_construction else _CSHARP_STATE_S5
        if state == terminal_state:
            reached_arrester = True
            break
        if changed == 0:
            break

        # ── 用新参数重算（对齐 C# 每轮 AllCall_CS(101) 重算跳闸率/风险）──────
        simulated_base, simulated_profile = _csharp_apply_params(
            base=base,
            profile=profile,
            insulator_mm=new_insulator_mm,
            ground_ohm=new_ground_ohm,
            protection_angle_deg=new_protection_angle if non_construction else None,
        )
        if recompute_fn is not None:
            # task 层注入的 ATP(wine) 重算：对齐 C# 的 AllCall_CS(101) 引擎重算
            recomputed = recompute_fn(simulated_base, simulated_profile)
        else:
            # 离线/单塔调试场景：规程法重算（task 层必须注入 ATP，见 service 调用处）
            recomputed = grade_snapshot_payload(
                {"base_tower_json": simulated_base, "profile_json": simulated_profile}
            )
        # 改造后风险已降到 ≤2（不再高风险）→ 停止迭代（C# 语义：该塔不再进下一轮调参）
        recomputed_grade = _as_int(recomputed.get("risk_grade"))
        if recomputed_grade is not None and recomputed_grade <= 2:
            break
        fj_tzl = _as_float(recomputed.get("counterstrike_trip_rate")) or fj_tzl
        rj_tzl = _as_float(recomputed.get("shielding_trip_rate")) or rj_tzl
        if fj_tzl is not None and fj_tzl != 0.0 and rj_tzl is not None:
            num4 = rj_tzl / fj_tzl

    # ── 汇总动作清单（与 C# 报告改造措施一致）────────────────────────────
    actions: list[dict[str, Any]] = []
    if new_insulator_mm > current_insulator_mm + 1e-9:
        actions.append(
            {
                "code": "insulator_upgrade",
                "label": "提高绝缘子串长度",
                "summary": f"将绝缘子串长度提高至约 {round(new_insulator_mm, 2)} mm",
                "current_value": round(current_insulator_mm, 2),
                "target_value": round(new_insulator_mm, 2),
                "unit": "mm",
            }
        )
    if new_ground_ohm < current_ground_ohm - 1e-9:
        actions.append(
            {
                "code": "grounding_upgrade",
                "label": "降低接地电阻",
                "summary": f"将接地电阻优化至 {round(new_ground_ohm, 2)} Ω 以内",
                "current_value": round(current_ground_ohm, 2),
                "target_value": round(new_ground_ohm, 2),
                "unit": "ohm",
            }
        )
    if non_construction and abs(new_protection_angle - current_protection_angle) > 1e-9:
        actions.append(
            {
                "code": "shielding_geometry",
                "label": "优化保护角",
                "summary": f"按非建线口径将保护角调整至约 {round(new_protection_angle, 2)}°",
                "current_value": round(current_protection_angle, 2),
                "target_value": round(new_protection_angle, 2),
                "unit": "deg",
            }
        )
    if reached_arrester:
        phases = _missing_arrester_phases(profile) or ["A", "B", "C"]
        actions.append(
            {
                "code": "arrester_install",
                "label": "补装避雷器",
                "summary": f"建议在 {','.join(phases)} 相补装或复核避雷器",
                "phases": phases,
            }
        )

    simulated_base, simulated_profile = _csharp_apply_params(
        base=base,
        profile=profile,
        insulator_mm=new_insulator_mm,
        ground_ohm=new_ground_ohm,
        protection_angle_deg=new_protection_angle if non_construction else None,
    )

    return {
        "actions": actions,
        "simulated_base": simulated_base,
        "simulated_profile": simulated_profile,
        "reached_arrester": reached_arrester,
        "expected_grade": None,
        "final_state": state,
        "turns": turns,
        "new_insulator_mm": round(new_insulator_mm, 2),
        "new_ground_ohm": round(new_ground_ohm, 2),
        "new_protection_angle_deg": round(new_protection_angle, 2),
    }


def _csharp_step_normal(
    *,
    state: int,
    grade_jyz: int | None,
    grade_jddz: int | None,
    num4: float,
    voltage_kv: int,
    std_jyz_mm: float,
    old_insulator_mm: float,
    old_ground_ohm: float,
) -> dict[str, Any]:
    """普通版（MyCanShu_2）单步状态机。

    C# 原文（MyFunction.cs MyCanShu_2_TuiJianCuoShi switch）逐 case 对齐。
    返回 {changed, next_state, new_insulator_mm?, new_ground_ohm?}。
    """
    changed = 0
    next_state = state
    new_insulator_mm: float | None = None
    new_ground_ohm: float | None = None

    if state == _CSHARP_STATE_INIT:
        if (grade_jyz is not None and grade_jyz <= 2) or (grade_jddz is not None and grade_jddz <= 2):
            if grade_jyz is not None and grade_jyz <= 2:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=1
                )
            if grade_jddz is not None and grade_jddz <= 2:
                changed += 1
                new_ground_ohm = 14.0
            next_state = _CSHARP_STATE_S1
        elif grade_jyz is not None and grade_jddz is not None and grade_jyz >= 3 and grade_jddz >= 3:
            if grade_jyz <= 4:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
                )
            if grade_jddz <= 4:
                changed += 1
                new_ground_ohm = 3.0
            next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1  # C# num==0 → num++ 且 mCallDLL=false
    elif state == _CSHARP_STATE_S1:
        if num4 > 1.2:
            if grade_jyz is not None and grade_jyz <= 3:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=2
                )
            next_state = _CSHARP_STATE_S2
        elif num4 <= 1.2:
            if grade_jyz is not None and grade_jyz <= 3:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=2
                )
            if grade_jddz is not None and grade_jddz <= 3:
                changed += 1
                new_ground_ohm = 5.0
            next_state = _CSHARP_STATE_S3
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S2:
        if grade_jyz is not None and grade_jyz <= 4:
            changed += 1
            new_insulator_mm = _csharp_new_insulator_length(
                voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
            )
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S201:
        if grade_jddz is not None and grade_jddz <= 4:
            changed += 1
            new_ground_ohm = 3.0
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S3:
        if grade_jyz is not None and grade_jyz <= 4:
            changed += 1
            new_insulator_mm = _csharp_new_insulator_length(
                voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
            )
        if grade_jddz is not None and grade_jddz <= 4:
            changed += 1
            new_ground_ohm = 3.0
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S4:
        # C# case 4：直接判装避雷器（mBLQ_need=true），由外层 break
        next_state = _CSHARP_STATE_S5
        changed = 0
    return {
        "changed": changed,
        "next_state": next_state,
        "new_insulator_mm": new_insulator_mm,
        "new_ground_ohm": new_ground_ohm,
    }


def _csharp_step_feijianxian(
    *,
    state: int,
    grade_jyz: int | None,
    grade_jddz: int | None,
    grade_bjh: int | None,
    num4: float,
    voltage_kv: int,
    std_jyz_mm: float,
    old_insulator_mm: float,
    old_ground_ohm: float,
    old_protection_angle: float,
    step1_insulator: float | None,
    step1_ground: float | None,
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """非检线版（MyCanShu_3）单步状态机。

    C# 原文（MyFunction.cs MyCanShu_3_TuiJianCuoShi_FeiJianXian switch）逐 case 对齐。
    相比普通版多「调保护角 + 重算避雷线间距」的 case 4/5/6/7。
    """
    changed = 0
    next_state = state
    new_insulator_mm: float | None = None
    new_ground_ohm: float | None = None
    new_protection_angle: float | None = None
    out_step1_insulator: float | None = None
    out_step1_ground: float | None = None

    if state == _CSHARP_STATE_INIT:
        if (grade_jyz is not None and grade_jyz <= 2) or (grade_jddz is not None and grade_jddz <= 2):
            if grade_jyz is not None and grade_jyz <= 2:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=1
                )
            if grade_jddz is not None and grade_jddz <= 2:
                changed += 1
                new_ground_ohm = 14.0
            next_state = _CSHARP_STATE_S1
        elif grade_jyz is not None and grade_jddz is not None and grade_jyz >= 3 and grade_jddz >= 3:
            if grade_jyz <= 4:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
                )
            if grade_jddz <= 4:
                changed += 1
                new_ground_ohm = 3.0
            next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S1:
        if num4 > 1.2:
            if grade_jyz is not None and grade_jyz <= 3:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=2
                )
            next_state = _CSHARP_STATE_S2
        elif num4 <= 1.2:
            if grade_jyz is not None and grade_jyz <= 3:
                changed += 1
                new_insulator_mm = _csharp_new_insulator_length(
                    voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=2
                )
            if grade_jddz is not None and grade_jddz <= 3:
                changed += 1
                new_ground_ohm = 5.0
            next_state = _CSHARP_STATE_S3
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S2:
        if grade_jyz is not None and grade_jyz <= 4:
            changed += 1
            new_insulator_mm = _csharp_new_insulator_length(
                voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
            )
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S201:
        if grade_jddz is not None and grade_jddz <= 4:
            changed += 1
            new_ground_ohm = 3.0
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S3:
        if grade_jyz is not None and grade_jyz <= 4:
            changed += 1
            new_insulator_mm = _csharp_new_insulator_length(
                voltage_kv=voltage_kv, old_mm=old_insulator_mm, standard_mm=std_jyz_mm, step=3
            )
        if grade_jddz is not None and grade_jddz <= 4:
            changed += 1
            new_ground_ohm = 3.0
        next_state = _CSHARP_STATE_S4
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S4:
        # C# case 4：记录 Step1，然后按保护角档次调保护角
        out_step1_insulator = step1_insulator if step1_insulator is not None else old_insulator_mm
        out_step1_ground = step1_ground if step1_ground is not None else old_ground_ohm
        if grade_bjh is not None and grade_bjh >= 5:
            new_insulator_mm = old_insulator_mm
            new_ground_ohm = old_ground_ohm
            changed += 1
            new_protection_angle = _csharp_target_protection_angle(base, profile)
            next_state = _CSHARP_STATE_S7
        elif grade_bjh == 4:
            new_insulator_mm = old_insulator_mm
            new_ground_ohm = old_ground_ohm
            changed += 1
            new_protection_angle = _csharp_target_protection_angle(base, profile)
            next_state = _CSHARP_STATE_S6
        elif grade_bjh is not None and grade_bjh <= 3:
            new_insulator_mm = old_insulator_mm
            new_ground_ohm = old_ground_ohm
            changed += 1
            new_protection_angle = -5.0
            next_state = _CSHARP_STATE_S5
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S5:
        # C# case 5：保护角仍不够 → 再调保护角
        if grade_bjh is not None and grade_bjh >= 4:
            new_insulator_mm = old_insulator_mm
            new_ground_ohm = old_ground_ohm
            changed += 1
            new_protection_angle = _csharp_target_protection_angle(base, profile)
        next_state = _CSHARP_STATE_S6
        if changed == 0:
            changed += 1
    elif state == _CSHARP_STATE_S6:
        # C# case 6：恢复 Step1 的绝缘子/接地值，重算避雷线间距
        changed += 1
        new_insulator_mm = step1_insulator if step1_insulator is not None else old_insulator_mm
        new_ground_ohm = step1_ground if step1_ground is not None else old_ground_ohm
        next_state = _CSHARP_STATE_S7
    elif state == _CSHARP_STATE_S7:
        # C# case 7：直接判装避雷器（mBLQ_need=true），由外层 break
        next_state = _CSHARP_STATE_S8
        changed = 0

    return {
        "changed": changed,
        "next_state": next_state,
        "new_insulator_mm": new_insulator_mm,
        "new_ground_ohm": new_ground_ohm,
        "new_protection_angle": new_protection_angle,
        "step1_insulator": out_step1_insulator,
        "step1_ground": out_step1_ground,
    }


def _standard_values_for_line(
    base: Mapping[str, Any],
    profile: Mapping[str, Any],
    voltage_kv: int,
    structure_count: int,
) -> tuple[float, float]:
    line_kind = _infer_line_kind(base, profile)
    if line_kind == "dc":
        insulator_length_mm, height_m = _DC_STANDARD_BY_VOLTAGE.get(voltage_kv, _DEFAULT_DC_STANDARD)
        return insulator_length_mm, height_m

    insulator_length_mm, structure_heights = _AC_STANDARD_BY_VOLTAGE.get(voltage_kv, _DEFAULT_AC_STANDARD)
    return insulator_length_mm, structure_heights.get(structure_count, structure_heights[max(structure_heights)])


def _infer_line_kind(base: Mapping[str, Any], profile: Mapping[str, Any]) -> str:
    geometry_layers = profile.get("geometry_layers_json") if isinstance(profile.get("geometry_layers_json"), Mapping) else {}
    return infer_topology_line_kind(
        tower_model=base.get("tower_model"),
        tower_type=base.get("tower_type"),
        structure_kind=profile.get("structure_kind"),
        geometry_topology=geometry_layers.get("topology_kind") if isinstance(geometry_layers, Mapping) else None,
    )


def _infer_voltage_kv(base: Mapping[str, Any], profile: Mapping[str, Any]) -> int:
    raw_extra = base.get("raw_extra_json") or {}
    for candidate in (
        raw_extra.get("voltage_kv"),
        base.get("line_voltage_kv"),
        profile.get("voltage_kv"),
    ):
        parsed = _as_int(candidate)
        if parsed is not None and parsed > 0:
            return parsed

    marker = "|".join(
        [
            str(base.get("tower_model") or ""),
            str(base.get("tower_type") or ""),
            str(profile.get("structure_kind") or ""),
        ]
    )
    for voltage in (1000, 800, 750, 500, 330, 220, 110, 66, 35):
        if str(voltage) in marker:
            return voltage
    return 110


def _infer_structure_count(base: Mapping[str, Any], profile: Mapping[str, Any]) -> int:
    geometry_layers = profile.get("geometry_layers_json") if isinstance(profile.get("geometry_layers_json"), Mapping) else {}
    return infer_topology_structure_count(
        tower_model=base.get("tower_model"),
        tower_type=base.get("tower_type"),
        structure_kind=profile.get("structure_kind"),
        geometry_topology=geometry_layers.get("topology_kind") if isinstance(geometry_layers, Mapping) else None,
    )


def _grade_insulator_length(value_mm: float | None, standard_mm: float) -> int | None:
    if value_mm is None:
        return None
    if value_mm <= standard_mm:
        return 1
    if value_mm <= 1.1 * standard_mm:
        return 2
    if value_mm <= 1.2 * standard_mm:
        return 3
    if value_mm <= 1.3 * standard_mm:
        return 4
    return 5


def _grade_ground_resistance(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 20:
        return 1
    if value > 15:
        return 2
    if value > 10:
        return 3
    if value > 5:
        return 4
    return 5


def _grade_height_exposure(value: float | None, standard_m: float) -> int | None:
    if value is None:
        return None
    if value > 1.3 * standard_m:
        return 1
    if value > 1.2 * standard_m:
        return 2
    if value > 1.1 * standard_m:
        return 3
    if value > standard_m:
        return 4
    return 5


def _grade_terrain_slope(value: float | None) -> int | None:
    if value is None:
        return None
    if value > 15:
        return 1
    if value > 10:
        return 2
    if value > 5:
        return 3
    if value > 0:
        return 4
    return 5


def _grade_protection_angle(value: float | None) -> int | None:
    # 对齐 C# MyFunction.cs MyCanShu_1_HuaFenDangJi 保护角分档：
    # >5=1档(最差) >0=2 >-5=3 >-10=4 <=-10=5档(最好)。
    # 原 web 实现用 >25/>20/>15/>10，与 C# 完全不同，已修正。
    if value is None:
        return None
    if value > 5.0:
        return 1
    if value > 0.0:
        return 2
    if value > -5.0:
        return 3
    if value > -10.0:
        return 4
    return 5


def _compute_protection_angle_deg(base: Mapping[str, Any], profile: Mapping[str, Any]) -> float | None:
    base_geometry = base.get("circuit_geometry_json") or {}
    lightning_wire = dict(base_geometry.get("lightning_wire") or {})
    horizontal = max(
        abs(_as_float(lightning_wire.get("left_mid_distance_m")) or 0.0),
        abs(_as_float(lightning_wire.get("right_mid_distance_m")) or 0.0),
    )
    shield_wire_height = _as_float(profile.get("shield_wire_height_m")) or _as_float(lightning_wire.get("height_m"))
    top_phase_height = _max_phase_height(base, profile)
    if horizontal <= 0 or shield_wire_height is None or top_phase_height is None:
        return None
    vertical = max(shield_wire_height - top_phase_height, 0.5)
    return round(math.degrees(math.atan(horizontal / vertical)), 2)


def _max_phase_height(base: Mapping[str, Any], profile: Mapping[str, Any]) -> float | None:
    base_geometry = base.get("circuit_geometry_json") or {}
    phase_heights: list[float] = []
    for circuit_key in ("I", "II", "III", "IV"):
        circuit = base_geometry.get(circuit_key) or {}
        heights = circuit.get("phase_height_m") or {}
        for key in ("upper", "middle", "lower"):
            value = _as_float(heights.get(key))
            if value is not None:
                phase_heights.append(value)
    if not phase_heights:
        geometry_layers = profile.get("geometry_layers_json") or {}
        for circuit_key in ("I", "II", "III", "IV"):
            circuit = geometry_layers.get(circuit_key) or {}
            heights = circuit.get("phase_height_m") or {}
            for key in ("upper", "middle", "lower"):
                value = _as_float(heights.get(key))
                if value is not None:
                    phase_heights.append(value)
    return max(phase_heights) if phase_heights else None


def _missing_arrester_phases(profile: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for phase in ("A", "B", "C"):
        value = str(profile.get(f"arrester_{phase.lower()}") or "").strip()
        if not value or value in _ARRESTER_NEGATIVE_VALUES:
            result.append(phase)
    return result


def _target_protection_angle_deg(base: Mapping[str, Any], profile: Mapping[str, Any]) -> float:
    marker = "|".join(
        [
            str(base.get("tower_model") or ""),
            str(base.get("tower_type") or ""),
            str(profile.get("structure_kind") or ""),
        ]
    ).lower()
    if any(token in marker for token in ("jiubei", "maotou")):
        return -10.0
    if any(token in marker for token in ("ganzi", "guxing", "shangzi", "zhiliu", "dc", "nz", "ky")):
        return -18.0
    return -10.0


def _normalize_insulator_length_mm(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 1000.0, 2) if value <= 20 else round(value, 2)


def _normalize_choice(value: Any, *, aliases: Mapping[str, str], default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    return aliases.get(text, aliases.get(text.lower(), default))


def _normalize_positive_number(value: Any, *, default: float) -> float:
    parsed = _as_float(value)
    if parsed is None or parsed <= 0:
        return round(default, 4)
    return round(parsed, 4)


def _build_scan_values(start: float, end: float, step: float) -> list[float]:
    minimum = min(start, end)
    maximum = max(start, end)
    normalized_step = max(step, 0.01)
    values: list[float] = []
    current = minimum
    while current <= maximum + 1e-9 and len(values) < _MAX_SCAN_AXIS_POINTS:
        values.append(round(current, 4))
        current += normalized_step
    if values and values[-1] < round(maximum, 4):
        values[-1] = round(maximum, 4)
    if not values:
        values.append(round(minimum, 4))
    return list(dict.fromkeys(values))


def _scaled_inverse(value: float | None, factor: float, *, digits: int) -> float | None:
    if value is None:
        return None
    if math.isclose(factor, 0.0, abs_tol=1e-9):
        return round(value, digits)
    return round(max(value / factor, 0.0), digits)


def _scaled_forward(value: float | None, factor: float, *, digits: int) -> float | None:
    if value is None:
        return None
    return round(max(value * factor, 0.0), digits)


def _clamp(value: float, *, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def _merge_semicolon_text(existing: Any, addition: Any) -> str:
    values = _split_semicolon_text(existing)
    values.extend(_split_semicolon_text(addition))
    return "；".join(dict.fromkeys(item for item in values if item))


def _grade_head_time(value: float) -> int:
    if value <= 2.0:
        return 1
    if value <= 2.3:
        return 2
    if value <= 2.6:
        return 3
    if value <= 3.0:
        return 4
    return 5


def _grade_tail_time(value: float) -> int:
    if value <= 30:
        return 1
    if value <= 40:
        return 2
    if value <= 50:
        return 3
    if value <= 60:
        return 4
    return 5


def _waveform_label(value: str) -> str:
    return {
        "heidler": "Heidler",
        "double_slope": "双斜角",
        "double_exponential": "双指数",
    }.get(value, value)


def _flashover_method_label(value: str) -> str:
    return {
        "guideline": "规程法",
        "intersection": "相交法",
        "leader_development": "先导发展法",
    }.get(value, value)


def _phase_count_label(value: int) -> str:
    return {
        1: "单相",
        2: "双相",
        3: "三相",
        4: "四相",
        5: "五相",
        6: "六相",
    }.get(value, f"{value}相")


def _risk_order(value: Any) -> int:
    normalized = _normalize_risk_level(value)
    if normalized == "high":
        return 3
    if normalized == "medium":
        return 2
    return 1


def _risk_level_label(value: Any) -> str:
    normalized = _normalize_risk_level(value)
    if normalized == "high":
        return "高"
    if normalized == "medium":
        return "中"
    return "低"


def _max_abs_float(*values: Any) -> float | None:
    parsed = [abs(number) for number in (_as_float(value) for value in values) if number is not None]
    return max(parsed) if parsed else None


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _as_geometry_float(value: Any) -> float | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    if math.isclose(parsed, -1.0, abs_tol=1e-9):
        return None
    return parsed


def _is_dc_line(*, line_name: str, tower_model: str) -> bool:
    tower_model_lower = tower_model.lower()
    return (
        "直流" in line_name
        or tower_model_lower.startswith("dc")
        or "zhiliu" in tower_model_lower
        or "vzhiliu" in tower_model_lower
    )


def _is_gentle_slope(normalized: _NormalizedLightningInputs) -> bool:
    return abs(normalized.slope_1_deg) < 10.0 and abs(normalized.slope_2_deg) < 10.0


def _rounded_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 6)
