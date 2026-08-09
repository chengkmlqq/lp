"""
Unit tests for worker_registry_service (LP-282).

The heartbeat_sent signal calls register_worker(heartbeat_increment=True) on
every heartbeat. Historically that bumped heartbeat_count without limit. After
LP-282 the count is no longer incremented per heartbeat — worker_ready
(heartbeat_increment=False) still initialises the baseline, and the count must
stay stable across repeated heartbeats.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.worker_registry import WorkerRegistry
from app.services import worker_registry_service as mod


@pytest.fixture()
def session():
    """Fresh in-memory sqlite with only the WorkerRegistry table, and a bound SessionLocal."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[WorkerRegistry.__table__])
    SessionLocal = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    mod.SessionLocal = SessionLocal
    yield SessionLocal
    engine.dispose()


def _get(session, worker_name: str) -> WorkerRegistry:
    return session.execute(
        select(WorkerRegistry).where(WorkerRegistry.worker_name == worker_name)
    ).scalar_one()


class TestRegisterWorkerHeartbeatCount:
    def test_worker_ready_initialises_count(self, session):
        mod.register_worker(
            worker_name="celery@worker-1",
            status="online",
            queues=["default"],
            heartbeat_increment=False,
        )
        with session() as s:
            row = _get(s, "celery@worker-1")
        assert row.status == "online"
        assert row.heartbeat_count == 0

    def test_repeated_heartbeats_do_not_increment_count(self, session):
        mod.register_worker(
            worker_name="celery@worker-1",
            status="online",
            heartbeat_increment=False,
        )
        for _ in range(5):
            mod.register_worker(
                worker_name="celery@worker-1",
                status="online",
                heartbeat_increment=True,
            )
        with session() as s:
            row = _get(s, "celery@worker-1")
        assert row.heartbeat_count == 0

    def test_heartbeat_updates_last_seen(self, session):
        mod.register_worker(
            worker_name="celery@worker-1",
            status="online",
            heartbeat_increment=False,
        )
        with session() as s:
            first_seen = _get(s, "celery@worker-1").last_seen_at
        mod.register_worker(
            worker_name="celery@worker-1",
            status="online",
            heartbeat_increment=True,
        )
        with session() as s:
            row = _get(s, "celery@worker-1")
        assert row.last_seen_at is not None
        assert row.last_seen_at >= first_seen
        assert row.heartbeat_count == 0


class TestRegisterWorkerCreate:
    def test_new_worker_registers_online(self, session):
        mod.register_worker(
            worker_name="ctb@worker-2",
            status="online",
            queues=["default", "high"],
            heartbeat_increment=False,
            metadata={"event": "worker_ready"},
        )
        with session() as s:
            row = _get(s, "ctb@worker-2")
        assert row.status == "online"
        assert row.queues_csv == "default,high"
        assert row.metadata_json is not None
        assert row.heartbeat_count == 0

    def test_empty_worker_name_is_ignored(self, session):
        mod.register_worker(worker_name="  ", status="online")
        with session() as s:
            rows = s.execute(select(WorkerRegistry)).scalars().all()
        assert rows == []
