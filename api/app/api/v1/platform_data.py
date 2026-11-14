from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.platform_data import (
    PLATFORM_DATA_CATEGORIES,
    PlatformDataExportRequest,
    PlatformDataImportReuseRequest,
    PlatformDataJobDetail,
    PlatformDataJobListResponse,
    PlatformDataJobSummary,
)
from ...services import platform_data_service as svc

router = APIRouter(prefix="/admin/platform-data", tags=["platform-data"])


def _to_summary(job) -> PlatformDataJobSummary:
    manifest = job.manifest_json or {}
    artifact_filename = f"platform-data-{job.kind}-{job.id}.zip" if job.artifact_storage_path else None
    return PlatformDataJobSummary(
        id=job.id,
        kind=job.kind,
        status=job.status,
        categories=manifest.get("categories"),
        schema_version=manifest.get("bundle_schema_version"),
        artifact_filename=artifact_filename,
        source_site=manifest.get("source_site"),
        create_date=job.create_date,
        finish_date=job.finish_date,
        result_summary=job.result_summary_json,
        error_message=job.error_message,
    )


def _to_detail(job) -> PlatformDataJobDetail:
    summary = _to_summary(job)
    return PlatformDataJobDetail(
        **summary.model_dump(),
        request_payload=job.request_payload_json or {},
        manifest=job.manifest_json,
        artifact_storage_path=job.artifact_storage_path,
        artifact_file_id=job.artifact_file_id,
    )


@router.post(
    "/export",
    response_model=PlatformDataJobSummary,
    dependencies=[Depends(require_enabled_menu_route)],
)
def export_platform_data(
    payload: PlatformDataExportRequest,
    current_user: CurrentUser = Depends(require_any_permission("platform_data.manage")),
    db: Session = Depends(get_db),
) -> PlatformDataJobSummary:
    """导出基础数据包：勾选类别 + 筛选条件，立即返回 job_id（异步打包，不阻塞）。"""
    bad = [c for c in payload.categories if c not in PLATFORM_DATA_CATEGORIES]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的类别: {bad}（可选：{PLATFORM_DATA_CATEGORIES}）",
        )
    try:
        job = svc.init_export(
            db,
            categories=payload.categories,
            filters=payload.filters,
            actor_user_id=current_user.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_summary(job)


@router.post(
    "/import",
    response_model=PlatformDataJobSummary,
    dependencies=[Depends(require_enabled_menu_route)],
)
async def import_platform_data(
    current_user: CurrentUser = Depends(require_any_permission("platform_data.manage")),
    db: Session = Depends(get_db),
    file: UploadFile | None = File(default=None),
    source_job_id: str | None = Form(default=None),
) -> PlatformDataJobSummary:
    """导入基础数据包：上传包文件 **或** 指定复用某次历史 export job_id，立即返回 job_id（异步）。"""
    upload_bytes: bytes | None = None
    upload_filename: str | None = None
    if file is not None and file.filename:
        upload_bytes = await file.read()
        upload_filename = file.filename
    if upload_bytes is None and not source_job_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="导入必须提供上传包文件或指定复用的 export job_id",
        )
    try:
        job = svc.init_import(
            db,
            upload_bytes=upload_bytes,
            upload_filename=upload_filename,
            source_job_id=source_job_id,
            actor_user_id=current_user.user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_summary(job)


@router.get(
    "/jobs",
    response_model=PlatformDataJobListResponse,
    dependencies=[Depends(require_enabled_menu_route)],
)
def list_platform_data_jobs(
    kind: str | None = Query(default=None, pattern="^(export|import)$"),
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("platform_data.manage")),
    db: Session = Depends(get_db),
) -> PlatformDataJobListResponse:
    """列出历史导入 / 导出任务（含状态、产物、清单摘要）。"""
    total, rows = svc.list_jobs(db, kind=kind, status=job_status, limit=limit, offset=offset)
    return PlatformDataJobListResponse(total=total, items=[_to_summary(r) for r in rows])


@router.get(
    "/jobs/{job_id}",
    response_model=PlatformDataJobDetail,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_platform_data_job(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("platform_data.manage")),
    db: Session = Depends(get_db),
) -> PlatformDataJobDetail:
    job = svc.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return _to_detail(job)


@router.get(
    "/jobs/{job_id}/download",
    dependencies=[Depends(require_enabled_menu_route)],
)
def download_platform_data_job(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("platform_data.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """重新下载某次导出 / 导入的产物包。"""
    try:
        filename, content, content_type = svc.download_job_artifact(db, job_id)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type=content_type or "application/octet-stream", headers=headers)
