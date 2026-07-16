from __future__ import annotations

from datetime import datetime

from app.services.fl_analysis_report import build_report_document, build_report_summary_payload


def _build_risk_row(
    *,
    tower_id: str,
    tower_no: str,
    tower_type: str,
    terrain: str,
    risk_level: str,
    risk_grade: int,
    score: int,
    cause_analysis: str,
    mitigation_recommendation: str,
    lightning_density: float,
    ground_resistance_ohm: float,
    slope_deg: float,
    protection_angle_deg: float,
    insulator_length_mm: float,
    shield_wire_height_m: float,
    counterstrike_withstand_ka: float,
    counterstrike_trip_rate: float,
    shielding_withstand_ka: float,
    shielding_trip_rate: float,
    reason_details: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "tower_id": tower_id,
        "tower_no": tower_no,
        "tower_type": tower_type,
        "base_tower_json": {
            "tower_type": tower_type,
            "terrain": terrain,
            "line_voltage_kv": 220,
            "lightning_density": lightning_density,
            "ground_resistance_ohm": ground_resistance_ohm,
            "slope_1": slope_deg,
            "slope_2": max(slope_deg - 2.0, 0.0),
            "longitude": 120.0 + score / 1000.0,
            "latitude": 30.0 + score / 1000.0,
        },
        "profile_json": {
            "structure_kind": "单回",
            "stroke_mode": "反击",
            "insulator_length_m": round(insulator_length_mm / 1000.0, 4),
            "shield_wire_height_m": shield_wire_height_m,
        },
        "risk_level": risk_level,
        "result_json": {
            "risk_grade": risk_grade,
            "score": score,
            "cause_analysis": cause_analysis,
            "mitigation_recommendation": mitigation_recommendation,
            "counterstrike_withstand_ka": counterstrike_withstand_ka,
            "counterstrike_trip_rate": counterstrike_trip_rate,
            "shielding_withstand_ka": shielding_withstand_ka,
            "shielding_trip_rate": shielding_trip_rate,
            "reason_details": reason_details,
            "inputs": {
                "ground_resistance_ohm": ground_resistance_ohm,
                "lightning_density": lightning_density,
                "insulator_length_mm": insulator_length_mm,
                "terrain_slope_deg": slope_deg,
                "protection_angle_deg": protection_angle_deg,
            },
        },
    }


def _sample_report_data() -> dict[str, object]:
    high_row = _build_risk_row(
        tower_id="tower-1",
        tower_no="001",
        tower_type="直线",
        terrain="山地",
        risk_level="high",
        risk_grade=3,
        score=88,
        cause_analysis="接地电阻偏高；保护角暴露偏大",
        mitigation_recommendation="优先降低接地电阻；优化避雷线与保护角配置",
        lightning_density=4.2,
        ground_resistance_ohm=18.0,
        slope_deg=6.8,
        protection_angle_deg=23.0,
        insulator_length_mm=2400.0,
        shield_wire_height_m=46.0,
        counterstrike_withstand_ka=96.2,
        counterstrike_trip_rate=0.108,
        shielding_withstand_ka=118.6,
        shielding_trip_rate=0.021,
        reason_details=[
            {"code": "ground_resistance", "label": "接地电阻", "grade": 1, "triggered": True},
            {"code": "protection_angle", "label": "保护角", "grade": 2, "triggered": True},
            {"code": "shield_wire_height", "label": "高度档次", "grade": 1, "triggered": True, "value": 46.0, "standard_value": 33.0},
            {"code": "terrain_slope", "label": "地面倾角档次", "grade": 3, "triggered": False, "value": 6.8},
            {"code": "insulator_length", "label": "绝缘子串长度档次", "grade": 3, "triggered": False, "value": 2400.0, "standard_value": 2265.0},
        ],
    )
    medium_row = _build_risk_row(
        tower_id="tower-2",
        tower_no="002",
        tower_type="耐张",
        terrain="丘陵",
        risk_level="medium",
        risk_grade=2,
        score=56,
        cause_analysis="地闪密度中等偏高",
        mitigation_recommendation="按高雷区口径校核绝缘与屏蔽配置",
        lightning_density=2.2,
        ground_resistance_ohm=9.0,
        slope_deg=3.5,
        protection_angle_deg=16.2,
        insulator_length_mm=2550.0,
        shield_wire_height_m=38.0,
        counterstrike_withstand_ka=105.0,
        counterstrike_trip_rate=0.052,
        shielding_withstand_ka=126.0,
        shielding_trip_rate=0.014,
        reason_details=[
            {"code": "lightning_density", "label": "地闪密度", "grade": 2, "triggered": True},
            {"code": "shield_wire_height", "label": "高度档次", "grade": 4, "triggered": False, "value": 38.0, "standard_value": 33.0},
            {"code": "terrain_slope", "label": "地面倾角档次", "grade": 4, "triggered": False, "value": 3.5},
            {"code": "insulator_length", "label": "绝缘子串长度档次", "grade": 4, "triggered": False, "value": 2550.0, "standard_value": 2265.0},
            {"code": "protection_angle", "label": "保护角", "grade": 3, "triggered": False, "value": 16.2},
        ],
    )
    low_row = _build_risk_row(
        tower_id="tower-3",
        tower_no="003",
        tower_type="直线",
        terrain="平原",
        risk_level="low",
        risk_grade=1,
        score=18,
        cause_analysis="主要输入参数处于低风险区间",
        mitigation_recommendation="维持现有防雷配置并保持常规巡检",
        lightning_density=0.62,
        ground_resistance_ohm=4.0,
        slope_deg=1.2,
        protection_angle_deg=8.0,
        insulator_length_mm=3100.0,
        shield_wire_height_m=30.0,
        counterstrike_withstand_ka=132.8,
        counterstrike_trip_rate=0.008,
        shielding_withstand_ka=148.4,
        shielding_trip_rate=0.003,
        reason_details=[
            {"code": "shield_wire_height", "label": "高度档次", "grade": 5, "triggered": False, "value": 30.0, "standard_value": 33.0},
            {"code": "terrain_slope", "label": "地面倾角档次", "grade": 4, "triggered": False, "value": 1.2},
            {"code": "insulator_length", "label": "绝缘子串长度档次", "grade": 5, "triggered": False, "value": 3100.0, "standard_value": 2265.0},
            {"code": "protection_angle", "label": "保护角", "grade": 5, "triggered": False, "value": 8.0},
        ],
    )
    return {
        "line": {
            "name": "示例线路",
            "code": "XL-001",
            "voltage_kv": 220,
        },
        "report": {
            "job_name": "示例线路-报告",
            "generated_at": datetime(2026, 6, 7, 17, 30, 0),
            "source_job_id": "risk-job-1",
            "source_job_type": "risk",
            "source_job_name": "示例线路-风险评估",
            "risk_job_id": "risk-job-1",
            "risk_job_name": "示例线路-风险评估",
            "mitigation_job_id": "mit-job-1",
            "mitigation_job_name": "示例线路-措施推荐",
            "scenario_job_id": "scenario-job-1",
            "scenario_job_name": "示例线路-加装避雷器复算",
            "scenario_base_job_type": "normal",
            "non_construction": False,
        },
        "risk_rows": [high_row, medium_row, low_row],
        "selected_risk_rows": [high_row, medium_row],
        "selected_mitigation_rows": [
            {
                "tower_id": "tower-1",
                "tower_no": "001",
                "risk_level": "medium",
                "result_json": {
                    "current_risk_level": "high",
                    "expected_risk_level": "medium",
                    "recommendation_result": "需要安装避雷器",
                    "non_construction": False,
                    "inputs": {
                        "ground_resistance_ohm": 18.0,
                        "insulator_length_mm": 2400.0,
                        "protection_angle_deg": 23.0,
                        "lightning_density": 4.2,
                    },
                    "mitigation_actions": [
                        {
                            "code": "grounding_upgrade",
                            "label": "接地治理",
                            "summary": "降低接地电阻",
                            "current_value": 18.0,
                            "target_value": 5.0,
                        },
                        {
                            "code": "arrester_install",
                            "label": "安装避雷器",
                            "summary": "关键相增设避雷器",
                            "phases": ["A", "B", "C"],
                        },
                    ],
                },
            }
        ],
        "selected_scenario_rows": [
            {
                "tower_id": "tower-1",
                "tower_no": "001",
                "risk_level": "low",
                "result_json": {
                    "counterstrike_withstand_ka": 112.45,
                    "counterstrike_trip_rate": 0.0215,
                    "shielding_withstand_ka": 136.2,
                    "shielding_trip_rate": 0.0085,
                },
            }
        ],
    }


def test_build_report_summary_payload_counts_risk_and_actions() -> None:
    summary = build_report_summary_payload(_sample_report_data())

    assert summary["selected_tower_count"] == 2
    assert summary["risk_counts"] == {"high": 1, "medium": 1, "low": 1}
    assert summary["selected_risk_counts"] == {"high": 1, "medium": 1, "low": 0}
    assert summary["post_mitigation_risk_counts"] == {"high": 0, "medium": 1, "low": 0}
    assert summary["selected_factor_trigger_counts"]["接地电阻"] == 1
    assert summary["selected_factor_trigger_counts"]["保护角"] == 1
    assert summary["selected_cause_counts"]["接地电阻偏高"] == 1
    assert summary["mitigation_action_counts"]["接地治理"] == 1
    assert summary["mitigation_action_counts"]["安装避雷器"] == 1
    assert summary["has_mitigation_data"] is True
    assert summary["scenario_row_count"] == 1
    assert summary["post_recalc_risk_counts"] == {"high": 0, "medium": 0, "low": 1}
    assert summary["has_scenario_data"] is True


def test_build_report_document_renders_word_compatible_html() -> None:
    filename, content = build_report_document(_sample_report_data())
    html = content.decode("utf-8")

    assert filename.endswith(".doc")
    assert "示例线路-报告" in filename
    assert "示例线路" in html
    assert "2.3线路杆塔高度" in html
    assert "图7 线路杆塔地闪密度雷区分布图" in html
    assert "图7 线路杆塔地闪密度雷区分布图（表格替代）" not in html
    assert 'src="data:image/png;base64,' in html
    assert "图8 线路杆塔避雷线保护角信息统计图" in html
    assert "表10 输电线路雷击风险等级划分规则" in html
    assert "表13 高风险杆塔差异化防雷措施" in html
    assert "雷害风险评估结果" in html
    assert "安装避雷器" in html
    assert "表14 采取措施后的计算结果表" in html
    assert "反击耐雷水平(kA)" in html
    assert "001" in html


def test_build_report_document_falls_back_to_table_when_map_points_missing() -> None:
    report_data = _sample_report_data()
    for row in report_data["risk_rows"]:
        row["base_tower_json"]["longitude"] = None
        row["base_tower_json"]["latitude"] = None

    _, content = build_report_document(report_data)
    html = content.decode("utf-8")

    assert "图7 线路杆塔地闪密度雷区分布图（表格替代）" in html
    assert 'src="data:image/png;base64,' not in html
