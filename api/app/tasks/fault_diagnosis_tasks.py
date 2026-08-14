from __future__ import annotations

from ..core.celery_app import celery_app


@celery_app.task(
    name="app.tasks.fault_diagnosis_tasks.run_fault_diagnosis_task",
    bind=True,
    # 判别任务走独立队列：仅 fquiz-matlab-worker（含 Wine + MATLAB Runtime）消费，
    # 保证 MATLAB 行波判别不因落到无 Runtime 的普通 worker 而降级。
    queue="matlab-diagnostics",
    soft_time_limit=300,
    time_limit=600,
)
def run_fault_diagnosis_task(self, analysis_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting fault diagnosis for analysis {analysis_id}"]
    try:
        from ..services.fault_diagnosis_service import run_fault_diagnosis
        from ..core.database import SessionLocal

        db = SessionLocal()
        try:
            run_fault_diagnosis(db, analysis_id)
        finally:
            db.close()
        log_parts.append(f"[{task_id}] Fault diagnosis for analysis {analysis_id} completed")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return {"analysis_id": analysis_id, "status": "done"}
    except Exception as exc:
        import traceback

        log_parts.append(f"[{task_id}] Fault diagnosis for analysis {analysis_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise
