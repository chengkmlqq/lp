from __future__ import annotations

import asyncio

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models.audit_log import AuditLog
from ..models.menu import Menu
from ..models.rbac import Permission, Role
from ..models.user import User
from ..schemas.admin import (
    AuditLogListResponse,
    AuditLogPublic,
    MenuCreateRequest,
    MenuListResponse,
    MenuPublic,
    MenuTreeItem,
    MenuUpdateRequest,
    RoleCreateRequest,
    RoleListResponse,
    RolePublic,
    RoleUpdateRequest,
)
from .legacy_authz_service import build_legacy_menu_tree
from .push_service import publish_topic
from .user_service import queue_users_auth_refresh


AUDIT_LOG_LOAD_OPTIONS = (
    selectinload(AuditLog.user).selectinload(User.roles),
)

REMOVED_MENU_CODES = {
    "dashboard",
    "admin.wxapp",
    "admin.inbox",
    "admin.code_review",
    "admin.git_desktop",
    "admin.agent",
    "admin.mcp_server",
    "admin.requirements",
    "admin.schedule",
    "admin.mindmap",
    "admin.mermaid_mgr",
    "admin.api_tester",
    "admin.orchestration",
    "admin.mdresolve",
    "admin.data_query",
    "admin.hot_search",
    "admin.filedetector",
    "admin.baidu_pan",
    "admin.tag",
    "admin.knowledge_point_mgr",
    "admin.question_bank",
    "admin.cron_task_mgr",
    "admin.todos",
    "admin.job_mgr",
    "admin.jwt_generator",
    "admin.queue_mgr",
    "admin.knowledge_mastery",
}


def _is_removed_menu_code(code: str | None) -> bool:
    return (code or "").strip() in REMOVED_MENU_CODES


def _audit_log_stmt():
    return select(AuditLog).options(*AUDIT_LOG_LOAD_OPTIONS)


def serialize_audit_log(log: AuditLog) -> AuditLogPublic:
    return AuditLogPublic(
        id=log.id,
        user_id=log.user_id,
        username=log.user.username if log.user else None,
        action=log.action,
        detail=log.detail,
        created_at=log.created_at,
    )


def list_audit_logs(
    db: Session,
    *,
    limit: int,
    offset: int,
    action: str | None,
    user_id: str | None,
) -> AuditLogListResponse:
    stmt = _audit_log_stmt()
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)

    total_stmt = select(func.count()).select_from(AuditLog)
    if action:
        total_stmt = total_stmt.where(AuditLog.action == action)
    if user_id:
        total_stmt = total_stmt.where(AuditLog.user_id == user_id)

    total = db.scalar(total_stmt) or 0
    logs = db.execute(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
    ).scalars().all()

    return AuditLogListResponse(
        items=[serialize_audit_log(log) for log in logs],
        total=total,
        limit=limit,
        offset=offset,
    )


def _role_stmt():
    # Build loader options lazily to avoid triggering mapper configuration
    # during module import before all models are registered.
    return select(Role).options(
        selectinload(Role.permissions),
        selectinload(Role.menus),
    )


def _menu_stmt():
    return select(Menu).options(selectinload(Menu.children))


def serialize_role(role: Role) -> RolePublic:
    return RolePublic(
        id=role.id,
        code=role.code,
        name=role.name,
        permission_codes=sorted({permission.code for permission in role.permissions}),
        menu_ids=sorted({menu.id for menu in role.menus}),
    )


def list_roles(db: Session) -> RoleListResponse:
    total = db.scalar(select(func.count()).select_from(Role)) or 0
    roles = db.execute(_role_stmt().order_by(Role.id.asc())).scalars().all()
    return RoleListResponse(items=[serialize_role(role) for role in roles], total=total)


def get_role_by_id(db: Session, role_id: int) -> Role | None:
    return db.execute(_role_stmt().where(Role.id == role_id)).scalar_one_or_none()


def get_role_by_code(db: Session, code: str) -> Role | None:
    return db.execute(_role_stmt().where(Role.code == code)).scalar_one_or_none()


def create_role(db: Session, payload: RoleCreateRequest) -> RolePublic | None:
    existing = db.scalar(select(Role.id).where(Role.code == payload.code))
    if existing:
        return None

    permissions = _load_permissions_by_codes(db, payload.permission_codes)
    if len(permissions) != len(set(payload.permission_codes)):
        return None

    menus = _load_menus_by_ids(db, payload.menu_ids)
    if len(menus) != len(set(payload.menu_ids)):
        return None

    role = Role(code=payload.code, name=payload.name)
    role.permissions = permissions
    role.menus = menus
    db.add(role)
    db.commit()
    saved = get_role_by_code(db, payload.code)
    if saved:
        _fire_and_forget(
            publish_topic(
                "admin.roles",
                name="roles.changed",
                payload={"action": "created", "role_id": saved.id, "role_code": saved.code},
                requires_refetch=["/api/v1/admin/roles"],
                dedupe_key=f"roles:created:{saved.id}",
            )
        )
    return serialize_role(saved) if saved else None


def update_role(db: Session, role_id: int, payload: RoleUpdateRequest) -> RolePublic | None:
    role = get_role_by_id(db, role_id)
    if not role:
        return None

    if payload.name is not None:
        role.name = payload.name

    permissions_changed = False
    if payload.permission_codes is not None:
        permissions = _load_permissions_by_codes(db, payload.permission_codes)
        if len(permissions) != len(set(payload.permission_codes)):
            return None
        role.permissions = permissions
        permissions_changed = True

    menus_changed = False
    if payload.menu_ids is not None:
        menus = _load_menus_by_ids(db, payload.menu_ids)
        if len(menus) != len(set(payload.menu_ids)):
            return None
        role.menus = menus
        menus_changed = True

    impacted_user_ids = _get_role_user_ids(role)
    db.commit()
    saved = get_role_by_id(db, role_id)
    if saved:
        if permissions_changed or menus_changed:
            queue_users_auth_refresh(db, impacted_user_ids)
        _fire_and_forget(
            publish_topic(
                "admin.roles",
                name="roles.changed",
                payload={"action": "updated", "role_id": saved.id, "role_code": saved.code},
                requires_refetch=["/api/v1/admin/roles"],
                dedupe_key=f"roles:updated:{saved.id}",
            )
        )
        if menus_changed:
            _fire_and_forget(
                publish_topic(
                    "admin.menus",
                    name="menus.changed",
                    payload={"action": "role_menus_updated", "role_id": saved.id, "role_code": saved.code},
                    requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
                    dedupe_key=f"menus:role_updated:{saved.id}",
                )
            )
    return serialize_role(saved) if saved else None


def delete_role(db: Session, role_id: int) -> bool:
    role = get_role_by_id(db, role_id)
    if not role or role.code in {"admin", "user"}:
        return False
    deleted_role_id = role.id
    deleted_role_code = role.code
    impacted_user_ids = _get_role_user_ids(role)
    db.delete(role)
    db.commit()
    queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.roles",
            name="roles.changed",
            payload={"action": "deleted", "role_id": deleted_role_id, "role_code": deleted_role_code},
            requires_refetch=["/api/v1/admin/roles"],
            dedupe_key=f"roles:deleted:{deleted_role_id}",
        )
    )
    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "role_deleted", "role_id": deleted_role_id, "role_code": deleted_role_code},
            requires_refetch=["/api/v1/admin/me/menus"],
            dedupe_key=f"menus:role_deleted:{deleted_role_id}",
        )
    )
    return True


def list_permissions(db: Session) -> list[dict[str, str | int]]:
    permissions = db.execute(select(Permission).order_by(Permission.code.asc())).scalars().all()
    return [{"id": permission.id, "code": permission.code, "name": permission.name} for permission in permissions]


def serialize_menu(menu: Menu) -> MenuPublic:
    return MenuPublic(
        id=str(menu.id),
        code=menu.code,
        name=menu.name,
        path=menu.path,
        icon=menu.icon,
        parent_id=str(menu.parent_id) if menu.parent_id is not None else None,
        type=menu.type,
        sort_order=menu.sort_order,
        status=menu.status,
        visible=menu.visible,
        cacheable=menu.cacheable,
        component=menu.component,
        permission_code=menu.permission_code,
    )


def list_menus(db: Session) -> MenuListResponse:
    menus = db.execute(_menu_stmt().order_by(Menu.sort_order.asc(), Menu.id.asc())).scalars().all()
    menus = [menu for menu in menus if not _is_removed_menu_code(menu.code)]
    total = len(menus)
    return MenuListResponse(items=[serialize_menu(menu) for menu in menus], total=total)


def get_menu_by_id(db: Session, menu_id: int) -> Menu | None:
    menu = db.execute(_menu_stmt().where(Menu.id == menu_id)).scalar_one_or_none()
    if menu and _is_removed_menu_code(menu.code):
        return None
    return menu


def get_menu_by_code(db: Session, code: str) -> Menu | None:
    if _is_removed_menu_code(code):
        return None
    return db.execute(_menu_stmt().where(Menu.code == code)).scalar_one_or_none()


def create_menu(db: Session, payload: MenuCreateRequest) -> MenuPublic | None:
    if _is_removed_menu_code(payload.code):
        return None
    existing = db.scalar(select(Menu.id).where(Menu.code == payload.code))
    if existing:
        return None

    if payload.parent_id is not None:
        parent = db.scalar(select(Menu.id).where(Menu.id == payload.parent_id))
        if parent is None:
            return None

    menu = Menu(
        code=payload.code,
        name=payload.name,
        path=payload.path,
        icon=payload.icon,
        parent_id=payload.parent_id,
        type=payload.type,
        sort_order=payload.sort_order,
        status=payload.status,
        visible=payload.visible,
        cacheable=payload.cacheable,
        component=payload.component,
        permission_code=payload.permission_code,
    )
    db.add(menu)
    db.commit()
    saved = get_menu_by_code(db, payload.code)
    if saved:
        _fire_and_forget(
            publish_topic(
                "admin.menus",
                name="menus.changed",
                payload={"action": "created", "menu_id": saved.id, "menu_code": saved.code},
                requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
                dedupe_key=f"menus:created:{saved.id}",
            )
        )
    return serialize_menu(saved) if saved else None


def update_menu(db: Session, menu_id: int, payload: MenuUpdateRequest) -> MenuPublic | None:
    menu = get_menu_by_id(db, menu_id)
    if not menu:
        return None

    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        parent_id = update_data["parent_id"]
        if parent_id == menu.id:
            return None
        if parent_id is not None:
            parent = db.scalar(select(Menu.id).where(Menu.id == parent_id))
            if parent is None:
                return None
        menu.parent_id = parent_id

    for field in [
        "name",
        "path",
        "icon",
        "type",
        "sort_order",
        "status",
        "visible",
        "cacheable",
        "component",
        "permission_code",
    ]:
        if field in update_data:
            setattr(menu, field, update_data[field])

    impacted_user_ids = _get_users_with_menu_access(db, menu.id)
    db.commit()
    saved = get_menu_by_id(db, menu_id)
    if saved:
        queue_users_auth_refresh(db, impacted_user_ids)
        _fire_and_forget(
            publish_topic(
                "admin.menus",
                name="menus.changed",
                payload={"action": "updated", "menu_id": saved.id, "menu_code": saved.code},
                requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
                dedupe_key=f"menus:updated:{saved.id}",
            )
        )
    return serialize_menu(saved) if saved else None


def delete_menu(db: Session, menu_id: int) -> bool:
    menu = get_menu_by_id(db, menu_id)
    if not menu or menu.code in {
        "admin.users",
        "admin.roles",
        "admin.menus",
        "admin.system_params",
        "admin.system_message",
        "admin.system",
        "admin.system_monitor",
        "admin.basic_data",
        "admin.power_lines",
        "admin.fl_analysis",
        "admin.fault_recurrence",
        "admin.lightning_currents",
        "admin.lightning_distribution",
        "admin.workers",
        "admin.task_monitor",
        "admin.scheduled_tasks",
        "admin.atp_models",
        "admin.tower_models",
        "admin.files",
        "admin.elevation",
        "admin.syslog",
        "admin.wine_runner",
    }:
        return False
    child_exists = db.scalar(select(Menu.id).where(Menu.parent_id == menu_id))
    if child_exists is not None:
        return False
    deleted_menu_id = menu.id
    deleted_menu_code = menu.code
    impacted_user_ids = _get_users_with_menu_access(db, menu.id)
    db.delete(menu)
    db.commit()
    queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "deleted", "menu_id": deleted_menu_id, "menu_code": deleted_menu_code},
            requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
            dedupe_key=f"menus:deleted:{deleted_menu_id}",
        )
    )
    return True


def build_menu_tree(db: Session, *, role_codes: set[str] | None = None) -> list[MenuTreeItem]:
    legacy_tree = build_legacy_menu_tree(db, role_codes=role_codes)
    if legacy_tree:
        return [MenuTreeItem.model_validate(item) for item in legacy_tree]

    menus = db.execute(_menu_stmt().order_by(Menu.sort_order.asc(), Menu.id.asc())).scalars().all()
    menus = [menu for menu in menus if not _is_removed_menu_code(menu.code)]
    menus = [menu for menu in menus if menu.status == "enabled" and menu.visible]
    if role_codes is not None and "admin" not in role_codes:
        allowed_ids = _get_allowed_menu_ids(db, role_codes)
        menus = [menu for menu in menus if menu.id in allowed_ids]

    return _to_tree(menus)


def list_role_menu_ids(db: Session, role_id: int) -> list[int] | None:
    role = get_role_by_id(db, role_id)
    if not role:
        return None
    return sorted({menu.id for menu in role.menus})


def replace_role_menus(db: Session, role_id: int, menu_ids: list[int]) -> RolePublic | None:
    role = get_role_by_id(db, role_id)
    if not role:
        return None

    menus = _load_menus_by_ids(db, menu_ids)
    if len(menus) != len(set(menu_ids)):
        return None

    impacted_user_ids = _get_role_user_ids(role)
    role.menus = menus
    db.commit()
    saved = get_role_by_id(db, role_id)
    if saved:
        queue_users_auth_refresh(db, impacted_user_ids)
        _fire_and_forget(
            publish_topic(
                "admin.roles",
                name="roles.changed",
                payload={"action": "menus_replaced", "role_id": saved.id, "role_code": saved.code},
                requires_refetch=["/api/v1/admin/roles"],
                dedupe_key=f"roles:menus_replaced:{saved.id}",
            )
        )
        _fire_and_forget(
            publish_topic(
                "admin.menus",
                name="menus.changed",
                payload={"action": "role_menus_replaced", "role_id": saved.id, "role_code": saved.code},
                requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
                dedupe_key=f"menus:role_menus_replaced:{saved.id}",
            )
        )
    return serialize_role(saved) if saved else None


def _load_permissions_by_codes(db: Session, codes: list[str]) -> list[Permission]:
    normalized = sorted(set(codes))
    if not normalized:
        return []
    return db.execute(select(Permission).where(Permission.code.in_(normalized))).scalars().all()


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)


def _load_menus_by_ids(db: Session, menu_ids: list[int]) -> list[Menu]:
    normalized = sorted(set(menu_ids))
    if not normalized:
        return []
    menus = db.execute(select(Menu).where(Menu.id.in_(normalized))).scalars().all()
    return [menu for menu in menus if not _is_removed_menu_code(menu.code)]


def _get_allowed_menu_ids(db: Session, role_codes: set[str]) -> set[int]:
    if not role_codes:
        return set()
    roles = db.execute(_role_stmt().where(Role.code.in_(sorted(role_codes)))).scalars().all()
    return {menu.id for role in roles for menu in role.menus}


def _get_role_user_ids(role: Role) -> list[str]:
    return [user.id for user in role.users]


def _get_users_with_menu_access(db: Session, menu_id: int) -> list[str]:
    users = db.execute(
        select(User)
        .join(User.roles)
        .join(Role.menus)
        .where(Menu.id == menu_id)
    ).unique().scalars().all()
    return [user.id for user in users]


def _to_tree(menus: list[Menu]) -> list[MenuTreeItem]:
    items = {
        menu.id: MenuTreeItem(**serialize_menu(menu).model_dump(), children=[])
        for menu in menus
    }
    roots: list[MenuTreeItem] = []
    for menu in menus:
        item = items[menu.id]
        if menu.parent_id and menu.parent_id in items:
            items[menu.parent_id].children.append(item)
        else:
            roots.append(item)

    def sort_children(node: MenuTreeItem) -> None:
        node.children.sort(key=lambda child: (child.sort_order, child.id))
        for child in node.children:
            sort_children(child)

    roots.sort(key=lambda item: (item.sort_order, item.id))
    for root in roots:
        sort_children(root)
    return roots
