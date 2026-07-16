from dataclasses import dataclass
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..models.menu import Menu
from ..models.user import User
from ..services.legacy_authz_service import get_user_authorization, is_user_enabled
from .database import get_db
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@dataclass
class CurrentUser:
    user: User
    role_codes: set[str]
    permission_codes: set[str]


MENU_ROUTE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("/api/v1/users", "/admin/users"),
    ("/api/v1/admin/roles-with-menus", "/admin/roles"),
    ("/api/v1/admin/roles", "/admin/roles"),
    ("/api/v1/admin/system-params", "/admin/system-params"),
    ("/api/v1/system-messages", "/admin/system-messages"),
    ("/api/v1/lines", "/admin/power-lines"),
    ("/api/v1/tower-profiles", "/admin/power-lines"),
    ("/api/v1/fl-analysis", "/admin/fl-analysis"),
    ("/api/v1/fault-recurrence", "/admin/fault-recurrence"),
    ("/api/v1/lightning-currents/stats/distribution", "/admin/lightning-distribution"),
    ("/api/v1/lightning-currents/import-distribution", "/admin/lightning-distribution"),
    ("/api/v1/lightning-currents", "/admin/lightning-currents"),
    ("/api/v1/admin/flower", "/admin/workers"),
    ("/api/v1/admin/task-monitor", "/admin/task-monitor"),
    ("/api/v1/admin/scheduled-tasks", "/admin/scheduled-tasks"),
    ("/api/v1/atp", "/admin/atp-models"),
    ("/api/v1/tower-models", "/admin/tower-models"),
    ("/api/v1/admin/files", "/admin/files"),
    ("/api/v1/elevation", "/admin/elevation"),
    ("/api/v1/wine", "/admin/wine-runner"),
)


def _load_user_with_rbac(db: Session, user_id: str) -> User | None:
    stmt = select(User).where(User.id == user_id)
    return db.execute(stmt).unique().scalar_one_or_none()


def _normalize_path(path: str | None) -> str | None:
    normalized = (path or "").strip()
    if not normalized:
        return None
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _menu_path_for_api_path(api_path: str) -> str | None:
    normalized_api_path = _normalize_path(api_path)
    if not normalized_api_path:
        return None
    for api_prefix, menu_path in MENU_ROUTE_PREFIXES:
        if _path_matches_prefix(normalized_api_path, api_prefix):
            return menu_path
    return None


def _enabled_menu_path_exists(db: Session, menu_path: str) -> bool:
    normalized_menu_path = _normalize_path(menu_path)
    if not normalized_menu_path:
        return True
    try:
        menu = db.execute(
            select(Menu.id, Menu.status, Menu.visible)
            .where(Menu.path == normalized_menu_path)
            .limit(1)
        ).first()
    except SQLAlchemyError:
        db.rollback()
        return True
    if not menu:
        return True
    return menu.status == "enabled" and bool(menu.visible)


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> CurrentUser:
    payload = decode_access_token(token)
    user_id = str(payload["sub"])
    user = _load_user_with_rbac(db, user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not is_user_enabled(user.status):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is disabled",
        )

    authz = get_user_authorization(db, user.id)
    return CurrentUser(
        user=user,
        role_codes=authz.role_codes,
        permission_codes=authz.permission_codes,
    )


def require_permission(permission_code: str):
    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if "admin" in current_user.role_codes:
            return current_user
        if permission_code not in current_user.permission_codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: {permission_code}",
            )
        return current_user

    return dependency


def require_any_permission(*permission_codes: str) -> Callable[[CurrentUser], CurrentUser]:
    required = tuple(dict.fromkeys(permission_codes))

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if "admin" in current_user.role_codes:
            return current_user
        if any(code in current_user.permission_codes for code in required):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing any permission: {', '.join(required)}",
        )

    return dependency


def require_enabled_menu_route(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    menu_path = _menu_path_for_api_path(request.url.path)
    if menu_path and not _enabled_menu_path_exists(db, menu_path):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Menu is disabled",
        )
    return current_user
