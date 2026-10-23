from __future__ import annotations

from datetime import datetime, timezone

from celery import signals
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ..core.database import DIALECT_IS_MYSQL, SessionLocal
from ..core.task_log_capture import TaskLogCapture
from ..models.base import utcnow
from ..models.task_history import TaskHistory
from ..services.task_log_service import (
    TaskLogServiceError,
    upload_task_log,
)

# beat 定期调度的系统任务（LP-281）：不应写入 celery_task_history 监控表，也不触发
# TaskLogCapture 日志采集。在信号层源头拦截，不做前端过滤。
SYSTEM_TASK_NAMES: frozenset[str] = frozenset({
    "app.tasks.worker_registry_tasks.flush_task_log_buffers",
    "app.tasks.worker_registry_tasks.sweep_worker_registry_offline",
    "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks",
    # LP-283：日志清理任务不该记录自身日志（否则“越清越多”），加入黑名单
    "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
})


def _is_system_task(task_name: str | None) -> bool:
    """判断任务是否命中系统任务黑名单（beat 系统任务不落监控表 / 不采集日志）。"""
    return bool(task_name and task_name in SYSTEM_TASK_NAMES)


def _get_db_task(task_id: str) -> TaskHistory | None:
    """Get existing task record from DB, or None."""
    db = SessionLocal()
    try:
        return db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
    finally:
        db.close()


def _upsert_task(
    task_id: str,
    *,
    name: str | None = None,
    state: str | None = None,
    worker: str | None = None,
    queue_name: str | None = None,
    retries: int | None = None,
    eta: datetime | None = None,
    started_at: datetime | None = None,
    done_at: datetime | None = None,
    runtime_seconds: float | None = None,
    error: str | None = None,
    log_path: str | None = None,
) -> None:
    """Create or update a task record atomically.

    Uses PostgreSQL ``INSERT ... ON CONFLICT (task_id) DO UPDATE`` so that the
    publish signal (PENDING, written in the producer process) and the execution
    signals (STARTED / SUCCESS / FAILURE, written in the worker process) can
    race on the same ``task_id`` without one hitting a UniqueViolation.

    Only columns explicitly provided (non-None) are written; ``None`` leaves an
    existing value untouched, preserving the previous partial-update semantics.
    ``update_date`` is always refreshed on update, mirroring the ORM onupdate.
    """
    values: dict[str, object] = {"task_id": task_id}
    if name is not None:
        values["name"] = name
    if state is not None:
        values["state"] = state
    if worker is not None:
        values["worker"] = worker
    if queue_name is not None:
        values["queue_name"] = queue_name
    if retries is not None:
        values["retries"] = retries
    if eta is not None:
        values["eta"] = eta
    if started_at is not None:
        values["started_at"] = started_at
    if done_at is not None:
        values["done_at"] = done_at
    if runtime_seconds is not None:
        values["runtime_seconds"] = runtime_seconds
    if error is not None:
        values["error"] = error
    if log_path is not None:
        values["log_path"] = log_path

    update_columns: dict[str, object] = {
        key: value for key, value in values.items() if key != "task_id"
    }
    update_columns["update_date"] = utcnow()

    insert_stmt = None
    if DIALECT_IS_MYSQL:
        # MySQL: INSERT ... ON DUPLICATE KEY UPDATE（task_id 为主键，冲突即更新）
        insert_stmt = mysql_insert(TaskHistory).values(**values)
        insert_stmt = insert_stmt.on_duplicate_key_update(**update_columns)
    else:
        # PostgreSQL: INSERT ... ON CONFLICT (task_id) DO UPDATE
        insert_stmt = pg_insert(TaskHistory).values(**values)
        insert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[TaskHistory.task_id],
            set_=update_columns,
        )

    db = SessionLocal()
    try:
        db.execute(insert_stmt)
        db.commit()
    finally:
        db.close()


def _persist_log(task_id: str, full_text: str) -> str | None:
    """
    任务终态持久化：上传全量日志到 MinIO 固定路径，返回 log_path。
    上传失败不抛异常（避免信号阻断任务收尾），返回 None，由调用方记录 error 字段提示。
    """
    try:
        log_path, _uploaded_at = upload_task_log(task_id, full_text)
        return log_path
    except TaskLogServiceError:
        return None


def _finalize_task_log(task_id: str) -> None:
    """
    任务收尾（task_postrun / task_revoked 内调用）：
      1. 先 flush 增量（含 Celery 的 succeeded/failed 边界日志 —— postrun 在日志输出之后触发）
      2. 卸载采集器并取全量文本
      3. 上传 MinIO 固定路径 + 写回 log_path
    上传失败不阻断：log_path 不写，error 字段追加提示（成功任务无 error 时写入）。
    """
    full_lines = TaskLogCapture.stop(task_id)
    if not full_lines:
        return
    full_text = "\n".join(full_lines)
    log_path = _persist_log(task_id, full_text)

    if log_path:
        _upsert_task(task_id, log_path=log_path)
        return

    # 上传失败：log_path 不写，保留 Redis 数据供页面降级展示，error 字段提示
    record = _get_db_task(task_id)
    if record is not None and not record.error:
        _upsert_task(task_id, error="日志未持久化（MinIO 不可用）")


@signals.task_prerun.connect
def on_task_prerun(task_id=None, task=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as STARTED when it begins executing."""
    if not task_id:
        return
    if _is_system_task(task.name if task else None):
        # 系统任务：不落监控表，也不装日志采集器（LP-281）
        return
    started_at = datetime.now(timezone.utc)
    request = getattr(task, "request", None) if task else None
    worker = getattr(request, "hostname", None) if request is not None else None
    queue_name = None
    if request is not None:
        delivery_info = getattr(request, "delivery_info", None) or {}
        queue_name = delivery_info.get("routing_key")
    _upsert_task(
        task_id,
        name=task.name if task else None,
        state="STARTED",
        worker=worker,
        queue_name=queue_name,
        started_at=started_at,
    )
    # 新增：安装采集器，从任务开始捕获 Celery / print / 业务日志
    TaskLogCapture.start(task_id)


@signals.task_postrun.connect
def on_task_postrun(sender=None, task_id=None, task=None, **kwargs):  # type: ignore[no-untyped-def]
    """
    Finalize task execution log capture (SUCCESS / FAILURE / REJECTED).

    注意：不要把它放在 task_success / task_failure 里 —— 这两个信号在 Celery 输出
    "Task xxx succeeded" / "raised unexpected" 边界日志**之前**触发，此时停止采集会
    丢掉边界日志；task_postrun 在 finally 块中、所有边界日志输出**之后**触发。
    """
    if not task_id:
        return
    if _is_system_task(task.name if task else None):
        # 系统任务：跳过后置处理（含 TaskLogCapture.stop / 日志上传）（LP-281）
        return
    _finalize_task_log(task_id)


@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as SUCCESS when it completes successfully."""
    # sender is the task class, not the task_id
    # Use the current_app's current request to get the task_id
    from celery._state import get_current_task

    if _is_system_task(sender.name if sender else None):
        # 系统任务：不写 SUCCESS 状态（LP-281）
        return

    current_task = get_current_task()
    if current_task is None:
        return
    task_id = current_task.request.id
    if not task_id:
        return

    done_at = datetime.now(timezone.utc)
    runtime = None
    record = _get_db_task(task_id)
    if record and record.started_at:
        runtime = (done_at - record.started_at).total_seconds()

    _upsert_task(
        task_id,
        state="SUCCESS",
        done_at=done_at,
        runtime_seconds=runtime,
        error=None,
    )


@signals.task_failure.connect
def on_task_failure(sender=None, task_id=None, exception=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as FAILURE when it fails."""
    if not task_id:
        return
    if _is_system_task(sender.name if sender else None):
        # 系统任务：不写 FAILURE 状态（LP-281）
        return

    done_at = datetime.now(timezone.utc)
    runtime = None
    record = _get_db_task(task_id)
    if record and record.started_at:
        runtime = (done_at - record.started_at).total_seconds()

    _upsert_task(
        task_id,
        state="FAILURE",
        done_at=done_at,
        runtime_seconds=runtime,
        error=str(exception) if exception else None,
    )


@signals.task_revoked.connect
def on_task_revoked(sender=None, request=None, terminated=None, signum=None, expired=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as REVOKED when it is revoked.

    ⚠️ 2026-09-14 修复：revoke(terminate=True) 时传入的是 celery 的 ``Context`` 对象，
    它**没有** ``task_name`` 属性 → 原实现直接 ``request.task_name`` 抛
    ``AttributeError: 'Context' object has no attribute 'task_name'``，整个信号处理器中断，
    导致 REVOKED 状态与日志收尾都被跳过（任务永远停在 STARTED，取消功能实测暴露该问题）。
    这里改为多来源兜底取任务名。
    """
    if request is None:
        return
    task_id = getattr(request, "id", None)
    if not task_id:
        return
    task_name = (
        getattr(request, "task_name", None)
        or getattr(request, "name", None)
        or getattr(getattr(request, "task", None), "name", None)
    )
    if _is_system_task(task_name):
        # 系统任务：不写 REVOKED 状态、不触发日志采集（LP-281）
        return

    _finalize_task_log(task_id)
    _upsert_task(
        task_id,
        state="REVOKED",
        done_at=datetime.now(timezone.utc),
    )


@signals.after_task_publish.connect
def on_after_task_publish(sender=None, headers=None, body=None, routing_key=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as PENDING when it is first published to the queue."""
    if not headers:
        return
    task_id = headers.get("id")
    task_name = headers.get("task")
    if not task_id:
        return
    if _is_system_task(task_name):
        # 系统任务：不写 PENDING，直接跳过（LP-281）
        return

    eta_raw = headers.get("eta")
    eta = None
    if eta_raw:
        try:
            eta = datetime.fromisoformat(eta_raw.replace("Z", "+00:00"))
            if eta.tzinfo is None:
                eta = eta.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            pass

    retries = headers.get("retries", 0)

    _upsert_task(
        task_id,
        name=task_name or "",
        state="PENDING",
        retries=retries,
        eta=eta,
        queue_name=routing_key,
    )
