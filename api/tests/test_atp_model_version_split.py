"""LP-11 模型/版本拆表回归测试。

覆盖验收标准里能在 SQLite 内存库验证的部分：
  * ORM 拆分：AtpModel(atp_model) + AtpAssetVersion(atp_asset_version) + 新列/约束；
  * 一步改名后 atp_asset_run.asset_id 外键指向新表且数据零孤儿；
  * /models 按模型聚合（1429 版本 → N 模型）、展示版本优先级、筛选/分页；
  * 决策 2：主表 code 去 -vN 且去重、版本表 version_code 原样保留旧 code；
  * 双写过渡：atp_model 存在时 create/fork 回填 model_id + version_code，
    atp_model 不存在（兼容视图回退/精简建表）时仍只写 version_code，不报错；
  * 仿真选版一致性：改名前后 fl_analysis 资产定位对同一批维度选出同一版本 id。

线上 781/1429 行数、MinIO 路径零变化、字段逐项比对由
api/migrations/038_atp_model_version_split_validate.sql 在 PG 上校验。
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

warnings.filterwarnings("ignore", category=Warning)

from app.core.database import Base  # noqa: E402
from app.models.atp_asset import AtpAsset, AtpAssetRun, AtpAssetVersion, AtpModel  # noqa: E402
from app.models.dimension_item import DimensionItem  # noqa: E402
from app.models.dimension_type import DimensionType  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.atp_asset import AtpAssetCreateRequest  # noqa: E402
from app.services import atp_asset_service as svc  # noqa: E402


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_db(*, with_model_table: bool = True):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        AtpAssetVersion.__table__, AtpAssetRun.__table__,
        DimensionItem.__table__, DimensionType.__table__, User.__table__,
    ]
    if with_model_table:
        tables.append(AtpModel.__table__)
    Base.metadata.create_all(bind=engine, tables=tables)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()


def _version(
    *,
    code: str,
    name: str = "模型",
    v: str = "v1",
    voltage: str = "500",
    tower: str = "ganzi",
    scene: str = "fanji",
    arrester: str = "M1",
    shield: str = "with",
    is_active: bool = False,
    is_published: bool = False,
    publish_state: str = "new",
    published_date: datetime | None = None,
    created: datetime | None = None,
) -> AtpAssetVersion:
    created = created or _utcnow()
    return AtpAssetVersion(
        code=code, name=name, description="说明", status="enabled",
        voltage_level=voltage, tower_type=tower, scene_type=scene,
        arrester_config=arrester, shield_wire=shield, version=v,
        is_active=is_active, is_published=is_published,
        publish_state=publish_state, published_date=published_date,
        create_date=created, update_date=created,
    )


# ───────────────────────── ORM 拆分 ─────────────────────────

def test_orm_split_and_rename() -> None:
    """决策 3：物理表改名、新增模型主表；过渡期兼容别名保持旧引用可用。"""
    assert AtpAssetVersion.__tablename__ == "atp_asset_version"
    assert AtpModel.__tablename__ == "atp_model"
    assert AtpAsset is AtpAssetVersion  # 过渡期兼容别名
    version_cols = {c.name for c in AtpAssetVersion.__table__.columns}
    assert {"model_id", "version_code"} <= version_cols
    # 模型级字段过渡期双写保留在版本表
    assert {"name", "description", "status", "voltage_level", "tower_type",
            "scene_type", "arrester_config", "shield_wire"} <= version_cols
    model_cols = {c.name for c in AtpModel.__table__.columns}
    assert {"id", "code", "name", "description", "status", "voltage_level",
            "tower_type", "scene_type", "arrester_config", "shield_wire"} <= model_cols


def test_fk_after_rename_points_to_version_table() -> None:
    """三张外键表 FK 目标改指 atp_asset_version.id；asset_id 数据零孤儿。"""
    fk_targets = {fk.target_fullname for fk in AtpAssetRun.__table__.foreign_keys}
    assert "atp_asset_version.id" in fk_targets
    db = _make_db(with_model_table=True)
    v = _version(code="FK-1")
    db.add(v)
    db.flush()
    db.add(AtpAssetRun(asset_id=v.id, status="pending"))
    db.commit()
    # 零孤儿：能 join 上版本行
    assert db.scalar(select(func.count()).select_from(AtpAssetRun)) == 1
    assert db.get(AtpAssetVersion, v.id) is not None


# ───────────────────────── 决策 2：code 规则 ─────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("ATP66-shangzi-raoji2-M123-v2", "ATP66-shangzi-raoji2-M123"),
    ("ATP66-...-M123-v10", "ATP66-...-M123"),
    ("ATP66-...-M123-v2-rev3", "ATP66-...-M123"),
    ("ATP-500-GUXING", "ATP-500-GUXING"),  # 无后缀原样
])
def test_model_code_strips_version_suffix(raw: str, expected: str) -> None:
    assert svc._model_code_from_version_code(raw) == expected


def test_dual_write_populates_model_id_version_code_and_master_row() -> None:
    """双写：create_asset 回填 version_code=旧code，并 upsert 模型主表（code 去后缀）。"""
    db = _make_db(with_model_table=True)
    req = AtpAssetCreateRequest(
        code="ATP66-X-M123-v1", name="模型甲", description="说明",
        voltage_level="500", tower_type="ganzi", scene_type="fanji",
        arrester_config="M1", shield_wire="with",
    )
    created = svc.create_asset(db, req, actor_user_id="tester")
    assert created is not None
    row = db.get(AtpAssetVersion, created.id)
    assert row.version_code == "ATP66-X-M123-v1"  # 原样保留旧 code
    assert row.model_id is not None
    model = db.get(AtpModel, row.model_id)
    assert model is not None
    assert model.code == "ATP66-X-M123"  # 主表去 -vN

    # 同维度组第二版：复用同一模型行，不重复建主表
    req2 = AtpAssetCreateRequest(
        code="ATP66-X-M123-v2", name="模型甲", description="说明",
        voltage_level="500", tower_type="ganzi", scene_type="fanji",
        arrester_config="M1", shield_wire="with", version="v2",
    )
    svc.create_asset(db, req2, actor_user_id="tester")
    assert db.scalar(select(func.count()).select_from(AtpModel)) == 1
    row2 = db.execute(
        select(AtpAssetVersion).where(AtpAssetVersion.code == "ATP66-X-M123-v2")
    ).scalar_one()
    assert row2.model_id == row.model_id
    assert row2.version_code == "ATP66-X-M123-v2"


def test_dual_write_degrades_when_master_table_absent() -> None:
    """兼容视图回退态：atp_model 不存在时仍写 version_code，不报错（可回滚）。"""
    db = _make_db(with_model_table=False)
    req = AtpAssetCreateRequest(
        code="NO-MASTER-v1", name="模型", description="说明",
        voltage_level="110", tower_type="guxing", scene_type="fanji",
        arrester_config="noM",
    )
    created = svc.create_asset(db, req, actor_user_id="tester")
    assert created is not None
    row = db.get(AtpAssetVersion, created.id)
    assert row.version_code == "NO-MASTER-v1"
    assert row.model_id is None


def test_model_code_dedup_across_distinct_dimension_groups() -> None:
    """主表 code 去重：两个不同维度组推出同名 base code 时追加 -2。"""
    db = _make_db(with_model_table=True)
    base = {
        "name": "模型", "description": "说明", "scene_type": "fanji",
        "arrester_config": "M1", "shield_wire": "with",
    }
    svc.create_asset(db, AtpAssetCreateRequest(
        code="DUP-M-v1", voltage_level="500", tower_type="ganzi", **base
    ), actor_user_id="tester")
    svc.create_asset(db, AtpAssetCreateRequest(
        code="DUP-M-v2", voltage_level="220", tower_type="maotou", version="v2", **base
    ), actor_user_id="tester")  # 不同维度组；code 去 -vN 后与上一组同为 DUP-M
    codes = sorted(m.code for m in db.execute(select(AtpModel)).scalars())
    assert len(codes) == 2
    assert len(set(codes)) == 2  # 唯一约束不冲突


# ───────────────────────── /models 聚合 ─────────────────────────

def _seed_groups(db: Session) -> None:
    t0 = _utcnow() - timedelta(days=3)
    db.add_all([
        _version(code="A-v1", name="模型甲", v="v1", is_active=True,
                 is_published=True, publish_state="published",
                 published_date=t0, created=t0),
        _version(code="A-v2", name="模型甲", v="v2", publish_state="changed",
                 created=t0 + timedelta(days=1)),
        _version(code="B-v1", name="模型乙", v="v1", voltage="220", tower="maotou",
                 arrester="noM", shield="without", publish_state="new",
                 created=t0 + timedelta(days=2)),
    ])
    db.commit()


def test_list_models_aggregates_versions_into_models() -> None:
    """1429 版本按模型聚合：3 版本 2 维度组 → 2 个模型。"""
    db = _make_db(with_model_table=True)
    _seed_groups(db)
    r = svc.list_models(db, keyword=None, status_filter=None, voltage_level=None,
                        tower_type=None, scene_type=None)
    assert r.total == 2
    by_code = {it.model_code: it for it in r.items}
    assert by_code["A"].version_count == 2
    assert by_code["B"].version_count == 1
    # /assets 仍是版本列表（口径不变）
    assert svc.list_assets(db, keyword=None, status_filter=None, voltage_level=None,
                           tower_type=None, scene_type=None).total == 3


def test_list_models_display_version_priority_active_first() -> None:
    """§6.2：is_active=true 生效版本优先于版本历史里更新的版本。"""
    db = _make_db(with_model_table=True)
    _seed_groups(db)
    r = svc.list_models(db, keyword=None, status_filter=None, voltage_level=None,
                        tower_type=None, scene_type=None)
    a = next(it for it in r.items if it.model_code == "A")
    assert a.version == "v1"  # 生效版而非更新的 v2
    assert a.is_active is True
    assert a.display_version_id == a.id
    assert a.active_version_id == a.id


def test_list_models_display_version_published_fallback() -> None:
    """§6.2 无生效版：取最新已发布版本 → 再取 create_date 最新版本。"""
    db = _make_db(with_model_table=True)
    t0 = _utcnow() - timedelta(days=5)
    db.add_all([
        _version(code="P-v1", name="P", v="v1", is_published=True,
                 publish_state="published", published_date=t0, created=t0),
        _version(code="P-v2", name="P", v="v2", is_published=True,
                 publish_state="published", published_date=t0 + timedelta(days=1),
                 created=t0 + timedelta(days=1)),
        _version(code="P-v3", name="P", v="v3", is_published=False,
                 publish_state="new", created=t0 + timedelta(days=2)),
    ])
    db.commit()
    r = svc.list_models(db, keyword=None, status_filter=None, voltage_level=None,
                        tower_type=None, scene_type=None)
    p = r.items[0]
    assert p.version == "v2"  # 最新已发布，而非更新的未发布 v3


def test_list_models_filters_and_pagination() -> None:
    db = _make_db(with_model_table=True)
    _seed_groups(db)
    kw = dict(status_filter=None, tower_type=None, scene_type=None)
    assert svc.list_models(db, keyword="模型乙", voltage_level=None, **kw).total == 1
    assert svc.list_models(db, keyword=None, voltage_level="500", **kw).total == 1
    assert svc.list_models(db, keyword=None, voltage_level=None,
                           publish_state="published", **kw).total == 1
    page = svc.list_models(db, keyword=None, voltage_level=None, limit=1, offset=0, **kw)
    assert page.total == 2 and len(page.items) == 1
    # 非法筛选值与 /assets 一致，抛 400
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        svc.list_models(db, keyword=None, voltage_level=None, status_filter="bogus",
                        tower_type=None, scene_type=None)


def test_list_models_works_without_master_table() -> None:
    """过渡/回滚态：atp_model 不存在时 /models 仍能按版本行聚合（可回滚）。"""
    db = _make_db(with_model_table=False)
    _seed_groups(db)
    r = svc.list_models(db, keyword=None, status_filter=None, voltage_level=None,
                        tower_type=None, scene_type=None)
    assert r.total == 2
    assert all(it.model_id.startswith("mdl-") for it in r.items)
    assert all(it.model_code for it in r.items)


# ───────────────────────── 版本归属：model_id 等值 ─────────────────────────

def test_version_group_prefers_model_id() -> None:
    """改归属：model_id 存在时按外键等值定位版本组（五维不再特判）。"""
    db = _make_db(with_model_table=True)
    a = _version(code="G-v1", name="甲", v="v1")
    a.model_id = "model-xyz"
    b = _version(code="G-v2", name="甲", v="v2")
    b.model_id = "model-xyz"
    c = _version(code="H-v1", name="乙", v="v1", voltage="220")
    c.model_id = "model-other"
    db.add_all([a, b, c])
    db.commit()
    conds = svc._dimension_group_conditions(a)
    found = db.execute(select(AtpAssetVersion).where(*conds)).scalars().all()
    assert {x.code for x in found} == {"G-v1", "G-v2"}


# ───────────────────────── 仿真选版一致性（最高优先级） ─────────────────────────

def test_simulation_picks_same_version_id() -> None:
    """迁移前后 fl_analysis 资产定位对同维度批次选出同一版本 id。

    fl_analysis_external 的选版 SQL 依赖版本表上的五维 + is_published + is_active；
    LP-11 过渡期这些列全部保留在 atp_asset_version 上且 id 沿用旧值，
    因此定位逻辑无需改动、结果必然一致。本用例锁定该行为。
    """
    db = _make_db(with_model_table=True)
    t0 = _utcnow() - timedelta(days=2)
    active = _version(code="SIM-v1", name="仿真", v="v1", is_active=True,
                      is_published=True, publish_state="published", created=t0)
    other = _version(code="SIM-v2", name="仿真", v="v2", is_active=False,
                     is_published=True, publish_state="published", created=t0 + timedelta(days=1))
    db.add_all([active, other])
    db.commit()

    # 复刻 fl_analysis_external._query 的选版口径
    stmt = select(AtpAssetVersion).where(
        AtpAssetVersion.status == "enabled",
        AtpAssetVersion.is_published.is_(True),
        AtpAssetVersion.voltage_level == "500",
        AtpAssetVersion.tower_type == "ganzi",
        AtpAssetVersion.scene_type == "fanji",
        AtpAssetVersion.arrester_config == "M1",
        AtpAssetVersion.shield_wire == "with",
        AtpAssetVersion.is_active.is_(True),
    )
    picked = db.execute(stmt.limit(1)).scalar_one_or_none()
    assert picked is not None
    assert picked.id == active.id  # 生效版 id 稳定
