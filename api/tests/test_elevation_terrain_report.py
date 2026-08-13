"""
LP-314: ctb worker 任务状态回执（report_ctb_task_state）的单元测试。

- report_ctb_task_state 任务把 ctb worker 上报的状态转发到 elevation_service。
- execute_file_record_terrain_state_report 把状态写入 celery_task_history，
  并在 FAILURE 时把文件记录标记为 failed。
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.elevation import ElevationFileRecord
from app.models.task_history import TaskHistory
from app.services import elevation_service
from app.tasks import elevation_tasks


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            ElevationFileRecord.__table__,
            TaskHistory.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _patch_sessions(monkeypatch, factory) -> None:
    from app.core import task_history_signals

    monkeypatch.setattr(elevation_service, "SessionLocal", factory)
    monkeypatch.setattr(task_history_signals, "SessionLocal", factory)


def _make_record(session: Session) -> ElevationFileRecord:
    record = ElevationFileRecord(
        file_name="record.tif",
        file_path="/elevation/records/ab/cd/record.tif",
        file_format="tif",
        file_size=32,
        mount_code="default",
        status="active",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def test_report_task_forwards_to_service(monkeypatch) -> None:
    called = {}

    def fake_report(**kwargs):
        called.update(kwargs)

    monkeypatch.setattr(elevation_service, "execute_file_record_terrain_state_report", fake_report)
    result = elevation_tasks.report_ctb_task_state.run(
        ctb_task_id="ctb-1",
        record_id="rec-1",
        state="STARTED",
    )
    assert result == {"record_id": "rec-1", "state": "STARTED"}
    assert called == {
        "ctb_task_id": "ctb-1",
        "record_id": "rec-1",
        "state": "STARTED",
        "error": None,
        "result": None,
    }


def test_started_report_upserts_task_history(monkeypatch) -> None:
    factory = _build_session_factory()
    _patch_sessions(monkeypatch, factory)

    elevation_service.execute_file_record_terrain_state_report(
        ctb_task_id="ctb-1",
        record_id="rec-1",
        state="STARTED",
    )
    with factory() as s:
        row = s.execute(
            select(TaskHistory).where(TaskHistory.task_id == "ctb-1")
        ).scalar_one()
    assert row.state == "STARTED"
    assert row.name == "app.tasks.ctb.build_file_record_terrain"
    assert row.started_at is not None


def test_failure_report_marks_record_failed_and_upserts_history(monkeypatch) -> None:
    factory = _build_session_factory()
    _patch_sessions(monkeypatch, factory)
    with factory() as s:
        record = _make_record(s)
        record_id = record.id

    elevation_service.execute_file_record_terrain_state_report(
        ctb_task_id="ctb-1",
        record_id=record_id,
        state="FAILURE",
        error="DEM not found: /data/app/temp/rec-1.tif",
    )
    with factory() as s:
        row = s.execute(
            select(TaskHistory).where(TaskHistory.task_id == "ctb-1")
        ).scalar_one()
        record = s.execute(
            select(ElevationFileRecord).where(ElevationFileRecord.id == record_id)
        ).scalar_one()
    assert row.state == "FAILURE"
    assert row.error == "DEM not found: /data/app/temp/rec-1.tif"
    assert record.terrain_status == "failed"
    assert record.terrain_error_message == "DEM not found: /data/app/temp/rec-1.tif"
