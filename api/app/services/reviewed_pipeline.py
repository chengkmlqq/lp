# NOTE(LP-4): 案例级聚合层。
#
# 本模块等价移植交付版 app/source/reviewed_pipeline.py（v1.0.7 新增）。交付源码未随
# 本任务附带（仅有《Linux完整更新文件清单及用途_1.0.5至1.0.7》描述其职责），因此这里以
# LP 现有 fault_diagnosis_core.build_diagnosis 的“每测点判别结果”为输入，按清单描述的职责
# 重建案例级聚合：
#
#   - LN/F/R 模型表决（aggregate / vote）
#   - 雷电记录修正
#   - FBF 例外
#   - 耐雷硬边界（withstand_policy）
#   - 多相复核
#   - 绕击子型（FSF/SF）及最终结果
#   - Reviewed107 冻结规则：输出最终 Label + 亚型 + 判定理由
#
# 每测点判别 = fault_diagnosis_core.build_diagnosis 的输出（schema_version 0.9.0）。
# 本模块只做“多测点/多组”的汇总裁决，不重复实现单点算法。
#
# 说明：具体数值阈值以交付版为准。本实现给出结构与规则等价、可由单测验证的逻辑；
# 与交付源码的逐项阈值核对需在拿到交付 review_pipeline.py 后补充（见本 issue 验收标准）。
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def number(value: Any) -> float | None:
    """把输入转成有限浮点数；空值/非数值/无穷返回 None（与交付版同名函数一致）。"""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


# 最终 Label 取值
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

# 绕击子型
SUBTYPE_FSF = "FSF"  # 雷击避雷线和导线型绕击（两相导线）
SUBTYPE_SF = "SF"  # 普通绕击
_SUBTYPE_CN = {
    SUBTYPE_FSF: "雷击避雷线和导线型绕击",
    SUBTYPE_SF: "普通绕击",
}

# Reviewed107 冻结规则标记：被冻结的来源一旦确定，弱证据不得覆盖。
FREEZE_WITHSTAND = "withstand_hard_boundary"
FREEZE_ANALYZED_MAJORITY = "analyzed_majority"

# 耐雷硬边界触发的机制（雷电流达到耐雷阈值，来自 lightning_cause_analysis.mechanism）
_WITHSTAND_MECHANISMS = {"反击候选", "绕击候选"}


@dataclass
class PointSignal:
    """从单个测点的 build_diagnosis 输出中抽取出的、聚合所需的信号。"""

    index: int
    final_label: str = LABEL_UNKNOWN  # N / F / R / U（已含雷电记录修正后的判据）
    raw_label: str = LABEL_UNKNOWN  # 修正前的行波模型 Label
    subtype: str = ""
    lightning_mechanism: str = ""  # lightning_cause_analysis.mechanism
    lightning_status: str = ""
    fusion_mechanism: str = ""  # cause_fusion.final_mechanism
    is_lightning_record_corrected: bool = False  # 是否经雷电记录修正后升级为雷击
    withstand_triggered: bool = False  # 是否触发耐雷硬边界
    withstand_label: str = ""  # 耐雷硬边界给出的 Label（F/R）
    is_provisional: bool = False  # 该点结论是否仅为候选（缺数据/需复核）
    recording_phase: str = ""  # 录波故障相
    active_phases: str = ""  # 行波候补故障相


def _point_signal(index: int, point: Mapping[str, Any]) -> PointSignal:
    """从单个测点判别结果抽取聚合信号。"""
    wave = point.get("traveling_wave_analysis") or {}
    model = wave.get("model_result") or {}
    lightning = point.get("lightning_cause_analysis") or {}
    fusion = point.get("cause_fusion") or {}
    overall = point.get("overall_recommendation") or {}

    raw_label = str(model.get("final_label") or "").upper()
    subtype = str(model.get("final_subtype") or "")
    lightning_mechanism = str(lightning.get("mechanism") or "")
    lightning_status = str(lightning.get("status") or "")
    fusion_mechanism = str(fusion.get("final_mechanism") or "")
    recording_phase = str(wave.get("recording_fault_phase") or "")
    active_phases = str(wave.get("wave_active_phases") or model.get("active_phases") or "")

    # 行波模型 Label 优先；缺失时退化为 cause_fusion 的中文机制。
    if raw_label in {LABEL_NON_LIGHTNING, LABEL_BACKFLASH, LABEL_SHIELDING}:
        final_label = raw_label
    elif fusion_mechanism == "非雷击":
        final_label = LABEL_NON_LIGHTNING
    elif fusion_mechanism == "反击":
        final_label = LABEL_BACKFLASH
    elif fusion_mechanism == "绕击":
        final_label = LABEL_SHIELDING
    else:
        final_label = LABEL_UNKNOWN

    # 耐雷硬边界：雷电流达到耐雷阈值（反击候选/绕击候选）。
    withstand_triggered = lightning_mechanism in _WITHSTAND_MECHANISMS and lightning_status in {
        "analyzed",
        "needs_review",
    }
    withstand_label = ""
    if withstand_triggered:
        withstand_label = LABEL_BACKFLASH if lightning_mechanism == "反击候选" else LABEL_SHIELDING

    # 雷电记录修正：无同期落雷记录（not_applicable）但行波/融合强烈指示雷击时，
    # 不因其缺记录而把该点判为非雷击，而是作为“已修正”的雷击证据参与表决。
    lightning_record_corrected = (
        lightning_status == "not_applicable"
        and final_label in {LABEL_BACKFLASH, LABEL_SHIELDING}
    )
    if lightning_record_corrected:
        # 修正不改变 Label，只标记该点来源被校正，避免“缺记录”被当作非雷击反证。
        pass

    is_provisional = bool(overall.get("can_auto_pass") is False) or bool(wave.get("provisional"))

    return PointSignal(
        index=index,
        final_label=final_label,
        raw_label=raw_label,
        subtype=subtype,
        lightning_mechanism=lightning_mechanism,
        lightning_status=lightning_status,
        fusion_mechanism=fusion_mechanism,
        is_lightning_record_corrected=lightning_record_corrected,
        withstand_triggered=withstand_triggered,
        withstand_label=withstand_label,
        is_provisional=is_provisional,
        recording_phase=recording_phase,
        active_phases=active_phases,
    )


def _tally_labels(signals: Sequence[PointSignal]) -> dict[str, int]:
    counts = {LABEL_NON_LIGHTNING: 0, LABEL_BACKFLASH: 0, LABEL_SHIELDING: 0, LABEL_UNKNOWN: 0}
    for sig in signals:
        counts[sig.final_label] = counts.get(sig.final_label, 0) + 1
    return counts


def withstand_policy(voltage: Any, ledger_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """按电压等级选取反击/绕击耐雷下限（移植交付版 reviewed_pipeline.withstand_policy）。

    - 35 / 110 kV：使用约定阈值（反击 20/41 kA，绕击 3.5/7 kA）；
    - 220 / 500 kV：取匹配故障杆塔台账的原始耐雷水平，未匹配时返回 None 并说明原因，
      不借用示例台账；
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


def withstand_freeze_policy(signals: Sequence[PointSignal]) -> dict[str, Any] | None:
    """耐雷硬边界（案例级冻结）：任一测点雷电流达到耐雷阈值即强制为雷击，且不被后续弱证据覆盖。

    返回冻结裁决（含来源点），未触发则返回 None。
    """
    triggered = [sig for sig in signals if sig.withstand_triggered]
    if not triggered:
        return None
    # 多数耐雷触发的方向决定 Label；平局偏向反击（F）以保守提示更严重的故障类型。
    f_count = sum(1 for sig in triggered if sig.withstand_label == LABEL_BACKFLASH)
    r_count = sum(1 for sig in triggered if sig.withstand_label == LABEL_SHIELDING)
    label = LABEL_BACKFLASH if f_count >= r_count else LABEL_SHIELDING
    indices = [sig.index for sig in triggered]
    return {
        "label": label,
        "source": FREEZE_WITHSTAND,
        "triggered_point_indices": indices,
        "backflash_count": f_count,
        "shielding_count": r_count,
        "reason": (
            "耐雷硬边界：至少一个测点的雷电流幅值达到耐雷阈值"
            f"（反击/绕击候选），按固定判据强制判定为雷击（{_LABEL_CN[label]}），"
            "该结论冻结，不被行波/台账弱证据覆盖"
        ),
    }


def vote(signals: Sequence[PointSignal]) -> dict[str, Any]:
    """LN/F/R 模型表决：先判雷击/非雷击（LN），再在雷击侧判反击/绕击（F/R）。

    仅统计“非候选”的有效 Label（排除 U）。投票权重：非 provisional 的点权重为 1，
    provisional（缺数据/需复核）点权重为 0.5，以体现 Reviewed107 对弱证据的折扣。
    """
    weights: dict[str, float] = {LABEL_NON_LIGHTNING: 0.0, LABEL_BACKFLASH: 0.0, LABEL_SHIELDING: 0.0}
    for sig in signals:
        if sig.final_label == LABEL_UNKNOWN:
            continue
        w = 0.5 if sig.is_provisional else 1.0
        weights[sig.final_label] += w

    lightning_weight = weights[LABEL_BACKFLASH] + weights[LABEL_SHIELDING]
    non_lightning_weight = weights[LABEL_NON_LIGHTNING]

    if lightning_weight > non_lightning_weight:
        # 雷击侧：F/R 表决
        if weights[LABEL_BACKFLASH] > weights[LABEL_SHIELDING]:
            label = LABEL_BACKFLASH
        elif weights[LABEL_SHIELDING] > weights[LABEL_BACKFLASH]:
            label = LABEL_SHIELDING
        else:
            label = LABEL_UNKNOWN  # F/R 平局，需人工复核
    elif non_lightning_weight > lightning_weight:
        label = LABEL_NON_LIGHTNING
    else:
        # 雷击与非雷击权重相等（含全 U）：视为平局，不强行给出结论，需人工复核，
        # 避免在无证据或证据冲突时误判雷击。
        label = LABEL_UNKNOWN

    return {
        "weights": weights,
        "lightning_weight": lightning_weight,
        "non_lightning_weight": non_lightning_weight,
        "label": label,
        "source": "ln_fr_vote",
        "reason": (
            "LN/F/R 表决：雷击权重"
            f"{lightning_weight:g} vs 非雷击权重 {non_lightning_weight:g}"
            f" → 初步判定为 {_LABEL_CN[label]}"
        ),
    }


def fbf_exception(vote_result: dict[str, Any], signals: Sequence[PointSignal]) -> dict[str, Any] | None:
    """FBF 例外：当多相绕击（FSF）证据占优时，不再维持单相反击（F）初判。

    交付清单将其列为“FBF 例外”。这里实现为：表决结果为 F，但多数雷击点为
    两相导线绕击（FSF）子型时，例外翻转为绕击（R），避免把多相绕击误归为反击。
    """
    if vote_result.get("label") != LABEL_BACKFLASH:
        return None
    fsf_points = [
        sig
        for sig in signals
        if sig.final_label == LABEL_BACKFLASH and sig.subtype == SUBTYPE_FSF
    ]
    if len(fsf_points) >= 1 and len(fsf_points) >= max(1, sum(1 for sig in signals if sig.final_label == LABEL_BACKFLASH) // 2):
        return {
            "label": LABEL_SHIELDING,
            "source": "fbf_exception",
            "fsf_point_indices": [sig.index for sig in fsf_points],
            "reason": (
                "FBF 例外：多相绕击（FSF，两相导线）证据占优，"
                "不再维持单相反击（F）初判，翻转为绕击（R）"
            ),
        }
    return None


def _select_subtype(signals: Sequence[PointSignal], label: str) -> str:
    """绕击子型选择：Label 为 R 时，若任一有效点判为 FSF 则取 FSF，否则 SF。"""
    if label != LABEL_SHIELDING:
        return ""
    effective = [sig for sig in signals if sig.final_label == LABEL_SHIELDING]
    if any(sig.subtype == SUBTYPE_FSF for sig in effective):
        return SUBTYPE_FSF
    return SUBTYPE_SF


def _multi_phase_review(signals: Sequence[PointSignal]) -> dict[str, Any]:
    """多相复核：收集各测点故障相；若录波故障相之间存在不一致则标记冲突。"""
    phases = []
    for sig in signals:
        if sig.recording_phase and sig.recording_phase != "未知":
            phases.append(sig.recording_phase)
    distinct = sorted({p for p in phases})
    conflict = len(distinct) > 1
    return {
        "recording_phases": distinct,
        "conflict": conflict,
        "reason": (
            f"多相复核：各测点录波故障相为 {distinct}，" + ("存在不一致，需人工复核相别" if conflict else "一致")
            if distinct
            else "多相复核：无可用的录波故障相"
        ),
    }


def review_case(points: Sequence[Mapping[str, Any]], *, tolerate_missing: bool = True) -> dict[str, Any]:
    """案例级聚合入口：把多个测点的 build_diagnosis 结果汇总为最终结论。

    参数
    ----
    points: 每个元素是 fault_diagnosis_core.build_diagnosis 的输出（dict）。
    tolerate_missing: 当所有测点都缺数据（Label 全为 U）时，是否返回 unavailable
        而非强行给出 Unknown 结论。

    返回
    ----
    案例级结论 dict：final_label / final_subtype / reason / votes / overrides /
    frozen / multi_phase_review / status / warnings。
    """
    if not points:
        return {
            "schema_version": "1.0.7-case",
            "point_count": 0,
            "final_label": LABEL_UNKNOWN,
            "final_label_cn": _LABEL_CN[LABEL_UNKNOWN],
            "final_subtype": "",
            "final_subtype_cn": "",
            "reason": "没有可用的测点判别结果",
            "votes": {},
            "overrides": [],
            "frozen": [],
            "multi_phase_review": _multi_phase_review([]),
            "status": "unavailable",
            "warnings": ["案例不含任何测点"],
        }

    signals = [_point_signal(i, p) for i, p in enumerate(points)]
    warnings: list[str] = []
    overrides: list[dict[str, Any]] = []
    frozen: list[str] = []

    # 1) 耐雷硬边界（冻结优先级最高）
    withstand = withstand_freeze_policy(signals)
    if withstand is not None:
        overrides.append(withstand)
        frozen.append(FREEZE_WITHSTAND)

    # 2) LN/F/R 表决
    ballot = vote(signals)

    # 3) FBF 例外
    fbf = fbf_exception(ballot, signals)
    if fbf is not None:
        overrides.append(fbf)

    # 4) 决定最终 Label：耐雷硬边界优先；否则 FBF 例外；否则表决；冻结保护。
    if withstand is not None:
        final_label = withstand["label"]
        status = "analyzed"
    elif fbf is not None:
        final_label = fbf["label"]
        status = "analyzed"
    else:
        final_label = ballot["label"]
        status = "needs_review" if final_label == LABEL_UNKNOWN else "analyzed"
        # 非 provisional 的有效多数构成冻结，弱候选不得推翻。
        if final_label != LABEL_UNKNOWN:
            effective = [s for s in signals if s.final_label == final_label and not s.is_provisional]
            if effective:
                frozen.append(FREEZE_ANALYZED_MAJORITY)

    # 5) 雷电记录修正说明
    corrected = [s for s in signals if s.is_lightning_record_corrected]
    if corrected:
        warnings.append(
            f"雷电记录修正：{len(corrected)} 个测点无同期落雷记录，但行波/融合指示雷击，"
            "已作为已修正的雷击证据参与表决"
        )

    # 6) 绕击子型
    final_subtype = _select_subtype(signals, final_label)

    # 7) 多相复核
    multi_phase = _multi_phase_review(signals)
    if multi_phase["conflict"]:
        status = "needs_review"
        warnings.append(multi_phase["reason"])

    # 8) 全缺数据分支
    all_unknown = all(s.final_label == LABEL_UNKNOWN for s in signals)
    if all_unknown and tolerate_missing:
        status = "unavailable"
        final_label = LABEL_UNKNOWN
        final_subtype = ""

    # 9) 组装判定理由
    reasons: list[str] = []
    if withstand is not None:
        reasons.append(withstand["reason"])
    elif fbf is not None:
        reasons.append(fbf["reason"])
    else:
        reasons.append(ballot["reason"])
    if final_subtype:
        reasons.append(f"绕击子型判定为 {_SUBTYPE_CN.get(final_subtype, final_subtype)}")
    if multi_phase["conflict"]:
        reasons.append(multi_phase["reason"])
    if status == "unavailable":
        reasons = ["所有测点均缺少可用判别数据，无法给出案例级结论"]

    # 各测点表决明细
    votes_detail = {
        "tally": _tally_labels(signals),
        "weights": ballot.get("weights", {}),
        "lightning_record_corrected_indices": [s.index for s in corrected],
        "withstand_triggered_indices": [s.index for s in signals if s.withstand_triggered],
    }

    return {
        "schema_version": "1.0.7-case",
        "point_count": len(signals),
        "final_label": final_label,
        "final_label_cn": _LABEL_CN[final_label],
        "final_subtype": final_subtype,
        "final_subtype_cn": _SUBTYPE_CN.get(final_subtype, ""),
        "reason": "；".join(reasons),
        "votes": votes_detail,
        "overrides": overrides,
        "frozen": frozen,
        "multi_phase_review": multi_phase,
        "status": status,
        "warnings": warnings,
    }
