"""overview_config_service 测试（可配置系统总览卡片布局）。"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401  # 触发全量模型注册（ForeignKey users 等）
from app.core.database import Base
from app.schemas.overview_config import OverviewConfigRequest, OverviewWidgetConfig
from app.services.overview_config_service import (
    default_widgets,
    get_overview_config,
    save_overview_config,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_default_config_when_no_row(db: Session):
    config = get_overview_config(db, user_id="u1")
    types = [w.type for w in config.widgets]
    assert types == ["asset_stats", "task_summary"]
    assert config.widgets[0].span == 24


def test_save_and_read_back(db: Session):
    request = OverviewConfigRequest(
        widgets=[
            OverviewWidgetConfig(type="asset_stats", span=12, props={"asset_keys": ["line", "atp_asset"]}),
            OverviewWidgetConfig(type="quick_links", span=8, props={"links": [{"label": "ATP模型", "href": "/admin/atp-models"}]}),
            OverviewWidgetConfig(type="task_states", span=6),
        ]
    )
    saved = save_overview_config(db, user_id="u1", payload=request)
    assert [w.type for w in saved.widgets] == ["asset_stats", "quick_links", "task_states"]

    loaded = get_overview_config(db, user_id="u1")
    assert loaded.widgets[0].props["asset_keys"] == ["line", "atp_asset"]
    assert loaded.widgets[1].props["links"] == [{"label": "ATP模型", "href": "/admin/atp-models"}]
    assert loaded.widgets[2].span == 6


def test_unknown_widget_type_dropped(db: Session):
    """DB 里若存在非法类型卡片（脏数据），读取时应被清洗丢弃。"""
    from app.models.user_overview_config import UserOverviewConfig

    db.add(
        UserOverviewConfig(
            user_id="u1",
            widgets_json='[{"type":"asset_stats","span":24,"props":{}},{"type":"not_a_real_type","span":8,"props":{}}]',
        )
    )
    db.commit()
    loaded = get_overview_config(db, user_id="u1")
    assert [w.type for w in loaded.widgets] == ["asset_stats"]


def test_invalid_asset_keys_sanitized(db: Session):
    request = OverviewConfigRequest(
        widgets=[
            OverviewWidgetConfig(
                type="asset_stats",
                span=24,
                props={"asset_keys": ["line", "bogus_key", 123]},
            )
        ]
    )
    saved = save_overview_config(db, user_id="u1", payload=request)
    keys = saved.widgets[0].props["asset_keys"]
    assert keys == ["line"]  # bogus 被清洗


def test_save_empty_falls_back_to_default(db: Session):
    request = OverviewConfigRequest(widgets=[])
    saved = save_overview_config(db, user_id="u1", payload=request)
    assert saved.widgets == default_widgets()


def test_per_user_isolation(db: Session):
    request = OverviewConfigRequest(widgets=[OverviewWidgetConfig(type="task_summary", span=12)])
    save_overview_config(db, user_id="u1", payload=request)
    # u2 无配置，仍是默认
    config_u2 = get_overview_config(db, user_id="u2")
    assert [w.type for w in config_u2.widgets] == ["asset_stats", "task_summary"]