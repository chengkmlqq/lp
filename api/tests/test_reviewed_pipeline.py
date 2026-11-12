# NOTE(LP-6): 案例级聚合与判别级联测试。
#
# 覆盖交付版 v1.0.7 `reviewed_pipeline.aggregate()` 的判定级联（第一层 located 排除 N、
# FBF 例外、耐雷硬边界、多相反击得分、冻结 F/R 表决、FBF/FSF/SF 三子型），以及三个
# 纠错案例（FBF-ZDB / 15F-HMJ / F-HMJ / 49F-CB）从聚合到报告字段的端到端一致性。
from __future__ import annotations

from typing import Any

from app.services.fault_diagnosis_core import build_diagnosis
from app.services.fault_diagnosis_report import fused_fault_conclusion, report_field_values
from app.services.reviewed_pipeline import (
    FEATURES,
    LABEL_BACKFLASH,
    LABEL_NON_LIGHTNING,
    LABEL_SHIELDING,
    aggregate,
    voltage_from_input,
    withstand_policy,
)


def _fields(**overrides: Any) -> dict[str, Any]:
    """一组 wave_module_prediction.txt 字段（1.0.7 行波模型输出）。"""
    base: dict[str, Any] = {
        "LNPrediction": "Lightning",
        "LNLightningScore": 0.9,
        "LNNonLightningScore": 0.1,
        "FRPrediction": LABEL_SHIELDING,
        "FRFScore": 0.2,
        "FRRScore": 0.8,
        "CorrectionMeetsFBF": 0,
        "CorrectionMeetsFSF": 0,
        "SoftwareVersion": "1.0.7",
    }
    base.update(overrides)
    return base


def _group(fields: dict[str, Any] | None = None, *, complete: bool = True) -> dict[str, Any]:
    return {"fields": fields or _fields(), "complete_three_phase_data": complete}


def _aggregate(
    groups: list[dict[str, Any]] | None = None,
    *,
    lightning: dict[str, Any] | None = None,
    voltage: Any = 110,
    fault_phase: str = "A",
) -> dict[str, Any]:
    return aggregate(
        groups or [_group()],
        lightning if lightning is not None else {"query_result": "是", "current_ka": 10},
        voltage,
        fault_phase,
        withstand=withstand_policy(voltage),
    )


# ---- 第一层 / FBF / 耐雷硬边界 三条修复分支 ----


def test_located_lightning_excludes_non_lightning_branch():
    """问题 3（49F-CB）：有雷电定位记录时第一层进入雷击分支，不再落到 N。"""
    result = _aggregate(
        [_group(_fields(LNPrediction="NonLightning", LNNonLightningScore=0.95, FRPrediction=LABEL_SHIELDING))],
        lightning={"query_result": "是", "current_ka": 30},
    )
    assert result["CaseFirstLayer"] == "Lightning"
    assert result["ModuleFinalLabel"] == LABEL_SHIELDING


def test_no_lightning_record_keeps_non_lightning():
    result = _aggregate(
        [_group(_fields(LNPrediction="NonLightning", LNNonLightningScore=0.95))],
        lightning={"query_result": "否", "current_ka": 30},
    )
    assert result["CaseFirstLayer"] == "NonLightning"
    assert result["ModuleFinalLabel"] == LABEL_NON_LIGHTNING


def test_fbf_evidence_and_frozen_shielding_gives_fbf_subtype():
    """问题 1（FBF-ZDB）：FBF 波形证据 + 冻结 FR 同判 R → R/FBF。"""
    result = _aggregate([_group(_fields(CorrectionMeetsFBF=1, FRPrediction=LABEL_SHIELDING))])
    assert result["CaseFBF"] == 1
    assert result["ModuleFinalLabel"] == LABEL_SHIELDING
    assert result["ModuleFinalSubtype"] == "FBF"
    assert "FBF" in result["ModuleCorrectionReason"]


def test_withstand_hard_boundary_turns_shielding_into_backflash():
    """问题 2（15F-HMJ / F-HMJ）：耐雷硬边界命中 → F，不再保留绕击。"""
    for current in (74.2, 84.7):
        result = _aggregate(
            [_group(_fields(FRPrediction=LABEL_SHIELDING))],
            lightning={"query_result": "是", "current_ka": current},
            voltage=110,
        )
        assert result["CaseLightningWithstandLowerKA"] == 41.0
        assert result["CaseLightningWithstandHit"] == 1
        assert result["ModuleFinalLabel"] == LABEL_BACKFLASH
        assert result["ModuleFinalSubtype"] == ""


def test_withstand_below_threshold_keeps_frozen_fr_vote():
    result = _aggregate(
        [_group(_fields(FRPrediction=LABEL_SHIELDING))],
        lightning={"query_result": "是", "current_ka": 20},
        voltage=110,
    )
    assert result["CaseLightningWithstandHit"] == 0
    assert result["ModuleFinalLabel"] == LABEL_SHIELDING
    assert result["ModuleFinalSubtype"] == "SF"


# ---- 多相反击得分与子型 ----


def _feature_fields(above: int) -> dict[str, Any]:
    """构造 6 项多相特征中前 above 项达标的字段。"""
    return {
        "MultiFeature_" + name: threshold if index < above else threshold - 1e-6
        for index, (name, threshold) in enumerate(FEATURES.items())
    }


def test_multiphase_score_confirms_backflash():
    result = _aggregate(
        [_group(_fields(FRPrediction=LABEL_SHIELDING, **_feature_fields(5)))],
        lightning={"query_result": "是", "current_ka": 5},
        fault_phase="AB",
    )
    assert result["CaseMultiphaseFScore"] == 5.0
    assert result["ModuleFinalLabel"] == LABEL_BACKFLASH


def test_multiphase_score_confirms_shielding():
    result = _aggregate(
        [_group(_fields(FRPrediction=LABEL_BACKFLASH, **_feature_fields(2)))],
        lightning={"query_result": "是", "current_ka": 5},
        fault_phase="AB",
    )
    assert result["CaseMultiphaseFScore"] == 2.0
    assert result["ModuleFinalLabel"] == LABEL_SHIELDING
    assert result["ModuleFinalSubtype"] == "SF"


def test_fsf_evidence_sets_fsf_subtype():
    result = _aggregate([_group(_fields(CorrectionMeetsFSF=1))])
    assert result["ModuleFinalLabel"] == LABEL_SHIELDING
    assert result["ModuleFinalSubtype"] == "FSF"


def test_subtype_checked_requires_complete_three_phase_data():
    result = _aggregate([_group(_fields(), complete=False)], fault_phase="A")
    assert result["CaseSubtypeChecked"] == 0


# ---- 按电压等级选取的耐雷下限（交付版 withstand_policy 等价移植） ----

def test_withstand_policy_uses_convention_thresholds_for_35_and_110():
    assert withstand_policy(110) == {
        "backflash_ka": 41.0,
        "shielding_ka": 7.0,
        "source": "110kV约定阈值",
    }
    assert withstand_policy(35) == {
        "backflash_ka": 20.0,
        "shielding_ka": 3.5,
        "source": "35kV约定阈值",
    }


def test_withstand_policy_reads_matched_ledger_for_220_and_500():
    ledger = {
        "matched": True,
        "record": {"backflashover_withstand_ka": 95.0, "shielding_failure_withstand_ka": 18.0},
    }
    for voltage in (220, 500):
        policy = withstand_policy(voltage, ledger)
        assert policy["backflash_ka"] == 95.0
        assert policy["shielding_ka"] == 18.0
        assert policy["source"] == "匹配故障杆塔的原台账"


def test_withstand_policy_degrades_without_matched_ledger():
    policy = withstand_policy(220, {"matched": False, "record": {"backflashover_withstand_ka": 95.0}})
    assert policy["backflash_ka"] is None
    assert policy["source"] == "原台账未匹配故障杆塔，耐雷水平缺失"


def test_withstand_policy_missing_voltage_returns_none():
    policy = withstand_policy(None, {"matched": True, "record": {"backflashover_withstand_ka": 95.0}})
    assert policy["backflash_ka"] is None
    assert policy["shielding_ka"] is None
    assert policy["source"] == "电压等级未提供，未指定耐雷水平"


def test_voltage_from_input_handles_units_and_blank_values():
    assert voltage_from_input({"voltage_level_kv": "110kV"}, []) == 110.0
    assert voltage_from_input({"电压等级": "500kV"}, []) == 500.0
    # 台账行作为兜底（故障信息完全没有电压字段时）
    assert voltage_from_input({}, [{"电压等级": "220kV"}]) == 220.0
    # 故障信息中显式留空视为缺失，不得借用台账电压
    assert voltage_from_input({"电压等级": " "}, [{"电压等级": "220kV"}]) is None
    assert voltage_from_input({"电压等级": "未提供"}, [{"电压等级": "220kV"}]) is None


# ---- 端到端：聚合 → decision_trace → 报告「判别过程」与最终结论 ----


def _wave_record(phase: str) -> dict[str, Any]:
    samples = [0.0] * 40 + [1.0, 3.0, 8.0, 2.0] + [0.2] * 156
    return {
        "file_name": f"{phase}.txt",
        "phase": phase,
        "samples": samples,
        "sample_rate_hz": 1_000_000.0,
        "head_time": "2026-01-01 10:00:00",
    }


def _diagnose(
    *,
    fields: dict[str, Any],
    fault_phase: str,
    current_ka: float,
    query_result: str = "是",
    voltage: Any = 110,
) -> dict[str, Any]:
    fault = {
        "line_name": "测试线",
        "fault_phase": fault_phase,
        "fault_time": "2026-01-01 10:00:00",
        "phase_voltage": 63.5,
        "phase_current": 1.2,
        "zero_sequence_current": 0.3,
        "duration_ms": 60,
        "voltage_level_kv": voltage,
    }
    lightning = {
        "line_name": "测试线",
        "query_result": query_result,
        "current_ka": current_ka,
        "nearest_tower": "N12",
        "location_time": "2026-01-01 10:00:00",
    }
    ledger_rows = [
        {
            "线路名称": "测试线",
            "塔号": "N12",
            "电压等级": f"{voltage}kV",
            "反击耐雷水平kA": 90.0,
            "绕击耐雷水平kA": 20.0,
        }
    ]
    records = [_wave_record(phase) for phase in "ABC"]
    return build_diagnosis(
        fault,
        {},
        ledger_rows,
        lightning_raw=lightning,
        traveling_wave_records=records,
        wave_model_result=fields,
    )


def _trace(diag: dict[str, Any]) -> dict[str, Any]:
    wave = diag["traveling_wave_analysis"]
    assert wave["pipeline_version"] == "1.0.7"
    return wave["decision_trace"]


def test_case_fbf_zdb_end_to_end():
    """纠错案例 1：FBF-ZDB → 判别过程显示符合 FBF 特征，最终结论为 FBF。"""
    diag = _diagnose(
        fields=_fields(FRPrediction=LABEL_SHIELDING, CorrectionMeetsFBF=1),
        fault_phase="A",
        current_ka=20,
    )
    trace = _trace(diag)
    assert trace["fbf_evidence"] == 1
    assert trace["first_layer"] == "Lightning"
    assert trace["withstand_hit"] == 0

    model = diag["traveling_wave_analysis"]["model_result"]
    assert model["final_label"] == LABEL_SHIELDING
    assert model["final_subtype"] == "FBF"

    values = report_field_values(diag)
    assert "符合避雷线与导线型绕击特征" in values["pipeline.shielding_pair_sentence"]
    assert "避雷线与导线型绕击" in values["pipeline.final_sentence"]
    assert "避雷线与导线型绕击" in fused_fault_conclusion(diag)


def test_case_withstand_hit_end_to_end():
    """纠错案例 2：15F-HMJ / F-HMJ 耐雷硬边界命中 → 最终结论为反击。"""
    for current in (74.2, 84.7):
        diag = _diagnose(
            fields=_fields(FRPrediction=LABEL_SHIELDING),
            fault_phase="AB",
            current_ka=current,
        )
        trace = _trace(diag)
        assert trace["withstand_hit"] == 1
        assert trace["withstand_lower_ka"] == 41.0

        model = diag["traveling_wave_analysis"]["model_result"]
        assert model["final_label"] == LABEL_BACKFLASH

        values = report_field_values(diag)
        assert "达到反击耐雷水平" in values["pipeline.withstand_sentence"]
        assert "反击" in values["pipeline.final_sentence"]
        assert "绕击" not in values["pipeline.final_sentence"]
        assert "反击" in fused_fault_conclusion(diag)


def test_case_lightning_location_end_to_end():
    """纠错案例 3：49F-CB 雷电定位记录判定雷击 → 最终结论不再是“非雷击”。"""
    diag = _diagnose(
        fields=_fields(LNPrediction="NonLightning", LNNonLightningScore=0.95, FRPrediction=LABEL_SHIELDING),
        fault_phase="AB",
        current_ka=30,
    )
    trace = _trace(diag)
    assert trace["first_layer"] == "Lightning"
    assert trace["ln_vote"] == "NonLightning"

    model = diag["traveling_wave_analysis"]["model_result"]
    assert model["final_label"] != LABEL_NON_LIGHTNING

    values = report_field_values(diag)
    assert "雷电定位记录" in values["pipeline.lightning_gate_sentence"]
    assert "非雷击" not in values["pipeline.final_sentence"]
    assert "非雷击" not in fused_fault_conclusion(diag)
