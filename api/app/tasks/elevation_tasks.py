from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.elevation_service import (
    execute_apply_job,
    execute_file_record_analysis_job,
    execute_file_record_terrain_build_job,
)


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


@celery_app.task(name="app.tasks.elevation_tasks.build_elevation_file_record_terrain_job", bind=True)
def build_elevation_file_record_terrain_job(self, record_id: str, actor_user_id: str | None) -> dict[str, str]:
    """Build terrain tiles for a single elevation file record.

    LP-314：仅负责把 DEM 投递到 ctb 队列（不再在任务内 ``result.get()`` 阻塞等待），
    瓦片构建结果由 ctb worker 通过 ``report_ctb_task_state`` 异步回调落库。
    """
    task_id = self.request.id
    log_parts: list[str] = []
    log_parts.append(f"[{task_id}] Dispatching terrain build for record {record_id}")
    try:
        execute_file_record_terrain_build_job(record_id=record_id, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] Terrain build dispatched for record {record_id}")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass  # Log upload failure is non-fatal
        return {"record_id": record_id, "status": "dispatched"}
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] Terrain build dispatch FAILED for record {record_id}: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass  # Log upload failure is non-fatal
        raise


@celery_app.task(name="app.tasks.elevation_tasks.report_ctb_task_state", bind=True)
def report_ctb_task_state(self, *, ctb_task_id: str, record_id: str, state: str, error: str | None = None, result: dict | None = None) -> dict[str, str]:
    """处理 ctb worker 上报的任务状态（LP-314）。

    ctb worker 独立进程无法直接写 DB，通过向 ``celery`` 队列投递本任务，
    由 API worker 把状态写入 celery_task_history 并同步文件记录状态。
    """
    from ..services.elevation_service import execute_file_record_terrain_state_report

    execute_file_record_terrain_state_report(
        ctb_task_id=ctb_task_id,
        record_id=record_id,
        state=state,
        error=error,
        result=result,
    )
    return {"record_id": record_id, "state": state}
