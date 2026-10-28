"""
Unit tests for celery task history upsert (LP-186).

The race: after_task_publish (PENDING, producer process) and task_prerun
(STARTED, worker process) touch the same task_id nearly simultaneously.
The old implementation did a non-atomic SELECT-then-INSERT which could raise
UniqueViolation when both saw no row and then inserted.  The fix switches
_upsert_task to INSERT ... ON CONFLICT (task_id) DO UPDATE.

Also covers SYSTEM_TASK_NAMES / _is_system_task (LP-281): beat system tasks
must be short-circuited at the signal layer so they never enter
celery_task_history nor trigger TaskLogCapture.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import task_history_signals as mod
from app.core.database import Base
from app.models.task_history import TaskHistory


@pytest.fixture()
def session():
    """Fresh in-memory sqlite with only the TaskHistory table, and a bound SessionLocal."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[TaskHistory.__table__])
    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    mod.SessionLocal = SessionLocal
    yield SessionLocal
    engine.dispose()


def _get(session: Session, task_id: str) -> TaskHistory:
    return session.execute(
        select(TaskHistory).where(TaskHistory.task_id == task_id)
    ).scalar_one()


class TestUpsertTask:
    def test_insert_new_record(self, session):
        mod._upsert_task("task-1", name="export", state="PENDING", retries=0)
        with session() as s:
            record = _get(s, "task-1")
        assert record.name == "export"
        assert record.state == "PENDING"
        assert record.retries == 0
        assert record.started_at is None

    def test_update_existing_record_preserves_other_fields(self, session):
        mod._upsert_task("task-1", name="export", state="PENDING", retries=0)
        started_at = datetime(2026, 8, 2, 1, 0, 0, tzinfo=timezone.utc)
        # STARTED only writes state/started_at; name/retries must survive.
        mod._upsert_task("task-1", state="STARTED", started_at=started_at)
        with session() as s:
            record = _get(s, "task-1")
        assert record.state == "STARTED"
        assert record.started_at is not None
        assert record.name == "export"
        assert record.retries == 0

    def test_repeated_upserts_never_raise_unique_violation(self, session):
        """The published PENDING + execution STARTED/SUCCESS sequence must be idempotent."""
        started_at = datetime(2026, 8, 2, 1, 0, 0, tzinfo=timezone.utc)
        done_at = datetime(2026, 8, 2, 1, 5, 0, tzinfo=timezone.utc)
        mod._upsert_task("task-race", name="race", state="PENDING")
        mod._upsert_task("task-race", state="STARTED", started_at=started_at)
        mod._upsert_task(
            "task-race",
            state="SUCCESS",
            done_at=done_at,
            runtime_seconds=300.0,
        )
        with session() as s:
            record = _get(s, "task-race")
        assert record.state == "SUCCESS"
        assert record.started_at is not None
        assert record.runtime_seconds == pytest.approx(300.0)
        assert record.name == "race"

    def test_none_fields_do_not_clobber_existing_values(self, session):
        mod._upsert_task("task-1", name="export", state="PENDING", retries=0)
        mod._upsert_task(
            "task-1",
            state="SUCCESS",
            runtime_seconds=42.0,
            error=None,
            name=None,
        )
        with session() as s:
            record = _get(s, "task-1")
        assert record.state == "SUCCESS"
        assert record.runtime_seconds == pytest.approx(42.0)
        assert record.name == "export"

    def test_update_refreshes_update_date(self, session):
        mod._upsert_task("task-1", state="PENDING")
        with session() as s:
            first_update_date = _get(s, "task-1").update_date
        mod._upsert_task("task-1", state="STARTED")
        with session() as s:
            record = _get(s, "task-1")
        assert record.update_date is not None
        assert record.update_date != first_update_date

    def test_created_record_gets_default_dates(self, session):
        mod._upsert_task("task-1", state="PENDING")
        with session() as s:
            record = _get(s, "task-1")
        assert record.create_date is not None
        assert record.update_date is not None


class TestIsSystemTask:
    """LP-281: beat 系统任务在被信号层拦截时需要被准确识别。"""

    @pytest.mark.parametrize(
        "task_name",
        [
            "app.tasks.worker_registry_tasks.flush_task_log_buffers",
            "app.tasks.worker_registry_tasks.sweep_worker_registry_offline",
            "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks",
            "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
            "app.tasks.lightning_tasks.cleanup_lightning_temp_files",
        ],
    )
    def test_hits_blacklist(self, task_name):
        assert mod._is_system_task(task_name) is True

    @pytest.mark.parametrize(
        "task_name",
        [
            "app.tasks.export.export_task",
            "app.core.something.unrelated",
            "app.tasks.worker_registry_tasks.flush_task_log_buffers_extra",
            "app.tasks.worker_registry_tasks.flush_task_log_buffersx",
            "",
        ],
    )
    def test_non_system_task_names(self, task_name):
        assert mod._is_system_task(task_name) is False

    def test_none_task_name(self):
        assert mod._is_system_task(None) is False

    def test_blacklist_is_frozenset_of_str(self):
        assert isinstance(mod.SYSTEM_TASK_NAMES, frozenset)
        assert all(isinstance(name, str) for name in mod.SYSTEM_TASK_NAMES)
        assert len(mod.SYSTEM_TASK_NAMES) == 5
