from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.tower_model import (
    TowerModelCreateRequest,
    TowerModelImageUploadResponse,
    TowerModelListResponse,
    TowerModelSeedResponse,
    TowerModelSummary,
    TowerModelUpdateRequest,
)
from ...services.file_service import download_file_from_path
from ...services.tower_model_service import (
    create_tower_model,
    delete_tower_model,
    get_tower_model_by_id,
    list_tower_models,
    list_tower_models_for_selector,
    seed_tower_models_from_legacy,
    seed_tower_models_from_upload,
    serialize_tower_model,
    update_tower_model,
    upload_tower_model_image,
)

router = APIRouter(prefix="/tower-models", tags=["tower-models"])


@router.get("", response_model=TowerModelListResponse, dependencies=[Depends(require_enabled_menu_route)])
def get_tower_model_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("tower_model.read", "tower_model.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> TowerModelListResponse:
    return list_tower_models(
        db,
        limit=limit,
        offset=offset,
        keyword=keyword,
        enabled=enabled,
    )


@router.get("/selector", response_model=list[TowerModelSummary])
def get_tower_model_selector(
    _: CurrentUser = Depends(require_any_permission("tower_model.read", "tower_model.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> list[TowerModelSummary]:
    return list_tower_models_for_selector(db)


@router.post("", response_model=TowerModelSummary, dependencies=[Depends(require_enabled_menu_route)])
def create_tower_model_endpoint(
    payload: TowerModelCreateRequest,
    current_user: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> TowerModelSummary:
    created = create_tower_model(db, payload, actor=current_user.user)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="杆塔模型编码已存在")
    return created


@router.patch("/{model_id}", response_model=TowerModelSummary, dependencies=[Depends(require_enabled_menu_route)])
def update_tower_model_endpoint(
    model_id: str,
    payload: TowerModelUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> TowerModelSummary:
    updated = update_tower_model(db, model_id, payload, actor=current_user.user)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型不存在")
    return updated


@router.delete("/{model_id}", dependencies=[Depends(require_enabled_menu_route)])
def delete_tower_model_endpoint(
    model_id: str,
    _: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_tower_model(db, model_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型不存在")
    return {"success": True}


@router.post("/{model_id}/image", response_model=TowerModelImageUploadResponse, dependencies=[Depends(require_enabled_menu_route)])
def upload_tower_model_image_endpoint(
    model_id: str,
    mount_code: str = Query(..., min_length=2, max_length=64),
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> TowerModelImageUploadResponse:
    return upload_tower_model_image(
        db,
        model_id=model_id,
        mount_code=mount_code,
        file=file,
        actor=current_user.user,
    )


@router.get("/{model_id}/image", dependencies=[Depends(require_enabled_menu_route)])
def get_tower_model_image(
    model_id: str,
    _: CurrentUser = Depends(require_any_permission("tower_model.read", "tower_model.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    item = get_tower_model_by_id(db, model_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型不存在")
    if not item.image_mount_code or not item.image_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型未配置图片")

    filename, content, content_type = download_file_from_path(
        db,
        mount_code=item.image_mount_code,
        path=item.image_path,
    )
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type=content_type or "application/octet-stream", headers=headers)


@router.post("/seed/legacy", response_model=TowerModelSeedResponse, dependencies=[Depends(require_enabled_menu_route)])
def seed_legacy_tower_models_endpoint(
    overwrite_existing: bool = Query(default=False),
    current_user: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> TowerModelSeedResponse:
    return seed_tower_models_from_legacy(
        db,
        actor=current_user.user,
        overwrite_existing=overwrite_existing,
    )


@router.post("/seed/upload", response_model=TowerModelSeedResponse, dependencies=[Depends(require_enabled_menu_route)])
def seed_uploaded_tower_models_endpoint(
    overwrite_existing: bool = Query(default=False),
    setting_file: UploadFile = File(...),
    ganta_file: UploadFile = File(...),
    images_zip: UploadFile | None = File(default=None),
    current_user: CurrentUser = Depends(require_permission("tower_model.manage")),
    db: Session = Depends(get_db),
) -> TowerModelSeedResponse:
    return seed_tower_models_from_upload(
        db,
        actor=current_user.user,
        overwrite_existing=overwrite_existing,
        setting_file=setting_file,
        ganta_file=ganta_file,
        images_zip=images_zip,
    )


@router.get("/{model_id}", response_model=TowerModelSummary, dependencies=[Depends(require_enabled_menu_route)])
def get_tower_model_detail(
    model_id: str,
    _: CurrentUser = Depends(require_any_permission("tower_model.read", "tower_model.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> TowerModelSummary:
    item = get_tower_model_by_id(db, model_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔模型不存在")
    return serialize_tower_model(item)
