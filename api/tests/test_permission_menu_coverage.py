"""权限码注册覆盖度回归测试。

背景（2026-09-27 权限审计，2026-11-09 / LP-28 调整后修订）：
    最初权限码的唯一授予途径是「角色绑定菜单」（menus.permission_code → 权限码），
    细粒度权限码必须挂在 type=button 的菜单项上才能被非 admin 角色勾到。
    2026-11-09 权限策略调整后：
      · 后端 require_*permission / require_any_permission / require_enabled_menu_route
        全部退化为「仅要求登录」，不再消费 permission_code；
      · 角色配置页只保留目录 + 页面，勾选页面后按模块前缀自动推导该模块全部权限码，
        button 行不再展示也无需逐个配置（web/src/app/admin/roles/page.tsx）；
      · type=button 菜单项已作为失效遗留数据由 LP-28 清理，不再写入 DEFAULT_MENUS。

因此现在校验的契约是：代码中引用的权限码必须注册在 DEFAULT_PERMISSIONS（permissions 表
种子）中，角色配置才能按模块前缀推导并分配给非 admin 角色；不再要求每个权限码都有
一个 type=button 的菜单出口。

注意：前端用例依赖仓库内的 web/src；在 api 镜像里运行（无 web 源码）会自动跳过。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from app.services.legacy_authz_service import (
    MANAGE_IMPLIED_PERMISSIONS,
    MENU_CODE_PERMISSION_MAP,
)
from app.services.seed_service import DEFAULT_MENUS, DEFAULT_PERMISSIONS

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_dir(candidates) -> Path | None:
    for cand in candidates:
        if cand and cand.is_dir():
            return cand
    return None


def _detect_web_src() -> Path | None:
    """定位 web/src：兼容仓库布局（<repo>/web/src）与容器内移植（/web/src）。"""
    bases = list(Path(__file__).resolve().parents)
    return _find_dir([*(b / "web" / "src" for b in bases), Path("/web/src")])


def _detect_api_app() -> Path | None:
    """定位 api 应用代码：兼容 <repo>/api/app 与容器内 /app/app。"""
    bases = list(Path(__file__).resolve().parents)
    for cand in [*(b / "api" / "app" for b in bases), Path("/app/app")]:
        if (cand / "services" / "seed_service.py").is_file():
            return cand
    return None


WEB_SRC = _detect_web_src()
API_APP = _detect_api_app()

_CODE_RE = re.compile(r'["\']([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)["\']')
_FE_RE = re.compile(r'hasPermission\s*\(\s*["\']([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)["\']')
_BE_CALL_RE = re.compile(r'require_(?:any_)?permission\s*\(([^)]*)\)')

_ENABLED = {"enabled", "active", "1", "true"}


def _grantable_permission_codes() -> set[str]:
    """算出角色配置可授予的权限码全集。

    - 页面菜单自带的 permission_code，以及静态映射/管理码推导出的码；
    - DEFAULT_PERMISSIONS 中注册的全部权限码：角色配置勾选页面后按模块前缀
      从 permissions 目录自动推导该模块的全部权限码，因此注册即代表可授予
      （不再需要 type=button 菜单作为出口，LP-28 起按钮菜单已从种子移除）。
    """
    codes: set[str] = set(DEFAULT_PERMISSIONS)
    for menu in DEFAULT_MENUS:
        if str(menu.get("status") or "").strip().lower() not in _ENABLED:
            continue
        menu_code = str(menu.get("code") or "")
        permission_code = str(menu.get("permission_code") or "").strip()

        if "." in permission_code:
            # DB 权限码优先（menus.permission_code 即契约）
            codes.add(permission_code)
            continue

        mapped = MENU_CODE_PERMISSION_MAP.get(menu_code)
        if mapped:
            codes |= set(mapped)

    for manage_code, implied in MANAGE_IMPLIED_PERMISSIONS.items():
        if manage_code in codes:
            codes |= set(implied)

    return codes


def _iter_files(root: Path, suffixes: tuple[str, ...]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {"node_modules", ".next", "__pycache__"}]
        for name in filenames:
            if name.endswith(suffixes):
                yield Path(dirpath) / name


def _frontend_permission_codes() -> set[str]:
    assert WEB_SRC is not None, "未定位到 web/src"
    codes: set[str] = set()
    for path in _iter_files(WEB_SRC, (".ts", ".tsx")):
        codes |= set(_FE_RE.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return codes


def _backend_permission_codes() -> set[str]:
    assert API_APP is not None, "未定位到后端应用代码目录"
    codes: set[str] = set()
    for path in _iter_files(API_APP, (".py",)):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for args in _BE_CALL_RE.findall(text):
            codes |= set(_CODE_RE.findall(args))
    return codes


def _assert_unregistered(label: str, codes: set[str]) -> None:
    grantable = _grantable_permission_codes()
    missing = sorted(codes - grantable)
    assert not missing, (
        f"{label} 引用了以下权限码，但 DEFAULT_PERMISSIONS 未注册、且没有菜单能授予它们，"
        f"非 admin 角色在角色管理页面永远拿不到：\n  "
        + "\n  ".join(missing)
        + "\n\n修法：在 seed_service.DEFAULT_PERMISSIONS 里注册该权限码"
          "（角色配置勾选页面后按模块前缀自动推导，无需再加 type=button 菜单）。"
    )


def test_grantable_set_is_not_empty() -> None:
    grantable = _grantable_permission_codes()
    assert grantable, "DEFAULT_PERMISSIONS / DEFAULT_MENUS 未解析出任何权限码，测试自身可能已失效"


def test_backend_permission_codes_are_registered() -> None:
    """后端每个 require_*permission 引用的权限码都必须是已注册的权限码。"""
    codes = _backend_permission_codes()
    assert codes, "未从 api/app 解析到任何权限码，测试自身可能已失效"
    _assert_unregistered("后端 require_*permission", codes)


@pytest.mark.skipif(WEB_SRC is None, reason="web/src 不在当前上下文（如 api 镜像内）")
def test_frontend_permission_codes_are_registered() -> None:
    """前端每个 hasPermission 引用的权限码都必须是已注册的权限码。"""
    codes = _frontend_permission_codes()
    assert codes, "未从 web/src 解析到任何权限码，测试自身可能已失效"
    _assert_unregistered("前端 hasPermission", codes)


@pytest.mark.skipif(WEB_SRC is None, reason="web/src 不在当前上下文（如 api 镜像内）")
def test_frontend_codes_are_not_hardcoded_open() -> None:
    """禁止用 `hasPermission(...) || true` 之类把权限判定整个废掉。"""
    assert WEB_SRC is not None
    pattern = re.compile(r'hasPermission\s*\([^)]*\)\s*\|\|\s*(true|1)\b')
    offenders = []
    for path in _iter_files(WEB_SRC, (".ts", ".tsx")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path}:{lineno}")
    assert not offenders, (
        "以下位置用 `|| true` 绕过了权限判定，属于无效校验，应改为对齐后端真实权限码：\n  "
        + "\n  ".join(offenders)
    )


def test_no_blank_permission_code_on_enabled_leaf_menu() -> None:
    """已启用的非目录菜单必须声明权限码，否则角色绑定后什么都授予不到。"""
    offenders = [
        str(m["code"])
        for m in DEFAULT_MENUS
        if str(m.get("type") or "").lower() == "menu"
        and str(m.get("status") or "").lower() in _ENABLED
        and not str(m.get("permission_code") or "").strip()
        and str(m.get("code") or "") not in MENU_CODE_PERMISSION_MAP
    ]
    assert not offenders, (
        "以下已启用菜单既没有 permission_code，也不在 MENU_CODE_PERMISSION_MAP 里，"
        "绑定后不会授予任何权限码：\n  " + "\n  ".join(offenders)
    )
