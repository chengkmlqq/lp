from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.param_category import (
    ParamCategoryCreate,
    ParamCategoryTreeItem,
    ParamCategoryUpdate,
)
from ...services.param_category_service import (
    create_category,
    delete_category,
    get_category_tree,
    update_category,
)

router = APIRouter(
    prefix="/admin/system-param-categories",
    tags=["admin-system-param-categories"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/tree", response_model=list[ParamCategoryTreeItem])
def get_category_tree_endpoint(
    _: CurrentUser = Depends(require_any_permission("system_param.read", "system_param.manage")),
    db: Session = Depends(get_db),
) -> list[ParamCategoryTreeItem]:
    return get_category_tree(db)


@router.post("", response_model=ParamCategoryTreeItem)
def create_category_endpoint(
    payload: ParamCategoryCreate,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> ParamCategoryTreeItem:
    return create_category(db, payload)


@router.patch("/{category_id}", response_model=ParamCategoryTreeItem)
def update_category_endpoint(
    category_id: int,
    payload: ParamCategoryUpdate,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> ParamCategoryTreeItem:
    updated = update_category(db, category_id, payload)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return updated


@router.delete("/{category_id}")
def delete_category_endpoint(
    category_id: int,
    current_user: CurrentUser = Depends(require_permission("system_param.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_category(db, category_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found or has associated parameters",
        )
    return {"success": True}