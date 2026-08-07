from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.lightning_distribution import LightningDistribution
from app.services import lightning_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[LightningDistribution.__table__],
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return testing_session()


def _add_distribution(
    session: Session,
    *,
    source_file_name: str = "flashes.csv",
    region_id: str = "HB",
    status: str = "completed",
) -> LightningDistribution:
    dist = LightningDistribution(
        source_file_name=source_file_name,
        source_object_key="lightning/distribution/source/abc_flashes.csv",
        region_id=region_id,
        status=status,
        stage="parsing",
        progress=0,
        valid_count=10,
    )
    session.add(dist)
    session.flush()
    return dist


def test_delete_distribution_removes_record(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        dist = _add_distribution(session)
        session.commit()

        result = lightning_service.delete_lightning_distribution(session, dist.id)

        assert result == {"success": True}
        remaining = session.execute(
            select(LightningDistribution).where(LightningDistribution.id == dist.id)
        ).scalar_one_or_none()
        assert remaining is None
    finally:
        session.close()


def test_delete_missing_returns_success_false() -> None:
    session = _build_session()
    try:
        result = lightning_service.delete_lightning_distribution(session, "nonexistent")
        assert result == {"success": False}
    finally:
        session.close()


def test_serialize_distribution_record() -> None:
    session = _build_session()
    try:
        dist = _add_distribution(session, status="completed")
        dist.overall_ng = 1.5
        dist.positive_count = 8
        dist.negative_count = 2
        dist.image_object_key = "lightning/distribution/image/x.png"
        dist.lp_draw_task_id = "ab9f-task-id"
        session.commit()

        record = lightning_service._serialize_distribution(dist)

        assert record.id == dist.id
        assert record.source_file_name == "flashes.csv"
        assert record.source_object_key == "lightning/distribution/source/abc_flashes.csv"
        assert record.status == "completed"
        assert record.stage == "parsing"
        assert record.has_image is True
        assert record.overall_ng == 1.5
        assert record.positive_count == 8
        assert record.negative_count == 2
        assert record.lp_draw_task_id == "ab9f-task-id"
    finally:
        session.close()


def test_serialize_distribution_strips_historical_grid_cells() -> None:
    """列表序列化兜底剥离 stats_json 中的 grid_cells（防历史数据/再次引入）。"""
    session = _build_session()
    try:
        dist = _add_distribution(session, status="completed")
        dist.overall_ng = 2.0
        dist.stats_json = {
            "total_records": 100,
            "area_km2": 25.0,
            "overall_ng": 2.0,
            "grid_cells": [{"grid_x": 0, "grid_y": 0, "strike_count": 99}],
        }
        session.commit()

        record = lightning_service._serialize_distribution(dist)

        assert record.stats_json is not None
        assert "grid_cells" not in record.stats_json
        assert record.stats_json["total_records"] == 100
        assert record.stats_json["overall_ng"] == 2.0
    finally:
        session.close()
