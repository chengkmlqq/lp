from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.atp_asset_service import execute_asset_run_job, process_release_archive_upload


@celery_app.task(name="app.tasks.atp_asset_tasks.execute_atp_asset_run_job")
def execute_atp_asset_run_job(
    run_id: str,
    payload_data: dict,
    actor_user_id: str | None,
) -> None:
    execute_asset_run_job(run_id=run_id, payload_data=payload_data, actor_user_id=actor_user_id)


@celery_app.task(name="app.tasks.atp_asset_tasks.process_release_archive_upload")
def process_release_archive_upload_task(
    asset_id: str,
    release_tag: str | None,
    archive_filename: str,
    archive_content: bytes,
    actor_user_id: str,
) -> dict:
    return process_release_archive_upload(
        asset_id=asset_id,
        release_tag=release_tag,
        archive_filename=archive_filename,
        archive_content=archive_content,
        actor_user_id=actor_user_id,
    )
