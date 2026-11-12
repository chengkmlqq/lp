# NOTE(LP-6): 案例级聚合层，逐字移植交付版 v1.0.7 `app/source/reviewed_pipeline.py`。
#
# 交付版的完整链路是：
#   MATLAB 每组测点输出 wave_module_prediction.txt
#     → aggregate(groups, lightning, voltage, fault_phase, withstand)  本模块
#     → 合并后的 fields（含 Case* 与 Module* 结论）
#     → build_diagnosis(wave_model_result=fields)
#       → fault_diagnosis.py 把 Case* 映射成 decision_trace.*
#       → 报告/记录统一取 ModuleFinalLabel / ModuleFinalSubtype
#
# LP 之前只做了「按清单重建」的近似版聚合，结果挂在 case_review 旁路上，
# 没有接管最终结论。这里改用交付版真实级联：LN/F/R 表决 → FBF 例外 →
# 耐雷硬边界 → 多相反击得分 → 冻结模型结果，并给出 FBF/FSF/SF 三子型。
from __future__ import annotations

import math
import re
from statistics import mean
from typing import Any, Mapping, Sequence

# 多相反击得分的六项特征阈值（交付版 FEATURES，逐字一致）。
FEATURES = {
    "peakAmplitudeEntropy": 0.92,
    "phaseCount60": 1.5,
    "thirdPeakRatio": 0.35,
    "secondPeakRatio": 0.60,
    "secondDurationAbove20Us": 45.0,
    "mainHighFreqEnergyRatio200k": 0.002,
}

LABEL_NON_LIGHTNING = "N"  # 非雷击故障
LABEL_BACKFLASH = "F"  # 雷击反击故障
LABEL_SHIELDING = "R"  # 雷击绕击故障
LABEL_UNKNOWN = "U"  # 无法判定

_LABEL_CN = {
    LABEL_NON_LIGHTNING: "非雷击故障",
    LABEL_BACKFLASH: "雷击反击故障",
    LABEL_SHIELDING: "雷击绕击故障",
    LABEL_UNKNOWN: "无法判定",
}

SUBTYPE_FBF = "FBF"  # 雷击避雷线与导线型绕击
SUBTYPE_FSF = "FSF"  # 雷击多相导线型绕击
SUBTYPE_SF = "SF"  # 普通绕击

_SUBTYPE_CN = {
    SUBTYPE_FBF: "雷击避雷线与导线型绕击",
    SUBTYPE_FSF: "雷击多相导线型绕击",
    SUBTYPE_SF: "普通绕击",
}


def number(value: Any) -> float | None:
    """把输入转成有限浮点数；空值/非数值/无穷返回 None（与交付版同名函数一致）。"""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def vote(fields: Sequence[Mapping[str, Any]], key: str, score) -> tuple[str, Mapping[str, Any]]:
    """多组字段投票：取出现次数最多的取值，同票时取模型区分度最大的一组。

    交付版按 `f[key]` 取字段；LP 需要容忍老引擎缺字段，故用 `.get`，取值语义不变。
    """
    counts: dict[str, int] = {}
    for item in fields:
        label = str(item.get(key))
        counts[label] = counts.get(label, 0) + 1
    maximum = max(counts.values())
    candidates = [item for item in fields if counts[str(item.get(key))] == maximum]
    representative = max(candidates, key=lambda item: abs(score(item)))
    return str(representative.get(key)), representative


def withstand_policy(voltage: Any, ledger_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """按电压等级选取反击/绕击耐雷下限（移植交付版 reviewed_pipeline.withstand_policy）。

    - 35 / 110 kV：使用约定阈值（反击 20/41 kA，绕击 3.5/7 kA）；
    - 220 / 500 kV：取匹配故障杆塔台账的原始耐雷水平，未匹配时返回 None 并说明原因；
    - 电压等级缺失：返回 None 并说明未指定耐雷水平。
    """
    voltage = number(voltage)
    if voltage in (35, 110):
        return {
            "backflash_ka": {35: 20.0, 110: 41.0}[voltage],
            "shielding_ka": {35: 3.5, 110: 7.0}[voltage],
            "source": f"{voltage:g}kV约定阈值",
        }
    ledger_result = ledger_result or {}
    record = ledger_result.get("record", {}) if ledger_result.get("matched") else {}
    if voltage in (220, 500):
        return {
            "backflash_ka": number(record.get("backflashover_withstand_ka")),
            "shielding_ka": number(record.get("shielding_failure_withstand_ka")),
            "source": "匹配故障杆塔的原台账" if record else "原台账未匹配故障杆塔，耐雷水平缺失",
        }
    return {"backflash_ka": None, "shielding_ka": None, "source": "电压等级未提供，未指定耐雷水平"}


def voltage_from_input(fault_raw: Mapping[str, Any], ledger_rows: Sequence[Mapping[str, Any]]) -> float | None:
    """从故障信息或台账行提取电压等级（移植交付版 voltage_from_input）。

    故障信息中显式留空的电压等级视为“缺失”，不借用台账（可能是示例台账）的电压；
    完全没有该字段时才回退到台账行。
    """
    for key in ("voltage_level_kv", "电压等级", "电压等级(kV)", "电压等级（kV）"):
        if key in fault_raw and str(fault_raw[key] or "").strip() in {"", "未提供", "未知"}:
            return None
    for raw in (fault_raw, *ledger_rows):
        for key in ("voltage_level_kv", "电压等级", "电压等级(kV)", "电压等级（kV）"):
            value = raw.get(key)
            match = re.search(r"(35|110|220|500)(?:\.0)?(?:\s*kV)?", str(value or ""), re.I)
            if match:
                return float(match.group(1))
    return None


def _located(lightning: Mapping[str, Any]) -> bool:
    return str(lightning.get("query_result", "")).strip().upper() in {
        "是",
        "有",
        "存在",
        "Y",
        "YES",
        "TRUE",
        "1",
    }


def _multiphase_values(fields: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """六项多相特征取各测点均值，缺任一项则该特征为 None（交付版同口径）。"""
    values: dict[str, float | None] = {}
    for name in FEATURES:
        observed = [number(item.get("MultiFeature_" + name)) for item in fields]
        observed = [value for value in observed if value is not None]
        values[name] = mean(observed) if observed else None
    return values


def _multiphase_score(values: Mapping[str, float | None]) -> float | None:
    """六项特征全齐才给分：逐项与阈值比较后计数（交付版判定级联用）。"""
    if not all(value is not None for value in values.values()):
        return None
    return float(sum(values[name] >= threshold for name, threshold in FEATURES.items()))


def aggregate(
    groups: Sequence[Mapping[str, Any]],
    lightning: Mapping[str, Any],
    voltage: Any,
    fault_phase: str = "",
    withstand: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """案例级聚合（交付版 aggregate 逐字移植，含判定级联与 Case* 输出）。

    groups 每个元素需含 `fields`（该组 wave_module_prediction.txt 全部字段）与
    `complete_three_phase_data`（该组是否为完整三相数据）。
    """
    fields = [dict(group["fields"]) for group in groups]
    ln, ln_rep = vote(
        fields,
        "LNPrediction",
        lambda item: (number(item.get("LNLightningScore")) or 0)
        - (number(item.get("LNNonLightningScore")) or 0),
    )
    fr, fr_rep = vote(
        fields,
        "FRPrediction",
        lambda item: (number(item.get("FRFScore")) or 0) - (number(item.get("FRRScore")) or 0),
    )
    located = _located(lightning)
    # 第一层：有雷电定位记录即进入雷击分支，从而排除 N。
    first = "Lightning" if located else ln
    fbf = any(number(item.get("CorrectionMeetsFBF")) == 1 for item in fields)
    fsf = any(number(item.get("CorrectionMeetsFSF")) == 1 for item in fields)
    current = number(lightning.get("current_ka"))
    voltage = number(voltage)
    policy = withstand if withstand is not None else withstand_policy(voltage)
    lower = number(policy.get("backflash_ka"))
    hit = located and current is not None and lower is not None and abs(current) >= lower
    multiphase_values = _multiphase_values(fields)
    score = _multiphase_score(multiphase_values)
    subtype = ""
    phase_count = len(set(re.findall("[ABC]", str(fault_phase).upper())))

    if first == "NonLightning":
        final, reason = LABEL_NON_LIGHTNING, "第一层判N，后续规则不覆盖N"
    elif fbf and fr == LABEL_SHIELDING:
        final, subtype, reason = (
            LABEL_SHIELDING,
            SUBTYPE_FBF,
            "FBF波形证据与冻结FR同判R，保留FBF例外",
        )
    elif hit:
        final, reason = LABEL_BACKFLASH, f"雷电流达到反击耐雷水平{lower:g}kA（{policy.get('source', '输入参数')}）"
    elif phase_count >= 2 and score is not None and score >= 5:
        final, reason = LABEL_BACKFLASH, f"多相反击得分{score:g}，确认F"
    elif phase_count >= 2 and score is not None and score <= 2:
        final, reason = LABEL_SHIELDING, f"多相反击得分{score:g}，确认R"
    else:
        final, reason = fr, "保留冻结F/R模型表决"
    if final == LABEL_SHIELDING and not subtype:
        subtype = SUBTYPE_FBF if fbf else SUBTYPE_FSF if fsf else SUBTYPE_SF

    selected = dict(fr_rep)
    selected.update(
        {
            "CaseMultiFeature_" + name: "" if value is None else value
            for name, value in multiphase_values.items()
        }
    )
    selected.update(
        {
            "ModuleInitialLabel": LABEL_NON_LIGHTNING if ln == "NonLightning" else fr,
            "ModuleFinalLabel": final,
            "FinalLabel": final,
            "ModuleFinalSubtype": subtype or (SUBTYPE_SF if final == LABEL_SHIELDING else ""),
            "FinalSubtype": subtype or (SUBTYPE_SF if final == LABEL_SHIELDING else ""),
            "ModuleCorrectionStatus": "Reviewed107",
            "ModuleCorrectionApplied": int(
                final != (LABEL_NON_LIGHTNING if ln == "NonLightning" else fr) or bool(subtype)
            ),
            "ModuleCorrectionReason": reason,
            "SoftwareVersion": "1.0.7",
            "CaseLNVote": ln,
            "CaseFirstLayer": first,
            "CaseFRVote": fr,
            "CaseFBF": int(fbf),
            "CaseFSF": int(fsf),
            "CaseSubtypeChecked": int(
                phase_count > 0 and any(bool(group.get("complete_three_phase_data")) for group in groups)
            ),
            "CaseMultiphaseFScore": "" if score is None else score,
            "CaseLightningWithstandLowerKA": "" if lower is None else lower,
            "CaseLightningWithstandHit": int(hit),
            "CaseShieldingWithstandKA": "" if policy.get("shielding_ka") is None else policy["shielding_ka"],
            "CaseWithstandSource": policy.get("source", "未提供"),
            "CaseRecordedFaultPhaseCount": phase_count,
            "LNPrediction": ln,
            "LNLightningScore": ln_rep.get("LNLightningScore"),
            "LNNonLightningScore": ln_rep.get("LNNonLightningScore"),
            "ModuleSuppliedFaultPhase": str(fault_phase),
            "ModuleCorrectedFaultPhase": str(fault_phase),
            "IntegratedBuild": "20261022_C2_retrained_LN",
        }
    )
    return selected


def case_summary(fields: Mapping[str, Any]) -> dict[str, Any]:
    """把 aggregate() 的输出整理为案例级结论摘要（只读，唯一来源为 Case* / Module*）。"""
    label = str(fields.get("ModuleFinalLabel") or LABEL_UNKNOWN).upper()
    subtype = str(fields.get("ModuleFinalSubtype") or "")
    return {
        "schema_version": "1.0.7-case",
        "final_label": label,
        "final_label_cn": _LABEL_CN.get(label, "无法判定"),
        "final_subtype": subtype,
        "final_subtype_cn": _SUBTYPE_CN.get(subtype, ""),
        "reason": str(fields.get("ModuleCorrectionReason") or ""),
        "software_version": fields.get("SoftwareVersion"),
    }
