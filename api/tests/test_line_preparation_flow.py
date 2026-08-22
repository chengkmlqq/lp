from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fl_analysis import FlAnalysisJob
from app.models.lightning_amplitude import LightningAmplitude
from app.models.lightning_current_backfill import LightningCurrentBackfillTask
from app.models.line import Line
from app.models.line_amplitude_backfill import LineAmplitudeBackfill
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.schemas.lightning import LightningCurrentPreparationAsyncResponse, LightningCurrentPreparationRequest
from app.services import fl_analysis_service, lightning_service


def _build_session() -> Session:
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
            LightningAmplitude.__table__,
            LineAmplitudeBackfill.__table__,
            LightningCurrentBackfillTask.__table__,
            FlAnalysisJob.__table__,
        ],
    )
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return testing_session()


def test_prepare_line_lightning_current_backfills_profiles_and_line_state(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_line_change", lambda *args, **kwargs: None)
        # 新实现按地闪密度做法：从 MinIO 源文件实时解析，mock get_object 返回波形数据
        from app.services import minio_storage
        source_files: dict[str, bytes] = {
            "lightning/amplitude/source/a.csv": "0\n-18\n0\n".encode("utf-8"),
            "lightning/amplitude/source/b.csv": "0\n-32\n0\n".encode("utf-8"),
            "lightning/amplitude/source/c.csv": "0\n-46\n0\n".encode("utf-8"),
        }
        monkeypatch.setattr(minio_storage, "get_object", lambda key: source_files[key])

        line = Line(code="L-001", name="示例线路", voltage_kv=220, lightning_param_json={})
        session.add(line)
        session.flush()

        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="N1", longitude=120.0, latitude=30.0),
                LineTower(line_id=line.id, seq_no=2, tower_no="N2", longitude=120.001, latitude=30.001),
            ]
        )
        session.add_all(
            [
                LightningAmplitude(
                    event_id="LC-001",
                    source_object_key="lightning/amplitude/source/a.csv",
                    status="completed",
                    region_id="HB",
                ),
                LightningAmplitude(
                    event_id="LC-002",
                    source_object_key="lightning/amplitude/source/b.csv",
                    status="completed",
                    region_id="HB",
                ),
                LightningAmplitude(
                    event_id="LC-003",
                    source_object_key="lightning/amplitude/source/c.csv",
                    status="completed",
                    region_id="HB",
                ),
            ]
        )
        session.commit()

        response = lightning_service._execute_line_lightning_current_backfill(
            session,
            LightningCurrentPreparationRequest(line_id=line.id, region_id="HB"),
            actor_user_id="tester",
        )

        profiles = session.execute(select(TowerProfile).order_by(TowerProfile.tower_id.asc())).scalars().all()
        assert len(profiles) == 2
        assert all(profile.current_a == response.current_a for profile in profiles)
        assert all(profile.current_b == response.current_b for profile in profiles)
        assert response.created_profile_count == 2
        assert response.line.preparation_json["lightning_current"]["ready"] is True
        assert session.get(Line, line.id).lightning_param_json["雷电流幅值a"] == response.current_a
        assert session.get(Line, line.id).lightning_param_json["雷电流幅值b"] == response.current_b

        # LP-265：回填关联表应记录本次实际用到的 amplitude_ids（幂等）
        backfill_rows = session.execute(
            select(LineAmplitudeBackfill).where(LineAmplitudeBackfill.line_id == line.id)
        ).scalars().all()
        assert len(backfill_rows) == 3
        assert {row.amplitude_id for row in backfill_rows} == {
            amp_id for amp_id in session.execute(select(LightningAmplitude.id)).scalars().all()
        }
        assert all(row.current_a == response.current_a for row in backfill_rows)
        assert all(row.sampled_event_count == response.sampled_event_count for row in backfill_rows)
        assert all(row.prepared_by_user_id == "tester" for row in backfill_rows)
    finally:
        session.close()


def test_prepare_line_lightning_current_no_data_aborts(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_line_change", lambda *args, **kwargs: None)
        from app.services import minio_storage
        monkeypatch.setattr(minio_storage, "get_object", lambda key: (_ for _ in ()).throw(KeyError(key)))

        line = Line(code="L-001", name="示例线路", voltage_kv=220, lightning_param_json={})
        session.add(line)
        session.flush()
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="N1", longitude=120.0, latitude=30.0),
            ]
        )
        session.commit()

        with pytest.raises(HTTPException) as captured:
            lightning_service._execute_line_lightning_current_backfill(
                session,
                LightningCurrentPreparationRequest(line_id=line.id, region_id="HB"),
                actor_user_id="tester",
            )

        assert captured.value.status_code == 400
        assert "未找到可用于线路雷电流拟合的幅值记录" in str(captured.value.detail)
    finally:
        session.close()


def test_prepare_line_lightning_current_dispatch_creates_pending_task_and_sends(monkeypatch) -> None:
    """异步派发：API 层创建 pending 回填任务并 send_task，立即返回 task_id。"""
    session = _build_session()
    try:
        sent: dict = {}

        class FakeCeleryTask:
            def __init__(self, _id: str) -> None:
                self.id = _id

        def fake_send_task(name: str, kwargs: dict, queue: str) -> FakeCeleryTask:
            sent["name"] = name
            sent["kwargs"] = kwargs
            sent["queue"] = queue
            return FakeCeleryTask("celery-task-abc")

        import app.core.celery_app as celery_app_module

        monkeypatch.setattr(celery_app_module, "celery_app", fake_celery, raising=False)
        monkeypatch.setattr(lightning_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(code="L-100", name="异步线路", voltage_kv=220, lightning_param_json={})
        session.add(line)
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="N1", longitude=120.0, latitude=30.0))
        session.add(
            LightningAmplitude(
                event_id="LC-010",
                source_object_key="lightning/amplitude/source/x.csv",
                status="completed",
            )
        )
        session.commit()

        response = lightning_service.prepare_line_lightning_current(
            session,
            LightningCurrentPreparationRequest(line_id=line.id),
            actor_user_id="tester",
        )
        assert isinstance(response, LightningCurrentPreparationAsyncResponse)
        assert response.task_id == "celery-task-abc"
        assert response.line_id == line.id
        assert response.status == "processing"

        task_rows = session.execute(select(LightningCurrentBackfillTask)).scalars().all()
        assert len(task_rows) == 1
        assert task_rows[0].status == "processing"
        assert task_rows[0].task_id == "celery-task-abc"
        assert task_rows[0].prepared_by_user_id == "tester"

        assert sent["name"] == "app.tasks.lightning_tasks.prepare_line_lightning_current_job"
        assert sent["kwargs"]["line_id"] == line.id
        assert sent["kwargs"]["backfill_task_id"] == task_rows[0].id
        assert sent["queue"] == "celery"
    finally:
        session.close()


def test_fl_analysis_create_job_rejects_unprepared_line(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)

        line = Line(code="L-002", name="待分析线路", voltage_kv=500, lightning_param_json={})
        session.add(line)
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0))
        session.commit()

        with pytest.raises(HTTPException) as captured:
            fl_analysis_service.create_job(
                session,
                FlAnalysisJobCreateRequest(line_id=line.id, job_type="normal"),
                actor=SimpleNamespace(id="tester"),
            )

        assert captured.value.status_code == 400
        assert "雷电流幅值" in str(captured.value.detail)
        assert "地闪密度" in str(captured.value.detail)
        assert "地面倾角" in str(captured.value.detail)
    finally:
        session.close()
