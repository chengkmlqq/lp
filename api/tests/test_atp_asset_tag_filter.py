"""ATP 模型「按标签过滤」（2026-11-16）单测。

覆盖：
- GET /atp/assets（版本列表）：多选 OR、total / 分页不失真、与其它筛选叠加、空结果、
  空白/重复标签归一化、不传 = 不过滤。SQL 侧筛选（SQLite json_each）。
- GET /atp/models（模型列表）：按**展示版本**的 tags_json 过滤（口径自洽）、OR、
  total / 分页、空标签不过滤。
- 标签候选 list_tag_options：去重、排序、未使用过的标签不出现。
- 方言兼容（SQLite / MySQL / PostgreSQL）：谓词在各方言下都能编译成对应 SQL，
  SQLite 端到端执行；MySQL 的 JSON 标量参数编码正确。
- 端点层（TestClient）：tags 多选 query 参数解析（tags=a&tags=b）+ 聚合接口可用。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects import mysql, postgresql, sqlite as sqlite_dialect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.atp_asset import AtpAssetVersion, AtpAssetRun
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.services import atp_asset_service as svc


# ─────────────────────── fixture / helpers ───────────────────────

_TABLES = [
    FileStorageBackend.__table__,
    FileStorageMount.__table__,
    FileIndexEntry.__table__,
    User.__table__,
    DimensionType.__table__,
    DimensionItem.__table__,
    AtpAssetVersion.__table__,
    AtpAssetRun.__table__,
]


def _build_sessionmaker():
    # StaticPool + check_same_thread=False：TestClient 在 worker 线程里执行请求，
    # 默认的 :memory: SingletonThreadPool 是线程本地的会让请求线程看到空库。
    # 单连接跨线程共享后，端点层测试与主线程的测试数据处于同一个连接。
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=_TABLES)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session() -> Session:
    db = _build_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


_DT = datetime(2026, 1, 1, 0, 0, 0)


def _add_version(
    db: Session,
    *,
    id: str,
    code: str,
    tags,
    voltage_level: str = "110",
    tower_type: str = "guxing",
    version: str = "v1",
    is_active: bool = False,
    is_published: bool = True,
    name: str | None = None,
) -> None:
    db.add(
        AtpAssetVersion(
            id=id,
            code=code,
            name=name or code,
            description="",
            status="enabled",
            voltage_level=voltage_level,
            tower_type=tower_type,
            scene_type="normal",
            arrester_config="none",
            shield_wire="with",
            version=version,
            version_code=code,
            is_active=is_active,
            is_published=is_published,
            tags_json=tags,
            create_date=_DT,
            update_date=_DT,
        )
    )


def _list_assets(db: Session, **kwargs):
    base = dict(
        keyword=None, status_filter=None, voltage_level=None,
        tower_type=None, scene_type=None,
    )
    base.update(kwargs)
    return svc.list_assets(db, **base)


def _list_models(db: Session, **kwargs):
    base = dict(
        keyword=None, status_filter=None, voltage_level=None,
        tower_type=None, scene_type=None,
    )
    base.update(kwargs)
    return svc.list_models(db, **base)


# ─────────────────────── /atp/assets：多选 OR + total/分页 ───────────────────────

def _seed_flat_versions(db: Session) -> None:
    """5 个版本，标签各不同；tags_json 含 None / [] 两类空值。

    每个版本给不同的电压等级，保证 /models 聚合时是 5 个独立模型组（而非合成一组），
    这样端点层 /models 的标签过滤断言才成立；list_assets 不分组，维度取值不影响它。
    """
    _add_version(db, id="a1", code="A1", tags=["现场", "基准"], voltage_level="110")
    _add_version(db, id="a2", code="A2", tags=["对拍"], voltage_level="220")
    _add_version(db, id="a3", code="A3", tags=[], voltage_level="330")
    _add_version(db, id="a4", code="A4", tags=None, voltage_level="500")
    _add_version(db, id="a5", code="A5", tags=["现场", "对拍"], voltage_level="750")
    db.commit()


def test_list_assets_tags_or_matching(session: Session) -> None:
    _seed_flat_versions(session)

    result = _list_assets(session, tags=["现场", "对拍"])

    # OR：命中任一标签即入选（a1/a2/a5），空/NULL 标签不入
    assert {item.code for item in result.items} == {"A1", "A2", "A5"}
    assert result.total == 3


def test_list_assets_tags_single(session: Session) -> None:
    _seed_flat_versions(session)

    result = _list_assets(session, tags=["基准"])
    assert {item.code for item in result.items} == {"A1"}
    assert result.total == 1


def test_list_assets_no_tags_means_no_filter(session: Session) -> None:
    _seed_flat_versions(session)

    # 不传 / 空数组 / 全空白 = 不过滤
    assert _list_assets(session, tags=None).total == 5
    assert _list_assets(session, tags=[]).total == 5
    assert _list_assets(session, tags=["", "  "]).total == 5


def test_list_assets_tags_total_and_pagination(session: Session) -> None:
    """分页后过滤的天敌：total 必须是过滤后的总数，而非当前页长度。"""
    for index in range(6):
        _add_version(db=session, id=f"p{index}", code=f"P{index}", tags=["命中"])
    # 一个不带标签的，过滤时应被排除
    _add_version(db=session, id="px", code="PX", tags=[])
    session.commit()

    page = _list_assets(session, tags=["命中"], limit=2, offset=1)
    assert page.total == 6                      # ← 不是 2，count 查询也带上了标签谓词
    assert len(page.items) == 2                # 当前页仍按 limit 截断
    assert [item.code for item in page.items] == ["P1", "P2"]

    last = _list_assets(session, tags=["命中"], limit=2, offset=4)
    assert last.total == 6
    assert [item.code for item in last.items] == ["P4", "P5"]


def test_list_assets_tags_overlay_with_keyword_and_state(session: Session) -> None:
    """与关键词 / 发布状态叠加：跨筛选类型 AND、标签内部 OR。"""
    _add_version(db=session, id="o1", code="O1", tags=["现场"], name="甲模型", is_published=True)
    _add_version(db=session, id="o2", code="O2", tags=["对拍"], name="甲模型", is_published=True)
    _add_version(db=session, id="o3", code="O3", tags=["现场"], name="乙模型", is_published=True)
    _add_version(db=session, id="o4", code="O4", tags=["现场"], name="甲模型", is_published=False)
    session.commit()

    # 标签(现场 OR 对拍) AND 关键词"甲模型" AND 已发布 → O1, O2
    result = _list_assets(
        session, tags=["现场", "对拍"], keyword="甲模型", is_published=True,
    )
    assert {item.code for item in result.items} == {"O1", "O2"}
    assert result.total == 2


def test_list_assets_tags_normalization(session: Session) -> None:
    """空白 / 重复标签归一化后等价于单个标签，且不静默裁剪。"""
    _seed_flat_versions(session)

    result = _list_assets(session, tags=[" 现场 ", "", "现场", " 基准 "])
    assert {item.code for item in result.items} == {"A1", "A5"}
    assert result.total == 2


def test_list_assets_tags_no_match_returns_empty(session: Session) -> None:
    _seed_flat_versions(session)

    result = _list_assets(session, tags=["不存在的标签"])
    assert result.items == []
    assert result.total == 0


# ─────────────────────── /atp/models：按展示版本过滤 ───────────────────────

def _seed_model_groups(session: Session) -> None:
    """三个模型组；G-A 有两版本，展示版本(active)标签为「新标签」，旧版本为「旧标签」。

    groups 通过五维组合区分：110/guxing、220/fanji、500/jiubei。
    """
    # G-A：v1 旧标签（非 active）、v2 新标签（active → 展示版本）
    _add_version(session, id="ga1", code="GA-v1", tags=["旧标签"], version="v1",
                 voltage_level="110", tower_type="guxing", is_active=False, is_published=True)
    _add_version(session, id="ga2", code="GA-v2", tags=["新标签"], version="v2",
                 voltage_level="110", tower_type="guxing", is_active=True, is_published=True)
    # G-B：单版本，含两个标签
    _add_version(session, id="gb1", code="GB-v1", tags=["现场", "基准"], version="v1",
                 voltage_level="220", tower_type="fanji")
    # G-C：单版本，无标签
    _add_version(session, id="gc1", code="GC-v1", tags=[], version="v1",
                 voltage_level="500", tower_type="jiubei")
    session.commit()


def _codes(resp) -> set[str]:
    return {item.code for item in resp.items}


def test_list_models_tags_use_display_version(session: Session) -> None:
    """口径自洽：卡片展示的是展示版本标签，筛选也必须只看展示版本。"""
    _seed_model_groups(session)

    # 展示版本 GA-v2 的标签是「新标签」
    assert _codes(_list_models(session, tags=["新标签"])) == {"GA-v2"}
    # 「旧标签」只挂在非展示版本 GA-v1 上 → /models 不应按它筛出该模型
    assert _codes(_list_models(session, tags=["旧标签"])) == set()


def test_list_models_tags_or_matching(session: Session) -> None:
    _seed_model_groups(session)

    result = _list_models(session, tags=["新标签", "现场"])
    assert _codes(result) == {"GA-v2", "GB-v1"}
    assert result.total == 2


def test_list_models_no_tags_means_no_filter(session: Session) -> None:
    _seed_model_groups(session)

    result = _list_models(session, tags=None)
    # 3 个模型组各一行（版本 4 → 模型 3）
    assert result.total == 3
    assert _codes(result) == {"GA-v2", "GB-v1", "GC-v1"}


def test_list_models_tags_total_and_pagination(session: Session) -> None:
    """过滤在分页前对全量分组生效，total 与切片都正确。"""
    for index in range(5):
        _add_version(session, id=f"m{index}", code=f"M{index}-v1", tags=["命中"],
                     voltage_level=f"v{index}", tower_type="t{index}", version="v1")
    _add_version(session, id="mn", code="MN-v1", tags=[], voltage_level="vn", tower_type="tn")
    session.commit()

    page = _list_models(session, tags=["命中"], limit=2, offset=1)
    assert page.total == 5
    assert len(page.items) == 2

    assert _list_models(session, tags=["不存在"]).total == 0
    assert _list_models(session, tags=["不存在"]).items == []


# ─────────────────────── 标签候选聚合 ───────────────────────

def test_tag_options_dedup_sorted_and_only_used(session: Session) -> None:
    _add_version(session, id="t1", code="T1", tags=["现场", "基准", " 现场 "])
    _add_version(session, id="t2", code="T2", tags=["对拍", "基准", "Base", "base"])
    _add_version(session, id="t3", code="T3", tags=[])
    _add_version(session, id="t4", code="T4", tags=None)
    _add_version(session, id="t5", code="T5", tags=["", "   "])
    session.commit()

    result = svc.list_tag_options(session)

    # 去空白 + 丢空 + 大小写不敏感去重（保留首次写法）+ 排序；未使用过的标签不出现
    assert result.items == sorted(["现场", "基准", "对拍", "Base"])
    assert result.total == len(result.items)
    assert "从未用过" not in result.items


def test_tag_options_empty(session: Session) -> None:
    _add_version(session, id="e1", code="E1", tags=[])
    session.commit()

    result = svc.list_tag_options(session)
    assert result.items == []
    assert result.total == 0


# ─────────────────────── 方言兼容（SQLite / MySQL / PostgreSQL） ───────────────────────

def _compile(predicate, dialect) -> str:
    stmt = select(func.count()).select_from(AtpAssetVersion).where(predicate)
    return str(stmt.compile(dialect=dialect)).lower()


def test_list_assets_dispatches_dialect_to_predicate(session: Session, monkeypatch) -> None:
    """确认 list_assets 把当前方言名与归一化后的标签透传给谓词（SQL 下推的接线）。"""
    _seed_flat_versions(session)
    captured: dict = {}
    original = svc._tag_match_predicate

    def spy(tags, dialect_name):
        captured["tags"] = tags
        captured["dialect"] = dialect_name
        return original(tags, dialect_name)

    monkeypatch.setattr(svc, "_tag_match_predicate", spy)
    _list_assets(session, tags=[" 现场 ", "现场"])
    assert captured["tags"] == ["现场"]     # 已归一化去重
    assert captured["dialect"] == "sqlite"  # 测试内存库方言


def test_tag_predicate_sqlite_executes_and_uses_json_each(session: Session) -> None:
    """SQLite：json_each EXISTS 端到端执行，结果与 SQL 语义一致（两方言口径统一）。"""
    _seed_flat_versions(session)
    pred = svc._tag_match_predicate(["现场", "对拍"], "sqlite")
    assert "json_each" in _compile(pred, sqlite_dialect.dialect())
    assert "json_contains" not in _compile(pred, sqlite_dialect.dialect())

    ids = session.scalars(
        select(AtpAssetVersion.id).select_from(AtpAssetVersion).where(pred)
    ).all()
    assert set(ids) == {"a1", "a2", "a5"}


def test_tag_predicate_mysql_uses_json_contains() -> None:
    """MySQL：JSON_CONTAINS(col, '"tag"')=1 以 OR 连接，每个标签一个 JSON 标量参数。

    单测库是 SQLite（无 MySQL 服务），这里以「方言编译产物」验证 MySQL 分支成立：
    生成合法 MySQL 语法且携带正确编码的 JSON 标量，语义与 SQLite 分支同为精确 OR 命中。
    """
    tags = ["现场", "对拍", '带"引号']
    pred = svc._tag_match_predicate(tags, "mysql")
    compiled = select(func.count()).select_from(AtpAssetVersion).where(pred)
    compiled_obj = compiled.compile(dialect=mysql.dialect())
    rendered = str(compiled_obj).lower()
    assert "json_contains" in rendered
    assert "json_each" not in rendered
    assert rendered.count("json_contains") == len(tags)  # 每标签一个 OR 项

    # 每个第二参都必须是合法的 JSON 字符串标量（含引号/中文转义）
    str_params = [v for v in compiled_obj.params.values() if isinstance(v, str)]
    for tag in tags:
        encoded = json.dumps(tag, ensure_ascii=False)
        assert encoded in str_params
        assert json.loads(encoded) == tag


def test_tag_predicate_postgresql_uses_json_array_elements_text() -> None:
    pred = svc._tag_match_predicate(["现场"], "postgresql")
    rendered = _compile(pred, postgresql.dialect())
    assert "json_array_elements_text" in rendered
    assert "json_contains" not in rendered


def test_tag_predicate_normalization_empty_is_noop(session: Session) -> None:
    """归一化后为空标签列表不应被下推（等价于不过滤），避免 IN () 之类非法 SQL。"""
    _seed_flat_versions(session)
    assert svc._normalize_tag_filter(None) == []
    assert svc._normalize_tag_filter(["", "  ", "  "]) == []
    # 传空标签到 list_assets 与不传等价
    assert _list_assets(session, tags=["", "  "]).total == _list_assets(session, tags=None).total


# ─────────────────────── 端点层：query 参数解析 + 聚合接口 ───────────────────────

def _build_client(session: Session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.atp_assets import router
    from app.core.database import get_db
    from app.core.dependencies import CurrentUser, get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user=User(
            id="tester", email="tester@example.com", username="tester",
            password_hash="x", status="ENABLED",
        ),
        role_codes=set(),
        permission_codes={"atp.read"},
    )
    return TestClient(app)


def test_endpoints_tags_query_param_and_options(session: Session) -> None:
    """TestClient 验证 list[str] 多选 query 参数解析（tags=a&tags=b）与 OR 结果。"""
    _seed_flat_versions(session)
    client = _build_client(session)

    # /models：聚合口径，命中任一标签
    r_models = client.get("/api/v1/atp/models", params=[("tags", "现场"), ("tags", "对拍")])
    assert r_models.status_code == 200, r_models.text
    models_payload = r_models.json()
    assert {item["code"] for item in models_payload["items"]} >= {"A1", "A2", "A5"}
    assert models_payload["total"] >= 3

    # /assets：版本口径，命中任一标签
    r_assets = client.get("/api/v1/atp/assets", params=[("tags", "现场"), ("tags", "对拍")])
    assert r_assets.status_code == 200, r_assets.text
    assert {item["code"] for item in r_assets.json()["items"]} == {"A1", "A2", "A5"}

    # 未命中 → 空结果
    r_empty = client.get("/api/v1/atp/assets", params=[("tags", "不存在")])
    assert r_empty.status_code == 200
    assert r_empty.json()["total"] == 0

    # 标签候选聚合接口
    r_opts = client.get("/api/v1/atp/models/tags")
    assert r_opts.status_code == 200, r_opts.text
    opts = r_opts.json()
    assert set(opts["items"]) == {"现场", "基准", "对拍"}
    assert opts["total"] == len(opts["items"])
