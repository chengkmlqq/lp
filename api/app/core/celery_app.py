from __future__ import annotations

from celery import Celery

from .config import get_settings

settings = get_settings()

celery_app = Celery(
    "fquiz",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=[
        "app.tasks.atp_asset_tasks",
        "app.tasks.elevation_tasks",
        "app.tasks.fl_analysis_tasks",
        "app.tasks.lightning_tasks",
        "app.tasks.scheduled_task_tasks",
        "app.tasks.wine_tasks",
        "app.tasks.worker_registry_tasks",
    ],
)

celery_app.conf.update(
    accept_content=["json"],
    beat_schedule={
        "sweep-worker-registry-offline": {
            "task": "app.tasks.worker_registry_tasks.sweep_worker_registry_offline",
            "schedule": 30.0,
        },
        "dispatch-due-scheduled-tasks": {
            "task": "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks",
            "schedule": 60.0,
        },
        "flush-task-log-buffers": {
            "task": "app.tasks.worker_registry_tasks.flush_task_log_buffers",
            "schedule": 30.0,
        },
    },
    # Redis broker 默认 visibility_timeout=3600s，重任务（如雷电分布导入约 106 分钟）
    # 超过 1 小时会被 Redis 重新投递，导致同一任务被两个 worker 并行执行。
    # 调大到 21600s（6 小时）覆盖最长任务耗时，避免超时重投造成双副本并行。
    broker_transport_options={"visibility_timeout": 21600},
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    # worker 异常退出时任务消息被 reject 而非 ack，配合 acks_late 让消息及时回到队列
    # 由其他 worker 继续处理，而不是依赖 Redis visibility_timeout 的漫长等待。
    task_reject_on_worker_lost=True,
    task_serializer="json",
    task_track_started=True,
    timezone=settings.celery_timezone,
    worker_prefetch_multiplier=1,
)

# Register worker lifecycle signals for auto-registration/heartbeat/offline states.
from . import worker_signals as _worker_signals  # noqa: F401,E402
# Register task lifecycle signals for persistent task history in PostgreSQL.
from . import task_history_signals as _task_history_signals  # noqa: F401,E402
