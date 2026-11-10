"""ATP 模型标签（2026-11-10）单测。

背景：模型卡片左下角原来挂的是「新版/旧版」形态说明，现改为展示发布时打的标签。
标签必须支持多个、可重复发布改写、PATCH 也能维护，且脏输入（空白/重复/超长/超量）
不能落库。本文件锁住这几条语义。
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRun
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.schemas.atp_asset import AtpAssetUpdateRequest
from app.services import atp_asset_service


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            FileStorageBackend.__table__,
            FileStorageMount.__table__,
            FileIndexEntry.__table__,
            User.__table__,
            DimensionType.__table__,
            DimensionItem.__table__,
            AtpAsset.__table__,
            AtpAssetRun.__table__,
        ],
    )
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _make_asset(db: Session, **overrides) -> AtpAsset:
    payload = {
        "id": "asset-1",
        "code": "atp-test-1",
        "name": "110kV 鼓型塔",
        "description": "单测用",
        "status": "enabled",
        "voltage_level": "110",
        "tower_type": "guxing",
        "scene_type": "normal",
        "arrester_config": "none",
        "version": "v1",
        "is_published": False,
        "shield_wire": "with",
        "tags_json": [],
    }
    payload.update(overrides)
    asset = AtpAsset(**payload)
    db.add(asset)
    db.commit()
    return asset


def test_normalize_tags_drops_blank_dup_and_overflow() -> None:
    normalized = atp_asset_service._normalize_tags([" 现场实测 ", "现场实测", "Base", "", "  ", "base"])
    # 去空白 + 去重（大小写不敏感，保留首次出现的写法）
    assert normalized == ["现场实测", "Base"]

    many = atp_asset_service._normalize_tags([f"t{i}" for i in range(12)])
    assert len(many) == 8

    long_tag = atp_asset_service._normalize_tags(["x" * 40])
    assert len(long_tag[0]) == 32

    assert atp_asset_service._normalize_tags(None) == []


def test_publish_writes_multiple_tags(session: Session) -> None:
    _make_asset(session)

    summary = atp_asset_service.publish_asset(
        session,
        asset_id="asset-1",
        release_notes="  修正横担坡度  ",
        tags=["基准", "已对拍", "基准"],
    )

    assert summary.tags == ["基准", "已对拍"]
    assert summary.release_notes == "修正横担坡度"
    assert summary.is_published is True


def test_publish_without_tags_keeps_existing(session: Session) -> None:
    _make_asset(session, tags_json=["基准"])
    atp_asset_service.publish_asset(session, asset_id="asset-1")

    # 不传 tags = 保留原标签（兼容旧客户端的 body），而不是清空
    assert atp_asset_service.get_asset_by_id(session, "asset-1").tags_json == ["基准"]


def test_publish_with_empty_list_clears_tags(session: Session) -> None:
    _make_asset(session, tags_json=["基准"])
    atp_asset_service.publish_asset(session, asset_id="asset-1", tags=[])

    assert atp_asset_service.get_asset_by_id(session, "asset-1").tags_json == []


def test_update_asset_can_replace_tags(session: Session) -> None:
    _make_asset(session, tags_json=["旧标签"], is_published=True)

    updated = atp_asset_service.update_asset(
        session,
        "asset-1",
        AtpAssetUpdateRequest(tags=["现场实测", "待复核"]),
        actor_user_id="user-1",
    )

    assert updated is not None
    assert updated.tags == ["现场实测", "待复核"]


def test_update_asset_omitted_tags_untouched(session: Session) -> None:
    _make_asset(session, tags_json=["基准"])

    updated = atp_asset_service.update_asset(
        session,
        "asset-1",
        AtpAssetUpdateRequest(name="改个名字"),
        actor_user_id="user-1",
    )

    assert updated is not None
    assert updated.tags == ["基准"]
