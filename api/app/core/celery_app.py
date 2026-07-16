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
    },
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    task_serializer="json",
    task_track_started=True,
    timezone=settings.celery_timezone,
    worker_prefetch_multiplier=1,
)

# Register worker lifecycle signals for auto-registration/heartbeat/offline states.
from . import worker_signals as _worker_signals  # noqa: F401,E402
# Register task lifecycle signals for persistent task history in PostgreSQL.
from . import task_history_signals as _task_history_signals  # noqa: F401,E402
