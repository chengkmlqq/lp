from __future__ import annotations

from ..core.celery_app import celery_app


@celery_app.task(name="app.tasks.traveling_wave_tasks.execute_traveling_wave_job", bind=True, soft_time_limit=300, time_limit=600)
def execute_traveling_wave_job(self, job_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting traveling wave analysis job {job_id}"]
    try:
        from ..services.traveling_wave_service import execute_job
        execute_job(job_id)
        log_parts.append(f"[{task_id}] Traveling wave analysis job {job_id} completed successfully")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return {"job_id": job_id, "status": "done"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] Traveling wave analysis job {job_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise
