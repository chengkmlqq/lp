from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.fl_analysis_service import execute_job


@celery_app.task(name="app.tasks.fl_analysis_tasks.execute_fl_analysis_job", bind=True, queue="wine")
def execute_fl_analysis_job(self, job_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting FL analysis job {job_id}"]
    try:
        from ..services.task_log_service import append_task_log_lines, mark_task_log_end

        append_task_log_lines(task_id, log_parts)
        execute_job(job_id)
        log_parts.append(f"[{task_id}] FL analysis job {job_id} completed successfully")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        try:
            mark_task_log_end(task_id)
        except Exception:
            pass
        return {"job_id": job_id, "status": "done"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] FL analysis job {job_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        try:
            from ..services.task_log_service import append_task_log_lines, mark_task_log_end
            append_task_log_lines(task_id, log_parts)
            mark_task_log_end(task_id)
        except Exception:
            pass
        raise