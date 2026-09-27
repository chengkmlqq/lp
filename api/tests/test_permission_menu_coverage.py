"""权限出口覆盖度回归测试。

背景（2026-09-27 权限审计）：
    权限码的唯一授予途径是「角色绑定菜单」（menus.permission_code → 权限码）。
    但代码里存在大量 require_*permission(...) / hasPermission(...) 引用的权限码
    在 DEFAULT_MENUS 里【没有任何菜单或按钮出口】，导致：
      · 角色管理页面里勾不到该权限 → 非 admin 角色永远无法获得
      · 页面/接口对非 admin 永久不可用（例：tower.read 导致线路详情列表空白）

本测试把「代码引用的权限码」与「菜单可授予的权限码」做全集比对：新增权限码却
忘记加菜单出口时，测试阶段就会失败，而不是等用户反馈"页面打不开"。

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
from app.services.seed_service import DEFAULT_MENUS

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


def _grantable_from_seed_menus() -> set[str]:
    """按 _permissions_for_menu 的优先级，算出 DEFAULT_MENUS 能授予的权限码全集。"""
    codes: set[str] = set()
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
            continue

        # button 类型兜底：menu_code 本身即权限码
        if str(menu.get("type") or "").strip().lower() == "button" and "." in menu_code:
            codes.add(menu_code)

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


def _assert_no_orphans(label: str, codes: set[str]) -> None:
    grantable = _grantable_from_seed_menus()
    missing = sorted(codes - grantable)
    assert not missing, (
        f"{label} 引用了以下权限码，但 DEFAULT_MENUS 里没有任何菜单/按钮能授予它们，"
        f"非 admin 角色在角色管理页面永远勾不到：\n  "
        + "\n  ".join(missing)
        + "\n\n修法：在 seed_service.DEFAULT_MENUS 里为对应菜单补一个"
          ' {"type": "button", "permission_code": "<缺失的码>"} 条目。'
    )


def test_grantable_set_is_not_empty() -> None:
    grantable = _grantable_from_seed_menus()
    assert grantable, "DEFAULT_MENUS 未解析出任何权限码，测试自身可能已失效"


def test_backend_permission_codes_have_menu_outlet() -> None:
    """后端每个 require_*permission 引用的权限码都必须有菜单出口。"""
    codes = _backend_permission_codes()
    assert codes, "未从 api/app 解析到任何权限码，测试自身可能已失效"
    _assert_no_orphans("后端 require_*permission", codes)


@pytest.mark.skipif(WEB_SRC is None, reason="web/src 不在当前上下文（如 api 镜像内）")
def test_frontend_permission_codes_have_menu_outlet() -> None:
    """前端每个 hasPermission 引用的权限码都必须有菜单出口。"""
    codes = _frontend_permission_codes()
    assert codes, "未从 web/src 解析到任何权限码，测试自身可能已失效"
    _assert_no_orphans("前端 hasPermission", codes)


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
