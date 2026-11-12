# NOTE(LP-5): 耐雷硬边界判据端到端测试。
#
# 覆盖 build_diagnosis 产出的 decision_trace（withstand_lower_ka / withstand_hit /
# withstand_source）以及报告 pipeline.withstand_sentence 的真实分支：
# 110 / 35 kV 约定阈值、220 / 500 kV 匹配台账、台账未匹配、电压/雷电流缺失。
from __future__ import annotations

from typing import Any

from app.services.fault_diagnosis_core import build_diagnosis
from app.services.fault_diagnosis_report import report_field_values


def _diagnose(
    *,
    voltage: Any,
    current_ka: Any,
    ledger_threshold_ka: float = 90.0,
    ledger_shielding_ka: float = 20.0,
    matched: bool = True,
    query_result: str = "是",
) -> dict[str, Any]:
    fault = {
        "line_name": "测试线",
        "fault_phase": "A",
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
    ledger_rows = (
        [
            {
                "线路名称": "测试线",
                "塔号": "N12",
                "电压等级": f"{voltage}kV" if voltage is not None else "220kV",
                "反击耐雷水平kA": ledger_threshold_ka,
                "绕击耐雷水平kA": ledger_shielding_ka,
            }
        ]
        if matched
        else []
    )
    return build_diagnosis(fault, {}, ledger_rows, lightning_raw=lightning)


def _trace(diag: dict[str, Any]) -> dict[str, Any]:
    wave = diag["traveling_wave_analysis"]
    assert wave["pipeline_version"] == "1.0.7"
    return wave["decision_trace"]


def test_110kv_convention_threshold_hit():
    diag = _diagnose(voltage=110, current_ka=45)
    trace = _trace(diag)
    assert trace["withstand_lower_ka"] == 41.0
    assert trace["withstand_hit"] == 1
    assert trace["withstand_source"] == "110kV约定阈值"
    assert trace["shielding_withstand_ka"] == 7.0


def test_110kv_convention_threshold_not_hit():
    trace = _trace(_diagnose(voltage=110, current_ka=30))
    assert trace["withstand_lower_ka"] == 41.0
    assert trace["withstand_hit"] == 0


def test_35kv_convention_threshold_hit():
    trace = _trace(_diagnose(voltage=35, current_ka=-25))
    assert trace["withstand_lower_ka"] == 20.0
    assert trace["withstand_hit"] == 1
    assert trace["withstand_source"] == "35kV约定阈值"


def test_220kv_uses_matched_ledger():
    trace = _trace(_diagnose(voltage=220, current_ka=120, ledger_threshold_ka=95))
    assert trace["withstand_lower_ka"] == 95.0
    assert trace["withstand_hit"] == 1
    assert trace["withstand_source"] == "匹配故障杆塔的原台账"


def test_500kv_uses_matched_ledger_and_misses():
    trace = _trace(_diagnose(voltage=500, current_ka=50, ledger_threshold_ka=95))
    assert trace["withstand_lower_ka"] == 95.0
    assert trace["withstand_hit"] == 0


def test_220kv_without_matched_ledger_degrades_with_reason():
    trace = _trace(_diagnose(voltage=220, current_ka=120, matched=False))
    assert trace["withstand_lower_ka"] is None
    assert trace["withstand_hit"] == 0
    assert trace["withstand_source"] == "原台账未匹配故障杆塔，耐雷水平缺失"


def test_missing_voltage_degrades_with_reason():
    trace = _trace(_diagnose(voltage=None, current_ka=120))
    assert trace["withstand_lower_ka"] is None
    assert trace["withstand_source"] == "电压等级未提供，未指定耐雷水平"


def test_missing_current_keeps_level_but_not_hit():
    trace = _trace(_diagnose(voltage=110, current_ka=None))
    assert trace["withstand_lower_ka"] == 41.0
    assert trace["withstand_hit"] == 0


def test_report_outputs_real_withstand_conclusion_for_each_voltage():
    expected = {
        110: "反击耐雷水平41 kA（来源：110kV约定阈值）",
        35: "反击耐雷水平20 kA（来源：35kV约定阈值）",
        220: "反击耐雷水平95 kA（来源：匹配故障杆塔的原台账）",
        500: "反击耐雷水平95 kA（来源：匹配故障杆塔的原台账）",
    }
    for voltage, fragment in expected.items():
        sentence = report_field_values(
            _diagnose(voltage=voltage, current_ka=200, ledger_threshold_ka=95)
        )["pipeline.withstand_sentence"]
        assert fragment in sentence
        assert "未提供按电压等级选取的反击耐雷下限" not in sentence


def test_report_explains_degraded_branches_without_fallback_wording():
    unmatched = report_field_values(
        _diagnose(voltage=220, current_ka=120, matched=False)
    )["pipeline.withstand_sentence"]
    assert "未执行反击耐雷硬边界" in unmatched
    assert "原台账未匹配故障杆塔" in unmatched

    no_voltage = report_field_values(_diagnose(voltage=None, current_ka=120))[
        "pipeline.withstand_sentence"
    ]
    assert "未执行反击耐雷硬边界" in no_voltage
    assert "电压等级未提供" in no_voltage

    no_current = report_field_values(_diagnose(voltage=110, current_ka=None))[
        "pipeline.withstand_sentence"
    ]
    assert "缺少雷电流幅值" in no_current
