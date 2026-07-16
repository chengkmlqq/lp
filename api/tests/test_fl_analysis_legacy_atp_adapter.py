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


def test_execute_job_runs_legacy_atp_adapter(monkeypatch, tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            fl_analysis_service,
            "resolve_legacy_atp_job",
            lambda **_: SimpleNamespace(
                template_identifier="fanji-template",
                calculation_mode="fanji",
                template_dir=tmp_path / "fanji",
            ),
        )
        monkeypatch.setattr(
            fl_analysis_service,
            "execute_legacy_atp_tower_analysis",
            lambda *_args, **kwargs: SimpleNamespace(
                result_json={
                    **kwargs["baseline_result"],
                    "risk_level": "medium",
                    "risk_grade": 2,
                    "summary_text": "legacy ATP执行完成",
                    "counterstrike_withstand_ka": 18.5,
                    "external_execution": {
                        "adapter": "legacy_atp",
                        "template_identifier": "fanji-template",
                    },
                },
                engine_command="wine /data/wine/ATP/tpbig.exe sample.atp",
                working_dir=str(tmp_path / "runs" / "tower-1"),
                stdout_text="legacy stdout",
                stderr_text="legacy stderr",
            ),
        )

        line = Line(
            code="L-LEGACY-1",
            name="Legacy线路",
            voltage_kv=220,
            lightning_param_json={"雷电流幅值a": 31.0, "雷电流幅值b": 2.6},
        )
        session.add(line)
        session.flush()

        tower = LineTower(
            line_id=line.id,
            seq_no=1,
            tower_no="N1",
            tower_model="220-TEST-ZX",
            tower_type="直线",
            altitude_m=1680.0,
            ground_resistance_ohm=12.0,
            lightning_density=3.2,
            span_large_m=260.0,
            slope_1=3.0,
            slope_2=1.5,
            circuit_geometry_json={
                "I": {
                    "phase_spacing_m": {"upper": 9.0, "middle": 4.5, "lower": 8.5},
                    "phase_height_m": {"upper": 29.0, "middle": 31.0, "lower": 25.0},
                },
                "lightning_wire": {
                    "left_mid_distance_m": 9.0,
                    "right_mid_distance_m": 9.0,
                    "height_m": 41.0,
                },
                "insulator_length_mm": 4200.0,
            },
            lightning_result_json={},
        )
        session.add(tower)
        session.flush()

        session.add(
            TowerProfile(
                tower_id=tower.id,
                structure_kind="直线",
                arrester_a="是",
                arrester_b="否",
                arrester_c="是",
                shield_wire_height_m=41.0,
                insulator_length_m=4200.0,
                current_a=31.0,
                current_b=2.6,
                current_type="Heidler",
                current_head_time_us=2.6,
                current_tail_time_us=50.0,
            )
        )
        session.commit()

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="普通计算-LegacyATP",
                job_type="normal",
                external_adapter="legacy_atp",
                adapter_config_json={"template_subdir": "fanji"},
                execution_options_json={
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
            ),
            actor=SimpleNamespace(id="tester"),
        )
        session.close()

        fl_analysis_service.execute_job(created.job.id)

        verify_session: Session = testing_session()
        try:
            saved_job = fl_analysis_service.get_job_by_id(verify_session, created.job.id)
            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_job.result_summary_json["adapter_status"] == "executed"
            assert saved_job.result_summary_json["external_engine_adapter"] == "legacy_atp"
            assert saved_job.result_summary_json["external_model_id"] == "fanji-template"

            result_row = verify_session.execute(
                select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == created.job.id)
            ).scalar_one()
            assert result_row.risk_level == "medium"
            assert result_row.summary_text == "legacy ATP执行完成"
            assert result_row.result_json["counterstrike_withstand_ka"] == 18.5
            assert result_row.result_json["external_execution"]["adapter"] == "legacy_atp"

            saved_run = verify_session.execute(
                select(FlAnalysisRun).where(FlAnalysisRun.job_id == created.job.id)
            ).scalar_one()
            assert saved_run.status == "success"
            assert saved_run.runner_kind == "legacy_atp"
            assert saved_run.engine_command == "wine /data/wine/ATP/tpbig.exe sample.atp"
            assert saved_run.stdout_text is not None
            assert saved_run.stderr_text is not None
        finally:
            verify_session.close()
    finally:
        session.close()
