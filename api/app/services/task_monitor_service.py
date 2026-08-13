from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import desc

from ..core.config import get_settings
from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.task_history import TaskHistory
from ..schemas.task_monitor import (
    TaskMonitorBucketItem,
    TaskMonitorOverviewResponse,
    TaskMonitorQueueItem,
    TaskMonitorTaskItem,
)

STATE_LABELS = {
    "PENDING": "待执行",
    "RECEIVED": "已接收",
    "STARTED": "执行中",
    "SCHEDULED": "定时中",
    "RETRY": "重试中",
    "SUCCESS": "成功",
    "FAILURE": "失败",
    "REVOKED": "已撤销",
}

STATE_PRIORITY = {
    "STARTED": 0,
    "RECEIVED": 1,
    "SCHEDULED": 2,
    "RETRY": 3,
    "FAILURE": 4,
    "SUCCESS": 5,
    "REVOKED": 6,
    "PENDING": 7,
}

logger = logging.getLogger(__name__)


def _load_db_task_history(*, limit: int) -> list[TaskMonitorTaskItem]:
    """Load task records from PostgreSQL. Returns empty list on DB errors."""
    try:
        db = SessionLocal()
        try:
            records = (
                db.query(TaskHistory)
                .order_by(desc(TaskHistory.create_date))
                .limit(limit)
                .all()
            )
            return [
                TaskMonitorTaskItem(
                    task_id=r.task_id,
                    name=r.name or "",
                    state=r.state,
                    queue_name=r.queue_name,
                    worker=r.worker,
                    retries=r.retries,
                    eta=r.eta,
                    started_at=r.started_at,
                    done_at=r.done_at,
                    runtime_seconds=r.runtime_seconds,
                    error=r.error,
                )
                for r in records
            ]
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to load task history from database")
        return []


def _safe_queue_pending_counts(queue_names: Iterable[str]) -> dict[str, int]:
    """Read pending message counts (LLEN) from the Redis broker queue keys.

    Returns {} on any error; missing/empty keys count as 0. Best-effort:
    queue stats must never crash the overview endpoint.
    """
    names = list(queue_names)
    if not names:
        return {}
    try:
        import redis as redis_lib

        settings = get_settings()
        broker = settings.resolved_celery_broker_url
        if not broker.startswith("redis://"):
            return {}
        client = redis_lib.from_url(broker)
        try:
            pipe = client.pipeline(transaction=False)
            for name in names:
                pipe.llen(name)
            counts = pipe.execute()
        finally:
            client.close()
        return {name: int(count or 0) for name, count in zip(names, counts)}
    except Exception:
        logger.exception("Failed to read queue pending counts from Redis broker")
        return {}


def build_task_monitor_overview(*, task_limit: int, history_limit: int) -> TaskMonitorOverviewResponse:
    """Build the task monitor overview purely from the task history database.

    Flower is no longer involved: running tasks are already persisted to
    celery_task_history by the celery signals (on_task_prerun writes STARTED),
    so polling this endpoint every ~5s gives near-real-time state.
    """
    db_tasks = _load_db_task_history(limit=max(task_limit, history_limit))

    # 队列统计：基于 DB 任务的 queue_name（STARTED 计 active）
    queue_runtime_counts: dict[str, dict[str, int]] = {}
    queue_names: set[str] = set()
    for task in db_tasks:
        if not task.queue_name:
            continue
        queue_names.add(task.queue_name)
        bucket = queue_runtime_counts.setdefault(
            task.queue_name,
            {"active": 0, "reserved": 0, "scheduled": 0},
        )
        if task.state == "STARTED":
            bucket["active"] += 1

    pending_counts = _safe_queue_pending_counts(queue_names)

    queues = sorted(
        [
            TaskMonitorQueueItem(
                name=name,
                pending_count=pending_counts.get(name, 0),
                consumer_count=0,
                active_count=queue_runtime_counts.get(name, {}).get("active", 0),
                reserved_count=0,
                scheduled_count=0,
            )
            for name in sorted(queue_names)
        ],
        key=lambda item: (-item.active_count - item.reserved_count - item.scheduled_count, item.name),
    )

    settings = get_settings()

    all_tasks = sorted(
        db_tasks,
        key=lambda item: (
            _task_priority(item.state),
            -_task_sort_timestamp(item).timestamp(),
            item.task_id,
        ),
    )

    return TaskMonitorOverviewResponse(
        generated_at=utcnow(),
        broker_url=settings.resolved_celery_broker_url,
        result_backend=settings.resolved_celery_result_backend,
        workers_online=0,
        worker_concurrency_total=0,
        queue_pending_total=sum(item.pending_count for item in queues),
        task_state_buckets=_build_state_buckets(all_tasks),
        workers=[],
        queues=queues,
        tasks=all_tasks[:task_limit],
    )


def _build_state_buckets(tasks: Iterable[TaskMonitorTaskItem]) -> list[TaskMonitorBucketItem]:
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.state] = counts.get(task.state, 0) + 1
    return [
        TaskMonitorBucketItem(key=state, label=STATE_LABELS.get(state, state), count=count)
        for state, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _task_priority(state: str) -> int:
    normalized = (state or "").strip().upper()
    return STATE_PRIORITY.get(normalized, 99)


def _task_sort_timestamp(item: TaskMonitorTaskItem) -> datetime:
    for candidate in [item.started_at, item.done_at, item.eta]:
        if candidate is not None:
            return candidate
    return datetime.fromtimestamp(0, tz=timezone.utc)
