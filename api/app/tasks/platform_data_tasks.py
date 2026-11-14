from __future__ import annotations

import traceback

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..services import platform_data_service as svc


@celery_app.task(name="app.tasks.platform_data_tasks.export_platform_data_job", bind=True)
def export_platform_data_job(self, job_id: str) -> None:
    """异步导出平台基础数据包：组装 ZIP 并落 MinIO，回写 platform_data_job。"""
    task_id = self.request.id
    try:
        with SessionLocal() as db:
            svc.run_export_job(db, job_id)
    except Exception as exc:  # noqa: BLE001
        try:
            from ..services.task_log_service import upload_task_log

            upload_task_log(task_id, f"[{task_id}] export_platform_data_job {job_id} FAILED: {exc}\n{traceback.format_exc()}")
        except Exception:  # noqa: BLE001
            pass
        raise


@celery_app.task(name="app.tasks.platform_data_tasks.import_platform_data_job", bind=True)
def import_platform_data_job(self, job_id: str) -> None:
    """异步导入平台基础数据包：校验 schema_version，按自然键幂等 upsert，落库收到的包。"""
    task_id = self.request.id
    try:
        with SessionLocal() as db:
            svc.run_import_job(db, job_id)
    except Exception as exc:  # noqa: BLE001
        try:
            from ..services.task_log_service import upload_task_log

            upload_task_log(task_id, f"[{task_id}] import_platform_data_job {job_id} FAILED: {exc}\n{traceback.format_exc()}")
        except Exception:  # noqa: BLE001
            pass
        raise
