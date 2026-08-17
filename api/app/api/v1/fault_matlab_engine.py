from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...services.fault_matlab_engine_service import (
    MatlabEngineError,
    activate_version,
    get_current_version_hash,
    list_versions,
    trigger_sync,
    upload_engine_version,
)

router = APIRouter(
    prefix="/fault-matlab",
    tags=["fault-matlab-engine"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/versions")
def get_versions(
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    versions = list_versions(db)
    current_hash = get_current_version_hash(db)
    for v in versions:
        v["is_active"] = v.get("version_hash") == current_hash
    return {"items": versions, "current_version": current_hash}


@router.post("/upload")
def upload_engine(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    try:
        version = upload_engine_version(
            db,
            content,
            uploaded_by=current_user.user.id,
            uploaded_by_name=current_user.user.user_name,
        )
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return version


@router.post("/activate/{version_hash}")
def activate_engine_version(
    version_hash: str,
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        version = activate_version(db, version_hash, actor_user_id=current_user.user.id)
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return version


@router.post("/sync")
def sync_engine(
    current_user: CurrentUser = Depends(require_permission("line.manage")),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        task_id = trigger_sync(db, actor_user_id=current_user.user.id)
    except MatlabEngineError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"task_id": task_id, "status": "dispatched"}
