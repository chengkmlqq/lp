from __future__ import annotations

from ..core.celery_app import celery_app
from ..core.config import get_settings
from ..services.task_log_service import cleanup_expired_task_logs as _cleanup_expired_task_logs


@celery_app.task(
    name="app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
    ignore_result=True,
    track_started=False,
)
def cleanup_expired_task_logs() -> dict[str, int]:
    """删除超过保留期的任务日志 MinIO 对象（logs/ 前缀），返回被删数量。"""
    settings = get_settings()
    deleted_count = _cleanup_expired_task_logs(
        retain_days=settings.task_log_retain_days,
    )
    return {
        "deleted_count": int(deleted_count),
    }
