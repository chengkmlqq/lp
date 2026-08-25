from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.atp_asset_service import execute_asset_run_job, process_release_archive_upload


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


@celery_app.task(name="app.tasks.atp_asset_tasks.process_release_archive_upload", bind=True)
def process_release_archive_upload_task(
    self,
    asset_id: str,
    release_tag: str | None,
    archive_filename: str,
    archive_content: bytes,
    actor_user_id: str,
) -> dict:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Processing release archive upload: {archive_filename} for asset {asset_id}"]
    try:
        result = process_release_archive_upload(
            asset_id=asset_id,
            release_tag=release_tag,
            archive_filename=archive_filename,
            archive_content=archive_content,
            actor_user_id=actor_user_id,
        )
        log_parts.append(f"[{task_id}] Release archive upload completed for asset {asset_id}")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return result
    except Exception as exc:
        import traceback
        log_parts.append(f"[{task_id}] Release archive upload FAILED for asset {asset_id}: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise
