from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.atp_asset_service import execute_asset_run_job
@celery_app.task(name="app.tasks.atp_asset_tasks.execute_atp_asset_run_job", bind=True, queue="wine")
def execute_atp_asset_run_job(
    self,
    run_id: str,
    payload_data: dict,
    actor_user_id: str | None,
) -> None:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting ATP asset run {run_id}"]
    try:
        execute_asset_run_job(run_id=run_id, payload_data=payload_data, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] ATP asset run {run_id} completed successfully")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] ATP asset run {run_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise



@celery_app.task(name="app.tasks.atp_asset_tasks.execute_atp_asset_test_run_job", bind=True, queue="wine")
def execute_atp_asset_test_run_job(
    self,
    run_id: str,
    payload_data: dict,
    actor_user_id: str | None,
) -> None:
    """ATP 模型「单模型测试」：分段执行 + 产出 compare.json（与 C# 端对拍用）。

    必须跑在 wine worker（queue="wine"）：只有该容器有 wine + /app/data/wine/ATP 引擎卷。
    """
    from ..services.atp_asset_test_service import execute_test_run_job

    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting ATP asset test run {run_id}"]
    try:
        execute_test_run_job(run_id=run_id, payload_data=payload_data, actor_user_id=actor_user_id)
        log_parts.append(f"[{task_id}] ATP asset test run {run_id} finished")
        _upload_test_log(task_id, "\n".join(log_parts))
    except Exception as exc:
        import traceback

        log_parts.append(f"[{task_id}] ATP asset test run {run_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        _upload_test_log(task_id, "\n".join(log_parts))
        raise


def _upload_test_log(task_id: str, log_content: str) -> None:
    try:
        from ..services.task_log_service import upload_task_log

        upload_task_log(task_id, log_content)
    except Exception:
        pass



