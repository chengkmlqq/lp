from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.task_log import TaskLogResponse, TaskLogUploadRequest, TaskLogUploadResponse
from ...services.task_log_service import (
    TaskLogNotFoundError,
    TaskLogServiceError,
    get_task_log,
    list_task_logs,
    upload_task_log,
)

router = APIRouter(prefix="/admin/task-logs", tags=["admin-task-logs"], dependencies=[Depends(require_enabled_menu_route)])


@router.post("/upload", response_model=TaskLogUploadResponse)
def upload_log(
    request: TaskLogUploadRequest,
    _: CurrentUser = Depends(require_any_permission("celery.manage")),
) -> TaskLogUploadResponse:
    """
    Upload task execution log to MinIO storage.
    Logs are stored in the path: logs/YYYY/MM/DD/{task_id}.log
    """
    try:
        log_path, uploaded_at = upload_task_log(request.task_id, request.log_content)
        return TaskLogUploadResponse(
            task_id=request.task_id,
            log_path=log_path,
            uploaded_at=uploaded_at,
        )
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}", response_model=TaskLogResponse)
def get_log(
    task_id: str,
    log_date: datetime | None = Query(default=None, description="Date of the log (defaults to today)"),
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> TaskLogResponse:
    """
    Retrieve task execution log from MinIO storage.
    If log_date is not provided, tries to find the log for today.
    """
    try:
        log_content, log_path = get_task_log(task_id, log_date)
        return TaskLogResponse(
            task_id=task_id,
            log_content=log_content,
            log_path=log_path,
            exists=True,
        )
    except TaskLogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}/list", response_model=list[str])
def list_logs(
    task_id: str,
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> list[str]:
    """
    List all available logs for a task across all dates.
    Returns list of log paths, sorted by most recent first.
    """
    try:
        return list_task_logs(task_id)
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
