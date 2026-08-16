from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_model import TowerModel
from app.models.tower_profile import TowerProfile
from app.models.user import User
from app.services import line_service, minio_storage
from app.api.v1.uploads import router as uploads_router


def _build_app(session_factory, *, permission_codes: set[str] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(uploads_router, prefix="/api/v1")

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
        permission_codes=permission_codes or {"tower.manage"},
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
            TowerModel.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_upload_temp_file_returns_temp_file_id(monkeypatch) -> None:
    session_factory = _build_session_factory()
    try:
        monkeypatch.setattr(
            minio_storage,
            "build_temp_key",
            lambda file_name, user_id: f"lightning/tmp/{user_id}/abc123_{file_name}",
        )
        monkeypatch.setattr(minio_storage, "put_object", lambda *args, **kwargs: "key")

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/uploads/temp",
            files={"file": ("towers.csv", b"a,b,c\n1,2,3\n", "text/csv")},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["temp_file_id"] == "lightning/tmp/tester/abc123_towers.csv"
        assert body["file_name"] == "towers.csv"
    finally:
        session_factory().close()


def test_upload_temp_file_rejects_oversized_file(monkeypatch) -> None:
    session_factory = _build_session_factory()
    try:
        from app.core.config import get_settings
        s = get_settings()
        orig = s.upload_max_file_size_mb
        s.upload_max_file_size_mb = 1

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/uploads/temp",
            files={"file": ("big.csv", b"x" * (2 * 1024 * 1024), "text/csv")},
        )
        assert response.status_code == 413
        s.upload_max_file_size_mb = orig
    finally:
        session_factory().close()


def test_upload_temp_file_requires_authentication(monkeypatch) -> None:
    session_factory = _build_session_factory()
    try:
        monkeypatch.setattr(
            minio_storage,
            "build_temp_key",
            lambda file_name, user_id: f"lightning/tmp/{user_id}/abc_{file_name}",
        )
        monkeypatch.setattr(minio_storage, "put_object", lambda *args, **kwargs: "key")

        client = _build_app(session_factory, permission_codes={"tower.read"})
        response = client.post(
            "/api/v1/uploads/temp",
            files={"file": ("towers.csv", b"a,b,c\n1,2,3\n", "text/csv")},
        )
        # 通用上传端点不要求具体业务权限，任意已登录用户即可使用。
        assert response.status_code == 200
    finally:
        session_factory().close()


def test_resolve_temp_file_reads_and_deletes(monkeypatch) -> None:
    from app.core.file_upload import resolve_temp_file

    temp_key = "lightning/tmp/tester/abc123_towers.csv"
    deleted: list[str] = []

    monkeypatch.setattr(minio_storage, "get_object", lambda key: b"a,b,c\n1,2,3\n")
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: deleted.append(key))

    content, file_name = resolve_temp_file(temp_key, "tester")
    assert content == b"a,b,c\n1,2,3\n"
    assert file_name == "towers.csv"
    assert deleted == [temp_key]


def test_resolve_temp_file_rejects_wrong_user(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.core.file_upload import resolve_temp_file

    with pytest.raises(HTTPException) as exc:
        resolve_temp_file("lightning/tmp/other-user/abc123_towers.csv", "tester")
    assert exc.value.status_code == 400


def test_import_line_towers_via_temp_file_id(monkeypatch) -> None:
    session = _build_session_factory()()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(code="PL-TEMP-001", name="临时导入线路", voltage_kv=220, status="enabled")
        session.add(line)
        session.commit()

        temp_key = "lightning/tmp/tester/abc123_towers.csv"
        csv_content = (
            "序号,塔号,经度,纬度,接地电阻,地闪密度,直线或耐张杆塔,杆塔模型\n"
            "1,T001,120.1,30.1,5,3.5,直线,ZM-001\n"
        ).encode("utf-8")

        monkeypatch.setattr(minio_storage, "get_object", lambda key: csv_content)
        monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)

        result = line_service.import_line_towers_from_csv(
            session,
            line=line,
            file=None,
            temp_file_id=temp_key,
            actor_user_id="tester",
        )

        assert result.imported_count == 1
        towers = session.execute(
            select(LineTower).where(LineTower.line_id == line.id)
        ).scalars().all()
        assert len(towers) == 1
        assert towers[0].tower_no == "T001"
    finally:
        session.close()


def test_import_line_towers_via_temp_file_id_missing_file(monkeypatch) -> None:
    from fastapi import HTTPException

    session = _build_session_factory()()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(code="PL-TEMP-002", name="缺文件线路", voltage_kv=220, status="enabled")
        session.add(line)
        session.commit()

        with pytest.raises(HTTPException) as exc:
            line_service.import_line_towers_from_csv(
                session,
                line=line,
                file=None,
                temp_file_id=None,
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
    finally:
        session.close()