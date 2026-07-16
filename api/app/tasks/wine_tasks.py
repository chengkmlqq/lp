from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.wine_service import execute_run_job


@celery_app.task(name="app.tasks.wine_tasks.execute_wine_run_job")
def execute_wine_run_job(run_id: str, actor_user_id: str | None) -> dict[str, str]:
    execute_run_job(run_id=run_id, actor_user_id=actor_user_id)
    return {"run_id": run_id, "status": "done"}
