# -*- coding: utf-8 -*-
"""故障分析详情页「计算过程」视图数据生成（view_model）。

把 result_json.diagnosis 转成前端可声明式渲染的结构，前端不再依赖 diagnosis
内部字段路径。LP 详情页统一走此 schema。
"""
from __future__ import annotations

from typing import Any, Mapping


def _view_safe(obj: Mapping[str, Any], key: str, default: Any = "-") -> Any:
    value = obj.get(key) if isinstance(obj, Mapping) else None
    if value is None or value == "":
        return default
    return value


def _view_has(obj: Mapping[str, Any], key: str) -> bool:
    if not isinstance(obj, Mapping):
        return False
    value = obj.get(key)
    return value is not None and value != ""


def _view_percent(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{num * 100:.1f}%"


def _view_status(obj: Mapping[str, Any], default: str | None, mapping: dict[str, str]) -> str | None:
    if not isinstance(obj, Mapping):
        return None
    raw = obj.get("status")
    if raw is None or raw == "":
        return default
    return mapping.get(str(raw), str(raw))


def _view_evidence(obj: Mapping[str, Any], key: str = "evidence") -> list[str]:
    value = obj.get(key) if isinstance(obj, Mapping) else None
    if not isinstance(value, list) or not value:
        return []
    return [str(item) for item in value if str(item).strip()]


def build_view_model(diag: Mapping[str, Any]) -> dict[str, Any]:
    """生成详情页「计算过程」步骤数据（声明式 schema）。

    返回: {"steps": [{key,title,header,empty,available,fields:[...]}]}
    fields 元素: {"label", "kind": "text|tag|bullets|kv", "value"?,
                  "options"?: {文本: 颜色} 供 tag, "items"?: list/bullets/kv}
    """
    sf = _view_safe
    steps: list[dict[str, Any]] = []
    inputs = diag.get("inputs", {}) if isinstance(diag, Mapping) else {}
    fault = inputs.get("fault_record", {}) if isinstance(inputs, Mapping) else {}

    # ---- 步骤1 接地判断 ----
    ground = diag.get("ground_fault_decision", {}) if isinstance(diag, Mapping) else {}
    ground_fields: list[dict[str, Any]] = [
        {"label": "最大零序电流", "kind": "text", "value": sf(fault, "zero_sequence_current", "未提取")},
        {"label": "故障相编码", "kind": "text", "value": sf(fault, "fault_phase", "未提供")},
    ]
    if _view_has(ground, "fault_kind"):
        ground_fields.append({"label": "故障类型", "kind": "tag", "value": sf(ground, "fault_kind")})
    if _view_has(ground, "confidence"):
        ground_fields.append({"label": "判别置信度", "kind": "text", "value": _view_percent(ground.get("confidence"))})
    ground_status = _view_status(ground, None, {"decided": "已判定", "uncertain": "不确定"})
    if ground_status is not None:
        ground_fields.append({"label": "判别状态", "kind": "text", "value": ground_status})
    evidence = _view_evidence(ground)
    if evidence:
        ground_fields.append({"label": "判定依据", "kind": "bullets", "items": evidence})
    steps.append({
        "key": "ground", "title": "接地判断", "header": "步骤1：接地故障判断",
        "empty": "该记录未包含接地故障判断中间数据。",
        "available": bool(ground_fields), "fields": ground_fields,
    })

    # ---- 步骤2 过渡电阻 ----
    resistance = diag.get("transition_resistance", {}) if isinstance(diag, Mapping) else {}
    resistance_fields: list[dict[str, Any]] = []
    if _view_has(resistance, "zm_ohm"):
        resistance_fields.append({"label": "零序阻抗 Zm", "kind": "text", "value": sf(resistance, "zm_ohm")})
    if _view_has(resistance, "transition_resistance_ohm"):
        resistance_fields.append({
            "label": "过渡电阻", "kind": "text", "value": f"{resistance.get('transition_resistance_ohm')} Ω",
        })
    if _view_has(resistance, "category"):
        resistance_fields.append({
            "label": "分级", "kind": "tag", "value": sf(resistance, "category"),
            "options": {
                "金属性接地故障": "green", "低阻接地": "green",
                "中阻接地": "orange", "高阻接地": "red",
            },
        })
    if _view_has(resistance, "category_report_text"):
        resistance_fields.append({
            "label": "分类说明", "kind": "text", "value": sf(resistance, "category_report_text"),
        })
    if _view_has(resistance, "formula_rf"):
        resistance_fields.append({"label": "计算公式", "kind": "text", "value": sf(resistance, "formula_rf")})
    resistance_evidence = _view_evidence(resistance) or _view_evidence(resistance, "warnings")
    if resistance_evidence:
        resistance_fields.append({"label": "计算依据", "kind": "bullets", "items": resistance_evidence})
    steps.append({
        "key": "resistance", "title": "过渡电阻", "header": "步骤2：过渡电阻计算",
        "empty": "该记录未包含过渡电阻计算中间数据。",
        "available": bool(resistance_fields), "fields": resistance_fields,
    })

    # ---- 步骤3 定位融合 ----
    location = diag.get("fault_location", {}) if isinstance(diag, Mapping) else {}
    location_fields: list[dict[str, Any]] = []
    if _view_has(location, "result_text"):
        location_fields.append({"label": "融合结果", "kind": "text", "value": sf(location, "result_text")})
    location_status = _view_status(location, None, {"located": "已定位", "needs_review": "需复核", "unavailable": "无法定位"})
    if location_status is not None:
        location_fields.append({"label": "状态", "kind": "text", "value": location_status})
    if _view_has(location, "confidence"):
        location_fields.append({"label": "融合置信度", "kind": "text", "value": _view_percent(location.get("confidence"))})
    sources = location.get("sources") if isinstance(location.get("sources"), list) else []
    active_sources = [
        item for item in sources
        if isinstance(item, dict) and item.get("available") and (item.get("label") or item.get("tower"))
    ]
    if active_sources:
        location_fields.append({
            "label": "数据源", "kind": "kv",
            "items": [{"key": sf(item, "label"), "value": sf(item, "tower")} for item in active_sources],
        })
    location_evidence = _view_evidence(location) or _view_evidence(location, "warnings")
    if location_evidence:
        location_fields.append({"label": "融合逻辑", "kind": "bullets", "items": location_evidence})
    steps.append({
        "key": "location", "title": "定位融合", "header": "步骤3：综合定位融合",
        "empty": "该记录未包含综合定位中间数据。",
        "available": bool(location_fields), "fields": location_fields,
    })

    # ---- 步骤4 台账匹配 ----
    ledger = inputs.get("line_ledger", {}) if isinstance(inputs, Mapping) else {}
    ledger_record = ledger.get("record", {}) if isinstance(ledger.get("record"), Mapping) else {}
    ledger_fields: list[dict[str, Any]] = []
    if _view_has(ledger, "matched"):
        ledger_fields.append({
            "label": "匹配结果", "kind": "tag",
            "value": "已匹配" if ledger.get("matched") else "未匹配",
            "options": {"已匹配": "green", "未匹配": "red"},
        })
    if _view_has(ledger, "requested_line_name"):
        ledger_fields.append({"label": "匹配线路", "kind": "text", "value": sf(ledger, "requested_line_name")})
    if _view_has(ledger, "query_tower"):
        ledger_fields.append({"label": "查询杆塔", "kind": "text", "value": sf(ledger, "query_tower")})
    if _view_has(ledger_record, "tower_no"):
        ledger_fields.append({"label": "匹配杆塔", "kind": "text", "value": sf(ledger_record, "tower_no")})
    if _view_has(ledger_record, "backflashover_withstand_ka"):
        ledger_fields.append({
            "label": "耐雷水平（反击）", "kind": "text", "value": sf(ledger_record, "backflashover_withstand_ka"),
        })
    if _view_has(ledger_record, "shielding_failure_withstand_ka"):
        ledger_fields.append({
            "label": "耐雷水平（绕击）", "kind": "text", "value": sf(ledger_record, "shielding_failure_withstand_ka"),
        })
    ledger_note = _view_safe(ledger, "diagnostic", "") or _view_safe(ledger, "reason", "")
    if ledger_note:
        ledger_fields.append({"label": "匹配说明", "kind": "text", "value": ledger_note})
    steps.append({
        "key": "ledger", "title": "台账匹配", "header": "步骤4：线路台账匹配",
        "empty": "该记录未包含台账匹配中间数据。",
        "available": bool(ledger_fields), "fields": ledger_fields,
    })

    # ---- 步骤5 雷击原因分析 ----
    lightning = diag.get("lightning_cause_analysis", {}) if isinstance(diag, Mapping) else {}
    lightning_inputs = inputs.get("lightning", {}) if isinstance(inputs, Mapping) else {}
    lightning_fields: list[dict[str, Any]] = []
    lightning_current = _view_safe(lightning, "lightning_current_ka", "") or _view_safe(lightning_inputs, "current_ka", "")
    if lightning_current:
        lightning_fields.append({"label": "雷电流幅值", "kind": "text", "value": f"{lightning_current} kA"})
    if _view_has(lightning, "conclusion"):
        lightning_fields.append({"label": "结论", "kind": "text", "value": sf(lightning, "conclusion")})
    if _view_has(lightning, "mechanism"):
        lightning_fields.append({"label": "机理", "kind": "text", "value": sf(lightning, "mechanism")})
    lightning_status = _view_status(lightning, None, {"not_applicable": "不适用", "unavailable": "不可用"})
    if lightning_status is not None:
        lightning_fields.append({"label": "状态", "kind": "text", "value": lightning_status})
    steps.append({
        "key": "lightning", "title": "雷击分析", "header": "步骤5：雷击原因分析",
        "empty": "该记录未包含雷击分析中间数据。",
        "available": bool(lightning_fields), "fields": lightning_fields,
    })

    # ---- 步骤6 行波分析 ----
    wave = diag.get("traveling_wave_analysis", {}) if isinstance(diag, Mapping) else {}
    wave_fields: list[dict[str, Any]] = []
    if _view_has(wave, "analysis_method"):
        method = sf(wave, "analysis_method")
        wave_fields.append({
            "label": "引擎类型", "kind": "tag", "value": method,
            "options": {"MATLAB": "blue"},
        })
    phase_count = None
    if isinstance(wave.get("phase_analyses"), list) and wave["phase_analyses"]:
        phase_count = len(wave["phase_analyses"])
    elif _view_has(wave, "active_phases"):
        phase_count = len(wave["active_phases"])
    if phase_count is not None:
        wave_fields.append({"label": "行波记录数", "kind": "text", "value": str(phase_count)})
    if _view_has(wave, "classification"):
        wave_fields.append({"label": "分类结论", "kind": "text", "value": sf(wave, "classification")})
    if _view_has(wave, "mechanism"):
        wave_fields.append({"label": "机理", "kind": "text", "value": sf(wave, "mechanism")})
    if _view_has(wave, "confidence"):
        wave_fields.append({"label": "置信度", "kind": "text", "value": _view_percent(wave.get("confidence"))})
    wave_model = wave.get("model_result", {}) if isinstance(wave.get("model_result"), Mapping) else {}
    if _view_has(wave_model, "meaning"):
        wave_fields.append({"label": "模型预测结果", "kind": "text", "value": sf(wave_model, "meaning")})
    if _view_has(wave, "report_conclusion"):
        wave_fields.append({"label": "详细判定依据", "kind": "text", "value": sf(wave, "report_conclusion")})
    steps.append({
        "key": "wave", "title": "行波分析", "header": "步骤6：行波分析",
        "empty": "该记录未包含行波分析中间数据。",
        "available": bool(wave_fields), "fields": wave_fields,
    })

    # ---- 步骤7 综合判定 ----
    overall = diag.get("overall_recommendation", {}) if isinstance(diag, Mapping) else {}
    overall_fields: list[dict[str, Any]] = []
    if _view_has(overall, "decision"):
        overall_fields.append({"label": "判定结论", "kind": "text", "value": sf(overall, "decision")})
    if _view_has(overall, "can_auto_pass"):
        overall_fields.append({
            "label": "是否可自动通过", "kind": "tag",
            "value": "可以自动通过" if overall.get("can_auto_pass") else "建议人工复核",
            "options": {"可以自动通过": "green", "建议人工复核": "orange"},
        })
    overall_confidence = _view_safe(diag, "confidence", "") or _view_safe(overall, "confidence", "")
    if overall_confidence:
        overall_fields.append({"label": "综合置信度", "kind": "text", "value": f"{overall_confidence}%"})
    if _view_has(diag, "risk_level"):
        overall_fields.append({
            "label": "风险等级", "kind": "tag", "value": sf(diag, "risk_level"),
            "options": {"low": "green", "medium": "orange", "high": "red", "critical": "red"},
        })
    if _view_has(overall, "summary"):
        overall_fields.append({"label": "汇总说明", "kind": "text", "value": sf(overall, "summary")})
    overall_reasons = _view_evidence(overall, "reasons")
    if overall_reasons:
        overall_fields.append({"label": "未通过原因", "kind": "bullets", "items": overall_reasons})
    steps.append({
        "key": "overall", "title": "综合判定", "header": "步骤7：综合判定",
        "empty": "该记录未包含综合判定中间数据。",
        "available": bool(overall_fields), "fields": overall_fields,
    })

    return {"steps": steps}
