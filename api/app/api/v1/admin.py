from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import (
    CurrentUser,
    get_current_user,
    require_any_permission,
    require_enabled_menu_route,
    require_permission,
)
from ...exceptions.menu_exceptions import MenuValidationError
from ...schemas.admin import (
    AuditLogListResponse,
    MenuCreateRequest,
    MenuListResponse,
    MenuPublic,
    MenuTreeItem,
    MenuUpdateRequest,
    RoleCreateRequest,
    RoleListResponse,
    RoleMenuUpdateRequest,
    RolePublic,
    RolesWithMenusResponse,
    SeedDefaultsResponse,
    RoleUpdateRequest,
)
from ...services.admin_service import (
    build_menu_tree,
    list_audit_logs,
)
from ...services.legacy_admin_rbac_service import (
    create_menu,
    create_role,
    delete_menu,
    delete_role,
    get_menu_by_id,
    get_role_by_id,
    list_menus,
    list_permissions,
    list_role_menu_ids,
    list_roles,
    list_roles_with_menus,
    replace_role_menus,
    update_menu,
    update_role,
)
from ...services.seed_service import seed_defaults

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/roles",
    response_model=RoleListResponse,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_roles(
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("role.read", "role.manage")),
    db: Session = Depends(get_db),
) -> RoleListResponse:
    return list_roles(db, keyword=keyword, limit=limit, offset=offset)


@router.get(
    "/roles-with-menus",
    response_model=RolesWithMenusResponse,
    dependencies=[Depends(require_enabled_menu_route)],
)
def get_roles_with_menus(
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("role.read", "role.manage")),
    db: Session = Depends(get_db),
) -> RolesWithMenusResponse:
    return list_roles_with_menus(db, keyword=keyword, limit=limit, offset=offset)


@router.post(
    "/roles",
    response_model=RolePublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def create_role_endpoint(
    payload: RoleCreateRequest,
    current_user: CurrentUser = Depends(require_permission("role.manage")),
    db: Session = Depends(get_db),
) -> RolePublic:
    created = create_role(db, payload, actor_user_id=current_user.user.id)
    if not created:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="创建角色失败，角色编码已存在或菜单权限配置不正确")
    return created


@router.patch(
    "/roles/{role_id}",
    response_model=RolePublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def update_role_endpoint(
    role_id: str,
    payload: RoleUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("role.manage")),
    db: Session = Depends(get_db),
) -> RolePublic:
    updated = update_role(db, role_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found or invalid update payload")
    return updated


@router.delete("/roles/{role_id}", dependencies=[Depends(require_enabled_menu_route)])
def delete_role_endpoint(
    role_id: str,
    current_user: CurrentUser = Depends(require_permission("role.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_role(db, role_id, actor_user_id=current_user.user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found or protected role cannot be deleted")
    return {"success": True}


@router.get("/roles/{role_id}/menus", dependencies=[Depends(require_enabled_menu_route)])
def get_role_menus(
    role_id: str,
    _: CurrentUser = Depends(require_any_permission("role.read", "role.manage")),
    db: Session = Depends(get_db),
) -> dict[str, list[str]]:
    if not get_role_by_id(db, role_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    menu_ids = list_role_menu_ids(db, role_id)
    return {"menu_ids": menu_ids or []}


@router.put(
    "/roles/{role_id}/menus",
    response_model=RolePublic,
    dependencies=[Depends(require_enabled_menu_route)],
)
def replace_role_menus_endpoint(
    role_id: str,
    payload: RoleMenuUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("role.manage")),
    db: Session = Depends(get_db),
) -> RolePublic:
    updated = replace_role_menus(db, role_id, payload.menu_ids, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Role not found or invalid menu ids")
    return updated


@router.get("/permissions")
def get_permissions(
    _: CurrentUser = Depends(require_any_permission("role.read", "role.manage")),
    db: Session = Depends(get_db),
) -> dict[str, list[dict[str, str | int]]]:
    return {"items": list_permissions(db)}


@router.get("/audit-logs", response_model=AuditLogListResponse)
def get_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("menu.read", "menu.manage")),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    return list_audit_logs(
        db,
        limit=limit,
        offset=offset,
        action=action,
        user_id=user_id,
    )


@router.post("/system/seed-defaults", response_model=SeedDefaultsResponse)
def seed_defaults_endpoint(
    force: bool = Query(default=False),
    _: CurrentUser = Depends(require_permission("menu.manage")),
    db: Session = Depends(get_db),
) -> SeedDefaultsResponse:
    result = seed_defaults(db, force=force)
    return SeedDefaultsResponse.model_validate(result.to_response())


@router.get("/menus", response_model=MenuListResponse)
def get_menus(
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("menu.read", "menu.manage")),
    db: Session = Depends(get_db),
) -> MenuListResponse:
    return list_menus(db, keyword=keyword, status=status)


@router.post("/menus", response_model=MenuPublic)
def create_menu_endpoint(
    payload: MenuCreateRequest,
    current_user: CurrentUser = Depends(require_permission("menu.manage")),
    db: Session = Depends(get_db),
) -> MenuPublic:
    try:
        return create_menu(db, payload, actor_user_id=current_user.user.id)
    except MenuValidationError as e:
        # Return detailed error with field information if available
        detail = e.message
        if hasattr(e, 'field') and e.field:
            detail = f"{e.message} (字段: {e.field})"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


@router.patch("/menus/{menu_id}", response_model=MenuPublic)
def update_menu_endpoint(
    menu_id: str,
    payload: MenuUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("menu.manage")),
    db: Session = Depends(get_db),
) -> MenuPublic:
    if not get_menu_by_id(db, menu_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu not found")
    updated = update_menu(db, menu_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid menu update payload")
    return updated


@router.delete("/menus/{menu_id}")
def delete_menu_endpoint(
    menu_id: str,
    current_user: CurrentUser = Depends(require_permission("menu.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_menu(db, menu_id, actor_user_id=current_user.user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Menu not found or protected menu cannot be deleted")
    return {"success": True}


@router.get("/menus/tree", response_model=list[MenuTreeItem])
def get_menu_tree(
    _: CurrentUser = Depends(require_any_permission("menu.read", "menu.manage")),
    db: Session = Depends(get_db),
) -> list[MenuTreeItem]:
    return build_menu_tree(db)


@router.get("/me/menus", response_model=list[MenuTreeItem])
def get_current_user_menus(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[MenuTreeItem]:
    return build_menu_tree(db, role_codes=current_user.role_codes)
