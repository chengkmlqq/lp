from __future__ import annotations

import csv
import io
from pathlib import Path
from types import SimpleNamespace

from app.services.fl_analysis_service import export_fl_analysis_results_to_csv


API_FILE = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "fl_analysis.py"


def _decode_csv(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))


def _build_job(job_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        job_type=job_type,
        job_name=f"{job_type}-job",
        line=SimpleNamespace(code="XL-001"),
    )


def _build_row(*, result_json: dict[str, object], risk_level: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id="result-1",
        risk_level=risk_level,
        summary_text=result_json.get("summary_text"),
        result_json=result_json,
        snapshot=SimpleNamespace(
            seq_no=1,
            tower_no="001",
            tower_model="220-TEST-ZX",
            tower_type="直线",
            base_tower_json={
                "tower_no": "001",
                "tower_type": "直线",
                "slope_1": 3.2,
                "slope_2": 1.8,
                "altitude_m": 1680.0,
                "terrain": "山地",
                "ground_resistance_ohm": 22.0,
                "lightning_density": 4.8,
            },
            profile_json={
                "stroke_mode": "反击",
                "current_a": 72.5,
                "current_b": 1.35,
                "current_head_time_us": 2.6,
                "current_tail_time_us": 50.0,
            },
        ),
    )


def test_export_normal_results_csv_contains_waveform_columns() -> None:
    result_json = {
        "risk_level": "high",
        "risk_grade": 3,
        "score": 88,
        "summary_text": "001普通计算结果，高风险。",
        "cause_analysis": "接地电阻偏高",
        "mitigation_recommendation": "优先降低接地电阻",
        "counterstrike_withstand_ka": 71.2,
        "counterstrike_trip_rate": 0.0123,
        "shielding_withstand_ka": 64.8,
        "shielding_trip_rate": 0.0081,
        "reason_details": [{"code": "ground_resistance", "label": "接地电阻", "grade": 1, "triggered": True}],
        "inputs": {
            "current_a": 72.5,
            "current_b": 1.35,
            "ground_resistance_ohm": 22.0,
            "lightning_density": 4.8,
            "insulator_length_mm": 4200.0,
            "protection_angle_deg": 24.5,
        },
        "workflow": {
            "current_waveform": "double_slope",
            "flashover_method": "intersection",
            "altitude_correction": "formula1",
            "induced_voltage_formula": "formula2",
            "scan_point_count": 4,
        },
        "selected_case": {
            "head_time_us": 2.4,
            "tail_time_us": 45.0,
        },
    }

    _filename, content = export_fl_analysis_results_to_csv(_build_job("normal"), [_build_row(result_json=result_json)])
    rows = _decode_csv(content)

    assert len(rows) == 2
    header = rows[0]
    values = rows[1]
    assert "最不利波头时间(μs)" in header
    assert "雷电流波形" in header
    assert "当前风险等级" not in header
    assert values[header.index("风险等级")] == "高风险"
    assert values[header.index("雷电流波形")] == "double_slope"
    assert values[header.index("最不利波头时间(μs)")] == "2.4"


def test_export_mitigation_results_csv_contains_recommendation_columns() -> None:
    result_json = {
        "risk_level": "medium",
        "current_risk_level": "high",
        "current_score": 92,
        "expected_risk_level": "medium",
        "expected_score": 63,
        "summary_text": "001当前高风险，建议后预期降为中风险。",
        "cause_analysis": "接地电阻偏高；保护角暴露偏大",
        "mitigation_recommendation": "降低接地电阻；优化保护角；补装避雷器",
        "recommendation_result": "需要安装避雷器",
        "reason_details": [{"code": "ground_resistance", "label": "接地电阻", "grade": 1, "triggered": True}],
        "inputs": {
            "current_a": 72.5,
            "ground_resistance_ohm": 35.0,
            "insulator_length_mm": 4200.0,
            "protection_angle_deg": 27.0,
        },
        "mitigation_actions": [
            {
                "code": "grounding_upgrade",
                "label": "降低接地电阻",
                "summary": "将接地电阻优化至 5.0 Ω 以内",
                "current_value": 35.0,
                "target_value": 5.0,
                "unit": "ohm",
            },
            {
                "code": "insulator_upgrade",
                "label": "提高绝缘子串长度",
                "summary": "将绝缘子串长度提高至约 5200.0 mm",
                "current_value": 4200.0,
                "target_value": 5200.0,
                "unit": "mm",
            },
            {
                "code": "shielding_geometry",
                "label": "优化保护角",
                "summary": "按非建线口径将保护角收紧至约 18.5°",
                "target_value": 18.5,
                "unit": "deg",
            },
            {
                "code": "arrester_install",
                "label": "补装避雷器",
                "summary": "建议在 A,C 相补装或复核避雷器",
                "phases": ["A", "C"],
            },
        ],
    }

    _filename, content = export_fl_analysis_results_to_csv(
        _build_job("mitigation"),
        [_build_row(result_json=result_json, risk_level="medium")],
    )
    rows = _decode_csv(content)

    assert len(rows) == 2
    header = rows[0]
    values = rows[1]
    assert "绝缘子串长推荐值(mm)" in header
    assert "避雷器推荐相别" in header
    assert "最不利波头时间(μs)" not in header
    assert values[header.index("当前风险等级")] == "高风险"
    assert values[header.index("避雷器推荐相别")] == "A,C"
    assert values[header.index("绝缘子串长推荐值(mm)")] == "5200"


def test_export_risk_results_csv_keeps_header_when_rows_are_empty() -> None:
    _filename, content = export_fl_analysis_results_to_csv(_build_job("risk"), [])
    rows = _decode_csv(content)

    assert len(rows) == 1
    assert "风险等级" in rows[0]
    assert "综合结论" in rows[0]


def test_fl_analysis_api_exposes_results_download_route() -> None:
    source = API_FILE.read_text(encoding="utf-8")

    assert '@router.get("/jobs/{job_id}/results/download")' in source
    assert "download_result_csv" in source
