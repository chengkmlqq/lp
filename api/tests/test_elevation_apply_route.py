from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.elevation import ElevationApplyJob, ElevationFileRecord
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.models.user import User
from app.services import elevation_service
from app.api.v1.elevation import router as elevation_router


def _build_app(session_factory, *, permission_codes: set[str] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(elevation_router, prefix="/api/v1")

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
        permission_codes=permission_codes or {"elevation.manage"},
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
            ElevationFileRecord.__table__,
            ElevationApplyJob.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_apply_line_route_wires_to_create_apply_job(monkeypatch) -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line = Line(code="L-ROUTE-001", name="路由接线线路", voltage_kv=220, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line, record])
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0))
        session.commit()

        dispatched: dict[str, str | None] = {}

        def _fake_dispatch(*, job_id: str, actor_user_id: str | None):
            dispatched["job_id"] = job_id
            dispatched["actor_user_id"] = actor_user_id
            return __import__("types").SimpleNamespace(id="celery-route-task")

        monkeypatch.setattr(elevation_service, "_dispatch_elevation_apply_task", _fake_dispatch)
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": line.id, "file_record_id": record.id, "mode": "overwrite_all"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["queued"] is True
        assert body["job"]["line_id"] == line.id
        assert body["job"]["file_record_id"] == record.id
        assert body["job"]["status"] == "pending"

        saved = session.get(ElevationApplyJob, body["job"]["id"])
        assert saved is not None
        assert saved.task_id == "celery-route-task"
        assert dispatched == {"job_id": body["job"]["id"], "actor_user_id": "tester"}
    finally:
        session.close()


def test_apply_line_route_forbidden_without_elevation_manage() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        client = _build_app(session_factory, permission_codes={"elevation.read"})
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": "missing", "mode": "fill_null_only"},
        )
        assert response.status_code == 403
    finally:
        session.close()


def test_apply_line_route_rejects_unknown_line() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add(record)
        session.commit()

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": "no-such-line", "file_record_id": record.id, "mode": "fill_null_only"},
        )
        assert response.status_code == 404
    finally:
        session.close()


def test_upload_csv_rejected_with_400(monkeypatch) -> None:
    session_factory = _build_session_factory()
    try:
        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/records",
            files={"file": ("record.csv", b"lon,lat,altitude_m\n120,30,100\n", "text/csv")},
            data={},
        )
        assert response.status_code == 400
        assert "不支持的文件格式" in response.json()["detail"]
    finally:
        session_factory().close()


def test_zip_with_csv_skipped_creates_no_csv_record(monkeypatch) -> None:
    import io
    import zipfile

    from app.schemas.elevation import ElevationFileRecordCreateRequest
    from app.services.elevation_file_record_service import _create_file_records_from_zip

    session_factory = _build_session_factory()
    session = session_factory()
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("data.csv", "lon,lat,altitude_m\n120,30,100\n")
            archive.writestr("terrain.tif", b"fake-tif-content")
        zip_buffer.seek(0)

        # Mock the driver so the tif-in-zip storage path never actually writes
        fake_driver = type(
            "FakeDriver",
            (),
            {
                "ensure_directory": lambda self, path: None,
                "write_file": lambda self, path, content, content_type=None: None,
            },
        )()

        result = _create_file_records_from_zip(
            db=session,
            zip_content=zip_buffer.getvalue(),
            zip_filename="archive.zip",
            payload=ElevationFileRecordCreateRequest(),
            mount_code="default",
            driver=fake_driver,
            actor=User(id="tester"),
        )

        # The .tif member should be imported, the .csv member skipped
        records = session.query(ElevationFileRecord).all()
        assert len(records) == 1
        assert records[0].file_name == "terrain.tif"
        assert records[0].file_format == "tif"
        assert result.detail.startswith("ZIP 文件已解压：成功创建 1 个文件记录")
    finally:
        session.close()
