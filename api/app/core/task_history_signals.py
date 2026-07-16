from __future__ import annotations

from datetime import datetime, timezone

from celery import signals

from ..core.database import SessionLocal
from ..models.task_history import TaskHistory


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
) -> None:
    """Create or update a task record in the DB."""
    db = SessionLocal()
    try:
        record = db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
        if record is None:
            record = TaskHistory(task_id=task_id)
            db.add(record)

        if name is not None:
            record.name = name
        if state is not None:
            record.state = state
        if worker is not None:
            record.worker = worker
        if queue_name is not None:
            record.queue_name = queue_name
        if retries is not None:
            record.retries = retries
        if eta is not None:
            record.eta = eta
        if started_at is not None:
            record.started_at = started_at
        if done_at is not None:
            record.done_at = done_at
        if runtime_seconds is not None:
            record.runtime_seconds = runtime_seconds
        if error is not None:
            record.error = error

        db.commit()
    finally:
        db.close()


@signals.task_prerun.connect
def on_task_prerun(task_id=None, task=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as STARTED when it begins executing."""
    if not task_id:
        return
    started_at = datetime.now(timezone.utc)
    _upsert_task(
        task_id,
        name=task.name if task else None,
        state="STARTED",
        started_at=started_at,
    )


@signals.task_success.connect
def on_task_success(sender=None, result=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as SUCCESS when it completes successfully."""
    # sender is the task class, not the task_id
    # Use the current_app's current request to get the task_id
    from celery._state import get_current_task

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
    """Record task as REVOKED when it is revoked."""
    if request is None:
        return
    task_id = request.id
    if not task_id:
        return

    _upsert_task(
        task_id,
        state="REVOKED",
        done_at=datetime.now(timezone.utc),
    )


@signals.after_task_publish.connect
def on_after_task_publish(sender=None, headers=None, body=None, **kwargs):  # type: ignore[no-untyped-def]
    """Record task as PENDING when it is first published to the queue."""
    if not headers:
        return
    task_id = headers.get("id")
    task_name = headers.get("task")
    if not task_id:
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
    )
