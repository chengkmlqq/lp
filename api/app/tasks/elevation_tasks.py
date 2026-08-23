from __future__ import annotations

import traceback

from ..core.celery_app import celery_app
from ..services.elevation_service import execute_apply_job, execute_file_record_analysis_job


def _capture(task_id: str, text: str) -> None:
    try:
        from ..core.task_log_capture import TaskLogCapture
        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:
        pass


def _append_log(log_parts: list[str], task_id: str, text: str) -> None:
    log_parts.append(text)
    _capture(task_id, text)


@celery_app.task(name="app.tasks.elevation_tasks.apply_elevation_for_line_job", bind=True)
def apply_elevation_for_line_job(self, job_id: str, actor_user_id: str | None = None) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] 开始执行高程回填任务：job_id={job_id}, actor={actor_user_id or '-'}"]
    try:
        execute_apply_job(job_id=job_id, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] 高程回填任务执行成功：job_id={job_id}")
        _append_log(log_parts, task_id, log_parts[-1])
        return {"job_id": job_id, "status": "done"}
    except Exception as exc:
        log_parts.append(f"[{task_id}] 高程回填任务失败：job_id={job_id}, 错误={exc}")
        log_parts.append(f"[{task_id}] 失败堆栈：\n{traceback.format_exc()}")
        _append_log(log_parts, task_id, log_parts[-2])
        _append_log(log_parts, task_id, log_parts[-1])
        raise


# ============================================================================


@celery_app.task(name="app.tasks.elevation_tasks.analyze_elevation_file_record_job", bind=True)
def analyze_elevation_file_record_job(self, record_id: str, actor_user_id: str | None) -> dict[str, str]:
    """Analyze a single elevation file record."""
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] 开始执行高程文件分析任务：record_id={record_id}, actor={actor_user_id or '-'}"]
    try:
        execute_file_record_analysis_job(record_id=record_id, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] 高程文件分析任务执行成功：record_id={record_id}")
        _append_log(log_parts, task_id, log_parts[-1])
        return {"record_id": record_id, "status": "done"}
    except Exception as exc:
        log_parts.append(f"[{task_id}] 高程文件分析任务失败：record_id={record_id}, 错误={exc}")
        log_parts.append(f"[{task_id}] 失败堆栈：\n{traceback.format_exc()}")
        _append_log(log_parts, task_id, log_parts[-2])
        _append_log(log_parts, task_id, log_parts[-1])
        raise


