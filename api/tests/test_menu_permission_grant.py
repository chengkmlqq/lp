"""菜单绑定即授予权限码的回归测试（LP-线路管理页授权问题）。

覆盖：角色绑定菜单后，登录鉴权（permission_codes）应包含该菜单/按钮在
menus.permission_code 中声明的访问码（如 line.read），而非仅靠静态映射推导。
"""
from __future__ import annotations

from app.services import legacy_admin_rbac_service
from app.services import legacy_authz_service


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _FakeDb:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.executions: list[tuple[str, dict[str, object]]] = []

    def execute(self, stmt, params=None) -> _FakeResult:
        self.executions.append((str(stmt), dict(params or {})))
        return _FakeResult(self.rows)


def test_permissions_for_menu_uses_db_permission_code_first() -> None:
    # DB 权限码优先：菜单元数据即契约（line.read 为页面访问码）
    assert legacy_authz_service._permissions_for_menu(
        "admin.power_lines", "menu", "line.read"
    ) == {"line.read"}
    # 按钮权限码同样来自 DB
    assert legacy_authz_service._permissions_for_menu(
        "admin.power_lines:btn.create", "button", "line.create"
    ) == {"line.create"}


def test_permissions_for_menu_falls_back_to_static_map() -> None:
    # 老数据无 permission_code：退回静态映射/button 推断
    assert legacy_authz_service._permissions_for_menu("admin.fl_analysis", "menu", None) == {
        "line.read",
        "line.manage",
    }
    assert legacy_authz_service._permissions_for_menu("admin.power_lines", "menu", None) == {
        "line.read",
        "line.manage",
    }
    # button 老数据无权限码：menu_name 即权限码（传统推断）
    assert legacy_authz_service._permissions_for_menu("line.create", "button", None) == {"line.create"}


def test_load_legacy_permissions_maps_menu_db_permission_code(monkeypatch) -> None:
    # 角色绑定线路管理菜单（menus.permission_code=line.read）→ 登录获得 line.read
    row = {
        "menu_name": "admin.power_lines",
        "menu_type": "menu",
        "state": "enabled",
        "menu_descr": "line.read",
    }
    db = _FakeDb([row])

    monkeypatch.setattr(
        legacy_authz_service,
        "_legacy_table_exists",
        lambda db_, table: table == "role_menu_rela",
    )

    result = legacy_authz_service._load_legacy_permissions(db, {"viewer"})

    assert result == {"line.read"}
    assert db.executions and "FROM role_menu_rela" in db.executions[0][0]
    assert "JOIN menus m" in db.executions[0][0]


def test_get_user_authorization_unions_menu_and_direct_permissions(monkeypatch) -> None:
    monkeypatch.setattr(
        legacy_authz_service, "_load_legacy_roles", lambda db, user_id: [("viewer", "查看者", "ENABLED")]
    )
    monkeypatch.setattr(legacy_authz_service, "_is_admin_role", lambda role_id, role_name: False)
    monkeypatch.setattr(legacy_authz_service, "_legacy_user_role_relation_exists", lambda db: True)
    # 老角色不触发默认 user 角色兜底（该逻辑需要探测缺表，测试中直接短路）
    monkeypatch.setattr(legacy_authz_service, "_load_legacy_permissions", lambda db, codes: {"line.read"})
    monkeypatch.setattr(legacy_authz_service, "_load_modern_permissions", lambda db, codes: {"tower.read"})

    authz = legacy_authz_service.get_user_authorization(object(), "u1")

    assert authz.role_codes == {"viewer"}
    assert authz.permission_codes == {"line.read", "tower.read"}


def test_permission_codes_from_menu_rows_uses_db_code() -> None:
    menu_rows = {
        "100": {
            "menu_name": "admin.power_lines",
            "menu_type": "menu",
            "state": "enabled",
            "menu_descr": "line.read",
        }
    }
    result = legacy_admin_rbac_service._permission_codes_from_menu_rows(menu_rows, ["100"])
    assert result == {"line.read"}