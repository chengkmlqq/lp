from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_model import AtpModel, AtpModelVersion, AtpSimulationRun
from app.models.fl_analysis import FlAnalysisJob, FlAnalysisRun, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services import fl_analysis_external, fl_analysis_service


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
            AtpModel.__table__,
            AtpModelVersion.__table__,
            AtpSimulationRun.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_render_atp_template_supports_binding_formats_and_defaults() -> None:
    rendered = fl_analysis_external.render_atp_template(
        "R={{GROUND_RES}}\nHEAD={{profile.current_head_time_us|F1|6|2.6}}\nNAME={{snapshot.tower_no}}",
        context={
            "snapshot": {"tower_no": "N-01"},
            "base_tower": {"ground_resistance_ohm": 12.34},
            "profile": {},
        },
        parameter_bindings={
            "GROUND_RES": {
                "path": "base_tower.ground_resistance_ohm",
                "format": "F1",
                "width": 6,
            }
        },
    )

    assert "R=  12.3" in rendered
    assert "HEAD=   2.6" in rendered
    assert "NAME=N-01" in rendered


def test_execute_job_runs_external_adapter_and_backfills_results(monkeypatch, tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(fl_analysis_external, "_resolve_engine_workdir", lambda: tmp_path)
        monkeypatch.setattr(fl_analysis_external, "_resolve_native_engine_executable", lambda: ("/bin/sh", None))

        line = Line(
            code="L-001",
            name="示例线路",
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

        model = AtpModel(code="fl-normal-model", name="普通计算ATP模型", source_type="atp", status="enabled")
        session.add(model)
        session.flush()

        session.add(
            AtpModelVersion(
                model_id=model.id,
                version_no=1,
                status="released",
                entry_file="runner.sh",
                artifact_manifest_json={
                    "fl_analysis": {
                        "result_file": "result.json",
                        "parameter_bindings": {
                            "GROUND_RES": {
                                "path": "base_tower.ground_resistance_ohm",
                                "format": "F1",
                            }
                        },
                    }
                },
                atp_text="""#!/bin/sh
cat > result.json <<'JSON'
{"counterstrike_withstand_ka": {{GROUND_RES}}, "risk_grade": 3, "score": 91, "summary_text": "ATP执行完成"}
JSON
""",
                content_hash="normal-v1",
            )
        )
        session.commit()

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="普通计算-ATP",
                job_type="normal",
                external_adapter="atp",
                adapter_config_json={"model_id": model.id},
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
            assert saved_job.result_summary_json["external_model_code"] == "fl-normal-model"
            assert saved_job.result_summary_json["external_version_no"] == 1

            result_row = verify_session.execute(
                select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == created.job.id)
            ).scalar_one()
            assert result_row.risk_level == "high"
            assert result_row.summary_text == "ATP执行完成"
            assert result_row.result_json["counterstrike_withstand_ka"] == 12.0
            assert result_row.result_json["external_execution"]["adapter"] == "atp"
            assert result_row.result_json["external_execution"]["model_code"] == "fl-normal-model"

            saved_run = verify_session.execute(
                select(FlAnalysisRun).where(FlAnalysisRun.job_id == created.job.id)
            ).scalar_one()
            assert saved_run.status == "success"
            assert saved_run.runner_kind == "atp"
            assert saved_run.engine_command is not None
            assert saved_run.working_dir is not None
        finally:
            verify_session.close()
    finally:
        session.close()
