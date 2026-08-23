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
        "app.tasks.fault_diagnosis_tasks",
        "app.tasks.lightning_tasks",
        "app.tasks.log_cleanup_tasks",
        "app.tasks.scheduled_task_tasks",
        "app.tasks.sync_matlab_engine_task",
        "app.tasks.traveling_wave_tasks",
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
        "cleanup-expired-task-logs": {
            "task": "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
            "schedule": 3600.0,  # 每小时清理一次（与 30 天保留期解耦，无需更频繁）
        },
        "cleanup-expired-lightning-temp-files": {
            "task": "app.tasks.lightning_tasks.cleanup_lightning_temp_files",
            "schedule": 3600.0,  # 每小时清理一次（覆盖 24h 保留期的孤儿临时文件）
        },
    },
    # Redis broker 默认 visibility_timeout=3600s，重任务（如雷电分布导入约 106 分钟）
    # 超过 1 小时会被 Redis 重新投递，导致同一任务被两个 worker 并行执行。
    # 调大到 21600s（6 小时）覆盖最长任务耗时，避免超时重投造成双副本并行。
    broker_transport_options={"visibility_timeout": 21600},
    enable_utc=True,
    result_serializer="json",
    # 心跳间隔显式设为 15s，替代 Celery event 模式约 2s 的默认值，降低每个 worker 对
    # worker_registry 表的心跳 UPSERT 写频率（2s → 15s）。配合 worker_registry_ttl_seconds=90，
    # 90s 内可收约 6 次心跳，离线判定仍可靠（TTL ≥ 3× 心跳间隔）。
    worker_heartbeat_interval=15.0,
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
# Ensure TaskLogCapture is installed at worker startup (root handler + stdout/stderr Tee).
from . import task_log_capture as _task_log_capture  # noqa: F401,E402
