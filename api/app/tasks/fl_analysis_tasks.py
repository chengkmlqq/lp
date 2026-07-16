from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.fl_analysis_service import execute_job


@celery_app.task(name="app.tasks.fl_analysis_tasks.execute_fl_analysis_job")
def execute_fl_analysis_job(job_id: str) -> dict[str, str]:
    execute_job(job_id)
    return {"job_id": job_id, "status": "done"}