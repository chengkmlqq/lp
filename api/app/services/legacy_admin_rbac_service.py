from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..exceptions.menu_exceptions import (
    DuplicateMenuCodeError,
    EmptyMenuCodeError,
    EmptyMenuNameError,
    MenuValidationError,
    ParentNotFoundError,
    RemovedMenuCodeError,
    SelfParentError,
)
from ..models.menu import Menu
from ..schemas.admin import (
    MenuCreateRequest,
    MenuListResponse,
    MenuPublic,
    MenuUpdateRequest,
    RoleCreateRequest,
    RoleListResponse,
    RolePublic,
    RolesWithMenusResponse,
    RoleUpdateRequest,
)
from .audit_service import compose_audit_detail, describe_changed_fields, summarize_values, write_audit_log
from .legacy_authz_service import (
    DEFAULT_ADMIN_PERMISSION_CODES,
    LEGACY_URL_PATH_MAP,
    MENU_CODE_PERMISSION_MAP,
)
from .push_service import publish_topic
from .user_service import queue_users_auth_refresh


PROTECTED_ROLE_IDS = {"admin", "user", "sys_mgr"}
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

PROTECTED_MENU_CODES = {
    "admin.users",
    "admin.roles",
    "admin.menus",
    "admin.system_params",
    "admin.system_message",
    "admin.system",
    "admin.system_monitor",
    "admin.wxapp",
    "admin.basic_data",
    "admin.files",
    "admin.elevation",
    "admin.tower_models",
    "admin.filedetector",
    "admin.baidu_pan",
    "admin.power_lines",
    "admin.fl_analysis",
    "admin.fault_recurrence",
    "admin.lightning_currents",
    "admin.lightning_distribution",
    "admin.workers",
    "admin.task_monitor",
    "admin.scheduled_tasks",
    "admin.atp_models",
    "admin.data_query",
    "admin.hot_search",
    "admin.cron_task_mgr",
    "admin.mdresolve",
    "admin.tag",
    "admin.knowledge_point_mgr",
    "admin.job_mgr",
    "admin.syslog",
    "admin.wine_runner",
    # quiz legacy defaults
    "sys_mgr",
    "menu_mgr",
    "role_mgr",
    "user_mgr",
}


def list_roles(
    db: Session,
    keyword: str | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> RoleListResponse:
    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"
    rows, total = _load_role_page(
        db,
        role_source=role_source,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    role_ids = [str(row["id"]) for row in rows]
    role_menu_ids = _load_role_menu_ids_map(db, role_ids, role_source=role_source)
    menu_rows = _load_menus_map(
        db,
        sorted({menu_id for ids in role_menu_ids.values() for menu_id in ids}),
        role_source=role_source,
    )
    role_permission_codes = _load_role_permission_codes_map(db, role_ids, role_source=role_source)

    items: list[RolePublic] = []
    for row in rows:
        role_id = str(row["id"])
        role_code = role_id if role_source == "legacy" else str(row.get("code") or role_id).strip() or role_id
        menu_ids = sorted(menu_id for menu_id in role_menu_ids.get(role_id, []) if menu_id in menu_rows)
        permission_codes = set(role_permission_codes.get(role_id, []))
        permission_codes.update(_permission_codes_from_menu_rows(menu_rows, menu_ids))

        items.append(
            RolePublic(
                id=role_id,
                code=role_code,
                name=(row.get("name") or role_code).strip(),
                permission_codes=sorted(permission_codes),
                menu_ids=menu_ids,
            )
        )
    return RoleListResponse(items=items, total=total)


def get_role_by_id(db: Session, role_id: str) -> RolePublic | None:
    role_id = role_id.strip()
    if not role_id:
        return None
    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"
    if role_source == "legacy":
        rows = db.execute(
            text("SELECT id, name FROM user_role WHERE id = :id"),
            {"id": role_id},
        ).mappings().all()
        role_code = role_id
        resolved_role_id = role_id
    else:
        rows = db.execute(
            text(
                """
                SELECT id::text AS id, code, name
                FROM roles
                WHERE id::text = :id OR code = :id
                LIMIT 1
                """
            ),
            {"id": role_id},
        ).mappings().all()
        resolved_role_id = str(rows[0]["id"]) if rows else ""
        role_code = str(rows[0].get("code") or resolved_role_id).strip() if rows else ""
    if not rows:
        return None
    role_menu_ids = _load_role_menu_ids_map(db, [resolved_role_id], role_source=role_source).get(resolved_role_id, [])
    menu_rows = _load_menus_map(db, role_menu_ids, role_source=role_source)
    role_permission_codes = _load_role_permission_codes_map(db, [resolved_role_id], role_source=role_source)
    filtered_menu_ids = sorted(menu_id for menu_id in role_menu_ids if menu_id in menu_rows)
    permission_codes = set(role_permission_codes.get(resolved_role_id, []))
    permission_codes.update(_permission_codes_from_menu_rows(menu_rows, filtered_menu_ids))
    return RolePublic(
        id=resolved_role_id,
        code=role_code or resolved_role_id,
        name=(rows[0].get("name") or role_code or resolved_role_id).strip(),
        permission_codes=sorted(permission_codes),
        menu_ids=filtered_menu_ids,
    )


def create_role(db: Session, payload: RoleCreateRequest, *, actor_user_id: str | None) -> RolePublic | None:
    role_id = payload.code.strip()
    if not role_id:
        return None
    role_name = payload.name.strip()
    if not role_name:
        return None

    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"

    # Check if role code already exists
    if role_source == "legacy":
        existing = db.scalar(text("SELECT id FROM user_role WHERE id = :id"), {"id": role_id})
    else:
        existing = db.scalar(text("SELECT id FROM roles WHERE code = :code"), {"code": role_id})

    if existing:
        return None

    menu_ids = sorted(set(menu_id.strip() for menu_id in payload.menu_ids if menu_id.strip()))
    if not _menu_ids_exist(db, menu_ids, role_source=role_source):
        return None

    now = datetime.now()
    try:
        if role_source == "legacy":
            db.execute(
                text(
                    """
                    INSERT INTO user_role (id, name, descr, state, create_date, update_date)
                    VALUES (:id, :name, :descr, 'ENABLED', :create_date, :update_date)
                    """
                ),
                {
                    "id": role_id,
                    "name": role_name,
                    "descr": role_name,
                    "create_date": now,
                    "update_date": now,
                },
            )
        else:
            db.execute(
                text(
                    """
                    INSERT INTO roles (code, name)
                    VALUES (:code, :name)
                    """
                ),
                {
                    "code": role_id,
                    "name": role_name,
                },
            )

        _replace_role_menus_internal(db, role_id, menu_ids, role_source=role_source)
        write_audit_log(
            db,
            action="role.create",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"role_id={role_id}",
                f"role_code={role_id}",
                f"role_name={role_name}",
                f"menu_ids={summarize_values(menu_ids)}" if menu_ids else None,
            ),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    _fire_and_forget(
        publish_topic(
            "admin.roles",
            name="roles.changed",
            payload={"action": "created", "role_id": role_id, "role_code": role_id},
            requires_refetch=["/api/v1/admin/roles"],
            dedupe_key=f"roles:created:{role_id}",
        )
    )
    return get_role_by_id(db, role_id)


def update_role(db: Session, role_id: str, payload: RoleUpdateRequest, *, actor_user_id: str | None) -> RolePublic | None:
    role_id = role_id.strip()
    if not role_id:
        return None
    current_role = get_role_by_id(db, role_id)
    if not current_role:
        return None
    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"
    resolved_role_id = role_id
    resolved_role_code = role_id
    if role_source == "legacy":
        role_exists = db.scalar(text("SELECT id FROM user_role WHERE id = :id"), {"id": role_id})
        if not role_exists:
            return None
    else:
        role_row = db.execute(
            text(
                """
                SELECT id::text AS id, code
                FROM roles
                WHERE id::text = :id OR code = :id
                LIMIT 1
                """
            ),
            {"id": role_id},
        ).mappings().first()
        if not role_row:
            return None
        resolved_role_id = str(role_row["id"])
        resolved_role_code = str(role_row.get("code") or resolved_role_id).strip() or resolved_role_id

    impacted_user_ids = _get_role_user_ids(db, resolved_role_id)
    changed_fields: list[str] = []
    menus_changed = False
    try:
        if payload.name is not None:
            role_name = payload.name.strip()
            if not role_name:
                db.rollback()
                return None
            if role_name != current_role.name:
                changed_fields.append("name")
            if role_source == "legacy":
                db.execute(
                    text("UPDATE user_role SET name = :name, descr = :descr, update_date = :update_date WHERE id = :id"),
                    {
                        "id": resolved_role_id,
                        "name": role_name,
                        "descr": role_name,
                        "update_date": datetime.now(),
                    },
                )
            else:
                db.execute(
                    text("UPDATE roles SET name = :name WHERE id::text = :id"),
                    {
                        "id": resolved_role_id,
                        "name": role_name,
                    },
                )

        if payload.menu_ids is not None:
            menu_ids = sorted(set(menu_id.strip() for menu_id in payload.menu_ids if menu_id.strip()))
            if not _menu_ids_exist(db, menu_ids, role_source=role_source):
                db.rollback()
                return None
            if menu_ids != sorted(current_role.menu_ids):
                changed_fields.append("menu_ids")
            _replace_role_menus_internal(db, resolved_role_id, menu_ids, role_source=role_source)
            menus_changed = True

        if changed_fields:
            write_audit_log(
                db,
                action="role.update",
                actor_user_id=actor_user_id,
                detail=compose_audit_detail(
                    f"role_id={resolved_role_id}",
                    f"role_code={resolved_role_code}",
                    f"role_name={payload.name.strip() if payload.name is not None else current_role.name}",
                    describe_changed_fields(changed_fields),
                    (
                        f"menu_ids={summarize_values(sorted(set(menu_id.strip() for menu_id in payload.menu_ids if menu_id.strip())))}"
                        if payload.menu_ids is not None and "menu_ids" in changed_fields
                        else None
                    ),
                ),
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    if menus_changed:
        queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.roles",
            name="roles.changed",
            payload={"action": "updated", "role_id": resolved_role_id, "role_code": resolved_role_code},
            requires_refetch=["/api/v1/admin/roles"],
            dedupe_key=f"roles:updated:{resolved_role_id}",
        )
    )
    if menus_changed:
        _fire_and_forget(
            publish_topic(
                "admin.menus",
                name="menus.changed",
                payload={"action": "role_menus_updated", "role_id": resolved_role_id, "role_code": resolved_role_code},
                requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
                dedupe_key=f"menus:role_updated:{resolved_role_id}",
            )
        )
    return get_role_by_id(db, resolved_role_id)


def delete_role(db: Session, role_id: str, *, actor_user_id: str | None) -> bool:
    role_id = role_id.strip()
    if not role_id:
        return False
    current_role = get_role_by_id(db, role_id)
    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"
    resolved_role_id = role_id
    resolved_role_code = role_id
    if role_source == "legacy":
        if role_id in PROTECTED_ROLE_IDS:
            return False
        exists = db.scalar(text("SELECT id FROM user_role WHERE id = :id"), {"id": role_id})
        if not exists:
            return False
    else:
        role_row = db.execute(
            text(
                """
                SELECT id::text AS id, code
                FROM roles
                WHERE id::text = :id OR code = :id
                LIMIT 1
                """
            ),
            {"id": role_id},
        ).mappings().first()
        if not role_row:
            return False
        resolved_role_id = str(role_row["id"])
        resolved_role_code = str(role_row.get("code") or resolved_role_id).strip() or resolved_role_id
        if resolved_role_code in PROTECTED_ROLE_IDS:
            return False

    impacted_user_ids = _get_role_user_ids(db, resolved_role_id)
    has_user_role_relation = _legacy_user_role_relation_exists(db)
    try:
        write_audit_log(
            db,
            action="role.delete",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"role_id={resolved_role_id}",
                f"role_code={resolved_role_code}",
                f"role_name={current_role.name}" if current_role else None,
            ),
        )
        if role_source == "legacy":
            db.execute(text("DELETE FROM role_menu_rela WHERE role_id = :role_id"), {"role_id": resolved_role_id})
            if has_user_role_relation:
                db.execute(text("DELETE FROM user_role_rela WHERE role_id = :role_id"), {"role_id": resolved_role_id})
            db.execute(text("DELETE FROM user_role WHERE id = :id"), {"id": resolved_role_id})
        else:
            db.execute(text("DELETE FROM role_menus WHERE role_id::text = :role_id"), {"role_id": resolved_role_id})
            db.execute(text("DELETE FROM role_permissions WHERE role_id::text = :role_id"), {"role_id": resolved_role_id})
            db.execute(text("DELETE FROM user_roles WHERE role_id::text = :role_id"), {"role_id": resolved_role_id})
            db.execute(text("DELETE FROM roles WHERE id::text = :id"), {"id": resolved_role_id})
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return False

    queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.roles",
            name="roles.changed",
            payload={"action": "deleted", "role_id": resolved_role_id, "role_code": resolved_role_code},
            requires_refetch=["/api/v1/admin/roles"],
            dedupe_key=f"roles:deleted:{resolved_role_id}",
        )
    )
    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "role_deleted", "role_id": resolved_role_id, "role_code": resolved_role_code},
            requires_refetch=["/api/v1/admin/me/menus"],
            dedupe_key=f"menus:role_deleted:{resolved_role_id}",
        )
    )
    return True


def list_permissions(_: Session) -> list[dict[str, str | int]]:
    codes = sorted(set(DEFAULT_ADMIN_PERMISSION_CODES))
    return [{"id": idx + 1, "code": code, "name": code} for idx, code in enumerate(codes)]


def list_menus(db: Session, keyword: str | None = None, status: str | None = None) -> MenuListResponse:
    rows = _load_menus_rows(db, keyword=keyword, status=status)
    items = [serialize_menu_row(row) for row in rows]
    return MenuListResponse(items=items, total=len(items))


def list_roles_with_menus(
    db: Session,
    keyword: str | None = None,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> RolesWithMenusResponse:
    """Get roles and menus in a single request to reduce network calls."""
    roles_response = list_roles(db, keyword=keyword, limit=limit, offset=offset)
    menus_response = list_menus(db)
    return RolesWithMenusResponse(
        roles=roles_response.items,
        roles_total=roles_response.total,
        menus=menus_response.items,
        menus_total=menus_response.total,
    )


def get_menu_by_id(db: Session, menu_id: str) -> MenuPublic | None:
    normalized_menu_id = menu_id.strip()
    if not normalized_menu_id:
        return None
    row = db.execute(
        text(
            """
            SELECT id::text AS menu_id, code AS menu_name, name AS menu_label, type AS menu_type,
                   parent_id, path AS url, icon AS menu_icon, sort_order AS seq, status AS state,
                   permission_code AS menu_descr
            FROM menus
            WHERE id::text = :menu_id OR code = :menu_id
            """
        ),
        {"menu_id": normalized_menu_id},
    ).mappings().first()
    if not row:
        return None
    if str(row.get("menu_name") or "").strip() in REMOVED_MENU_CODES:
        return None
    return serialize_menu_row(row)


def create_menu(db: Session, payload: MenuCreateRequest, *, actor_user_id: str | None) -> MenuPublic:
    menu_code = payload.code.strip()
    if not menu_code:
        raise EmptyMenuCodeError()
    if menu_code in REMOVED_MENU_CODES:
        raise RemovedMenuCodeError(menu_code)
    menu_name = payload.name.strip()
    if not menu_name:
        raise EmptyMenuNameError()
    exists = db.scalar(text("SELECT id FROM menus WHERE code = :menu_name"), {"menu_name": menu_code})
    if exists:
        raise DuplicateMenuCodeError(menu_code)

    parent_id = payload.parent_id.strip() if payload.parent_id else None
    if parent_id and parent_id == menu_code:
        raise SelfParentError()
    if parent_id and not db.scalar(text("SELECT id FROM menus WHERE id::text = :menu_id OR code = :menu_id"), {"menu_id": parent_id}):
        raise ParentNotFoundError(parent_id)

    menu_id = menu_code if len(menu_code) <= 32 else uuid4().hex
    try:
        result = db.execute(
            text(
                """
                INSERT INTO menus (
                    code, name, type, parent_id, path, icon, sort_order, status, permission_code,
                    visible, cacheable, component
                )
                VALUES (
                    :code, :name, :type, :parent_id, :path, :icon, :sort_order, :status, :permission_code,
                    :visible, :cacheable, :component
                )
                RETURNING id::text AS menu_id
                """
            ),
            {
                "code": menu_code,
                "name": menu_name,
                "type": payload.type,
                "parent_id": int(parent_id) if parent_id and parent_id.isdigit() else None,
                "path": payload.path,
                "icon": payload.icon,
                "sort_order": payload.sort_order,
                "status": payload.status,
                "permission_code": payload.permission_code or payload.component,
                "visible": payload.visible,
                "cacheable": payload.cacheable,
                "component": payload.component,
            },
        )
        row = result.mappings().first()
        menu_id = str(row["menu_id"]) if row else menu_code
        write_audit_log(
            db,
            action="menu.create",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"menu_id={menu_id}",
                f"menu_code={menu_code}",
                f"menu_name={menu_name}",
                f"path={_to_legacy_url(payload.path) or ''}",
                f"parent_id={parent_id}" if parent_id else None,
            ),
        )
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        # Re-raise with more context for database errors
        raise MenuValidationError(f"数据库错误：{str(e)}") from e

    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "created", "menu_id": menu_id, "menu_code": menu_code},
            requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
            dedupe_key=f"menus:created:{menu_id}",
        )
    )
    created_menu = get_menu_by_id(db, menu_id)
    if not created_menu:
        raise MenuValidationError(f"创建成功但无法获取菜单 {menu_id}")
    return created_menu


def update_menu(db: Session, menu_id: str, payload: MenuUpdateRequest, *, actor_user_id: str | None) -> MenuPublic | None:
    menu = get_menu_by_id(db, menu_id)
    if not menu:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    changed_fields: list[str] = []
    next_name = menu.name
    if "name" in update_data and update_data["name"] is not None:
        candidate_name = str(update_data["name"]).strip()
        if not candidate_name:
            return None
        next_name = candidate_name
        if candidate_name != menu.name:
            changed_fields.append("name")
    next_parent_id = menu.parent_id
    if "parent_id" in update_data:
        parent_id = update_data["parent_id"]
        if parent_id:
            normalized_parent = parent_id.strip()
            if normalized_parent == menu.id:
                return None
            parent_exists = db.scalar(text("SELECT id FROM menus WHERE id::text = :menu_id OR code = :menu_id"), {"menu_id": normalized_parent})
            if not parent_exists:
                return None
            next_parent_id = normalized_parent
        else:
            next_parent_id = None
        if next_parent_id != menu.parent_id:
            changed_fields.append("parent_id")

    if "path" in update_data and update_data["path"] != menu.path:
        changed_fields.append("path")
    if "icon" in update_data and update_data["icon"] != menu.icon:
        changed_fields.append("icon")
    if "type" in update_data and update_data["type"] != menu.type:
        changed_fields.append("type")
    if "sort_order" in update_data and update_data["sort_order"] != menu.sort_order:
        changed_fields.append("sort_order")
    if "status" in update_data and update_data["status"] != menu.status:
        changed_fields.append("status")
    if "permission_code" in update_data and update_data["permission_code"] != menu.permission_code:
        changed_fields.append("permission_code")
    if "component" in update_data and update_data["component"] != menu.component:
        changed_fields.append("component")

    impacted_user_ids = _get_users_with_menu_access(db, menu.id)
    try:
        db.execute(
            text(
                """
                UPDATE menus
                SET
                    name = :name,
                    path = :path,
                    icon = :icon,
                    parent_id = :parent_id,
                    type = :type,
                    sort_order = :sort_order,
                    status = :status,
                    permission_code = :permission_code
                WHERE id::text = :menu_id OR code = :menu_id
                """
            ),
            {
                "menu_id": menu.id,
                "name": next_name,
                "path": update_data.get("path", menu.path),
                "icon": update_data.get("icon", menu.icon),
                "parent_id": int(next_parent_id) if next_parent_id and str(next_parent_id).isdigit() else None,
                "type": update_data.get("type", menu.type),
                "sort_order": int(update_data.get("sort_order", menu.sort_order)),
                "status": update_data.get("status", menu.status),
                "permission_code": update_data.get("permission_code", menu.permission_code) or update_data.get("component"),
            },
        )
        if changed_fields:
            next_status = str(update_data.get("status", menu.status))
            next_path = update_data.get("path", menu.path)
            write_audit_log(
                db,
                action="menu.update",
                actor_user_id=actor_user_id,
                detail=compose_audit_detail(
                    f"menu_id={menu.id}",
                    f"menu_code={menu.code}",
                    f"menu_name={next_name}",
                    describe_changed_fields(changed_fields),
                    f"path={next_path}" if next_path else None,
                    (
                        f"status_transition={menu.status}->{next_status}"
                        if "status" in changed_fields
                        else None
                    ),
                ),
            )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "updated", "menu_id": menu.id, "menu_code": menu.code},
            requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
            dedupe_key=f"menus:updated:{menu.id}",
        )
    )
    return get_menu_by_id(db, menu.id)


def delete_menu(db: Session, menu_id: str, *, actor_user_id: str | None) -> bool:
    normalized_menu_id = menu_id.strip()
    if not normalized_menu_id:
        return False

    menu_source = "legacy" if _legacy_menu_table_exists(db) else "modern"

    if menu_source == "legacy":
        menu = get_menu_by_id(db, normalized_menu_id)
        if not menu:
            return False
        if menu.code in PROTECTED_MENU_CODES:
            return False

        child_exists = db.scalar(text("SELECT id FROM menus WHERE parent_id::text = :parent_id LIMIT 1"), {"parent_id": menu.id})
        if child_exists:
            return False

        impacted_user_ids = _get_users_with_menu_access(db, menu.id, role_source=menu_source)
        try:
            write_audit_log(
                db,
                action="menu.delete",
                actor_user_id=actor_user_id,
                detail=compose_audit_detail(
                    f"menu_id={menu.id}",
                    f"menu_code={menu.code}",
                    f"menu_name={menu.name}",
                    f"path={menu.path}" if menu.path else None,
                ),
            )
            db.execute(text("DELETE FROM role_menu_rela WHERE menu_id = :menu_id"), {"menu_id": menu.id})
            db.execute(text("DELETE FROM menus WHERE id::text = :menu_id OR code = :menu_id"), {"menu_id": menu.id})
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            return False

        deleted_menu_id = menu.id
        deleted_menu_code = menu.code
    else:
        menu_row = db.execute(
            text(
                """
                SELECT id::text AS menu_id, code AS menu_code
                FROM menus
                WHERE id::text = :menu_id OR code = :menu_id
                LIMIT 1
                """
            ),
            {"menu_id": normalized_menu_id},
        ).mappings().first()
        if not menu_row:
            return False

        resolved_menu_id = str(menu_row["menu_id"])
        resolved_menu_code = str(menu_row.get("menu_code") or "").strip()
        if not resolved_menu_code or resolved_menu_code in PROTECTED_MENU_CODES:
            return False

        child_exists = db.scalar(text("SELECT id::text FROM menus WHERE parent_id::text = :parent_id LIMIT 1"), {"parent_id": resolved_menu_id})
        if child_exists:
            return False

        impacted_user_ids = _get_users_with_menu_access(db, resolved_menu_id, role_source=menu_source)
        try:
            write_audit_log(
                db,
                action="menu.delete",
                actor_user_id=actor_user_id,
                detail=compose_audit_detail(
                    f"menu_id={resolved_menu_id}",
                    f"menu_code={resolved_menu_code}",
                ),
            )
            db.execute(text("DELETE FROM role_menus WHERE menu_id::text = :menu_id"), {"menu_id": resolved_menu_id})
            db.execute(text("DELETE FROM menus WHERE id::text = :menu_id"), {"menu_id": resolved_menu_id})
            db.commit()
        except SQLAlchemyError:
            db.rollback()
            return False

        deleted_menu_id = resolved_menu_id
        deleted_menu_code = resolved_menu_code

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


def list_role_menu_ids(db: Session, role_id: str) -> list[str] | None:
    role_source = "legacy" if _legacy_role_table_exists(db) else "modern"
    resolved_role_id = role_id
    if role_source == "legacy":
        role_exists = db.scalar(text("SELECT id FROM user_role WHERE id = :id"), {"id": role_id})
        if not role_exists:
            return None
    else:
        role_row = db.execute(
            text(
                """
                SELECT id::text AS id
                FROM roles
                WHERE id::text = :id OR code = :id
                LIMIT 1
                """
            ),
            {"id": role_id},
        ).mappings().first()
        if not role_row:
            return None
        resolved_role_id = str(role_row["id"])
    rows = db.execute(
        text(
            "SELECT menu_id FROM role_menu_rela WHERE role_id = :role_id ORDER BY menu_id ASC"
            if role_source == "legacy"
            else "SELECT menu_id::text AS menu_id FROM role_menus WHERE role_id::text = :role_id ORDER BY menu_id ASC"
        ),
        {"role_id": resolved_role_id},
    ).all()
    menu_ids = [str(row[0]) for row in rows]
    menu_rows = _load_menus_map(db, menu_ids, role_source=role_source)
    return [menu_id for menu_id in menu_ids if menu_id in menu_rows]


def replace_role_menus(db: Session, role_id: str, menu_ids: list[str], *, actor_user_id: str | None) -> RolePublic | None:
    role_exists = db.scalar(text("SELECT id FROM user_role WHERE id = :id"), {"id": role_id})
    if not role_exists:
        return None
    current_role = get_role_by_id(db, role_id)
    normalized_menu_ids = sorted(set(menu_id.strip() for menu_id in menu_ids if menu_id.strip()))
    if not _menu_ids_exist(db, normalized_menu_ids):
        return None

    impacted_user_ids = _get_role_user_ids(db, role_id)
    try:
        _replace_role_menus_internal(db, role_id, normalized_menu_ids)
        write_audit_log(
            db,
            action="role.menus.replace",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"role_id={role_id}",
                f"role_code={current_role.code}" if current_role else f"role_code={role_id}",
                f"role_name={current_role.name}" if current_role else None,
                f"menu_ids={summarize_values(normalized_menu_ids)}",
            ),
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        return None

    queue_users_auth_refresh(db, impacted_user_ids)
    _fire_and_forget(
        publish_topic(
            "admin.roles",
            name="roles.changed",
            payload={"action": "menus_replaced", "role_id": role_id, "role_code": role_id},
            requires_refetch=["/api/v1/admin/roles"],
            dedupe_key=f"roles:menus_replaced:{role_id}",
        )
    )
    _fire_and_forget(
        publish_topic(
            "admin.menus",
            name="menus.changed",
            payload={"action": "role_menus_replaced", "role_id": role_id, "role_code": role_id},
            requires_refetch=["/api/v1/admin/menus", "/api/v1/admin/me/menus"],
            dedupe_key=f"menus:role_menus_replaced:{role_id}",
        )
    )
    return get_role_by_id(db, role_id)


def serialize_menu_row(row: dict[str, object]) -> MenuPublic:
    menu_code = str(row.get("menu_name") or row.get("menu_id") or "")
    return MenuPublic(
        id=str(row["menu_id"]),
        code=menu_code,
        name=str(row.get("menu_label") or menu_code),
        path=_to_api_path(row.get("url")),
        icon=(row.get("menu_icon") or None),
        parent_id=(str(row["parent_id"]) if row.get("parent_id") else None),
        type=_to_api_menu_type(row.get("menu_type")),
        sort_order=int(row.get("seq") or 0),
        status=_to_api_state(row.get("state")),
        visible=_to_api_state(row.get("state")) == "enabled",
        cacheable=False,
        component=None,
        permission_code=_primary_permission(menu_code, row.get("menu_type")),
    )


def _load_role_menu_ids_map(db: Session, role_ids: list[str], *, role_source: str = "legacy") -> dict[str, list[str]]:
    mapping = {role_id: [] for role_id in role_ids}
    if not role_ids:
        return mapping
    if role_source == "legacy":
        stmt = text(
            """
            SELECT role_id, menu_id
            FROM role_menu_rela
            WHERE role_id IN :role_ids
            ORDER BY menu_id ASC
            """
        )
    else:
        stmt = text(
            """
            SELECT role_id::text AS role_id, menu_id::text AS menu_id
            FROM role_menus
            WHERE role_id::text IN :role_ids
            ORDER BY menu_id ASC
            """
        )
    rows = db.execute(
        stmt.bindparams(bindparam("role_ids", expanding=True)),
        {"role_ids": role_ids},
    ).mappings().all()
    for row in rows:
        mapping.setdefault(str(row["role_id"]), []).append(str(row["menu_id"]))
    return mapping


def _load_menus_map(db: Session, menu_ids: list[str], *, role_source: str = "legacy") -> dict[str, dict[str, object]]:
    if not menu_ids:
        return {}
    if role_source == "legacy":
        stmt = text(
            """
            SELECT id::text AS menu_id, code AS menu_name, type AS menu_type, status AS state
            FROM menus
            WHERE id::text IN :menu_ids OR code IN :menu_ids
            """
        )
    else:
        stmt = text(
            """
            SELECT id::text AS menu_id, code AS menu_name, type AS menu_type, status AS state
            FROM menus
            WHERE id::text IN :menu_ids
            """
        )
    rows = db.execute(
        stmt.bindparams(bindparam("menu_ids", expanding=True)),
        {"menu_ids": menu_ids},
    ).mappings().all()
    return {
        str(row["menu_id"]): dict(row)
        for row in rows
        if str(row.get("menu_name") or "").strip() not in REMOVED_MENU_CODES
    }


def _load_role_page(
    db: Session,
    *,
    role_source: str,
    keyword: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[dict[str, object]], int]:
    normalized_offset = max(offset, 0)
    normalized_limit = max(limit, 0) if limit is not None else None
    params: dict[str, object] = {"offset": normalized_offset}
    limit_clause = ""
    if normalized_limit is not None:
        limit_clause = "LIMIT :limit"
        params["limit"] = normalized_limit

    trimmed_keyword = keyword.strip() if keyword else ""
    keyword_clause = ""
    if trimmed_keyword:
        keyword_clause = """
            AND (
                {role_keyword_predicates}
                OR EXISTS (
                    {menu_exists_query}
                )
            )
        """
        params["keyword"] = f"%{trimmed_keyword.lower()}%"

    if role_source == "legacy":
        role_keyword_predicates = """
                LOWER(r.id) LIKE :keyword
                OR LOWER(r.name) LIKE :keyword
        """
        menu_exists_query = """
                    SELECT 1
                    FROM role_menu_rela rmr
                    JOIN menus m ON m.id::text = rmr.menu_id OR m.code = rmr.menu_id
                    WHERE rmr.role_id = r.id
                      AND m.code NOT IN :removed_menu_codes
                      AND (
                          LOWER(m.code) LIKE :keyword
                          OR LOWER(m.name) LIKE :keyword
                      )
        """
        from_clause = """
            FROM user_role r
            WHERE 1 = 1
            {keyword_clause}
        """
        select_clause = "SELECT r.id, r.name"
        order_clause = "ORDER BY r.create_date DESC NULLS LAST, r.id ASC"
    else:
        role_keyword_predicates = """
                LOWER(r.code) LIKE :keyword
                OR LOWER(r.name) LIKE :keyword
        """
        menu_exists_query = """
                    SELECT 1
                    FROM role_menus rm
                    JOIN menus m ON m.id = rm.menu_id
                    WHERE rm.role_id = r.id
                      AND m.code NOT IN :removed_menu_codes
                      AND (
                          LOWER(m.code) LIKE :keyword
                          OR LOWER(m.name) LIKE :keyword
                      )
        """
        from_clause = """
            FROM roles r
            WHERE 1 = 1
            {keyword_clause}
        """
        select_clause = "SELECT r.id::text AS id, r.code, r.name"
        order_clause = "ORDER BY r.id ASC"

    if keyword_clause:
        keyword_clause = keyword_clause.format(
            role_keyword_predicates=role_keyword_predicates,
            menu_exists_query=menu_exists_query,
        )
    from_clause = from_clause.format(keyword_clause=keyword_clause)
    query_params = {**params, "removed_menu_codes": tuple(REMOVED_MENU_CODES)} if trimmed_keyword else params

    def role_page_stmt(sql: str):
        stmt = text(sql)
        if trimmed_keyword:
            return stmt.bindparams(bindparam("removed_menu_codes", expanding=True))
        return stmt

    total = db.scalar(
        role_page_stmt(f"SELECT COUNT(*) {from_clause}"),
        query_params,
    ) or 0
    rows = db.execute(
        role_page_stmt(
            f"""
            {select_clause}
            {from_clause}
            {order_clause}
            {limit_clause}
            OFFSET :offset
            """
        ),
        query_params,
    ).mappings().all()
    return [dict(row) for row in rows], int(total)


def _load_role_permission_codes_map(
    db: Session,
    role_ids: list[str],
    *,
    role_source: str,
) -> dict[str, list[str]]:
    mapping = {role_id: [] for role_id in role_ids}
    if not role_ids or role_source == "legacy":
        return mapping
    rows = db.execute(
        text(
            """
            SELECT rp.role_id::text AS role_id, p.code AS permission_code
            FROM role_permissions rp
            JOIN permissions p ON p.id = rp.permission_id
            WHERE rp.role_id::text IN :role_ids
            ORDER BY p.code ASC
            """
        ).bindparams(bindparam("role_ids", expanding=True)),
        {"role_ids": role_ids},
    ).mappings().all()
    for row in rows:
        role_key = str(row["role_id"])
        code = str(row.get("permission_code") or "").strip()
        if not code:
            continue
        mapping.setdefault(role_key, []).append(code)
    return mapping


def _legacy_role_table_exists(db: Session) -> bool:
    try:
        return bool(db.scalar(text("SELECT to_regclass('public.user_role')")))
    except SQLAlchemyError:
        db.rollback()
        return False


def _legacy_menu_table_exists(db: Session) -> bool:
    try:
        return bool(db.scalar(text("SELECT to_regclass('public.menu')")))
    except SQLAlchemyError:
        db.rollback()
        return False


def _permission_codes_from_menu_rows(
    menu_rows: dict[str, dict[str, object]],
    menu_ids: list[str],
) -> set[str]:
    codes: set[str] = set()
    for menu_id in menu_ids:
        row = menu_rows.get(menu_id)
        if not row:
            continue
        if _to_api_state(row.get("state")) != "enabled":
            continue
        menu_name = str(row.get("menu_name") or "")
        if menu_name in REMOVED_MENU_CODES:
            continue
        menu_type = row.get("menu_type")
        mapped = MENU_CODE_PERMISSION_MAP.get(menu_name, set())
        codes.update(mapped)
        if not mapped and str(menu_type or "").upper() == "BUTTON" and "." in menu_name:
            codes.add(menu_name)
    return codes


def _menu_ids_exist(db: Session, menu_ids: list[str], *, role_source: str = "legacy") -> bool:
    if not menu_ids:
        return True
    if role_source == "legacy":
        rows = db.execute(
            text("SELECT id::text AS menu_id, code AS menu_name FROM menus WHERE id::text IN :menu_ids OR code IN :menu_ids").bindparams(bindparam("menu_ids", expanding=True)),
            {"menu_ids": menu_ids},
        ).mappings().all()
    else:
        rows = db.execute(
            text(
                """
                SELECT id::text AS menu_id, code AS menu_name
                FROM menus
                WHERE id::text IN :menu_ids
                """
            ).bindparams(bindparam("menu_ids", expanding=True)),
            {"menu_ids": menu_ids},
        ).mappings().all()
    existing = {
        str(row["menu_id"])
        for row in rows
        if str(row.get("menu_name") or "").strip() not in REMOVED_MENU_CODES
    }
    return set(menu_ids).issubset(existing)


def _replace_role_menus_internal(db: Session, role_id: str, menu_ids: list[str], *, role_source: str = "legacy") -> None:
    if role_source == "legacy":
        db.execute(text("DELETE FROM role_menu_rela WHERE role_id = :role_id"), {"role_id": role_id})
    else:
        db.execute(text("DELETE FROM role_menus WHERE role_id::text = :role_id"), {"role_id": role_id})
    if not menu_ids:
        return
    if role_source == "legacy":
        stmt = text(
            """
            INSERT INTO role_menu_rela (rela_id, role_id, menu_id)
            VALUES (:rela_id, :role_id, :menu_id)
            """
        )
        for menu_id in menu_ids:
            db.execute(
                stmt,
                {
                    "rela_id": uuid4().hex,
                    "role_id": role_id,
                    "menu_id": menu_id,
                },
            )
    else:
        stmt = text(
            """
            INSERT INTO role_menus (role_id, menu_id)
            VALUES (CAST(:role_id AS INTEGER), CAST(:menu_id AS INTEGER))
            """
        )
        for menu_id in menu_ids:
            db.execute(
                stmt,
                {
                    "role_id": role_id,
                    "menu_id": menu_id,
                },
            )


def _legacy_user_role_relation_exists(db: Session) -> bool:
    try:
        return bool(db.scalar(text("SELECT to_regclass('public.user_role_rela')")))
    except SQLAlchemyError:
        db.rollback()
        return False


def _get_role_user_ids(db: Session, role_id: str) -> list[str]:
    try:
        if _legacy_user_role_relation_exists(db):
            rows = db.execute(
                text("SELECT user_id FROM user_role_rela WHERE role_id = :role_id"),
                {"role_id": role_id},
            ).all()
        else:
            rows = db.execute(
                text("SELECT user_id FROM user_roles WHERE role_id::text = :role_id"),
                {"role_id": role_id},
            ).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    return sorted({str(row[0]) for row in rows})


def _get_users_with_menu_access(db: Session, menu_id: str, *, role_source: str = "legacy") -> list[str]:
    try:
        if role_source == "legacy":
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT urr.user_id
                    FROM role_menu_rela rmr
                    JOIN user_role_rela urr ON urr.role_id = rmr.role_id
                    WHERE rmr.menu_id = :menu_id
                    """
                ),
                {"menu_id": menu_id},
            ).all()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT ur.user_id
                    FROM role_menus rm
                    JOIN user_roles ur ON ur.role_id = rm.role_id
                    WHERE rm.menu_id::text = :menu_id
                    """
                ),
                {"menu_id": menu_id},
            ).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    return sorted({str(row[0]) for row in rows})


def _load_menus_rows(db: Session, keyword: str | None = None, status: str | None = None) -> list[dict[str, object]]:
    # Build WHERE conditions
    where_clauses = []
    params = {}

    if keyword:
        normalized_keyword = f"%{keyword.strip().lower()}%"
        where_clauses.append("(LOWER(code) LIKE :keyword OR LOWER(name) LIKE :keyword OR LOWER(COALESCE(path, '')) LIKE :keyword)")
        params["keyword"] = normalized_keyword

    if status and status in ("enabled", "disabled"):
        where_clauses.append("status = :status")
        params["status"] = status

    where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    try:
        rows = db.execute(
            text(
                f"""
                SELECT id::text AS menu_id, code AS menu_name, name AS menu_label, type AS menu_type,
                       parent_id, path AS url, icon AS menu_icon, sort_order AS seq, status AS state,
                       permission_code AS menu_descr
                FROM menus
                {where_clause}
                ORDER BY sort_order ASC NULLS LAST, id ASC
                """
            ),
            params
        ).mappings().all()
    except SQLAlchemyError:
        db.rollback()
        query = db.query(Menu)

        if keyword:
            normalized_keyword = f"%{keyword.strip().lower()}%"
            from sqlalchemy import func, or_
            query = query.filter(
                or_(
                    func.lower(Menu.code).like(normalized_keyword),
                    func.lower(Menu.name).like(normalized_keyword),
                    func.lower(func.coalesce(Menu.path, '')).like(normalized_keyword)
                )
            )

        if status and status in ("enabled", "disabled"):
            query = query.filter(Menu.status == status)

        menus = query.order_by(Menu.sort_order.asc(), Menu.id.asc()).all()
        rows = [
            {
                "menu_id": str(menu.id),
                "menu_name": menu.code,
                "menu_label": menu.name,
                "menu_type": _to_legacy_menu_type(menu.type),
                "parent_id": (str(menu.parent_id) if menu.parent_id is not None else None),
                "url": _to_legacy_url(menu.path),
                "menu_icon": menu.icon,
                "seq": menu.sort_order,
                "state": _to_legacy_state(menu.status),
                "menu_descr": menu.permission_code or menu.component,
            }
            for menu in menus
        ]
    return [
        dict(row)
        for row in rows
        if str(row.get("menu_name") or "").strip() not in REMOVED_MENU_CODES
    ]


def _primary_permission(menu_name: str, menu_type: object) -> str | None:
    mapped = MENU_CODE_PERMISSION_MAP.get(menu_name)
    if mapped:
        return sorted(mapped)[0]
    if str(menu_type or "").upper() == "BUTTON" and "." in menu_name:
        return menu_name
    return None


def _to_api_state(raw_state: object) -> str:
    return "enabled" if str(raw_state or "").upper() in {"ENABLED", "ACTIVE", "1", "TRUE", ""} else "disabled"


def _to_legacy_state(status: str | None) -> str:
    return "DISABLED" if (status or "").strip().lower() == "disabled" else "ENABLED"


def _to_api_menu_type(raw_type: object) -> str:
    value = str(raw_type or "").strip().upper()
    if value == "DIRECTORY":
        return "directory"
    if value == "BUTTON":
        return "button"
    return "menu"


def _to_legacy_menu_type(raw_type: str | None) -> str:
    value = (raw_type or "").strip().lower()
    if value == "directory":
        return "DIRECTORY"
    if value == "button":
        return "BUTTON"
    return "MENU"


def _to_api_path(raw_url: object) -> str | None:
    url = str(raw_url or "").strip()
    if not url:
        return None
    if url in LEGACY_URL_PATH_MAP:
        return LEGACY_URL_PATH_MAP[url]
    if url.startswith(("http://", "https://", "/")):
        return url
    return f"/admin/{url}"


def _to_legacy_url(path: str | None) -> str:
    normalized = (path or "").strip()
    if not normalized:
        return ""
    reverse = {value: key for key, value in LEGACY_URL_PATH_MAP.items()}
    if normalized in reverse:
        return reverse[normalized]
    if normalized.startswith("/admin/"):
        tail = normalized.removeprefix("/admin/")
        if tail:
            return tail
    return normalized


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)
