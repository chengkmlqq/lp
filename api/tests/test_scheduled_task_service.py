from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.audit_log import AuditLog
from app.models.scheduled_task import ScheduledTask
from app.schemas.scheduled_task import ScheduledTaskCreateRequest, ScheduledTaskUpdateRequest
from app.services.scheduled_task_service import (
    cleanup_audit_logs,
    compute_next_run_at,
    create_scheduled_task,
    get_scheduled_task_by_key,
    seed_default_scheduled_tasks,
    update_scheduled_task,
)


def _build_sessionmaker(*tables):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=list(tables))
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_seed_default_scheduled_tasks_creates_syslog_cleanup_task() -> None:
    testing_session = _build_sessionmaker(ScheduledTask.__table__)
    session: Session = testing_session()
    try:
        seed_default_scheduled_tasks(session)
        created = get_scheduled_task_by_key(session, "syslog.cleanup.default")
        assert created is not None
        assert created.task_type == "syslog_cleanup"
        assert created.enabled is True
        assert created.retain_days == 30
        assert created.next_run_at is not None
    finally:
        session.close()


def test_create_and_update_scheduled_task_recomputes_next_run() -> None:
    testing_session = _build_sessionmaker(ScheduledTask.__table__)
    session: Session = testing_session()
    try:
        created = create_scheduled_task(
            session,
            ScheduledTaskCreateRequest(
                task_key="syslog.cleanup.weekly",
                name="每周日志清理",
                task_type="syslog_cleanup",
                description="weekly cleanup",
                cron_expression="0 2 * * 1",
                timezone="Asia/Shanghai",
                retain_days=14,
                enabled=True,
            ),
            actor_user_id=None,
        )
        assert created is not None
        original_next_run = created.next_run_at
        assert original_next_run is not None

        updated = update_scheduled_task(
            session,
            created.id,
            ScheduledTaskUpdateRequest(cron_expression="0 4 * * 1", retain_days=21),
            actor_user_id=None,
        )
        assert updated is not None
        assert updated.retain_days == 21
        assert updated.next_run_at is not None
        assert updated.next_run_at != original_next_run
    finally:
        session.close()


def test_cleanup_audit_logs_only_removes_expired_rows() -> None:
    testing_session = _build_sessionmaker(AuditLog.__table__)
    session: Session = testing_session()
    try:
        expired = AuditLog(user_id=None, action="expired", detail="old")
        fresh = AuditLog(user_id=None, action="fresh", detail="new")
        session.add_all([expired, fresh])
        session.flush()
        expired.created_at = expired.created_at - timedelta(days=45)
        fresh.created_at = fresh.created_at - timedelta(days=5)
        session.commit()

        deleted_count = cleanup_audit_logs(session, retain_days=30)
        session.commit()

        assert deleted_count == 1
        remaining_actions = session.scalars(select(AuditLog.action).order_by(AuditLog.id.asc())).all()
        assert remaining_actions == ["fresh"]
    finally:
        session.close()


def test_compute_next_run_at_returns_future_utc_timestamp() -> None:
    next_run = compute_next_run_at("0 3 * * *", "Asia/Shanghai", from_time=None)
    assert next_run.tzinfo is not None
    assert next_run > datetime.now(timezone.utc)
