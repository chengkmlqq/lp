"""LP-123 左侧维度树统计口径修正回归测试。

覆盖：
  * 同一模型多版本 → 各层树节点只计一次（普通模式 + 搜索模式）；
  * 未生效版本不再额外计入；无 active 版本时按展示版本口径仍计一次；
  * 「全部」节点（首层 count 之和）/ 点击节点后的子节点 count 与
    /api/v1/atp/models 的 total 一致；
  * 搜索模式与普通模式计数口径一致、has_children 同源一致。
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

warnings.filterwarnings("ignore", category=Warning)

from app.core.database import Base  # noqa: E402
from app.models.atp_asset import AtpAsset, AtpAssetRun, AtpAssetVersion, AtpModel  # noqa: E402
from app.models.dimension_item import DimensionItem  # noqa: E402
from app.models.dimension_type import DimensionType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import atp_asset_service as svc  # noqa: E402


def _make_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        AtpAssetVersion.__table__, AtpAssetRun.__table__,
        DimensionItem.__table__, DimensionType.__table__, User.__table__,
        AtpModel.__table__,
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()


_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dt(days: int) -> datetime:
    return _BASE + timedelta(days=days)


def _version(
    *,
    code: str,
    voltage: str = "110",
    tower: str = "ganzi",
    scene: str = "fanji",
    arrester: str = "M1",
    shield: str = "with",
    name: str = "塔模型",
    is_active: bool = False,
    is_published: bool = False,
    created: datetime | None = None,
) -> AtpAssetVersion:
    created = created or _dt(0)
    return AtpAssetVersion(
        code=code, name=name, description="说明", status="enabled",
        voltage_level=voltage, tower_type=tower, scene_type=scene,
        arrester_config=arrester, shield_wire=shield, version="v1",
        is_active=is_active, is_published=is_published, publish_state="new",
        published_date=created if is_published else None,
        create_date=created, update_date=created,
    )


def _model_total(db: Session, **kwargs) -> int:
    params = dict(
        keyword=None, status_filter=None, voltage_level=None, tower_type=None,
        scene_type=None, arrester_config=None, test_status=None,
        is_published=None, publish_state=None, tags=None, limit=50, offset=0,
    )
    params.update(kwargs)
    return svc.list_models(db, **params).total


def _counts(nodes: list[dict]) -> dict[str, int]:
    return {node["code"]: node["count"] for node in nodes}


def _add_dimension_labels(db: Session) -> None:
    """让树节点 label 全部含「塔」：搜索时节点过滤与资产过滤都能命中。"""
    db.add_all([
        DimensionItem(dimension_type="voltage_level", code="110", name="110塔压"),
        DimensionItem(dimension_type="voltage_level", code="220", name="220塔压"),
        DimensionItem(dimension_type="tower_type", code="ganzi", name="甘孜塔"),
        DimensionItem(dimension_type="tower_type", code="guxing", name="古心塔"),
        DimensionItem(dimension_type="scenario", code="fanji", name="防击塔"),
        DimensionItem(dimension_type="arrester_combination", code="M1", name="M1塔"),
    ])
    db.flush()


# ─────────────────── 同一模型多版本只计一次 ───────────────────

def test_multi_version_model_counted_once_in_normal_tree() -> None:
    """一个模型 3 个版本（1 active + 2 未生效）时，首层节点只计 1。"""
    db = _make_db()
    # 模型 A：voltage=110，3 个版本同维度 → 同一模型
    db.add(_version(code="A-v1", voltage="110", is_active=True, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", is_active=False, created=_dt(2)))
    db.add(_version(code="A-v3", voltage="110", is_active=False, created=_dt(3)))
    # 模型 B：voltage=220，2 个版本，均非 active → 按「最新已发布/最新创建」选展示版本
    db.add(_version(code="B-v1", voltage="220", is_published=True, created=_dt(4)))
    db.add(_version(code="B-v2", voltage="220", is_active=False, created=_dt(5)))
    db.commit()

    roots = svc.list_asset_tree_children(db)
    assert _counts(roots) == {"110": 1, "220": 1}
    assert sum(n["count"] for n in roots) == _model_total(db) == 2


def test_all_inactive_model_still_counted_once() -> None:
    """无 active 版本时仍按展示版本口径计一次（不是直接过滤 is_active=True）。"""
    db = _make_db()
    db.add(_version(code="A-v1", voltage="110", is_active=False, is_published=False, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", is_active=False, is_published=False, created=_dt(2)))
    db.commit()

    roots = svc.list_asset_tree_children(db)
    assert _counts(roots) == {"110": 1}
    assert _model_total(db) == 1


# ─────────────────── 各层节点数与卡片列表一致 ───────────────────

def test_deeper_level_count_matches_model_filter_total() -> None:
    """点击「110」后展开的杆塔节点 count 与 /models?voltage_level=110 的 total 一致。"""
    db = _make_db()
    db.add(_version(code="A-v1", voltage="110", tower="ganzi", is_active=True, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", tower="ganzi", is_active=False, created=_dt(2)))
    db.add(_version(code="B-v1", voltage="110", tower="guxing", created=_dt(3)))
    db.add(_version(code="C-v1", voltage="220", tower="ganzi", created=_dt(4)))
    db.commit()

    children = svc.list_asset_tree_children(db, path="vl:110")
    assert _counts(children) == {"ganzi": 1, "guxing": 1}
    assert _model_total(db, voltage_level="110") == 2

    # 叶子层（电压→杆塔→场景→避雷器）：has_children 恒为 False
    leaf = svc.list_asset_tree_children(db, path="vl:110|tw:ganzi|sc:fanji")
    assert len(leaf) == 1
    assert leaf[0]["code"] == "M1"
    assert leaf[0]["count"] == 1
    assert leaf[0]["has_children"] is False


def test_has_children_follows_display_versions() -> None:
    """has_children 基于展示版本集合判定，与当前层计数同源。"""
    db = _make_db()
    # 模型 A：有更深维度（tower）→ vl:110 应有 children
    db.add(_version(code="A-v1", voltage="110", tower="ganzi", is_active=True, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", tower="ganzi", created=_dt(2)))
    # 模型 B：无 tower（更深维度为空）→ 仍是一模型，但不产生 has_children
    db.add(_version(code="B-v1", voltage="110", tower="", created=_dt(3)))
    db.commit()

    roots = svc.list_asset_tree_children(db)
    node_110 = next(n for n in roots if n["code"] == "110")
    assert node_110["count"] == 2
    assert node_110["has_children"] is True


# ─────────────────── 搜索模式与普通模式一致 ───────────────────

def test_search_tree_count_matches_normal_tree() -> None:
    """搜索模式命中全部模型时，各层 count 与普通模式完全相同。"""
    db = _make_db()
    db.add(_version(code="A-v1", voltage="110", tower="ganzi", name="塔模型A", is_active=True, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", tower="ganzi", name="塔模型A", created=_dt(2)))
    db.add(_version(code="B-v1", voltage="110", tower="guxing", name="塔模型B", created=_dt(3)))
    db.add(_version(code="C-v1", voltage="220", tower="ganzi", name="塔模型C", is_active=True, created=_dt(4)))
    db.add(_version(code="C-v2", voltage="220", tower="ganzi", name="塔模型C", created=_dt(5)))
    _add_dimension_labels(db)
    db.commit()

    normal_roots = svc.list_asset_tree_children(db)
    search_roots = svc.list_asset_tree_children(db, keyword="塔")

    assert _counts(search_roots) == _counts(normal_roots) == {"110": 2, "220": 1}

    def _flatten(nodes: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for node in nodes:
            out[node["key"]] = node["count"]
            out.update(_flatten(node.get("children", [])))
        return out

    # 搜索模式返回嵌套树：逐节点核对 count（key 编码到杆塔层）
    search_flat = _flatten(search_roots)
    assert search_flat["vl:110|tw:ganzi"] == 1
    assert search_flat["vl:110|tw:guxing"] == 1
    assert search_flat["vl:220|tw:ganzi"] == 1


def test_search_tree_excludes_inactive_duplicate() -> None:
    """搜索模式同样只计展示版本：同一模型 2 版本都命中关键词也只计 1。"""
    db = _make_db()
    db.add(_version(code="A-v1", voltage="110", name="塔A", is_active=True, created=_dt(1)))
    db.add(_version(code="A-v2", voltage="110", name="塔A", created=_dt(2)))
    _add_dimension_labels(db)
    db.commit()

    search_roots = svc.list_asset_tree_children(db, keyword="塔")
    assert _counts(search_roots) == {"110": 1}
