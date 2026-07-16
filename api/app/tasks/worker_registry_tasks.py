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
