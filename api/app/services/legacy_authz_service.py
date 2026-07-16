from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

# Keep this list aligned with runtime permission checks used by API endpoints.
DEFAULT_ADMIN_PERMISSION_CODES: set[str] = {
    "user.read",
    "user.write",
    "user.manage",
    "role.read",
    "role.manage",
    "menu.read",
    "menu.manage",
    "system_param.read",
    "system_param.manage",
    "admin.system_message",
    "file.read",
    "file.manage",
    "line.read",
    "line.manage",
    "tower.read",
    "tower.manage",
    "tower_model.read",
    "tower_model.manage",
    "lightning.read",
    "lightning.manage",
    "elevation.read",
    "elevation.manage",
    "atp.read",
    "atp.manage",
    "atp.run",
    "celery.read",
    "celery.manage",
    "wine.read",
    "wine.manage",
}

ADMIN_ROLE_IDS = {
    "admin",
    "sys_mgr",
    "sysadmin",
    "administrator",
}

DISABLED_MENU_CODES: set[str] = {
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

MENU_CODE_PERMISSION_MAP: dict[str, set[str]] = {
    # quiz legacy menu codes
    "user_mgr": {"user.read", "user.manage"},
    "role_mgr": {"role.read", "role.manage"},
    "menu_mgr": {"menu.read", "menu.manage"},
    "sys_mgr": {"menu.read", "menu.manage"},
    # fquiz menu codes
    "admin.users": {"user.read", "user.manage"},
    "admin.roles": {"role.read", "role.manage"},
    "admin.menus": {"menu.read", "menu.manage"},
    "admin.system_params": {"system_param.read", "system_param.manage"},
    "admin.system_message": {"admin.system_message"},
    "admin.fl_analysis": {"line.read", "line.manage"},
    "admin.files": {"file.read", "file.manage"},
    "admin.elevation": {"elevation.read", "elevation.manage"},
    "admin.tower_models": {"tower_model.read", "tower_model.manage"},
    "admin.workers": {"celery.read", "celery.manage"},
    "admin.task_monitor": {"celery.read", "celery.manage"},
    "admin.scheduled_tasks": {"celery.read", "celery.manage"},
    "admin.atp_models": {"atp.read", "atp.manage", "atp.run"},
    "admin.fault_recurrence": {"line.read", "line.manage", "tower.read", "tower.manage"},
    "admin.lightning_currents": {"lightning.read", "lightning.manage"},
    "admin.lightning_distribution": {"lightning.read", "lightning.manage"},
    "admin.wine_runner": {"wine.read", "wine.manage"},
}

SYNTHETIC_LEGACY_MENU_ROWS: list[dict[str, Any]] = [
    {
        "menu_id": "admin.workers",
        "menu_name": "admin.workers",
        "menu_label": "Worker监控",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/workers",
        "menu_icon": "DeploymentUnitOutlined",
        "seq": 53,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.tower_models",
        "menu_name": "admin.tower_models",
        "menu_label": "杆塔模型管理",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/tower-models",
        "menu_icon": "Apartment",
        "seq": 56,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.files",
        "menu_name": "admin.files",
        "menu_label": "文件管理",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/files",
        "menu_icon": "FolderTree",
        "seq": 57,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.elevation",
        "menu_name": "admin.elevation",
        "menu_label": "高程数据管理",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/elevation",
        "menu_icon": "Database",
        "seq": 58,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.task_monitor",
        "menu_name": "admin.task_monitor",
        "menu_label": "任务监控",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/task-monitor",
        "menu_icon": "RadarChart",
        "seq": 54,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.scheduled_tasks",
        "menu_name": "admin.scheduled_tasks",
        "menu_label": "定时任务管理",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/scheduled-tasks",
        "menu_icon": "CalendarClock",
        "seq": 55,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.atp_models",
        "menu_name": "admin.atp_models",
        "menu_label": "ATP模型管理",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/atp-models",
        "menu_icon": "Experiment",
        "seq": 56,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.fault_recurrence",
        "menu_name": "admin.fault_recurrence",
        "menu_label": "故障复现",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/fault-recurrence",
        "menu_icon": "Experiment",
        "seq": 50,
        "state": "ENABLED",
    },
    {
        "menu_id": "admin.wine_runner",
        "menu_name": "admin.wine_runner",
        "menu_label": "Wine执行器",
        "menu_type": "MENU",
        "parent_id": None,
        "url": "/admin/wine-runner",
        "menu_icon": "Terminal",
        "seq": 65,
        "state": "ENABLED",
    },
]

LEGACY_URL_PATH_MAP = {
    "user": "/admin/users",
    "role": "/admin/roles",
    "menu": "/admin/menus",
}


@dataclass(frozen=True)
class UserAuthorization:
    role_codes: set[str]
    permission_codes: set[str]


def normalize_user_status(raw_status: str | None) -> str:
    state = (raw_status or "").strip().upper()
    if state in {"ENABLED", "ACTIVE", "1", "TRUE"}:
        return "active"
    if state in {"DISABLED", "INACTIVE", "0", "FALSE"}:
        return "disabled"
    return "disabled" if not state else raw_status.strip().lower()


def is_user_enabled(raw_status: str | None) -> bool:
    return normalize_user_status(raw_status) == "active"


def get_user_authorization(db: Session, user_id: str) -> UserAuthorization:
    role_rows = _load_legacy_roles(db, user_id)
    if not role_rows:
        # Fallback for non-legacy tables.
        role_rows = _load_modern_roles(db, user_id)

    enabled_roles: list[tuple[str, str | None]] = []
    for role_id, role_name, role_state in role_rows:
        normalized_id = (role_id or "").strip()
        if not normalized_id:
            continue
        if role_state is not None and not _is_role_enabled(role_state):
            continue
        enabled_roles.append((normalized_id, role_name))

    role_codes = {role_id for role_id, _ in enabled_roles}
    is_admin = any(_is_admin_role(role_id, role_name) for role_id, role_name in enabled_roles)
    if not is_admin and not role_codes and _is_builtin_admin_user_id(user_id):
        is_admin = True
    if not is_admin and not role_codes and _should_apply_default_user_role_fallback(db):
        role_codes.add("user")
    if is_admin:
        role_codes.add("admin")

    permission_codes: set[str] = set()
    if is_admin:
        permission_codes.update(DEFAULT_ADMIN_PERMISSION_CODES)
    elif role_codes:
        permission_codes.update(_load_legacy_permissions(db, role_codes))
        if not permission_codes:
            permission_codes.update(_load_modern_permissions(db, role_codes))

    return UserAuthorization(role_codes=role_codes, permission_codes=permission_codes)


def _is_builtin_admin_user_id(user_id: str) -> bool:
    normalized = user_id.strip().lower()
    return normalized in {"admin", "administrator", "root", "sysadmin"}


def _should_apply_default_user_role_fallback(db: Session) -> bool:
    # Compatibility fallback: some legacy dumps contain user/role/menu tables
    # but miss the user_role_rela mapping table used by the old auth queries.
    if _legacy_user_role_relation_exists(db):
        return False
    if _legacy_user_role_exists(db):
        return True
    return _modern_user_role_exists(db)


def _legacy_user_role_relation_exists(db: Session) -> bool:
    try:
        result = db.scalar(text("SELECT to_regclass('public.user_role_rela')"))
    except SQLAlchemyError:
        _rollback_safely(db)
        return True
    return result is not None


def _legacy_user_role_exists(db: Session) -> bool:
    try:
        result = db.scalar(
            text(
                """
                SELECT id
                FROM user_role
                WHERE id = 'user' AND UPPER(COALESCE(state, 'ENABLED')) IN ('ENABLED', 'ACTIVE', '1', 'TRUE')
                LIMIT 1
                """
            )
        )
    except SQLAlchemyError:
        _rollback_safely(db)
        return False
    return result is not None


def _modern_user_role_exists(db: Session) -> bool:
    try:
        from sqlalchemy import select

        from ..models.rbac import Role

        role_id = db.scalar(select(Role.id).where(Role.code == "user").limit(1))
    except SQLAlchemyError:
        _rollback_safely(db)
        return False
    return role_id is not None


def build_legacy_menu_tree(
    db: Session,
    *,
    role_codes: set[str] | None,
) -> list[dict[str, Any]]:
    rows = _load_legacy_menus(db)
    if not rows:
        return []

    if role_codes is not None and "admin" not in role_codes:
        allowed_menu_ids = _load_legacy_allowed_menu_ids(db, role_codes)
        if not allowed_menu_ids:
            return []
        rows = [row for row in rows if row["menu_id"] in allowed_menu_ids]

    # Keep only enabled menus for menu tree response.
    rows = [row for row in rows if _is_menu_enabled(row.get("state"))]
    rows = [row for row in rows if str(row.get("menu_name") or "").strip() not in DISABLED_MENU_CODES]

    rows.sort(key=lambda row: ((row.get("seq") or 0), row.get("menu_id") or ""))
    nodes: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for row in rows:
        legacy_id = str(row["menu_id"])
        menu_name = (row.get("menu_name") or legacy_id).strip()
        node: dict[str, Any] = {
            "id": legacy_id,
            "code": menu_name,
            "name": (row.get("menu_label") or menu_name).strip(),
            "path": _normalize_menu_path(row.get("url")),
            "icon": row.get("menu_icon"),
            "parent_id": (str(row.get("parent_id")) if row.get("parent_id") else None),
            "type": _normalize_menu_type(row.get("menu_type")),
            "sort_order": int(row.get("seq") or 0),
            "status": "enabled" if _is_menu_enabled(row.get("state")) else "disabled",
            "visible": True,
            "cacheable": False,
            "component": None,
            "permission_code": _primary_permission_for_menu(menu_name, row.get("menu_type")),
            "children": [],
        }
        nodes[legacy_id] = node

    for node in nodes.values():
        parent_id = node.get("parent_id")
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    _sort_menu_tree(roots)
    return roots


def _sort_menu_tree(nodes: list[dict[str, Any]]) -> None:
    nodes.sort(key=lambda item: (item["sort_order"], item["id"]))
    for node in nodes:
        children = node.get("children")
        if isinstance(children, list):
            _sort_menu_tree(children)


def _load_legacy_roles(db: Session, user_id: str) -> list[tuple[str, str | None, str | None]]:
    if not _legacy_table_exists(db, "user_role_rela") or not _legacy_table_exists(db, "user_role"):
        return []
    stmt = text(
        """
        SELECT ur.id AS role_id, ur.name AS role_name, ur.state AS role_state
        FROM user_role_rela urr
        JOIN user_role ur ON ur.id = urr.role_id
        WHERE urr.user_id = :user_id
        """
    )
    try:
        rows = db.execute(stmt, {"user_id": user_id}).mappings().all()
    except SQLAlchemyError:
        _rollback_safely(db)
        return []
    return [
        (
            str(row["role_id"]),
            row.get("role_name"),
            row.get("role_state"),
        )
        for row in rows
    ]


def _load_modern_roles(db: Session, user_id: str) -> list[tuple[str, str | None, str | None]]:
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        # Ensure Role mapper is registered before resolving User.roles.
        from ..models.rbac import Role as _Role  # noqa: F401
        from ..models.user import User

        user = db.execute(
            select(User).options(joinedload(User.roles)).where(User.id == user_id)
        ).unique().scalar_one_or_none()
    except SQLAlchemyError:
        _rollback_safely(db)
        return []
    if not user:
        return []
    roles = []
    for role in getattr(user, "roles", []):
        role_id = str(getattr(role, "code", None) or getattr(role, "id", ""))
        role_name = getattr(role, "name", None)
        role_state = getattr(role, "state", None)
        if role_id:
            roles.append((role_id, role_name, role_state))
    return roles


def _load_legacy_permissions(db: Session, role_codes: set[str]) -> set[str]:
    real_role_ids = sorted(code for code in role_codes if code != "admin")
    if not real_role_ids:
        return set()
    if not _legacy_table_exists(db, "role_menu_rela") or not _legacy_table_exists(db, "menu"):
        return set()

    stmt = text(
        """
        SELECT DISTINCT m.menu_name, m.menu_type, m.state
        FROM role_menu_rela rmr
        JOIN menu m ON m.menu_id = rmr.menu_id
        WHERE rmr.role_id IN :role_ids
        """
    ).bindparams(bindparam("role_ids", expanding=True))
    try:
        rows = db.execute(stmt, {"role_ids": real_role_ids}).mappings().all()
    except SQLAlchemyError:
        _rollback_safely(db)
        return set()

    permission_codes: set[str] = set()
    for row in rows:
        if not _is_menu_enabled(row.get("state")):
            continue
        menu_name = (row.get("menu_name") or "").strip()
        if menu_name in DISABLED_MENU_CODES:
            continue
        permission_codes.update(_permissions_for_menu(menu_name, row.get("menu_type")))
    return permission_codes


def _load_modern_permissions(db: Session, role_codes: set[str]) -> set[str]:
    real_role_ids = sorted(code for code in role_codes if code != "admin")
    if not real_role_ids:
        return set()

    try:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        from ..models.rbac import Role

        roles = db.execute(
            select(Role)
            .options(joinedload(Role.permissions))
            .where(Role.code.in_(real_role_ids))
        ).unique().scalars().all()
    except SQLAlchemyError:
        _rollback_safely(db)
        return set()

    return {
        permission.code
        for role in roles
        for permission in getattr(role, "permissions", [])
        if getattr(permission, "code", None)
    }


def _load_legacy_menus(db: Session) -> list[dict[str, Any]]:
    if not _legacy_table_exists(db, "menu"):
        return []
    stmt = text(
        """
        SELECT
            m.id::text AS menu_id,
            m.code AS menu_name,
            m.name AS menu_label,
            m.type AS menu_type,
            m.parent_id,
            m.path AS url,
            m.icon AS menu_icon,
            m.sort_order AS seq,
            m.status AS state
        FROM menus m
        """
    )
    try:
        rows = db.execute(stmt).mappings().all()
    except SQLAlchemyError:
        _rollback_safely(db)
        return []
    items = [dict(row) for row in rows]
    existing_codes = {str(row.get("menu_name") or "").strip() for row in items}
    for row in SYNTHETIC_LEGACY_MENU_ROWS:
        if str(row["menu_name"]) not in existing_codes:
            items.append(dict(row))
    return items


def _load_legacy_allowed_menu_ids(db: Session, role_codes: set[str]) -> set[str]:
    real_role_ids = sorted(code for code in role_codes if code != "admin")
    if not real_role_ids:
        return set()
    if not _legacy_table_exists(db, "role_menu_rela"):
        return set()

    stmt = text(
        """
        SELECT DISTINCT menu_id
        FROM role_menu_rela
        WHERE role_id IN :role_ids
        """
    ).bindparams(bindparam("role_ids", expanding=True))
    try:
        rows = db.execute(stmt, {"role_ids": real_role_ids}).all()
    except SQLAlchemyError:
        _rollback_safely(db)
        return set()
    return {str(row[0]) for row in rows}


def _rollback_safely(db: Session) -> None:
    try:
        db.rollback()
    except SQLAlchemyError:
        return


def _legacy_table_exists(db: Session, table_name: str) -> bool:
    try:
        result = db.scalar(text("SELECT to_regclass(:table_name)"), {"table_name": f"public.{table_name}"})
    except SQLAlchemyError:
        _rollback_safely(db)
        return False
    return result is not None


def _is_role_enabled(raw_state: str) -> bool:
    state = raw_state.strip().upper()
    return state in {"ENABLED", "ACTIVE", "1", "TRUE"}


def _is_admin_role(role_id: str, role_name: str | None) -> bool:
    normalized_id = role_id.strip().lower()
    if normalized_id in ADMIN_ROLE_IDS:
        return True
    normalized_name = (role_name or "").strip().lower()
    return "admin" in normalized_name or "管理员" in (role_name or "")


def _is_menu_enabled(raw_state: str | None) -> bool:
    state = (raw_state or "").strip().upper()
    return state in {"ENABLED", "ACTIVE", "1", "TRUE", ""}


def _permissions_for_menu(menu_name: str, menu_type: str | None) -> set[str]:
    if not menu_name:
        return set()
    mapped = MENU_CODE_PERMISSION_MAP.get(menu_name)
    if mapped:
        return set(mapped)
    if (menu_type or "").strip().upper() == "BUTTON" and "." in menu_name:
        return {menu_name}
    return set()


def _primary_permission_for_menu(menu_name: str, menu_type: str | None) -> str | None:
    permissions = sorted(_permissions_for_menu(menu_name, menu_type))
    return permissions[0] if permissions else None


def _normalize_menu_type(raw_menu_type: str | None) -> str:
    menu_type = (raw_menu_type or "").strip().lower()
    if menu_type in {"directory", "button", "menu"}:
        return menu_type
    return "menu"


def _normalize_menu_path(raw_url: str | None) -> str | None:
    url = (raw_url or "").strip()
    if not url:
        return None
    if url in LEGACY_URL_PATH_MAP:
        return LEGACY_URL_PATH_MAP[url]
    if url.startswith(("http://", "https://", "/")):
        return url
    return f"/admin/{url}"
