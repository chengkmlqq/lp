from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.dimension_type import (
    DimensionTypeCreateRequest,
    DimensionTypeSummary,
    DimensionTypeTreeItem,
    DimensionTypeUpdateRequest,
)
from ...services.dimension_type_service import (
    create_dimension_type,
    delete_dimension_type,
    get_dimension_type_tree,
    update_dimension_type,
)

router = APIRouter(
    prefix="/dimensions/types",
    tags=["dimensions"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/tree", response_model=list[DimensionTypeTreeItem])
def get_dimension_type_tree_endpoint(
    _: CurrentUser = Depends(require_any_permission("dimension.read", "dimension.manage")),
    db: Session = Depends(get_db),
) -> list[DimensionTypeTreeItem]:
    return get_dimension_type_tree(db)


@router.post("", response_model=DimensionTypeSummary)
def create_dimension_type_endpoint(
    payload: DimensionTypeCreateRequest,
    current_user: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionTypeSummary:
    created = create_dimension_type(db, payload, actor=current_user.user)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="类型编码已存在或父类型不存在")
    return created


@router.patch("/{type_id}", response_model=DimensionTypeSummary)
def update_dimension_type_endpoint(
    type_id: str,
    payload: DimensionTypeUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionTypeSummary:
    updated = update_dimension_type(db, type_id, payload, actor=current_user.user)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="维度类型不存在或更新失败")
    return updated


@router.delete("/{type_id}")
def delete_dimension_type_endpoint(
    type_id: str,
    _: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_dimension_type(db, type_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="维度类型不存在或存在维度值引用")
    return {"success": True}