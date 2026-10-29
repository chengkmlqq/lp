"""系统参数分类种子（4 分类 + 参数按前缀自动归类）。

幂等、兼容 PG/MySQL/SQLite（ORM 写入）。启动自动播种 + seed-defaults 端点。
- 分类按 name 判存在（新建/复用），默认不覆盖手动改动（force 才覆盖）。
- 参数按 param_key 前缀映射到分类；已挂分类的不覆盖（force 才覆盖）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.param_category import SystemParamCategory
from app.models.system_param import SystemParam

# 4 个根分类：(name, sort_order)
PARAM_CATEGORIES: list[dict[str, Any]] = [
    {"name": "AI 智能问答", "sort_order": 0},
    {"name": "天地图底图", "sort_order": 1},
    {"name": "登录认证", "sort_order": 2},
    {"name": "MATLAB 引擎", "sort_order": 3},
]

# 参数 param_key 前缀 -> 分类名（按声明顺序匹配，首个命中生效）
PARAM_CATEGORY_MAP: list[tuple[str, str]] = [
    ("ai_chat", "AI 智能问答"),
    ("tianditu", "天地图底图"),
    ("auth", "登录认证"),
    ("matlab_engine", "MATLAB 引擎"),
]


def _resolve_category(prefix: str) -> str | None:
    for p, name in PARAM_CATEGORY_MAP:
        if prefix.startswith(p):
            return name
    return None


def seed_param_categories(db: Session, *, force: bool = False, operator: str | None = None) -> dict[str, int]:
    """幂等种子：建分类 + 参数按前缀归类。

    force=True 才覆盖已有分类/参数的手动改动；默认只补缺失。
    返回 {"categories_created": int, "params_mapped": int, "categories_skipped": int, "params_skipped": int}。
    """
    now = datetime.now(timezone.utc)
    categories_created = categories_skipped = params_mapped = params_skipped = 0

    # ---- 分类：按 name 判存在 ----
    existing = {row.name: row for row in db.execute(select(SystemParamCategory)).scalars().all()}
    cat_ids: dict[str, int] = {}
    for item in PARAM_CATEGORIES:
        name = item["name"]
        row = existing.get(name)
        if row is not None and not force:
            cat_ids[name] = row.id
            categories_skipped += 1
            continue
        if row is None:
            row = SystemParamCategory(name=name, created_at=now, updated_at=now)
            db.add(row)
            db.flush()
            categories_created += 1
        cat_ids[name] = row.id
        row.sort_order = int(item["sort_order"])
        row.updated_at = now
    db.flush()

    # ---- 参数：按 param_key 前缀归类 ----
    for param in db.execute(select(SystemParam)).scalars().all():
        target = _resolve_category(param.param_key)
        if not target or target not in cat_ids:
            params_skipped += 1
            continue
        target_id = cat_ids[target]
        if param.category_id == target_id:
            params_skipped += 1
            continue
        if param.category_id is not None and not force:
            # 已挂手动分类，默认不覆盖
            params_skipped += 1
            continue
        param.category_id = target_id
        param.updated_at = now
        params_mapped += 1
    db.flush()

    return {
        "categories_created": categories_created,
        "categories_skipped": categories_skipped,
        "params_mapped": params_mapped,
        "params_skipped": params_skipped,
        "categories": len(PARAM_CATEGORIES),
    }