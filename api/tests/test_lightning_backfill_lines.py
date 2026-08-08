from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.lightning_amplitude import LightningAmplitude
from app.models.line import Line
from app.models.line_amplitude_backfill import LineAmplitudeBackfill
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.models.user import User
from app.api.v1.lightning import router as lightning_router
from app.services import lightning_service


def _build_app(session_factory, *, permission_codes: set[str] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(lightning_router, prefix="/api/v1")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    current_user = CurrentUser(
        user=User(
            id="tester",
            email="tester@example.com",
            username="tester",
            password_hash="secret",
            status="ENABLED",
        ),
        role_codes=set(),
        permission_codes=permission_codes or {"lightning.manage"},
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _build_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Line.__table__,
            LineTower.__table__,
            TowerProfile.__table__,
            TowerCircuit.__table__,
            TowerLightningResult.__table__,
            TowerAnalysis.__table__,
            LightningAmplitude.__table__,
            LineAmplitudeBackfill.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _add_line(session, *, code: str = "L-A", name: str = "线路A", voltage_kv: int = 220) -> Line:
    line = Line(code=code, name=name, voltage_kv=voltage_kv, lightning_param_json={})
    session.add(line)
    session.flush()
    return line


def _add_amplitude(session, *, event_id: str = "LC-1", status: str = "completed") -> LightningAmplitude:
    amp = LightningAmplitude(
        event_id=event_id,
        source_file_name="wave.csv",
        source_object_key="lightning/amplitude/source/wave.csv",
        status=status,
        progress=100 if status == "completed" else 0,
        sample_count=3,
        peak_abs_current_ka=10.5,
        polarity="positive",
    )
    session.add(amp)
    session.flush()
    return amp


def test_backfill_lines_endpoint_returns_linked_lines() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = _add_line(session, code="L-A", name="线路A", voltage_kv=220)
        line_b = _add_line(session, code="L-B", name="线路B", voltage_kv=110)
        amp = _add_amplitude(session, event_id="LC-1")
        session.add_all(
            [
                LineAmplitudeBackfill(
                    line_id=line_a.id,
                    amplitude_id=amp.id,
                    prepared_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    current_a=18.5,
                    current_b=2.6,
                    peak_max=20.0,
                    peak_min=15.0,
                    sampled_event_count=10,
                    prepared_by_user_id="tester",
                ),
                LineAmplitudeBackfill(
                    line_id=line_b.id,
                    amplitude_id=amp.id,
                    prepared_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
                    current_a=18.5,
                    current_b=2.6,
                    peak_max=20.0,
                    peak_min=15.0,
                    sampled_event_count=10,
                    prepared_by_user_id="tester",
                ),
            ]
        )
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/lightning-currents/amplitudes/{amp.id}/backfill-lines")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        # 按 prepared_at 倒序：line_b（2025-02-01）在前
        assert body["items"][0]["line_id"] == line_b.id
        assert body["items"][0]["line_code"] == "L-B"
        assert body["items"][0]["line_name"] == "线路B"
        assert body["items"][0]["voltage_kv"] == 110
        assert body["items"][0]["current_a"] == 18.5
        assert body["items"][1]["line_id"] == line_a.id
    finally:
        session.close()


def test_backfill_lines_endpoint_404_for_missing_amplitude() -> None:
    session_factory = _build_session_factory()
    try:
        client = _build_app(session_factory)
        response = client.get("/api/v1/lightning-currents/amplitudes/nope/backfill-lines")
        assert response.status_code == 404
    finally:
        session_factory().close()


def test_backfill_lines_endpoint_empty_when_no_rows() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        amp = _add_amplitude(session, event_id="LC-EMPTY")
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/lightning-currents/amplitudes/{amp.id}/backfill-lines")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []
    finally:
        session.close()


def test_list_amplitudes_includes_backfill_line_count() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = _add_line(session, code="L-A", name="线路A")
        line_b = _add_line(session, code="L-B", name="线路B")
        amp = _add_amplitude(session, event_id="LC-COUNT")
        amp2 = _add_amplitude(session, event_id="LC-COUNT-2")
        session.add_all(
            [
                LineAmplitudeBackfill(line_id=line_a.id, amplitude_id=amp.id),
                LineAmplitudeBackfill(line_id=line_b.id, amplitude_id=amp.id),
            ]
        )
        session.commit()

        result = lightning_service.list_lightning_amplitudes(session, limit=50, offset=0)
        by_id = {item.id: item for item in result.items}
        assert by_id[amp.id].backfill_line_count == 2
        assert by_id[amp2.id].backfill_line_count == 0
    finally:
        session.close()


def test_serialize_line_tower_includes_lightning_current_preparation() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line = _add_line(session, code="L-A", name="线路A")
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N1", longitude=120.0, latitude=30.0)
        session.add(tower)
        session.flush()
        profile = TowerProfile(
            tower_id=tower.id,
            current_a=18.5,
            current_b=2.6,
            current_type="line_prepared",
            extra_profile_json={
                "lightning_current_preparation": {
                    "line_id": line.id,
                    "line_code": line.code,
                    "current_a": 18.5,
                    "current_b": 2.6,
                    "peak_max": 20.0,
                    "peak_min": 15.0,
                    "sampled_event_count": 10,
                    "region_id": "HB",
                    "is_synthetic": False,
                    "prepared_at": "2025-01-01T00:00:00+00:00",
                }
            },
        )
        session.add(profile)
        session.commit()

        from app.services.line_service import serialize_line_tower

        summary = serialize_line_tower(tower)
        assert summary.current_a == 18.5
        assert summary.current_type == "line_prepared"
        assert summary.lightning_current_preparation is not None
        assert summary.lightning_current_preparation.peak_max == 20.0
        assert summary.lightning_current_preparation.sampled_event_count == 10
        assert summary.lightning_current_preparation.prepared_at == "2025-01-01T00:00:00+00:00"
    finally:
        session.close()


def test_serialize_line_tower_no_profile_no_prep() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line = _add_line(session, code="L-A", name="线路A")
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N1")
        session.add(tower)
        session.commit()

        from app.services.line_service import serialize_line_tower

        summary = serialize_line_tower(tower)
        assert summary.current_a is None
        assert summary.current_type is None
        assert summary.lightning_current_preparation is None
    finally:
        session.close()
