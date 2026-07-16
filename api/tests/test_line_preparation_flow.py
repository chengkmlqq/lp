from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fl_analysis import FlAnalysisJob
from app.models.lightning_event import LightningCurrentEvent
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.schemas.lightning import LightningCurrentPreparationRequest
from app.services import elevation_service, fl_analysis_service, lightning_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Line.__table__,
            LineTower.__table__,
            TowerProfile.__table__,
            LightningCurrentEvent.__table__,
            FlAnalysisJob.__table__,
        ],
    )
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return testing_session()


def test_prepare_line_lightning_current_backfills_profiles_and_line_state(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(code="L-001", name="示例线路", voltage_kv=220, lightning_param_json={})
        session.add(line)
        session.flush()

        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="N1", longitude=120.0, latitude=30.0),
                LineTower(line_id=line.id, seq_no=2, tower_no="N2", longitude=120.001, latitude=30.001),
            ]
        )
        session.add_all(
            [
                LightningCurrentEvent(
                    event_id="LC-001",
                    peak_abs_current_ka=18.0,
                    peak_current_ka=18.0,
                    polarity="negative",
                    sample_count=1,
                    stroke_count=1,
                    stroke_peaks_json=[],
                    region_id="HB",
                ),
                LightningCurrentEvent(
                    event_id="LC-002",
                    peak_abs_current_ka=32.0,
                    peak_current_ka=32.0,
                    polarity="negative",
                    sample_count=1,
                    stroke_count=1,
                    stroke_peaks_json=[],
                    region_id="HB",
                ),
                LightningCurrentEvent(
                    event_id="LC-003",
                    peak_abs_current_ka=46.0,
                    peak_current_ka=46.0,
                    polarity="negative",
                    sample_count=1,
                    stroke_count=1,
                    stroke_peaks_json=[],
                    region_id="HB",
                ),
            ]
        )
        session.commit()

        response = lightning_service.prepare_line_lightning_current(
            session,
            LightningCurrentPreparationRequest(line_id=line.id, region_id="HB"),
            actor_user_id="tester",
        )

        profiles = session.execute(select(TowerProfile).order_by(TowerProfile.tower_id.asc())).scalars().all()
        assert len(profiles) == 2
        assert all(profile.current_a == response.current_a for profile in profiles)
        assert all(profile.current_b == response.current_b for profile in profiles)
        assert response.created_profile_count == 2
        assert response.line.preparation_json["lightning_current"]["ready"] is True
        assert session.get(Line, line.id).lightning_param_json["雷电流幅值a"] == response.current_a
        assert session.get(Line, line.id).lightning_param_json["雷电流幅值b"] == response.current_b
    finally:
        session.close()


def test_fl_analysis_create_job_rejects_unprepared_line(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)

        line = Line(code="L-002", name="待分析线路", voltage_kv=500, lightning_param_json={})
        session.add(line)
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0))
        session.commit()

        with pytest.raises(HTTPException) as captured:
            fl_analysis_service.create_job(
                session,
                FlAnalysisJobCreateRequest(line_id=line.id, job_type="normal"),
                actor=SimpleNamespace(id="tester"),
            )

        assert captured.value.status_code == 400
        assert "雷电流幅值" in str(captured.value.detail)
        assert "地闪密度" in str(captured.value.detail)
        assert "地面倾角" in str(captured.value.detail)
    finally:
        session.close()


def test_apply_points_to_line_towers_computes_ground_slopes() -> None:
    session = _build_session()
    try:
        line = Line(code="L-003", name="高程线路", voltage_kv=110, lightning_param_json={})
        session.add(line)
        session.flush()

        meter_to_lat = 1 / 111_320.0
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="P1", longitude=120.0, latitude=30.0 + 300 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=2, tower_no="P2", longitude=120.0, latitude=30.0 + 600 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=3, tower_no="P3", longitude=120.0, latitude=30.0 + 900 * meter_to_lat),
            ]
        )
        session.commit()

        points = [
            elevation_service.ElevationSamplePoint(
                lon=120.0,
                lat=30.0 + distance_m * meter_to_lat,
                altitude_m=100.0 + distance_m * 0.12,
            )
            for distance_m in range(0, 1251, 50)
        ]

        stats = elevation_service._apply_points_to_line_towers(
            session,
            line_id=line.id,
            elevation_source=SimpleNamespace(id="ds-1", code="DEM-001"),
            mode="overwrite_all",
            points=points,
        )

        towers = session.execute(select(LineTower).where(LineTower.line_id == line.id).order_by(LineTower.seq_no.asc())).scalars().all()
        assert stats["updated_tower_count"] == 3
        assert all(tower.altitude_m is not None for tower in towers)
        assert towers[1].slope_1 is not None
        assert towers[1].slope_2 is not None
    finally:
        session.close()
