from __future__ import annotations

from ..core.celery_app import celery_app
from ..core.config import get_settings
from ..services.worker_registry_service import sweep_offline_workers


@celery_app.task(
    name="app.tasks.worker_registry_tasks.sweep_worker_registry_offline",
    ignore_result=True,
    track_started=False,
)
def sweep_worker_registry_offline() -> dict[str, int]:
    settings = get_settings()
    updated_count = sweep_offline_workers(ttl_seconds=settings.worker_registry_ttl_seconds)
    return {
        "updated_count": int(updated_count),
    }


@celery_app.task(
    name="app.tasks.worker_registry_tasks.flush_task_log_buffers",
    ignore_result=True,
    track_started=False,
)
def flush_task_log_buffers() -> dict[str, int]:
    """beat 周期兜底任务（P3）：对仍活跃的任务日志缓冲 flush 增量到 Redis Stream。

    任务由 beat 周期调度后经 broker 投递到 worker 进程执行，因此能访问到该 worker
    进程内存中的采集器注册表；即使长任务一段时间没有新日志（写入驱动的 3s 闸门
    不触发），兜底任务也会把已积累的增量推入 Redis，缩小 worker crash 时的日志丢失窗口。
    """
    from ..core.task_log_capture import TaskLogCapture

    active = TaskLogCapture.flush_all()
    return {
        "active_buffers": int(active),
    }
