from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fl_analysis import FlAnalysisJob, FlAnalysisRun, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services import fl_analysis_service


def _build_sessionmaker():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Line.__table__,
            LineTower.__table__,
            TowerProfile.__table__,
            FlAnalysisJob.__table__,
            FlAnalysisRun.__table__,
            FlAnalysisTowerSnapshot.__table__,
            FlAnalysisTowerResult.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _create_completed_job(
    session: Session,
    *,
    line: Line,
    tower: LineTower,
    profile: TowerProfile,
    job_type: str,
    job_name: str,
    risk_level: str,
    result_json: dict[str, object],
    execution_options_json: dict[str, object] | None = None,
    external_adapter: str = "placeholder",
) -> tuple[FlAnalysisJob, FlAnalysisRun]:
    job = FlAnalysisJob(
        line_id=line.id,
        job_name=job_name,
        job_type=job_type,
        status="success",
        source_kind="line",
        total_tower_count=1,
        snapshotted_tower_count=1,
        result_tower_count=1,
        external_adapter=external_adapter,
        execution_options_json=execution_options_json or {},
        result_summary_json={},
        create_user="tester",
        update_user="tester",
    )
    session.add(job)
    session.flush()

    run = FlAnalysisRun(
        job_id=job.id,
        status="success",
        runner_kind=external_adapter,
        create_user="tester",
        update_user="tester",
    )
    session.add(run)
    session.flush()

    job.latest_run_id = run.id
    snapshot = FlAnalysisTowerSnapshot(
        job_id=job.id,
        run_id=run.id,
        tower_id=tower.id,
        seq_no=tower.seq_no,
        tower_no=tower.tower_no,
        tower_model=tower.tower_model,
        tower_type=tower.tower_type,
        longitude=tower.longitude,
        latitude=tower.latitude,
        altitude_m=tower.altitude_m,
        terrain=tower.terrain,
        base_tower_json=fl_analysis_service._build_base_tower_json(tower, line),
        profile_json=fl_analysis_service._build_profile_json(profile),
    )
    session.add(snapshot)
    session.flush()

    session.add(
        FlAnalysisTowerResult(
            job_id=job.id,
            run_id=run.id,
            snapshot_id=snapshot.id,
            status="success",
            risk_level=risk_level,
            summary_text=str(result_json.get("summary_text") or ""),
            result_json=result_json,
        )
    )
    session.flush()
    return job, run


def _seed_job_chain(session: Session) -> dict[str, object]:
    line = Line(
        code="L-100",
        name="迁移验证线路",
        voltage_kv=220,
        lightning_param_json={"雷电流幅值a": 31.0, "雷电流幅值b": 2.6},
    )
    session.add(line)
    session.flush()

    tower = LineTower(
        line_id=line.id,
        seq_no=1,
        tower_no="T001",
        tower_model="220-TEST-ZX",
        tower_type="直线",
        longitude=120.0,
        latitude=30.0,
        altitude_m=128.0,
        terrain="山地",
        ground_resistance_ohm=16.0,
        lightning_density=4.2,
        span_large_m=320.0,
        span_small_m=280.0,
        slope_1=5.0,
        slope_2=3.0,
        circuit_geometry_json={
            "I": {
                "phase_spacing_m": {"upper": 9.0, "middle": 4.5, "lower": 8.5},
                "phase_height_m": {"upper": 29.0, "middle": 31.0, "lower": 25.0},
            },
            "lightning_wire": {
                "left_mid_distance_m": 8.0,
                "right_mid_distance_m": 8.0,
                "height_m": 38.0,
            },
            "insulator_length_mm": 4200.0,
        },
        lightning_result_json={},
    )
    session.add(tower)
    session.flush()

    profile = TowerProfile(
        tower_id=tower.id,
        structure_kind="直线",
        stroke_mode="反击",
        arrester_a="否",
        arrester_b="否",
        arrester_c="否",
        insulator_length_m=4200.0,
        current_a=31.0,
        current_b=2.6,
        current_type="Heidler",
        current_head_time_us=2.6,
        current_tail_time_us=50.0,
    )
    session.add(profile)
    session.flush()

    base_job, base_run = _create_completed_job(
        session,
        line=line,
        tower=tower,
        profile=profile,
        job_type="normal",
        job_name="基线普通计算",
        risk_level="high",
        result_json={
            "risk_level": "high",
            "summary_text": "基线普通计算完成",
            "score": 88,
        },
        execution_options_json={
            "current_waveform": "double_slope",
            "flashover_method": "intersection",
            "altitude_correction": "formula1",
            "induced_voltage_formula": "formula2",
            "head_time_min_us": 2.4,
            "head_time_max_us": 2.8,
            "head_time_step_us": 0.2,
            "tail_time_min_us": 45.0,
            "tail_time_max_us": 55.0,
            "tail_time_step_us": 5.0,
        },
    )
    risk_job, risk_run = _create_completed_job(
        session,
        line=line,
        tower=tower,
        profile=profile,
        job_type="risk",
        job_name="风险评估",
        risk_level="high",
        result_json={
            "risk_level": "high",
            "summary_text": "高风险",
            "score": 91,
            "cause_analysis": "接地电阻偏高",
            "mitigation_recommendation": "建议安装避雷器",
            "reason_details": [{"code": "ground_resistance", "label": "接地电阻", "triggered": True}],
        },
    )
    mitigation_job, mitigation_run = _create_completed_job(
        session,
        line=line,
        tower=tower,
        profile=profile,
        job_type="mitigation",
        job_name="措施推荐",
        risk_level="medium",
        result_json={
            "risk_level": "medium",
            "summary_text": "仍需补强",
            "current_risk_level": "high",
            "expected_risk_level": "medium",
            "cause_analysis": "接地电阻偏高",
            "recommendation_result": "需要安装避雷器",
            "mitigation_recommendation": "安装避雷器并优化接地",
            "mitigation_actions": [
                {"code": "arrester_install", "label": "安装避雷器", "summary": "关键相增设避雷器"},
            ],
        },
        execution_options_json={
            "source_job_id": risk_job.id,
            "source_run_id": risk_run.id,
            "selected_tower_ids": [tower.id],
        },
    )

    session.commit()
    return {
        "line": line,
        "tower": tower,
        "profile": profile,
        "base_job": base_job,
        "base_run": base_run,
        "risk_job": risk_job,
        "risk_run": risk_run,
        "mitigation_job": mitigation_job,
        "mitigation_run": mitigation_run,
    }


def test_execute_scenario_job_reuses_base_waveform_and_forces_arresters(monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    session = testing_session()
    try:
        seeded = _seed_job_chain(session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=seeded["line"].id,
                job_name="加装避雷器复算",
                job_type="scenario",
                execution_options_json={
                    "source_job_id": seeded["mitigation_job"].id,
                    "base_job_id": seeded["base_job"].id,
                    "selected_tower_ids": [seeded["tower"].id],
                },
            ),
            actor=SimpleNamespace(id="tester"),
        )

        assert created.job.external_adapter == "placeholder"
        assert created.job.execution_options_json["base_job_type"] == "normal"
        assert created.job.execution_options_json["current_waveform"] == "double_slope"
        assert created.job.execution_options_json["mitigation_job_id"] == seeded["mitigation_job"].id

        captured_payloads: list[dict[str, object]] = []

        def fake_grade_normal_snapshot_payload(payload: dict[str, object], *, execution_options: dict[str, object]) -> dict[str, object]:
            captured_payloads.append(
                {
                    "profile_json": dict(payload["profile_json"]),
                    "execution_options": dict(execution_options),
                }
            )
            return {
                "risk_level": "low",
                "summary_text": "复算完成",
                "score": 12,
                "workflow": {"scan_point_count": 1},
                "counterstrike_withstand_ka": 120.5,
                "counterstrike_trip_rate": 0.02,
                "shielding_withstand_ka": 140.0,
                "shielding_trip_rate": 0.005,
            }

        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        monkeypatch.setattr(fl_analysis_service, "grade_normal_snapshot_payload", fake_grade_normal_snapshot_payload)
        monkeypatch.setattr(
            fl_analysis_service,
            "grade_tongtiao_snapshot_payload",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scenario should reuse normal path")),
        )
        monkeypatch.setattr(
            fl_analysis_service,
            "grade_snapshot_payload",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scenario should not fall back to generic risk grading")),
        )

        session.close()
        fl_analysis_service.execute_job(created.job.id)

        verify_session = testing_session()
        try:
            saved_job = fl_analysis_service.get_job_by_id(verify_session, created.job.id)
            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_job.result_summary_json["base_job_type"] == "normal"
            assert saved_job.result_summary_json["selected_tower_count"] == 1
            assert saved_job.result_summary_json["workflow"]["current_waveform"] == "double_slope"

            saved_row = verify_session.execute(
                select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == created.job.id)
            ).scalar_one()
            assert saved_row.risk_level == "low"
            assert saved_row.result_json["counterstrike_withstand_ka"] == 120.5
        finally:
            verify_session.close()

        assert len(captured_payloads) == 1
        assert captured_payloads[0]["profile_json"]["arrester_a"] == "是"
        assert captured_payloads[0]["profile_json"]["arrester_b"] == "是"
        assert captured_payloads[0]["profile_json"]["arrester_c"] == "是"
        assert captured_payloads[0]["execution_options"]["current_waveform"] == "double_slope"
    finally:
        session.close()


def test_report_job_auto_links_latest_scenario_rows(monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    session = testing_session()
    try:
        seeded = _seed_job_chain(session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)

        scenario_job, scenario_run = _create_completed_job(
            session,
            line=seeded["line"],
            tower=seeded["tower"],
            profile=seeded["profile"],
            job_type="scenario",
            job_name="加装避雷器复算",
            risk_level="low",
            result_json={
                "risk_level": "low",
                "summary_text": "复算完成",
                "score": 14,
                "counterstrike_withstand_ka": 112.45,
                "counterstrike_trip_rate": 0.0215,
                "shielding_withstand_ka": 136.2,
                "shielding_trip_rate": 0.0085,
            },
            execution_options_json={
                "source_job_id": seeded["mitigation_job"].id,
                "source_run_id": seeded["mitigation_run"].id,
                "source_job_type": "mitigation",
                "mitigation_job_id": seeded["mitigation_job"].id,
                "mitigation_run_id": seeded["mitigation_run"].id,
                "risk_job_id": seeded["risk_job"].id,
                "risk_run_id": seeded["risk_run"].id,
                "base_job_id": seeded["base_job"].id,
                "base_run_id": seeded["base_run"].id,
                "base_job_type": "normal",
                "base_job_name": seeded["base_job"].job_name,
            },
        )
        session.commit()

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=seeded["line"].id,
                job_name="效果报告",
                job_type="report",
                execution_options_json={
                    "source_job_id": seeded["mitigation_job"].id,
                    "selected_tower_ids": [seeded["tower"].id],
                },
            ),
            actor=SimpleNamespace(id="tester"),
        )

        assert created.job.execution_options_json["scenario_job_id"] == scenario_job.id
        assert created.job.execution_options_json["scenario_run_id"] == scenario_run.id

        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        session.close()
        fl_analysis_service.execute_job(created.job.id)

        verify_session = testing_session()
        try:
            report_job = fl_analysis_service.get_job_by_id(verify_session, created.job.id)
            assert report_job is not None
            assert report_job.status == "success"
            assert report_job.result_summary_json["scenario_row_count"] == 1
            assert report_job.result_summary_json["has_scenario_data"] is True
            assert report_job.result_summary_json["post_recalc_risk_counts"] == {"high": 0, "medium": 0, "low": 1}

            filename, content = fl_analysis_service.download_report_document(verify_session, job_id=created.job.id)
        finally:
            verify_session.close()

        html = content.decode("utf-8")
        assert filename.endswith(".doc")
        assert "表14 采取措施后的计算结果表" in html
        assert "加装避雷器复算" in html
        assert "112.45" in html
    finally:
        session.close()
