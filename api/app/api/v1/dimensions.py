from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.dimension_item import (
    DimensionItemCreateRequest,
    DimensionItemListResponse,
    DimensionItemSummary,
    DimensionItemTreeNode,
    DimensionItemUpdateRequest,
)
from ...services.dimension_item_service import (
    create_dimension_item,
    delete_dimension_item,
    get_dimension_item_by_id,
    get_dimension_tree,
    list_dimension_items,
    serialize_dimension_item,
    update_dimension_item,
)

router = APIRouter(prefix="/dimensions", tags=["dimensions"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("", response_model=DimensionItemListResponse)
def get_dimension_item_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
    dimension_type: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("dimension.read", "dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionItemListResponse:
    return list_dimension_items(
        db,
        limit=limit,
        offset=offset,
        keyword=keyword,
        dimension_type=dimension_type,
        enabled=enabled,
    )


@router.get("/tree", response_model=list[DimensionItemTreeNode])
def get_dimension_item_tree(
    dimension_type: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("dimension.read", "dimension.manage")),
    db: Session = Depends(get_db),
) -> list[DimensionItemTreeNode]:
    return get_dimension_tree(db, dimension_type=dimension_type)


@router.post("", response_model=DimensionItemSummary)
def create_dimension_item_endpoint(
    payload: DimensionItemCreateRequest,
    current_user: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionItemSummary:
    created = create_dimension_item(db, payload, actor=current_user.user)
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="维度项编码已存在或父节点不存在")
    return created


@router.patch("/{item_id}", response_model=DimensionItemSummary)
def update_dimension_item_endpoint(
    item_id: str,
    payload: DimensionItemUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionItemSummary:
    updated = update_dimension_item(db, item_id, payload, actor=current_user.user)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="维度项不存在或更新失败")
    return updated


@router.delete("/{item_id}")
def delete_dimension_item_endpoint(
    item_id: str,
    _: CurrentUser = Depends(require_permission("dimension.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_dimension_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="维度项不存在或存在子节点")
    return {"success": True}


@router.get("/{item_id}", response_model=DimensionItemSummary)
def get_dimension_item_detail(
    item_id: str,
    _: CurrentUser = Depends(require_any_permission("dimension.read", "dimension.manage")),
    db: Session = Depends(get_db),
) -> DimensionItemSummary:
    item = get_dimension_item_by_id(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="维度项不存在")
    return serialize_dimension_item(item)
