"""ATP 参数模板：运行时加载（DB）与模式开关。

ATP_MAPPING_MODE:
  - code      : 只用代码路径（compute_csharp_atp_params 原实现）
  - config    : 只用 JSON 配置（api/app/services/atp_param_mappings/*.json）
  - config_db : 优先 DB 表（atp_param_template/atp_param_global），DB 不可用则回落 JSON（默认）

进程内缓存 TTL 默认 30s；页面保存后调用 invalidate() 立即失效（同进程），
其他进程（worker）靠 TTL 收敛。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Mapping

from app.services.atp_param_resolver import (
    MAPPINGS_DIR,
    MappingRules,
    build_context,
    globals_from_rows,
    load_mappings,
    load_mappings_from_rows,
    resolve_params,
)

_CACHE: dict[str, Any] = {"ts": 0.0, "rules": None, "source": None}
_LOCK = threading.Lock()


def mode() -> str:
    return os.environ.get("ATP_MAPPING_MODE", "config_db").strip().lower() or "config_db"


def cache_ttl() -> float:
    try:
        return float(os.environ.get("ATP_MAPPING_CACHE_TTL", "30"))
    except ValueError:
        return 30.0


def invalidate() -> None:
    with _LOCK:
        _CACHE["ts"] = 0.0
        _CACHE["rules"] = None
        _CACHE["source"] = None


def _load_common(glob_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    common = json.loads((MAPPINGS_DIR / "_common.json").read_text(encoding="utf-8"))
    if glob_rows:
        common["globals"] = globals_from_rows(glob_rows)
    return common


def _load_from_db() -> MappingRules | None:
    try:
        from sqlalchemy import text

        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            tpl_rows = [
                dict(row._mapping)
                for row in db.execute(text("SELECT * FROM atp_param_template WHERE enabled")).fetchall()
            ]
            glob_rows = [
                dict(row._mapping)
                for row in db.execute(text("SELECT * FROM atp_param_global WHERE enabled")).fetchall()
            ]
        finally:
            db.close()
        if not tpl_rows:
            return None
        return load_mappings_from_rows(tpl_rows, common=_load_common(glob_rows))
    except Exception:
        return None


def get_rules(*, force: bool = False) -> MappingRules | None:
    """取当前生效规则；mode=code 时返回 None（调用方回落代码路径）。"""
    current_mode = mode()
    if current_mode == "code":
        return None
    now = time.time()
    with _LOCK:
        cached = _CACHE["rules"]
        if cached is not None and not force and now - float(_CACHE["ts"]) < cache_ttl():
            return cached
    rules: MappingRules | None = None
    source = "json"
    if current_mode == "config_db":
        rules = _load_from_db()
        if rules is not None:
            source = "db"
    if rules is None:
        try:
            rules = load_mappings()
        except Exception:
            rules = None
    with _LOCK:
        _CACHE.update({"ts": time.time(), "rules": rules, "source": source})
    return rules


def cache_info() -> dict[str, Any]:
    return {"mode": mode(), "ttl": cache_ttl(), "source": _CACHE.get("source"), "loaded": _CACHE.get("rules") is not None}


def compute_params_from_runtime(
    *,
    base_tower: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    execution_options: Mapping[str, Any] | None = None,
) -> dict[str, str] | None:
    """运行时入口：返回配置驱动的参数；不可用时返回 None（调用方回落代码路径）。"""
    rules = get_rules()
    if rules is None:
        return None
    context = build_context(base_tower=base_tower, profile=profile, execution_options=execution_options)
    resolved = resolve_params(context, rules)
    return resolved.as_dict() or None
