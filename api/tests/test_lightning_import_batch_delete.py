from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.lightning_distribution import LightningDistributionPoint
from app.models.lightning_event import LightningCurrentEvent
from app.models.lightning_import_batch import LightningImportBatch
from app.services import lightning_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            LightningDistributionPoint.__table__,
            LightningCurrentEvent.__table__,
            LightningImportBatch.__table__,
        ],
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return testing_session()


def _add_distribution_points(
    session: Session,
    import_time: datetime,
    *,
    count: int,
    source_file_name: str = "flashes.csv",
    region_id: str = "HB",
    location_tag: str | None = None,
    city: str | None = None,
    event_prefix: str = "",
) -> list[str]:
    ids: list[str] = []
    for i in range(count):
        point = LightningDistributionPoint(
            event_id=f"dist-{event_prefix}{source_file_name}-{i}",
            source_file_name=source_file_name,
            event_time=import_time,
            peak_current_ka=float(i),
            peak_abs_current_ka=float(i),
            polarity="negative",
            region_id=region_id,
            location_tag=location_tag,
            city=city,
            longitude=120.0,
            latitude=30.0,
            create_date=import_time,
        )
        session.add(point)
        ids.append(point.id)
    session.flush()
    return ids


def _add_waveform_events(
    session: Session,
    import_time: datetime,
    *,
    count: int,
    source_file_name: str = "wave.csv",
    region_id: str = "HB",
    location_tag: str | None = None,
    city: str | None = None,
) -> list[str]:
    ids: list[str] = []
    for i in range(count):
        event = LightningCurrentEvent(
            event_id=f"wave-{source_file_name}-{i}",
            source_file_name=source_file_name,
            event_time=import_time,
            peak_current_ka=float(i),
            peak_abs_current_ka=float(i),
            polarity="negative",
            sample_count=1,
            stroke_count=1,
            stroke_peaks_json=[],
            region_id=region_id,
            location_tag=location_tag,
            city=city,
            longitude=120.0,
            latitude=30.0,
            create_date=import_time,
        )
        session.add(event)
        ids.append(event.id)
    session.flush()
    return ids


def test_delete_distribution_batch_deletes_points_and_batch_record(monkeypatch) -> None:
    import_time = datetime(2026, 7, 30, 8, 0, 0)
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)

        # One import-batch record + 3 matching distribution points
        session.add(
            LightningImportBatch(
                source_file_name="flashes.csv",
                import_type="distribution",
                status="completed",
                region_id="HB",
                create_date=import_time,
            )
        )
        _add_distribution_points(session, import_time, count=3, source_file_name="flashes.csv", region_id="HB")
        session.commit()

        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="flashes.csv",
            import_time=import_time,
            region_id="HB",
            location_tag=None,
            city=None,
            import_type="distribution",
        )

        assert result == {"success": True, "deleted_count": 4}
        remaining = session.execute(
            select(LightningDistributionPoint).where(
                LightningDistributionPoint.source_file_name == "flashes.csv"
            )
        ).scalars().all()
        assert remaining == []
        assert session.execute(select(func.count()).select_from(LightningImportBatch)).scalar_one() == 0
    finally:
        session.close()


def test_delete_import_type_filters_respect_waveform_and_distribution(monkeypatch) -> None:
    import_time = datetime(2026, 7, 30, 8, 0, 0)
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)

        _add_distribution_points(session, import_time, count=2, source_file_name="flashes.csv")
        _add_waveform_events(session, import_time, count=2, source_file_name="wave.csv")
        session.commit()

        # distribution 只删地闪分布，不动波形事件
        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="flashes.csv",
            import_time=import_time,
            region_id="HB",
            location_tag=None,
            city=None,
            import_type="distribution",
        )
        assert result == {"success": True, "deleted_count": 2}
        assert session.execute(
            select(func.count()).select_from(LightningDistributionPoint)
        ).scalar_one() == 0
        assert session.execute(
            select(func.count()).select_from(LightningCurrentEvent)
        ).scalar_one() == 2

        # waveform 只删波形事件
        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="wave.csv",
            import_time=import_time,
            region_id="HB",
            location_tag=None,
            city=None,
            import_type="waveform",
        )
        assert result == {"success": True, "deleted_count": 2}
        assert session.execute(
            select(func.count()).select_from(LightningCurrentEvent)
        ).scalar_one() == 0
    finally:
        session.close()


def test_delete_chunked_batches_accumulate_count(monkeypatch) -> None:
    import_time = datetime(2026, 7, 30, 8, 0, 0)
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        # 缩小分块，触发多轮批量删除，验证分块循环与计数
        monkeypatch.setattr(lightning_service, "DELETE_CHUNK_SIZE", 10)

        _add_distribution_points(session, import_time, count=25, source_file_name="flashes.csv")
        session.commit()

        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="flashes.csv",
            import_time=import_time,
            region_id="HB",
            location_tag=None,
            city=None,
            import_type="distribution",
        )

        assert result == {"success": True, "deleted_count": 25}
        assert session.execute(
            select(func.count()).select_from(LightningDistributionPoint)
        ).scalar_one() == 0
    finally:
        session.close()


def test_delete_no_match_returns_success_false(monkeypatch) -> None:
    import_time = datetime(2026, 7, 30, 8, 0, 0)
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)

        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="missing.csv",
            import_time=import_time,
            region_id="HB",
            location_tag=None,
            city=None,
            import_type="distribution",
        )

        assert result == {"success": False, "deleted_count": 0}
    finally:
        session.close()


def test_delete_region_none_matches_null_and_empty_string(monkeypatch) -> None:
    import_time = datetime(2026, 7, 30, 8, 0, 0)
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)

        # 同批 source_file_name，一部分 region 为 NULL、一部分为 ""
        _add_distribution_points(session, import_time, count=2, source_file_name="flashes.csv", region_id=None, event_prefix="a-")
        _add_distribution_points(session, import_time, count=1, source_file_name="flashes.csv", region_id="", event_prefix="b-")
        session.commit()

        result = lightning_service.delete_lightning_import_batch(
            session,
            source_file_name="flashes.csv",
            import_time=import_time,
            region_id=None,
            location_tag=None,
            city=None,
            import_type="distribution",
        )

        assert result == {"success": True, "deleted_count": 3}
        assert session.execute(
            select(func.count()).select_from(LightningDistributionPoint)
        ).scalar_one() == 0
    finally:
        session.close()
