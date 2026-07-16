from __future__ import annotations

import pytest

from app.services.fl_analysis_rules import (
    grade_mitigation_snapshot_payload,
    grade_normal_snapshot_payload,
    grade_snapshot_payload,
    grade_tongtiao_snapshot_payload,
)


def _build_circuit_geometry(
    *,
    shield_left_m: float,
    shield_right_m: float,
    shield_height_m: float,
    insulator_length_mm: float,
    circuit_i_upper_m: float,
    circuit_i_middle_m: float,
    circuit_i_lower_m: float,
    circuit_i_upper_h_m: float,
    circuit_i_middle_h_m: float,
    circuit_i_lower_h_m: float,
    circuit_ii_upper_m: float | None = None,
    circuit_ii_middle_m: float | None = None,
    circuit_ii_lower_m: float | None = None,
    circuit_ii_upper_h_m: float | None = None,
    circuit_ii_middle_h_m: float | None = None,
    circuit_ii_lower_h_m: float | None = None,
) -> dict[str, object]:
    return {
        "I": {
            "phase_spacing_m": {
                "upper": circuit_i_upper_m,
                "middle": circuit_i_middle_m,
                "lower": circuit_i_lower_m,
            },
            "phase_height_m": {
                "upper": circuit_i_upper_h_m,
                "middle": circuit_i_middle_h_m,
                "lower": circuit_i_lower_h_m,
            },
        },
        "II": {
            "phase_spacing_m": {
                "upper": circuit_ii_upper_m,
                "middle": circuit_ii_middle_m,
                "lower": circuit_ii_lower_m,
            },
            "phase_height_m": {
                "upper": circuit_ii_upper_h_m,
                "middle": circuit_ii_middle_h_m,
                "lower": circuit_ii_lower_h_m,
            },
        },
        "lightning_wire": {
            "left_mid_distance_m": shield_left_m,
            "right_mid_distance_m": shield_right_m,
            "height_m": shield_height_m,
        },
        "insulator_length_mm": insulator_length_mm,
    }


def test_grade_snapshot_payload_marks_high_risk_and_actions() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "T001",
            "tower_type": "耐张",
            "ground_resistance_ohm": 35.0,
            "lightning_density": 6.5,
            "span_large_m": 620.0,
            "line_voltage_kv": 110,
            "slope_1": 18.0,
            "slope_2": 6.0,
            "circuit_geometry_json": {
                "I": {
                    "phase_height_m": {"upper": 28.0, "middle": 24.0, "lower": 20.0},
                },
                "lightning_wire": {
                    "left_mid_distance_m": 9.0,
                    "right_mid_distance_m": 9.0,
                    "height_m": 32.0,
                },
            },
        },
        "profile_json": {
            "structure_kind": "耐张",
            "stroke_mode": "反击",
            "arrester_a": "否",
            "arrester_b": "否",
            "arrester_c": "否",
            "insulator_length_m": 1200.0,
        },
    }

    result = grade_snapshot_payload(payload)

    assert result["risk_level"] == "high"
    assert result["score"] >= 80
    assert "接地电阻偏高" in result["cause_analysis"]
    assert "避雷器" in result["mitigation_recommendation"]
    assert any(item["code"] == "insulator_length" for item in result["reason_details"])


def test_grade_snapshot_payload_marks_low_risk_when_inputs_are_good() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "T002",
            "tower_type": "直线",
            "ground_resistance_ohm": 4.0,
            "lightning_density": 1.5,
            "span_large_m": 180.0,
            "line_voltage_kv": 110,
        },
        "profile_json": {
            "structure_kind": "直线",
            "stroke_mode": "绕击",
            "arrester_a": "是",
            "arrester_b": "是",
            "arrester_c": "是",
            "insulator_length_m": 1800.0,
        },
    }

    result = grade_snapshot_payload(payload)

    assert result["risk_level"] == "low"
    assert result["score"] < 40
    assert result["cause_analysis"]
    assert result["mitigation_recommendation"]


def test_grade_mitigation_snapshot_payload_builds_actions_and_reduces_expected_risk() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "T003",
            "tower_type": "耐张",
            "ground_resistance_ohm": 28.0,
            "lightning_density": 5.0,
            "span_large_m": 420.0,
            "line_voltage_kv": 220,
            "slope_1": 12.0,
            "slope_2": 8.0,
            "circuit_geometry_json": {
                "I": {
                    "phase_height_m": {"upper": 36.0, "middle": 32.0, "lower": 28.0},
                },
                "lightning_wire": {
                    "left_mid_distance_m": 8.5,
                    "right_mid_distance_m": 8.5,
                    "height_m": 40.0,
                },
            },
        },
        "profile_json": {
            "structure_kind": "耐张",
            "stroke_mode": "反击",
            "arrester_a": "否",
            "arrester_b": "否",
            "arrester_c": "否",
            "insulator_length_m": 2000.0,
        },
    }

    result = grade_mitigation_snapshot_payload(payload, non_construction=False)

    assert result["recommendation_result"] in {"需要安装避雷器", "不需要安装避雷器"}
    assert result["mitigation_actions"]
    assert result["expected_score"] < result["current_score"]
    assert any(action["code"] == "grounding_upgrade" for action in result["mitigation_actions"])


def test_grade_mitigation_snapshot_payload_includes_non_construction_action() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "T004",
            "tower_model": "s220guxing",
            "tower_type": "直线",
            "ground_resistance_ohm": 16.0,
            "lightning_density": 3.5,
            "span_large_m": 260.0,
            "line_voltage_kv": 220,
            "circuit_geometry_json": {
                "I": {
                    "phase_height_m": {"upper": 30.0, "middle": 26.0, "lower": 22.0},
                },
                "lightning_wire": {
                    "left_mid_distance_m": 10.0,
                    "right_mid_distance_m": 10.0,
                    "height_m": 33.0,
                },
            },
        },
        "profile_json": {
            "structure_kind": "直线",
            "stroke_mode": "绕击",
            "arrester_a": "是",
            "arrester_b": "是",
            "arrester_c": "是",
            "insulator_length_m": 2500.0,
        },
    }

    result = grade_mitigation_snapshot_payload(payload, non_construction=True)

    assert result["non_construction"] is True
    assert any(action["code"] == "shielding_geometry" for action in result["mitigation_actions"])


def test_grade_mitigation_snapshot_payload_prefers_source_risk_result() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "T005",
            "tower_type": "直线",
            "ground_resistance_ohm": 4.0,
            "lightning_density": 1.5,
            "span_large_m": 180.0,
            "line_voltage_kv": 110,
        },
        "profile_json": {
            "structure_kind": "直线",
            "stroke_mode": "绕击",
            "arrester_a": "是",
            "arrester_b": "是",
            "arrester_c": "是",
            "insulator_length_m": 1800.0,
        },
        "source_result_json": {
            "risk_level": "high",
            "score": 92,
            "cause_analysis": "沿用前驱风险结果",
            "reason_details": [{"code": "source_reason", "label": "前驱原因"}],
            "inputs": {"ground_resistance_ohm": 35.0},
        },
    }

    result = grade_mitigation_snapshot_payload(payload, non_construction=False)

    assert result["current_risk_level"] == "high"
    assert result["current_score"] == 92
    assert result["cause_analysis"] == "沿用前驱风险结果"
    assert result["reason_details"][0]["code"] == "source_reason"


def test_grade_snapshot_payload_uses_source_formula_and_converts_mm_to_m() -> None:
    geometry = _build_circuit_geometry(
        shield_left_m=12.4,
        shield_right_m=15.9,
        shield_height_m=73.5,
        insulator_length_mm=5945.0,
        circuit_i_upper_m=14.5,
        circuit_i_middle_m=10.5,
        circuit_i_lower_m=12.0,
        circuit_i_upper_h_m=53.0,
        circuit_i_middle_h_m=65.5,
        circuit_i_lower_h_m=42.0,
        circuit_ii_upper_m=14.5,
        circuit_ii_middle_m=10.5,
        circuit_ii_lower_m=12.0,
        circuit_ii_upper_h_m=53.0,
        circuit_ii_middle_h_m=65.5,
        circuit_ii_lower_h_m=42.0,
    )
    payload = {
        "base_tower_json": {
            "tower_no": "P1",
            "tower_type": "耐张",
            "tower_model": "500-MC31S-DJC2-42",
            "line_name": "交流500kV雁船线（双回段）",
            "line_voltage_kv": 500,
            "ground_resistance_ohm": 20.0,
            "lightning_density": 5.42528304182587,
            "slope_1": -5.70339674677262,
            "slope_2": -1.42923539492821,
            "circuit_geometry_json": geometry,
            "lightning_result_json": {},
        },
        "profile_json": {
            "structure_kind": "耐张",
            "arrester_a": "否",
            "arrester_b": "否",
            "arrester_c": "否",
            "shield_wire_height_m": 73.5,
            "insulator_length_m": 5945.0,
            "current_a": 25.109,
            "current_b": 3.62,
        },
    }

    result = grade_snapshot_payload(payload)

    assert result["risk_level"] == "high"
    assert result["risk_grade"] == 3
    assert result["inputs"]["insulator_length_m"] == pytest.approx(5.945, abs=1e-6)
    assert result["counterstrike_withstand_ka"] == pytest.approx(75.8070, rel=1e-4)
    assert result["counterstrike_trip_rate"] == pytest.approx(0.529876, rel=1e-4)
    assert result["shielding_withstand_ka"] == pytest.approx(31.2860, rel=1e-4)
    assert result["shielding_trip_rate"] == pytest.approx(0.000003, abs=1e-6)
    assert "接地电阻" in result["cause_analysis"]
    assert "规程法等级 3" in result["summary_text"]


def test_grade_snapshot_payload_marks_low_risk_for_good_inputs() -> None:
    geometry = _build_circuit_geometry(
        shield_left_m=8.0,
        shield_right_m=8.0,
        shield_height_m=40.0,
        insulator_length_mm=3500.0,
        circuit_i_upper_m=10.0,
        circuit_i_middle_m=3.0,
        circuit_i_lower_m=8.0,
        circuit_i_upper_h_m=28.0,
        circuit_i_middle_h_m=31.0,
        circuit_i_lower_h_m=24.0,
    )
    payload = {
        "base_tower_json": {
            "tower_no": "L1",
            "tower_type": "直线",
            "tower_model": "220-TEST-ZX",
            "line_name": "交流220kV示例线",
            "line_voltage_kv": 220,
            "ground_resistance_ohm": 5.0,
            "lightning_density": 1.2,
            "slope_1": 0.0,
            "slope_2": 0.0,
            "circuit_geometry_json": geometry,
            "lightning_result_json": {},
        },
        "profile_json": {
            "structure_kind": "直线",
            "arrester_a": "是",
            "arrester_b": "是",
            "arrester_c": "是",
            "shield_wire_height_m": 40.0,
            "insulator_length_m": 3500.0,
            "current_a": 31.0,
            "current_b": 2.6,
        },
    }

    result = grade_snapshot_payload(payload)

    assert result["risk_level"] == "low"
    assert result["risk_grade"] == 1
    assert result["score"] < 30
    assert result["counterstrike_trip_rate"] == pytest.approx(0.109404, rel=1e-4)
    assert result["shielding_trip_rate"] == pytest.approx(0.006737, rel=1e-4)
    assert "高风险" not in result["summary_text"]


def test_grade_snapshot_payload_falls_back_to_legacy_result_when_geometry_is_missing() -> None:
    payload = {
        "base_tower_json": {
            "tower_no": "F1",
            "lightning_result_json": {
                "counterstroke_withstand_ka": 52.3,
                "counterstroke_trip_rate": 0.12,
                "shielding_withstand_ka": 18.6,
                "shielding_trip_rate": 0.03,
                "risk_level": 2,
            },
        },
        "profile_json": {},
    }

    result = grade_snapshot_payload(payload)

    assert result["used_legacy_fallback"] is True
    assert result["risk_level"] == "medium"
    assert result["counterstrike_withstand_ka"] == pytest.approx(52.3)
    assert result["shielding_trip_rate"] == pytest.approx(0.03)
    assert "历史结果" in result["cause_analysis"]


def test_grade_normal_snapshot_payload_builds_waveform_scan_and_selected_case() -> None:
    geometry = _build_circuit_geometry(
        shield_left_m=9.0,
        shield_right_m=9.0,
        shield_height_m=41.0,
        insulator_length_mm=4200.0,
        circuit_i_upper_m=9.0,
        circuit_i_middle_m=4.5,
        circuit_i_lower_m=8.5,
        circuit_i_upper_h_m=29.0,
        circuit_i_middle_h_m=31.0,
        circuit_i_lower_h_m=25.0,
    )
    payload = {
        "base_tower_json": {
            "tower_no": "N1",
            "tower_type": "直线",
            "tower_model": "220-TEST-ZX",
            "line_name": "交流220kV示例线",
            "line_voltage_kv": 220,
            "ground_resistance_ohm": 12.0,
            "lightning_density": 3.2,
            "altitude_m": 1680.0,
            "slope_1": 3.0,
            "slope_2": 1.5,
            "circuit_geometry_json": geometry,
            "lightning_result_json": {},
        },
        "profile_json": {
            "structure_kind": "直线",
            "arrester_a": "是",
            "arrester_b": "否",
            "arrester_c": "是",
            "shield_wire_height_m": 41.0,
            "insulator_length_m": 4200.0,
            "current_type": "Heidler",
        },
    }

    result = grade_normal_snapshot_payload(
        payload,
        execution_options={
            "current_waveform": "double_slope",
            "flashover_method": "intersection",
            "altitude_correction": "formula1",
            "induced_voltage_formula": "formula2",
            "head_time_min_us": 2.4,
            "head_time_max_us": 2.6,
            "head_time_step_us": 0.2,
            "tail_time_min_us": 45.0,
            "tail_time_max_us": 50.0,
            "tail_time_step_us": 5.0,
        },
    )

    assert result["job_type"] == "normal"
    assert result["workflow"]["scan_point_count"] == 4
    assert len(result["scan_points"]) == 4
    assert result["selected_case"]["head_time_us"] is not None
    assert result["selected_case"]["tail_time_us"] is not None
    assert any(item["code"] == "current_head_time" for item in result["reason_details"])
    assert any(item["code"] == "current_tail_time" for item in result["reason_details"])
    assert "普通计算" in result["summary_text"]


def test_grade_tongtiao_snapshot_payload_builds_phase_and_multi_phase_results() -> None:
    geometry = _build_circuit_geometry(
        shield_left_m=11.0,
        shield_right_m=11.0,
        shield_height_m=72.0,
        insulator_length_mm=5600.0,
        circuit_i_upper_m=14.0,
        circuit_i_middle_m=11.0,
        circuit_i_lower_m=9.0,
        circuit_i_upper_h_m=54.0,
        circuit_i_middle_h_m=50.0,
        circuit_i_lower_h_m=46.0,
        circuit_ii_upper_m=14.0,
        circuit_ii_middle_m=11.0,
        circuit_ii_lower_m=9.0,
        circuit_ii_upper_h_m=53.0,
        circuit_ii_middle_h_m=49.0,
        circuit_ii_lower_h_m=45.0,
    )
    payload = {
        "base_tower_json": {
            "tower_no": "TT1",
            "tower_type": "耐张",
            "tower_model": "500-GUXING",
            "line_name": "交流500kV双回示例线",
            "line_voltage_kv": 500,
            "ground_resistance_ohm": 18.0,
            "lightning_density": 4.6,
            "altitude_m": 1220.0,
            "slope_1": 8.0,
            "slope_2": 3.0,
            "circuit_geometry_json": geometry,
            "lightning_result_json": {},
        },
        "profile_json": {
            "structure_kind": "耐张",
            "phase_sequence_1": "ABC",
            "phase_sequence_2": "CAB",
            "arrester_a": "否",
            "arrester_b": "否",
            "arrester_c": "是",
            "shield_wire_height_m": 72.0,
            "insulator_length_m": 5600.0,
            "current_type": "Heidler",
        },
    }

    result = grade_tongtiao_snapshot_payload(
        payload,
        execution_options={
            "current_waveform": "heidler",
            "flashover_method": "leader_development",
            "head_time_min_us": 2.6,
            "head_time_max_us": 2.6,
            "head_time_step_us": 0.1,
            "tail_time_min_us": 50.0,
            "tail_time_max_us": 50.0,
            "tail_time_step_us": 1.0,
        },
    )

    assert result["job_type"] == "tongtiao"
    assert result["phase_results"]
    assert result["multi_phase_results"]
    assert result["dominant_phase_set"] in {"单相", "双相", "三相", "四相", "五相", "六相"}
    assert result["flashover_phase"]
    assert result["workflow"]["current_waveform"] == "heidler"
