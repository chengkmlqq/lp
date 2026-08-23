from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import delete as sa_delete
from sqlalchemy import desc, func, or_, select

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

# 任务中文显示名（需与 web/src/lib/celery-task-display.ts 的 TASK_NAME_LABELS 保持一致，
# 由 api/tests/test_task_monitor_service.py 的 TestTaskNameLabelMappingSync 同步校验）
TASK_NAME_LABELS = {
    "app.tasks.atp_asset_tasks.execute_atp_asset_run_job": "ATP 模型运行",
    "app.tasks.atp_asset_tasks.process_release_archive_upload": "ATP 版本归档处理",
    "app.tasks.elevation_tasks.analyze_elevation_file_record_job": "高程文件记录分析",
    "app.tasks.elevation_tasks.apply_elevation_for_line_job": "线路高程回填",
    "app.tasks.fl_analysis_tasks.execute_fl_analysis_job": "防雷分析计算",
    "app.tasks.fault_diagnosis_tasks.run_fault_diagnosis_task": "故障综合判别",
    "app.tasks.lightning_tasks.import_lightning_distribution_job": "地闪分布数据导入",
    "app.tasks.lightning_tasks.import_lightning_amplitude_job": "雷电流幅值数据导入",
    "app.tasks.lightning_tasks.render_lp_density_job": "LP 分区密度图绘制",
    "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs": "过期任务日志清理",
    "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks": "到期定时任务派发",
    "app.tasks.scheduled_task_tasks.execute_scheduled_task_job": "定时任务执行",
    "app.tasks.wine_tasks.execute_wine_run_job": "Wine 程序执行",
    "app.tasks.worker_registry_tasks.sweep_worker_registry_offline": "执行节点离线巡检",
    "app.tasks.worker_registry_tasks.flush_task_log_buffers": "任务日志缓冲落库",
}

logger = logging.getLogger(__name__)


def _keyword_condition(keyword: str | None):
    """Build a SQLAlchemy filter condition for keyword search.

    Matches the raw fields (task_id/name/queue_name/worker/state) plus the
    Chinese display names previously matched by the frontend (state label,
    task display name, "默认队列" for the default queue). Returns None when
    keyword is blank.
    """
    kw = (keyword or "").strip()
    if not kw:
        return None
    lowered = kw.lower()
    like = f"%{kw}%"

    conditions = [
        TaskHistory.task_id.ilike(like),
        TaskHistory.name.ilike(like),
        TaskHistory.queue_name.ilike(like),
        TaskHistory.worker.ilike(like),
        TaskHistory.state.ilike(like),
    ]

    # 状态中文标签（如"成功" -> SUCCESS）
    matched_states = [s for s, label in STATE_LABELS.items() if lowered in label.lower()]
    if matched_states:
        conditions.append(TaskHistory.state.in_(matched_states))

    # 队列显示名（celery/default -> "默认队列"）
    if lowered in "默认队列".lower():
        conditions.append(func.lower(TaskHistory.queue_name).in_(["celery", "default"]))

    # 任务中文显示名（如"ATP 模型运行" -> app.tasks...）
    matched_names = [n for n, label in TASK_NAME_LABELS.items() if lowered in label.lower()]
    if matched_names:
        conditions.append(TaskHistory.name.in_(matched_names))

    return or_(*conditions)


def _to_task_item(r: TaskHistory) -> TaskMonitorTaskItem:
    display_map = {
        "app.tasks.fl_analysis_tasks.execute_fl_analysis_job": "防雷计算任务",
        "app.tasks.lightning_tasks.prepare_line_lightning_current_job": "雷电流回填任务",
        "app.tasks.lightning_tasks.render_lp_density_job": "地闪密度绘图任务",
        "app.tasks.worker_registry_tasks.sweep_worker_registry_offline": "Worker 注册表清理",
        "app.tasks.worker_registry_tasks.flush_task_log_buffers": "日志缓冲区刷新",
        "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks": "定时任务调度",
    }
    return TaskMonitorTaskItem(
        task_id=r.task_id,
        name=r.name or "",
        display_name=display_map.get(r.name) if r.name else None,
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


def _load_db_task_history(
    *,
    offset: int,
    limit: int,
    keyword: str | None = None,
) -> list[TaskMonitorTaskItem]:
    """Load a page of task records from PostgreSQL. Returns empty list on DB errors."""
    try:
        db = SessionLocal()
        try:
            query = db.query(TaskHistory)
            cond = _keyword_condition(keyword)
            if cond is not None:
                query = query.filter(cond)
            records = (
                query.order_by(desc(TaskHistory.create_date), TaskHistory.task_id)
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [_to_task_item(r) for r in records]
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to load task history from database")
        return []


def _count_db_task_history(keyword: str | None = None) -> int:
    """Count task history records (optionally filtered by keyword). Returns 0 on DB errors."""
    try:
        db = SessionLocal()
        try:
            stmt = select(func.count()).select_from(TaskHistory)
            cond = _keyword_condition(keyword)
            if cond is not None:
                stmt = stmt.where(cond)
            return int(db.scalar(stmt) or 0)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to count task history in database")
        return 0


def _load_state_bucket_items(keyword: str | None = None) -> list[TaskMonitorBucketItem]:
    """Aggregate state buckets over the full filtered task set via SQL GROUP BY."""
    try:
        db = SessionLocal()
        try:
            query = db.query(TaskHistory.state, func.count(TaskHistory.task_id))
            cond = _keyword_condition(keyword)
            if cond is not None:
                query = query.filter(cond)
            rows = query.group_by(TaskHistory.state).all()
            counts = {state: count for state, count in rows}
            return [
                TaskMonitorBucketItem(key=state, label=STATE_LABELS.get(state, state), count=count)
                for state, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            ]
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to build task state buckets from database")
        return []


def _load_queue_runtime_stats(keyword: str | None = None) -> tuple[set[str], dict[str, int]]:
    """Aggregate queue runtime stats over the full filtered task set.

    Returns (queue_names, active_counts) where active_counts[queue] is the
    number of STARTED tasks. Used for queue list + Redis pending counts.
    """
    try:
        db = SessionLocal()
        try:
            query = db.query(
                TaskHistory.queue_name,
                TaskHistory.state,
                func.count(TaskHistory.task_id),
            )
            cond = _keyword_condition(keyword)
            if cond is not None:
                query = query.filter(cond)
            rows = query.group_by(TaskHistory.queue_name, TaskHistory.state).all()
            queue_names: set[str] = set()
            active_counts: dict[str, int] = {}
            for queue_name, state, count in rows:
                if not queue_name:
                    continue
                queue_names.add(queue_name)
                if state == "STARTED":
                    active_counts[queue_name] = active_counts.get(queue_name, 0) + int(count or 0)
            return queue_names, active_counts
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to load queue runtime stats from database")
        return set(), {}


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


def delete_task_history(task_id: str) -> bool:
    """Delete a task history record by task_id.

    Returns True if a row was deleted, False if the record does not exist or
    the database is unreachable (callers may treat both as "nothing to do").
    """
    try:
        db = SessionLocal()
        try:
            result = db.execute(sa_delete(TaskHistory).where(TaskHistory.task_id == task_id))
            db.commit()
            return bool(result.rowcount)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to delete task history %s", task_id)
        return False


def build_task_monitor_overview(
    *,
    offset: int,
    limit: int,
    keyword: str | None = None,
) -> TaskMonitorOverviewResponse:
    """Build the task monitor overview purely from the task history database.

    Server-side pagination: the task list is a stable-sorted page (create_date
    desc, task_id) fetched with offset/limit; keyword filtering happens in SQL.
    total is the filtered count. Aggregates (state buckets, queue stats) are
    computed over the full filtered set, independent of the page slice.
    """
    keyword = (keyword or "").strip() or None

    db_tasks = _load_db_task_history(offset=offset, limit=limit, keyword=keyword)
    total = _count_db_task_history(keyword=keyword)

    queue_names, queue_active_counts = _load_queue_runtime_stats(keyword=keyword)
    pending_counts = _safe_queue_pending_counts(queue_names)

    queues = sorted(
        [
            TaskMonitorQueueItem(
                name=name,
                pending_count=pending_counts.get(name, 0),
                consumer_count=0,
                active_count=queue_active_counts.get(name, 0),
                reserved_count=0,
                scheduled_count=0,
            )
            for name in sorted(queue_names)
        ],
        key=lambda item: (-item.active_count - item.reserved_count - item.scheduled_count, item.name),
    )

    settings = get_settings()

    return TaskMonitorOverviewResponse(
        generated_at=utcnow(),
        broker_url=settings.resolved_celery_broker_url,
        result_backend=settings.resolved_celery_result_backend,
        workers_online=0,
        worker_concurrency_total=0,
        queue_pending_total=sum(item.pending_count for item in queues),
        task_state_buckets=_load_state_bucket_items(keyword=keyword),
        workers=[],
        queues=queues,
        tasks=db_tasks,
        total=total,
    )
