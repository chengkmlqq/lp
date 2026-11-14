from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fl_analysis import FlAnalysisJob, FlAnalysisRun, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
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
            TowerCircuit.__table__,
            TowerLightningResult.__table__,
            TowerAnalysis.__table__,
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
    )
    session.add(tower)
    session.flush()

    session.add(
        TowerCircuit(
            tower_id=tower.id,
            circuit_no=1,
            phase_sequence="ABC",
            spacing_upper_m=9.0,
            spacing_middle_m=4.5,
            spacing_lower_m=8.5,
            height_upper_m=29.0,
            height_middle_m=31.0,
            height_lower_m=25.0,
        )
    )
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


def test_list_jobs_keyword_and_offset_pagination() -> None:
    testing_session = _build_sessionmaker()
    session = testing_session()
    try:
        line_a = Line(code="LA-001", name="甲线路", voltage_kv=110)
        line_b = Line(code="LB-002", name="乙线路", voltage_kv=220)
        session.add_all([line_a, line_b])
        session.flush()

        for idx in range(1, 6):
            session.add(
                FlAnalysisJob(
                    line_id=line_a.id,
                    job_name=f"普通计算{idx}",
                    job_type="normal",
                    status="success",
                    source_kind="line",
                    total_tower_count=1,
                    external_adapter="placeholder",
                    execution_options_json={},
                    result_summary_json={},
                )
            )
        session.add(
            FlAnalysisJob(
                line_id=line_b.id,
                job_name="风险评估",
                job_type="risk",
                status="success",
                source_kind="line",
                total_tower_count=1,
                external_adapter="placeholder",
                execution_options_json={},
                result_summary_json={},
            )
        )
        session.commit()

        # 按任务名关键字过滤
        matched = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="风险")
        assert matched.total == 1
        assert len(matched.items) == 1
        assert matched.items[0].job_name == "风险评估"

        # 按线路编码关键字过滤
        matched = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="LB-002")
        assert matched.total == 1
        assert matched.items[0].job_name == "风险评估"

        # 按线路名称关键字过滤
        matched = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="甲线路")
        assert matched.total == 5

        # 关键字空白串视为不过滤
        matched = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="   ")
        assert matched.total == 6

        # offset/limit 翻页且 total 为过滤后总数
        page1 = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="普通计算", limit=2, offset=0)
        assert page1.total == 5
        assert len(page1.items) == 2
        page2 = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="普通计算", limit=2, offset=2)
        assert len(page2.items) == 2
        page3 = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, keyword="普通计算", limit=2, offset=4)
        assert len(page3.items) == 1
        page_ids = {job.id for job in (page1.items + page2.items + page3.items)}
        assert len(page_ids) == 5

        # 无关键字时 offset 同样生效
        first_page = fl_analysis_service.list_jobs(session, line_id=None, status_filter=None, limit=2, offset=0)
        assert first_page.total == 6
        assert len(first_page.items) == 2
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


# ---- LP-18：绕击(raoji1/2/3) ATP 资产落库 ----

def test_raoji_asset_record_serializes_identity_and_dimensions() -> None:
    asset = SimpleNamespace(
        id="asset-raoji3-v2",
        code="ATP750-jiubei-raoji3-M2",
        name="酒杯塔绕击C相模型",
        model_id="model-m2",
        version="v2",
        version_code="ATP750-jiubei-raoji3-M2-v2",
        voltage_level="750",
        tower_type="jiubei",
        scene_type="raoji3",
        arrester_config="noM",
        shield_wire="with",
    )
    rec = fl_analysis_service._raoji_asset_record(asset, "raoji3")
    assert rec["asset_id"] == "asset-raoji3-v2"
    assert rec["asset_code"] == "ATP750-jiubei-raoji3-M2"
    assert rec["asset_name"] == "酒杯塔绕击C相模型"
    assert rec["model_id"] == "model-m2"
    assert rec["version"] == "v2"
    assert rec["version_code"] == "ATP750-jiubei-raoji3-M2-v2"
    assert rec["scene_type"] == "raoji3"
    assert rec["voltage_level"] == "750"
    assert rec["tower_type"] == "jiubei"
    assert rec["arrester_config"] == "noM"
    assert rec["shield_wire"] == "with"


def test_raoji_asset_record_tolerates_missing_attributes() -> None:
    # 资产对象缺列时降级为 None，不抛异常 → 不影响主计算流程
    rec = fl_analysis_service._raoji_asset_record(SimpleNamespace(id="x"), "raoji1")
    assert rec["asset_id"] == "x"
    assert rec["scene_type"] == "raoji1"
    assert rec["version"] is None
    assert rec["model_id"] is None


def _raoji_graded(phase_specs: dict[str, tuple[str, str, str]]) -> dict[str, object]:
    """phase_specs: {"A相": (asset_id, version, scene_type), ...}"""
    return {
        "risk_level": "low",
        "score": 10,
        "shielding_raoji_assets_by_phase": {
            phase: {
                "asset_id": aid,
                "asset_code": f"code-{aid}",
                "asset_name": f"name-{aid}",
                "model_id": f"model-{scene}",
                "version": ver,
                "version_code": f"{aid}-{ver}",
                "scene_type": scene,
                "voltage_level": "750",
                "tower_type": "jiubei",
                "arrester_config": "noM",
                "shield_wire": "with",
            }
            for phase, (aid, ver, scene) in phase_specs.items()
        },
    }


def test_accumulate_result_summary_aggregates_shielding_raoji_assets() -> None:
    summary = fl_analysis_service._new_result_summary()
    common = {
        "A相": ("raoji1-v2", "v2", "raoji1"),
        "B相": ("raoji2-v2", "v2", "raoji2"),
        "C相": ("raoji3-v2", "v2", "raoji3"),
    }
    # 塔1/塔2 同塔型 → 同一组绕击资产；塔3 的 B 相落到不同资产/版本
    tower3 = dict(common)
    tower3["B相"] = ("raoji2-v1-othertower", "v1", "raoji2")
    for graded in (_raoji_graded(common), _raoji_graded(common), _raoji_graded(tower3)):
        fl_analysis_service._accumulate_result_summary(summary, graded)

    models = summary["shielding_external_models"]
    by_id = {m["asset_id"]: m for m in models}
    assert set(by_id) == {"raoji1-v2", "raoji2-v2", "raoji3-v2", "raoji2-v1-othertower"}
    # 去重 + 命中塔数（每塔对同一资产只计一次）
    assert by_id["raoji1-v2"]["hit_tower_count"] == 3
    assert by_id["raoji2-v2"]["hit_tower_count"] == 2
    assert by_id["raoji3-v2"]["hit_tower_count"] == 3
    assert by_id["raoji2-v1-othertower"]["hit_tower_count"] == 1
    # 字段齐全、相位标签正确
    assert by_id["raoji1-v2"]["phase_labels"] == ["A相"]
    assert by_id["raoji1-v2"]["scene_type"] == "raoji1"
    assert by_id["raoji1-v2"]["version"] == "v2"
    assert by_id["raoji1-v2"]["version_code"] == "raoji1-v2-v2"
    assert by_id["raoji1-v2"]["voltage_level"] == "750"
    # 可按 version / scene_type 统计覆盖率：V1 一条、V2 三条；raoji2 两条
    assert sum(1 for m in models if m["version"] == "v1") == 1
    assert sum(1 for m in models if m["version"] == "v2") == 3
    assert sum(1 for m in models if m["scene_type"] == "raoji2") == 2
    # 既有汇总字段不受影响（反击 external_model_* 行为不变、无回归）
    assert summary["risk_counts"]["low"] == 3
    assert summary["score_total"] == 30


def test_accumulate_result_summary_without_raoji_and_same_asset_multi_phase() -> None:
    summary = fl_analysis_service._new_result_summary()
    # 无绕击资产时聚合保持空（规程法 / 纯反击任务）
    fl_analysis_service._accumulate_result_summary(summary, {"risk_level": "high", "score": 5})
    assert summary["shielding_external_models"] == []
    assert summary["risk_counts"]["high"] == 1

    # 同一塔内两相命中同一 asset_id 时，该资产命中塔数只计一次
    fl_analysis_service._accumulate_result_summary(
        summary,
        _raoji_graded({
            "A相": ("shared", "v1", "raoji1"),
            "B相": ("shared", "v1", "raoji2"),
            "C相": ("raoji3", "v2", "raoji3"),
        }),
    )
    by_id = {m["asset_id"]: m for m in summary["shielding_external_models"]}
    assert by_id["shared"]["hit_tower_count"] == 1
    assert by_id["shared"]["phase_labels"] == ["A相", "B相"]
    assert by_id["raoji3"]["hit_tower_count"] == 1
