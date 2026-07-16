from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc

from ..core.database import SessionLocal
from ..models.task_history import TaskHistory
from ..schemas.task_monitor import (
    TaskMonitorBucketItem,
    TaskMonitorOverviewResponse,
    TaskMonitorQueueItem,
    TaskMonitorTaskItem,
)
from .flower_monitor_service import build_worker_task_overview, build_workers_overview

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


def _load_db_task_history(*, limit: int) -> list[TaskMonitorTaskItem]:
    """Load all task records from PostgreSQL (primary data source for persistence across restarts)."""
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


def build_task_monitor_overview(*, task_limit: int, history_limit: int) -> TaskMonitorOverviewResponse:
    workers_overview = build_workers_overview(force_refresh=False)
    task_items: list[TaskMonitorTaskItem] = []
    queue_runtime_counts: dict[str, dict[str, int]] = {}
    queue_consumer_counts: dict[str, int] = {}

    for worker in workers_overview.workers:
        queue_names = worker.queue_names
        for queue_name in queue_names:
            queue_consumer_counts[queue_name] = queue_consumer_counts.get(queue_name, 0) + 1
            queue_runtime_counts.setdefault(
                queue_name,
                {"active": 0, "reserved": 0, "scheduled": 0},
            )

        worker_tasks = build_worker_task_overview(
            worker=worker.worker,
            force_refresh=False,
            recent_limit=max(history_limit, 1),
        )
        task_items.extend(_convert_flower_tasks(worker_tasks.active_tasks, source_state="STARTED"))
        task_items.extend(_convert_flower_tasks(worker_tasks.reserved_tasks, source_state="RECEIVED"))
        task_items.extend(_convert_flower_tasks(worker_tasks.scheduled_tasks, source_state="SCHEDULED"))
        task_items.extend(_convert_flower_tasks(worker_tasks.recent_tasks, source_state=None))

        for task in worker_tasks.active_tasks:
            if task.queue_name:
                queue_runtime_counts.setdefault(task.queue_name, {"active": 0, "reserved": 0, "scheduled": 0})
                queue_runtime_counts[task.queue_name]["active"] += 1
        for task in worker_tasks.reserved_tasks:
            if task.queue_name:
                queue_runtime_counts.setdefault(task.queue_name, {"active": 0, "reserved": 0, "scheduled": 0})
                queue_runtime_counts[task.queue_name]["reserved"] += 1
        for task in worker_tasks.scheduled_tasks:
            if task.queue_name:
                queue_runtime_counts.setdefault(task.queue_name, {"active": 0, "reserved": 0, "scheduled": 0})
                queue_runtime_counts[task.queue_name]["scheduled"] += 1

    # Load all task history from database first (primary source)
    db_tasks = _load_db_task_history(limit=max(task_limit, history_limit))
    all_tasks_by_id: dict[str, TaskMonitorTaskItem] = {}
    for item in db_tasks:
        if item.task_id:
            all_tasks_by_id[item.task_id] = item

    # Supplement with Flower's real-time active/reserved/scheduled tasks
    # (Flower data takes priority only for currently running tasks)
    runtime_tasks_by_id: dict[str, TaskMonitorTaskItem] = {}
    for item in task_items:
        if not item.task_id:
            continue
        # Only override database state if this is an active/running task from Flower
        if item.state in ("STARTED", "RECEIVED", "SCHEDULED"):
            runtime_tasks_by_id[item.task_id] = item
        else:
            # For completed tasks, keep existing entry or add new
            existing = runtime_tasks_by_id.get(item.task_id)
            if existing is None:
                runtime_tasks_by_id[item.task_id] = item
                continue
            if _task_priority(item.state) < _task_priority(existing.state):
                runtime_tasks_by_id[item.task_id] = item

    # Merge: database is primary, Flower runtime data supplements active tasks
    for task_id, flower_item in runtime_tasks_by_id.items():
        db_item = all_tasks_by_id.get(task_id)
        if db_item is None:
            all_tasks_by_id[task_id] = flower_item
        elif flower_item.state in ("STARTED", "RECEIVED", "SCHEDULED"):
            # Flower has more current state for active tasks
            all_tasks_by_id[task_id] = flower_item
        # Otherwise keep database record (it's more persistent)

    all_tasks = sorted(
        all_tasks_by_id.values(),
        key=lambda item: (
            _task_priority(item.state),
            -_task_sort_timestamp(item).timestamp(),
            item.task_id,
        ),
    )

    queues = sorted(
        [
            TaskMonitorQueueItem(
                name=name,
                pending_count=0,
                consumer_count=queue_consumer_counts.get(name, 0),
                active_count=queue_runtime_counts.get(name, {}).get("active", 0),
                reserved_count=queue_runtime_counts.get(name, {}).get("reserved", 0),
                scheduled_count=queue_runtime_counts.get(name, {}).get("scheduled", 0),
            )
            for name in sorted(set(queue_runtime_counts) | set(queue_consumer_counts))
        ],
        key=lambda item: (-item.active_count - item.reserved_count - item.scheduled_count, item.name),
    )

    return TaskMonitorOverviewResponse(
        generated_at=workers_overview.generated_at,
        broker_url="flower",
        result_backend="flower",
        workers_online=workers_overview.summary.online,
        worker_concurrency_total=sum(item.concurrency for item in workers_overview.workers),
        queue_pending_total=sum(item.pending_count for item in queues),
        task_state_buckets=_build_state_buckets(all_tasks_by_id.values()),
        workers=[
            {
                "worker": worker.worker,
                "online": worker.status == "ONLINE",
                "queue_names": worker.queue_names,
                "max_concurrency": worker.concurrency,
                "prefetch_count": worker.prefetch_count,
                "uptime_seconds": 0,
                "processed_total": worker.processed_count,
                "active_count": worker.active_count,
                "reserved_count": worker.reserved_count,
                "scheduled_count": worker.scheduled_count,
            }
            for worker in workers_overview.workers
        ],
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


def _convert_flower_tasks(tasks: list[Any], *, source_state: str | None) -> list[TaskMonitorTaskItem]:
    items: list[TaskMonitorTaskItem] = []
    for task in tasks:
        state = source_state or task.state
        items.append(
            TaskMonitorTaskItem(
                task_id=task.task_id,
                name=task.name,
                state=state,
                queue_name=task.queue_name,
                worker=task.worker,
                retries=0,
                eta=task.eta,
                started_at=task.started_at,
                done_at=task.finished_at,
                runtime_seconds=task.runtime_seconds,
                error=task.exception_text,
            )
        )
    return items


def _task_priority(state: str) -> int:
    normalized = (state or "").strip().upper()
    return STATE_PRIORITY.get(normalized, 99)


def _task_sort_timestamp(item: TaskMonitorTaskItem) -> datetime:
    for candidate in [item.started_at, item.done_at, item.eta]:
        if candidate is not None:
            return candidate
    return datetime.fromtimestamp(0, tz=timezone.utc)
