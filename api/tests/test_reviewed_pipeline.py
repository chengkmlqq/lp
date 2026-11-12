# NOTE(LP-4): reviewed_pipeline 案例级聚合单元测试。
#
# 交付版 reviewed_pipeline.py 未随任务附带，本测试覆盖 LP 等价重建的聚合规则：
# LN/F/R 表决、雷电记录修正、FBF 例外、耐雷硬边界（withstand_policy）、多相复核、
# 绕击子型（FSF/SF）、Reviewed107 冻结、缺数据分支。
from __future__ import annotations

from app.services.reviewed_pipeline import (
    LABEL_BACKFLASH,
    LABEL_NON_LIGHTNING,
    LABEL_SHIELDING,
    LABEL_UNKNOWN,
    review_case,
)


def _point(
    *,
    label: str = "",
    subtype: str = "",
    lightning_mechanism: str = "",
    lightning_status: str = "",
    fusion_mechanism: str = "",
    can_auto_pass: bool = True,
    recording_phase: str = "A",
    active_phases: str = "A",
    provisional: bool = False,
) -> dict:
    """构造一个最小化的 build_diagnosis 输出（仅含聚合所需字段）。"""
    return {
        "traveling_wave_analysis": {
            "model_result": {"final_label": label, "final_subtype": subtype},
            "recording_fault_phase": recording_phase,
            "wave_active_phases": active_phases,
            "provisional": provisional,
        },
        "lightning_cause_analysis": {
            "mechanism": lightning_mechanism,
            "status": lightning_status,
        },
        "cause_fusion": {"final_mechanism": fusion_mechanism},
        "overall_recommendation": {"can_auto_pass": can_auto_pass},
    }


def test_single_point_non_lightning():
    r = review_case([_point(label=LABEL_NON_LIGHTNING)])
    assert r["final_label"] == LABEL_NON_LIGHTNING
    assert r["status"] == "analyzed"


def test_single_point_backflash():
    r = review_case([_point(label=LABEL_BACKFLASH)])
    assert r["final_label"] == LABEL_BACKFLASH
    assert r["final_subtype"] == ""


def test_single_point_shielding_sf():
    r = review_case([_point(label=LABEL_SHIELDING, subtype="SF")])
    assert r["final_label"] == LABEL_SHIELDING
    assert r["final_subtype"] == "SF"


def test_single_point_shielding_fsf():
    r = review_case([_point(label=LABEL_SHIELDING, subtype="FSF")])
    assert r["final_label"] == LABEL_SHIELDING
    assert r["final_subtype"] == "FSF"


def test_multi_point_majority_backflash():
    # 2 个 F + 1 个 N → F
    r = review_case([_point(label=LABEL_BACKFLASH), _point(label=LABEL_BACKFLASH), _point(label=LABEL_NON_LIGHTNING)])
    assert r["final_label"] == LABEL_BACKFLASH


def test_multi_point_majority_shielding():
    r = review_case([
        _point(label=LABEL_SHIELDING, subtype="SF"),
        _point(label=LABEL_SHIELDING, subtype="SF"),
        _point(label=LABEL_NON_LIGHTNING),
    ])
    assert r["final_label"] == LABEL_SHIELDING


def test_vote_tie_is_needs_review():
    # 雷击与非雷击权重相等 → 平局，不强行结论
    r = review_case([_point(label=LABEL_SHIELDING, subtype="SF"), _point(label=LABEL_NON_LIGHTNING)])
    assert r["final_label"] == LABEL_UNKNOWN
    assert r["status"] == "needs_review"


def test_lightning_record_correction():
    # 无同期落雷记录（not_applicable）但行波/融合指示雷击 → 修正为雷击参与表决
    r = review_case([_point(label=LABEL_SHIELDING, lightning_status="not_applicable", fusion_mechanism="绕击")])
    assert r["final_label"] == LABEL_SHIELDING
    assert any("雷电记录修正" in w for w in r["warnings"])
    assert r["votes"]["lightning_record_corrected_indices"] == [0]


def test_withstand_hard_boundary_backflash():
    # 雷电流达到反击耐雷阈值（反击候选）→ 耐雷硬边界强制 F，冻结
    r = review_case([_point(label=LABEL_NON_LIGHTNING, lightning_mechanism="反击候选", lightning_status="analyzed")])
    assert r["final_label"] == LABEL_BACKFLASH
    assert "withstand_hard_boundary" in r["frozen"]
    assert any(o["source"] == "withstand_hard_boundary" for o in r["overrides"])


def test_withstand_hard_boundary_shielding():
    r = review_case([_point(label=LABEL_NON_LIGHTNING, lightning_mechanism="绕击候选", lightning_status="analyzed")])
    assert r["final_label"] == LABEL_SHIELDING


def test_withstand_overrides_vote():
    # 多数测点判非雷击，但一个测点触发耐雷硬边界 → 最终为雷击（冻结不被推翻）
    r = review_case([
        _point(label=LABEL_NON_LIGHTNING),
        _point(label=LABEL_NON_LIGHTNING),
        _point(label=LABEL_NON_LIGHTNING, lightning_mechanism="反击候选", lightning_status="analyzed"),
    ])
    assert r["final_label"] == LABEL_BACKFLASH


def test_multi_phase_conflict():
    r = review_case([_point(label=LABEL_SHIELDING, recording_phase="A"), _point(label=LABEL_SHIELDING, recording_phase="B")])
    assert r["multi_phase_review"]["conflict"] is True
    assert r["status"] == "needs_review"


def test_missing_data_branch():
    r = review_case([_point(label="", lightning_status="unavailable")])
    assert r["final_label"] == LABEL_UNKNOWN
    assert r["status"] == "unavailable"


def test_empty_points():
    r = review_case([])
    assert r["point_count"] == 0
    assert r["status"] == "unavailable"


def test_fbf_exception_flips_to_shielding():
    # 表决为 F，但存在 FSF（两相导线绕击）证据占优 → FBF 例外翻转为 R
    r = review_case([_point(label=LABEL_BACKFLASH), _point(label=LABEL_BACKFLASH, subtype="FSF")])
    assert r["final_label"] == LABEL_SHIELDING
    assert any(o["source"] == "fbf_exception" for o in r["overrides"])


def test_provisional_weight_discount():
    # 一个非 provisional 雷击点胜过两个 provisional 非雷击点
    r = review_case([
        _point(label=LABEL_SHIELDING, provisional=True),
        _point(label=LABEL_NON_LIGHTNING, provisional=True),
        _point(label=LABEL_NON_LIGHTNING, provisional=True),
        _point(label=LABEL_SHIELDING),
    ])
    assert r["final_label"] == LABEL_SHIELDING
