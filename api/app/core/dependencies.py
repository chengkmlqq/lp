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
from . import auth_cache
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
    # /runtime 为共享读（天地图等），不绑「系统参数」菜单可见性
    ("/api/v1/admin/system-params/runtime", ""),
    ("/api/v1/admin/system-params", "/admin/system-params"),
    ("/api/v1/system-messages", "/admin/system-messages"),
    ("/api/v1/lines", "/admin/power-lines"),
    ("/api/v1/tower-profiles", "/admin/power-lines"),
    ("/api/v1/fl-analysis", "/admin/fl-analysis"),
    ("/api/v1/fault-recurrence", "/admin/fault-recurrence"),
    ("/api/v1/lightning-currents/stats/distribution", "/admin/lightning-distribution"),
    ("/api/v1/lightning-currents/import-distribution", "/admin/lightning-distribution"),
    ("/api/v1/lightning-currents", "/admin/lightning-currents"),
    ("/api/v1/lightning-retrofit", "/admin/lightning-retrofit"),
    ("/api/v1/admin/flower", "/admin/workers"),
    ("/api/v1/admin/task-monitor", "/admin/task-monitor"),
    ("/api/v1/admin/scheduled-tasks", "/admin/scheduled-tasks"),
    ("/api/v1/admin/overview", "/admin/overview"),
    # 测试线路单独成页（/admin/atp-test-lines），必须排在 /api/v1/atp 之前，
    # 否则前缀匹配会先落到 /api/v1/atp → /admin/atp-models。
    ("/api/v1/atp/test-lines", "/admin/atp-models"),
    ("/api/v1/atp", "/admin/atp-models"),
    ("/api/v1/tower-models", "/admin/tower-models"),
    ("/api/v1/admin/files", "/admin/files"),
    ("/api/v1/elevation", "/admin/elevation"),
    ("/api/v1/fault-matlab", "/admin/matlab-engine"),
)

# 同一 API 前缀可以被多个菜单"持有"时，用这里补可选菜单路径（任一个启用即放行）。
# 典型场景：/api/v1/atp/test-lines 既服务「ATP模型管理」页，也服务独立的
# 「测试线路管理」页；只给用户后者菜单时不应该 403。
MENU_ROUTE_ALTERNATES: dict[str, tuple[str, ...]] = {
    "/api/v1/atp/test-lines": ("/admin/atp-test-lines",),
}


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


def _menu_paths_for_api_path(api_path: str) -> tuple[str, ...]:
    """返回该 API 路径可接受的菜单路径集合（主菜单 + 可选别名）。

    任一菜单启用即视为可见（空字符串表示「不绑菜单」，直接放行）。
    AIP 风格的冒号动作（``/atp/test-lines:derive``）先剥掉后缀再匹配，
    否则会退化成匹配更短的 ``/api/v1/atp`` 前缀。
    """
    normalized_api_path = _normalize_path(api_path)
    if not normalized_api_path:
        return ()
    match_path = normalized_api_path.split(":", 1)[0]
    for api_prefix, menu_path in MENU_ROUTE_PREFIXES:
        if _path_matches_prefix(match_path, api_prefix):
            alternates = MENU_ROUTE_ALTERNATES.get(api_prefix, ())
            return (menu_path, *alternates)
    return ()


def _menu_paths_allow_access(db: Session, menu_paths: tuple[str, ...]) -> bool:
    """多候选菜单路径的放行判定。

    语义（保持与单路径版本向后兼容）：
    - 候选里有空串 → 不绑菜单，直接放行
    - 候选路径在库里一条记录都没有 → 放行（fresh install 还没 seed 菜单时不能把人挡在外面）
    - 否则：任一候选是 enabled + visible 即放行
    """
    normalized_paths = [path for path in (_normalize_path(item) for item in menu_paths) if path]
    if not normalized_paths:
        return True
    try:
        rows = db.execute(
            select(Menu.path, Menu.status, Menu.visible).where(Menu.path.in_(normalized_paths))
        ).all()
    except SQLAlchemyError:
        db.rollback()
        return True
    if not rows:
        return True
    return any(row.status == "enabled" and bool(row.visible) for row in rows)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> CurrentUser:
    # 2026-11-10 性能修复：同一请求内 FastAPI 对不同 security scopes 的依赖会各自
    # 解析一次，导致鉴权链路（用户 + 角色 + 权限 + 菜单）被重复执行 2~3 次，每次都
    # 要跨公网访问阿里云 RDS。这里按请求缓存，确保只解析一次。
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

    payload = decode_access_token(token)
    user_id = str(payload["sub"])

    # 2026-11-10：鉴权结果（用户快照 + 角色码 + 权限码）走 Redis 短缓存，
    # 命中时整条链路不碰数据库。详见 app/core/auth_cache.py 的一致性约定。
    entry = auth_cache.load(user_id)
    if entry is not None:
        cached_user = auth_cache.build_user(entry)
        if not is_user_enabled(cached_user.status):
            # 账号已停用：清缓存后按正常链路走，交给下方分支抛 403
            auth_cache.invalidate(user_id)
        else:
            current = CurrentUser(
                user=cached_user,
                role_codes=auth_cache.role_codes(entry),
                permission_codes=auth_cache.permission_codes(entry),
            )
            request.state.current_user = current
            return current

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
    auth_cache.store(user, role_codes=authz.role_codes, permission_codes=authz.permission_codes)
    current = CurrentUser(
        user=user,
        role_codes=authz.role_codes,
        permission_codes=authz.permission_codes,
    )
    request.state.current_user = current
    return current


# ── 2026-11-09 权限策略调整 ─────────────────────────────────────────────
# 接口层不再做权限码/菜单路由校验，仅要求登录（+ 用户启用）。
# 访问控制统一收敛到「菜单可见性」：role_menus → 前端侧边栏按角色渲染。
# require_permission / require_any_permission / require_enabled_menu_route
# 保留原签名以兼容约 30 个路由文件的既有 import，内部全部退化为登录校验。
# 下方 MENU_ROUTE_PREFIXES / _menu_paths_for_api_path / _menu_paths_allow_access
# 为旧菜单路由守卫的实现，暂保留用于回滚，运行期不再调用。


def require_permission(permission_code: str):
    """仅要求登录（原：按权限码 403）。参数保留以兼容既有路由签名。"""

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        return current_user

    return dependency


def require_any_permission(*permission_codes: str) -> Callable[[CurrentUser], CurrentUser]:
    """仅要求登录（原：任一权限码 403）。参数保留以兼容既有路由签名。"""

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        return current_user

    return dependency


def require_enabled_menu_route(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """仅要求登录（原：按菜单全局 enabled+visible 403）。"""
    return current_user
