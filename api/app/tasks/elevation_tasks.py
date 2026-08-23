from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.elevation_service import execute_apply_job, execute_file_record_analysis_job


@celery_app.task(name="app.tasks.elevation_tasks.apply_elevation_for_line_job", bind=True)
def apply_elevation_for_line_job(self, job_id: str, actor_user_id: str | None = None) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting apply elevation job {job_id}"]
    try:
        execute_apply_job(job_id=job_id, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] Apply elevation job {job_id} completed successfully")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return {"job_id": job_id, "status": "done"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] Apply elevation job {job_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise


# ============================================================================


@celery_app.task(name="app.tasks.elevation_tasks.analyze_elevation_file_record_job", bind=True)
def analyze_elevation_file_record_job(self, record_id: str, actor_user_id: str | None) -> dict[str, str]:
    """Analyze a single elevation file record."""
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting analysis for file record {record_id}"]
    try:
        execute_file_record_analysis_job(record_id=record_id, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] Analysis completed for file record {record_id}")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return {"record_id": record_id, "status": "done"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] Analysis FAILED for file record {record_id}: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise


