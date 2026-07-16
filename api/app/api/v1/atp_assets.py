from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.atp_asset import (
    AtpAssetCreateRequest,
    AtpAssetDetail,
    AtpAssetFileListResponse,
    AtpAssetListResponse,
    AtpAssetReleaseCreateRequest,
    AtpAssetReleaseDetail,
    AtpAssetReleaseListResponse,
    AtpAssetReleaseUpdateRequest,
    AtpAssetReleaseUploadResponse,
    AtpAssetRunDetail,
    AtpAssetRunListResponse,
    AtpAssetRunRequest,
    AtpAssetUpdateRequest,
    AtpEngineStatusResponse,
)
from ...services.atp_asset_service import (
    activate_release,
    create_asset,
    create_release,
    create_release_from_archive,
    delete_asset,
    get_asset_by_id,
    get_engine_status,
    get_release_by_id,
    get_run_detail,
    list_assets,
    list_asset_files,
    list_release_files,
    list_releases,
    list_runs,
    run_release,
    serialize_asset,
    serialize_release_detail,
    upload_asset_files,
    update_asset,
    update_release,
)

router = APIRouter(prefix="/atp", tags=["atp-assets"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("/engine/status", response_model=AtpEngineStatusResponse)
def get_atp_engine_status_endpoint(
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
) -> AtpEngineStatusResponse:
    return get_engine_status()


@router.get("/assets", response_model=AtpAssetListResponse)
def get_atp_asset_list(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    voltage_level: str | None = Query(default=None),
    tower_type: str | None = Query(default=None),
    scene_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetListResponse:
    return list_assets(
        db,
        keyword=keyword,
        status_filter=status_filter,
        voltage_level=voltage_level,
        tower_type=tower_type,
        scene_type=scene_type,
        limit=limit,
        offset=offset,
    )


@router.post("/assets", response_model=AtpAssetDetail)
def create_atp_asset_endpoint(
    payload: AtpAssetCreateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    created = create_asset(db, payload, actor_user_id=current_user.user.id)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Asset code already exists")
    return AtpAssetDetail(**created.model_dump())


@router.post("/assets/{asset_id}/files", response_model=AtpAssetDetail)
def upload_atp_asset_files_endpoint(
    asset_id: str,
    files: list[UploadFile] = File(...),
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    updated = upload_asset_files(
        db,
        asset_id=asset_id,
        files=files,
        actor_user_id=current_user.user.id,
    )
    return AtpAssetDetail(**updated.model_dump())


@router.get("/assets/{asset_id}", response_model=AtpAssetDetail)
def get_atp_asset_detail(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    item = get_asset_by_id(db, asset_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    active_release = next((release for release in item.releases if release.is_active), None)
    detail = serialize_asset(
        item,
        release_count=len(item.releases),
        run_count=len(item.runs),
        last_run_status=item.runs[0].status if item.runs else None,
        last_run_date=item.runs[0].create_date if item.runs else None,
        active_release=active_release,
    )
    return AtpAssetDetail(**detail.model_dump())


@router.patch("/assets/{asset_id}", response_model=AtpAssetDetail)
def update_atp_asset_endpoint(
    asset_id: str,
    payload: AtpAssetUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    updated = update_asset(db, asset_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return AtpAssetDetail(**updated.model_dump())


@router.delete("/assets/{asset_id}")
def delete_atp_asset_endpoint(
    asset_id: str,
    _: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_asset(db, asset_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return {"success": True}


@router.get("/assets/{asset_id}/files", response_model=AtpAssetFileListResponse)
def get_atp_asset_files(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileListResponse:
    return list_asset_files(db, asset_id=asset_id)


@router.get("/assets/{asset_id}/releases", response_model=AtpAssetReleaseListResponse)
def get_atp_asset_releases(
    asset_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseListResponse:
    if not get_asset_by_id(db, asset_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return list_releases(db, asset_id=asset_id, limit=limit, offset=offset)


@router.post("/assets/{asset_id}/releases", response_model=AtpAssetReleaseDetail)
def create_atp_asset_release_endpoint(
    asset_id: str,
    payload: AtpAssetReleaseCreateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseDetail:
    return create_release(db, asset_id=asset_id, payload=payload, actor_user_id=current_user.user.id)


@router.post("/assets/{asset_id}/releases/upload", response_model=AtpAssetReleaseUploadResponse)
def upload_atp_asset_release_endpoint(
    asset_id: str,
    release_tag: str | None = Form(default=None),
    archive: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseUploadResponse:
    from ...tasks.atp_asset_tasks import process_release_archive_upload_task

    try:
        archive_content = archive.file.read()
    finally:
        try:
            archive.file.close()
        except Exception:
            pass

    task = process_release_archive_upload_task.delay(
        asset_id=asset_id,
        release_tag=release_tag,
        archive_filename=archive.filename or "release.zip",
        archive_content=archive_content,
        actor_user_id=current_user.user.id,
    )

    return AtpAssetReleaseUploadResponse(task_id=task.id, status="processing")


@router.get("/releases", response_model=AtpAssetReleaseListResponse)
def get_atp_release_list(
    active_only: bool = Query(default=False),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseListResponse:
    return list_releases(
        db,
        active_only=active_only,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )


@router.get("/releases/{release_id}", response_model=AtpAssetReleaseDetail)
def get_atp_release_detail(
    release_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseDetail:
    item = get_release_by_id(db, release_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return serialize_release_detail(item)


@router.patch("/releases/{release_id}", response_model=AtpAssetReleaseDetail)
def update_atp_release_endpoint(
    release_id: str,
    payload: AtpAssetReleaseUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetReleaseDetail:
    return update_release(db, release_id=release_id, payload=payload, actor_user_id=current_user.user.id)


@router.post("/releases/{release_id}/activate", response_model=AtpAssetDetail)
def activate_atp_release_endpoint(
    release_id: str,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetDetail:
    detail = activate_release(db, release_id=release_id, actor_user_id=current_user.user.id)
    return AtpAssetDetail(**detail.model_dump())


@router.get("/releases/{release_id}/files", response_model=AtpAssetFileListResponse)
def get_atp_release_files(
    release_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileListResponse:
    return list_release_files(db, release_id=release_id)


@router.get("/assets/{asset_id}/files", response_model=AtpAssetFileListResponse)
def get_atp_asset_files(
    asset_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetFileListResponse:
    return list_asset_files(db, asset_id=asset_id)


@router.get("/releases/{release_id}/runs", response_model=AtpAssetRunListResponse)
def get_atp_release_runs(
    release_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunListResponse:
    if not get_release_by_id(db, release_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Release not found")
    return list_runs(db, release_id=release_id, limit=limit, offset=offset)


@router.post("/releases/{release_id}/runs", response_model=AtpAssetRunDetail)
def run_atp_release_endpoint(
    release_id: str,
    payload: AtpAssetRunRequest,
    current_user: CurrentUser = Depends(require_any_permission("atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunDetail:
    return run_release(db, release_id=release_id, payload=payload, actor_user_id=current_user.user.id)


@router.get("/runs/{run_id}", response_model=AtpAssetRunDetail)
def get_atp_run_detail(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpAssetRunDetail:
    return get_run_detail(db, run_id=run_id)
