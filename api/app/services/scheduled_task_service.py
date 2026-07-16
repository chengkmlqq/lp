from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery.schedules import crontab, crontab_parser
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..core.config import get_settings
from ..core.database import SessionLocal
from ..models.audit_log import AuditLog
from ..models.base import utcnow
from ..models.scheduled_task import ScheduledTask
from ..schemas.scheduled_task import (
    ScheduledTaskCreateRequest,
    ScheduledTaskListResponse,
    ScheduledTaskRunResponse,
    ScheduledTaskSummary,
    ScheduledTaskUpdateRequest,
)
from .push_service import publish_topic
from .user_service import serialize_user

SCHEDULED_TASK_TOPIC = "admin.scheduled-tasks"
SYSLOG_CLEANUP_TASK_KEY = "syslog.cleanup.default"
SUPPORTED_TASK_TYPES = {"syslog_cleanup"}
CRON_FIELD_LIMITS: tuple[tuple[int, int], ...] = (
    (60, 0),
    (24, 0),
    (31, 1),
    (12, 1),
    (7, 0),
)


@dataclass(slots=True)
class ScheduledTaskExecutionResult:
    detail: str
    payload: dict[str, int | str]


def _scheduled_task_stmt():
    return select(ScheduledTask).options(
        selectinload(ScheduledTask.creator),
        selectinload(ScheduledTask.updater),
    )


def serialize_scheduled_task(item: ScheduledTask) -> ScheduledTaskSummary:
    return ScheduledTaskSummary(
        id=item.id,
        task_key=item.task_key,
        name=item.name,
        task_type=item.task_type,
        description=item.description,
        cron_expression=item.cron_expression,
        timezone=item.timezone,
        retain_days=item.retain_days,
        enabled=item.enabled,
        status=item.status,
        last_run_at=item.last_run_at,
        next_run_at=item.next_run_at,
        last_success_at=item.last_success_at,
        last_error_at=item.last_error_at,
        last_error_message=item.last_error_message,
        last_result_json=item.last_result_json or {},
        run_count=item.run_count,
        create_user=item.create_user,
        update_user=item.update_user,
        create_date=item.create_date,
        update_date=item.update_date,
        creator=serialize_user(item.creator) if item.creator else None,
        updater=serialize_user(item.updater) if item.updater else None,
    )


def list_scheduled_tasks(
    db: Session,
    *,
    keyword: str | None,
    status_filter: str | None,
) -> ScheduledTaskListResponse:
    stmt = _scheduled_task_stmt()
    total_stmt = select(func.count()).select_from(ScheduledTask)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        criteria = or_(
            ScheduledTask.task_key.ilike(like),
            ScheduledTask.name.ilike(like),
            ScheduledTask.description.ilike(like),
            ScheduledTask.cron_expression.ilike(like),
        )
        stmt = stmt.where(criteria)
        total_stmt = total_stmt.where(criteria)

    normalized_status = (status_filter or "").strip().lower()
    if normalized_status in {"enabled", "disabled"}:
        enabled = normalized_status == "enabled"
        stmt = stmt.where(ScheduledTask.enabled.is_(enabled))
        total_stmt = total_stmt.where(ScheduledTask.enabled.is_(enabled))
    elif normalized_status in {"idle", "queued", "running", "success", "failed", "disabled"}:
        stmt = stmt.where(ScheduledTask.status == normalized_status)
        total_stmt = total_stmt.where(ScheduledTask.status == normalized_status)

    total = db.scalar(total_stmt) or 0
    items = db.execute(
        stmt.order_by(ScheduledTask.enabled.desc(), ScheduledTask.next_run_at.asc(), ScheduledTask.id.asc())
    ).scalars().all()
    return ScheduledTaskListResponse(items=[serialize_scheduled_task(item) for item in items], total=total)


def get_scheduled_task_by_id(db: Session, task_id: int) -> ScheduledTask | None:
    return db.execute(_scheduled_task_stmt().where(ScheduledTask.id == task_id)).scalar_one_or_none()


def get_scheduled_task_by_key(db: Session, task_key: str) -> ScheduledTask | None:
    return db.execute(_scheduled_task_stmt().where(ScheduledTask.task_key == task_key)).scalar_one_or_none()


def create_scheduled_task(
    db: Session,
    payload: ScheduledTaskCreateRequest,
    *,
    actor_user_id: str | None,
) -> ScheduledTaskSummary | None:
    task_key = payload.task_key.strip()
    if not task_key:
        return None
    if db.scalar(select(ScheduledTask.id).where(ScheduledTask.task_key == task_key)):
        return None

    normalized_type = payload.task_type.strip()
    _validate_task_definition(
        cron_expression=payload.cron_expression,
        timezone_name=payload.timezone,
        task_type=normalized_type,
    )

    task = ScheduledTask(
        task_key=task_key,
        name=payload.name.strip(),
        task_type=normalized_type,
        description=(payload.description or "").strip(),
        cron_expression=normalize_cron_expression(payload.cron_expression),
        timezone=payload.timezone.strip(),
        retain_days=payload.retain_days,
        enabled=payload.enabled,
        status="idle" if payload.enabled else "disabled",
        next_run_at=compute_next_run_at(
            normalize_cron_expression(payload.cron_expression),
            payload.timezone.strip(),
            from_time=None,
        ) if payload.enabled else None,
        create_user=actor_user_id if actor_user_id != "system" else None,
        update_user=actor_user_id if actor_user_id != "system" else None,
    )
    db.add(task)
    db.commit()
    saved = get_scheduled_task_by_id(db, task.id)
    if not saved:
        return None
    _publish_scheduled_task_changed(
        action="created",
        task=saved,
        requires_refetch=["/api/v1/admin/scheduled-tasks"],
    )
    return serialize_scheduled_task(saved)


def update_scheduled_task(
    db: Session,
    task_id: int,
    payload: ScheduledTaskUpdateRequest,
    *,
    actor_user_id: str,
) -> ScheduledTaskSummary | None:
    item = get_scheduled_task_by_id(db, task_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    next_name = str(update_data.get("name", item.name)).strip()
    next_description = (
        (str(update_data["description"]) if update_data["description"] is not None else "")
        if "description" in update_data else (item.description or "")
    ).strip()
    next_cron = normalize_cron_expression(str(update_data.get("cron_expression", item.cron_expression)))
    next_timezone = str(update_data.get("timezone", item.timezone)).strip()
    next_retain_days = int(update_data.get("retain_days", item.retain_days))
    next_enabled = bool(update_data.get("enabled", item.enabled))

    _validate_task_definition(
        cron_expression=next_cron,
        timezone_name=next_timezone,
        task_type=item.task_type,
    )

    item.name = next_name
    item.description = next_description
    item.cron_expression = next_cron
    item.timezone = next_timezone
    item.retain_days = next_retain_days
    item.enabled = next_enabled
    item.status = "disabled" if not next_enabled else ("idle" if item.status == "disabled" else item.status)
    item.next_run_at = compute_next_run_at(next_cron, next_timezone, from_time=None) if next_enabled else None
    item.update_user = actor_user_id if actor_user_id != "system" else None
    db.commit()
    saved = get_scheduled_task_by_id(db, task_id)
    if not saved:
        return None
    _publish_scheduled_task_changed(
        action="updated",
        task=saved,
        requires_refetch=["/api/v1/admin/scheduled-tasks", f"/api/v1/admin/scheduled-tasks/{saved.id}"],
    )
    return serialize_scheduled_task(saved)


def run_scheduled_task_now(
    db: Session,
    task_id: int,
    *,
    actor_user_id: str,
) -> ScheduledTaskRunResponse | None:
    item = get_scheduled_task_by_id(db, task_id)
    if not item:
        return None

    item.status = "queued"
    item.update_user = actor_user_id if actor_user_id != "system" else None
    db.commit()

    from ..tasks.scheduled_task_tasks import execute_scheduled_task_job

    result = execute_scheduled_task_job.delay(item.id, actor_user_id)
    saved = get_scheduled_task_by_id(db, task_id)
    if not saved:
        return None
    _publish_scheduled_task_changed(
        action="queued",
        task=saved,
        requires_refetch=["/api/v1/admin/scheduled-tasks"],
    )
    return ScheduledTaskRunResponse(
        success=True,
        task=serialize_scheduled_task(saved),
        celery_task_id=result.id,
    )


def seed_default_scheduled_tasks(db: Session) -> None:
    if get_scheduled_task_by_key(db, SYSLOG_CLEANUP_TASK_KEY):
        return

    payload = ScheduledTaskCreateRequest(
        task_key=SYSLOG_CLEANUP_TASK_KEY,
        name="系统日志定时清理",
        task_type="syslog_cleanup",
        description="按保留天数自动清理历史系统日志，避免审计表持续膨胀。",
        cron_expression="0 3 * * *",
        timezone=get_settings().celery_timezone,
        retain_days=30,
        enabled=True,
    )
    create_scheduled_task(db, payload, actor_user_id=None)


def dispatch_due_scheduled_tasks(*, actor_user_id: str = "system") -> dict[str, int]:
    now = utcnow()
    queued_count = 0
    scanned_count = 0
    db = SessionLocal()
    try:
        items = db.execute(
            _scheduled_task_stmt().where(
                ScheduledTask.enabled.is_(True),
                ScheduledTask.next_run_at.is_not(None),
                ScheduledTask.next_run_at <= now,
            ).order_by(ScheduledTask.next_run_at.asc(), ScheduledTask.id.asc())
        ).scalars().all()

        from ..tasks.scheduled_task_tasks import execute_scheduled_task_job

        for item in items:
            scanned_count += 1
            item.status = "queued"
            item.update_user = actor_user_id if actor_user_id != "system" else None
            item.next_run_at = compute_next_run_at(item.cron_expression, item.timezone, from_time=now)
            db.commit()
            execute_scheduled_task_job.delay(item.id, actor_user_id)
            queued_count += 1
            _publish_scheduled_task_changed(
                action="queued",
                task=item,
                requires_refetch=["/api/v1/admin/scheduled-tasks"],
            )
        return {
            "scanned_count": scanned_count,
            "queued_count": queued_count,
        }
    finally:
        db.close()


def execute_scheduled_task(task_id: int, *, actor_user_id: str = "system") -> dict[str, object]:
    db = SessionLocal()
    try:
        item = get_scheduled_task_by_id(db, task_id)
        if not item:
            return {"success": False, "detail": "scheduled task not found", "task_id": task_id}
        return _execute_scheduled_task_with_session(db, item, actor_user_id=actor_user_id)
    finally:
        db.close()


def cleanup_audit_logs(db: Session, *, retain_days: int) -> int:
    threshold = utcnow() - timedelta(days=retain_days)
    candidate_ids = db.scalars(
        select(AuditLog.id).where(AuditLog.created_at < threshold).order_by(AuditLog.id.asc()).limit(5000)
    ).all()
    if not candidate_ids:
        return 0
    deleted = db.query(AuditLog).filter(AuditLog.id.in_(candidate_ids)).delete(synchronize_session=False)
    return int(deleted or 0)


def normalize_cron_expression(value: str) -> str:
    fields = value.strip().split()
    if len(fields) != 5:
        raise ValueError("cron expression must contain exactly 5 fields")
    return " ".join(field.strip() for field in fields)


def compute_next_run_at(
    cron_expression: str,
    timezone_name: str,
    *,
    from_time: datetime | None,
) -> datetime:
    tz = _get_zoneinfo(timezone_name)
    base = (from_time or utcnow()).astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    minutes, hours, days, months, weekdays = _parse_cron_expression(cron_expression)

    for offset in range(0, 366 * 24 * 60):
        candidate = base + timedelta(minutes=offset)
        if candidate.minute not in minutes:
            continue
        if candidate.hour not in hours:
            continue
        if candidate.day not in days:
            continue
        if candidate.month not in months:
            continue
        weekday = candidate.isoweekday() % 7
        if weekday not in weekdays:
            continue
        return candidate.astimezone(ZoneInfo("UTC"))
    raise ValueError("unable to compute next run time within 1 year")


def _execute_scheduled_task_with_session(
    db: Session,
    item: ScheduledTask,
    *,
    actor_user_id: str,
) -> dict[str, object]:
    now = utcnow()
    item.status = "running"
    item.last_run_at = now
    item.update_user = actor_user_id if actor_user_id != "system" else None
    db.commit()
    _publish_scheduled_task_changed(
        action="running",
        task=item,
        requires_refetch=["/api/v1/admin/scheduled-tasks"],
    )

    try:
        result = _run_task_handler(db, item)
        now = utcnow()
        item.status = "success"
        item.last_success_at = now
        item.last_error_at = None
        item.last_error_message = None
        item.last_result_json = result.payload
        item.run_count += 1
        item.update_user = actor_user_id if actor_user_id != "system" else None
        if item.enabled:
            item.next_run_at = compute_next_run_at(item.cron_expression, item.timezone, from_time=now)
        db.add(
            AuditLog(
                user_id=actor_user_id if actor_user_id != "system" else None,
                action="scheduled_task.run",
                detail=f"{item.task_key}: {result.detail}",
            )
        )
        db.commit()
        _publish_scheduled_task_changed(
            action="success",
            task=item,
            requires_refetch=["/api/v1/admin/scheduled-tasks", "/api/v1/admin/audit-logs"],
        )
        return {
            "success": True,
            "detail": result.detail,
            "task": serialize_scheduled_task(item).model_dump(mode="json"),
        }
    except Exception as exc:
        now = utcnow()
        item.status = "failed"
        item.last_error_at = now
        item.last_error_message = str(exc)
        item.update_user = actor_user_id if actor_user_id != "system" else None
        if item.enabled:
            item.next_run_at = compute_next_run_at(item.cron_expression, item.timezone, from_time=now)
        db.add(
            AuditLog(
                user_id=actor_user_id if actor_user_id != "system" else None,
                action="scheduled_task.run_failed",
                detail=f"{item.task_key}: {exc}",
            )
        )
        db.commit()
        _publish_scheduled_task_changed(
            action="failed",
            task=item,
            requires_refetch=["/api/v1/admin/scheduled-tasks", "/api/v1/admin/audit-logs"],
        )
        raise


def _run_task_handler(db: Session, item: ScheduledTask) -> ScheduledTaskExecutionResult:
    if item.task_type == "syslog_cleanup":
        deleted_count = cleanup_audit_logs(db, retain_days=item.retain_days)
        return ScheduledTaskExecutionResult(
            detail=f"已清理 {deleted_count} 条系统日志",
            payload={"deleted_count": deleted_count, "retain_days": item.retain_days},
        )
    raise ValueError(f"unsupported scheduled task type: {item.task_type}")


def _parse_cron_expression(value: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = normalize_cron_expression(value).split()
    parsed: list[set[int]] = []
    for field, (max_value, min_value) in zip(fields, CRON_FIELD_LIMITS, strict=True):
        parsed.append({int(item) for item in crontab_parser(max_value, min_value).parse(field)})
    return tuple(parsed)  # type: ignore[return-value]


def _validate_task_definition(*, cron_expression: str, timezone_name: str, task_type: str) -> None:
    if task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError(f"unsupported task type: {task_type}")
    normalized_cron = normalize_cron_expression(cron_expression)
    _parse_cron_expression(normalized_cron)
    _get_zoneinfo(timezone_name)
    minute, hour, day_of_month, month_of_year, day_of_week = normalized_cron.split()
    crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def _get_zoneinfo(value: str) -> ZoneInfo:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timezone is required")
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone: {normalized}") from exc


def _publish_scheduled_task_changed(
    *,
    action: str,
    task: ScheduledTask,
    requires_refetch: list[str],
) -> None:
    _fire_and_forget(
        publish_topic(
            SCHEDULED_TASK_TOPIC,
            name="scheduled_tasks.changed",
            payload={"action": action, "task_id": task.id, "task_key": task.task_key},
            requires_refetch=requires_refetch,
            dedupe_key=f"scheduled-tasks:{action}:{task.id}",
        )
    )


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)
