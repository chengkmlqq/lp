from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.system_param import (
    SystemParamCreateRequest,
    SystemParamListResponse,
    SystemParamSummary,
    SystemParamUpdateRequest,
)
from ...services.system_param_service import (
    create_system_param,
    delete_system_param,
    get_system_param_by_id,
    list_system_params,
    serialize_system_param,
    update_system_param,
)

router = APIRouter(
    prefix="/admin/system-params",
    tags=["admin-system-params"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("", response_model=SystemParamListResponse)
def get_system_params(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _: CurrentUser = Depends(require_any_permission("system_param.read", "system_param.manage")),
    db: Session = Depends(get_db),
) -> SystemParamListResponse:
    return list_system_params(db, limit=limit, offset=offset, keyword=keyword, status_filter=status_filter)


@router.post("", response_model=SystemParamSummary)
def create_system_param_endpoint(
    payload: SystemParamCreateRequest,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> SystemParamSummary:
    created = create_system_param(db, payload, actor_user_id=current_user.user.id)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System parameter key already exists",
        )
    return created


@router.get("/{param_id}", response_model=SystemParamSummary)
def get_system_param_detail(
    param_id: int,
    _: CurrentUser = Depends(require_any_permission("system_param.read", "system_param.manage")),
    db: Session = Depends(get_db),
) -> SystemParamSummary:
    item = get_system_param_by_id(db, param_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System parameter not found")
    return serialize_system_param(item)


@router.patch("/{param_id}", response_model=SystemParamSummary)
def update_system_param_endpoint(
    param_id: int,
    payload: SystemParamUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> SystemParamSummary:
    updated = update_system_param(db, param_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System parameter not found")
    return updated


@router.delete("/{param_id}")
def delete_system_param_endpoint(
    param_id: int,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_system_param(db, param_id, actor_user_id=current_user.user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System parameter not found")
    return {"success": True}
