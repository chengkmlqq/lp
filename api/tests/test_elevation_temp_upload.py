"""Tests for elevation two-phase temp upload (LP-366)."""
from __future__ import annotations

import os
from io import BytesIO

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

import pytest
from fastapi import HTTPException, UploadFile

from app.core import file_upload
from app.core.dependencies import CurrentUser, get_current_user
from app.models.user import User
from app.services import minio_storage


def _make_upload(filename: str, content: bytes = b"fake-tif-content") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


def _current_user(uid: str = "user-1") -> CurrentUser:
    return CurrentUser(
        user=User(
            id=uid,
            email="u@example.com",
            username="u",
            password_hash="secret",
            status="ENABLED",
        ),
        role_codes={"admin"},
        permission_codes={"elevation.manage"},
    )


def _build_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.elevation import router as elevation_router
    from app.core.database import get_db
    from app.core.dependencies import require_enabled_menu_route

    app = FastAPI()
    app.include_router(elevation_router, prefix="/api/v1")

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _current_user()
    app.dependency_overrides[require_enabled_menu_route] = lambda: _current_user()
    return TestClient(app)


# ---------------------------------------------------------------------------
# 临时文件名还原（core/file_upload.py）
# ---------------------------------------------------------------------------


def test_resolve_temp_upload_returns_content_and_name(monkeypatch) -> None:
    temp_key = "lightning/tmp/user-1/abc1234_高程.tif"
    deleted: list[str] = []
    monkeypatch.setattr(minio_storage, "get_object", lambda key: b"content" if key == temp_key else b"")
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: deleted.append(key))

    content, file_name = file_upload.resolve_temp_upload(temp_key, "user-1")
    assert content == b"content"
    assert file_name == "高程.tif"
    assert deleted == [temp_key]


def test_resolve_temp_upload_rejects_wrong_user() -> None:
    with pytest.raises(HTTPException) as exc:
        file_upload.resolve_temp_upload("lightning/tmp/other-user/abc.txt", "user-1")
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# /api/v1/elevation/upload-temp 端点
# ---------------------------------------------------------------------------


def test_elevation_upload_temp_endpoint(monkeypatch) -> None:
    from app.api.v1 import elevation as elevation_api

    monkeypatch.setattr(
        minio_storage,
        "build_temp_key",
        lambda name, uid: f"lightning/tmp/{uid}/abc1234_{name}",
    )
    monkeypatch.setattr(
        minio_storage,
        "put_object",
        lambda key, data, content_type=None: key,
    )

    client = _build_client()
    resp = client.post(
        "/api/v1/elevation/upload-temp",
        files={"file": ("高程.tif", b"fake-tif-content", "image/tiff")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["temp_file_id"] == "lightning/tmp/user-1/abc1234_高程.tif"
    assert body["file_name"] == "高程.tif"


def test_elevation_upload_temp_rejects_bad_extension(monkeypatch) -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/elevation/upload-temp",
        files={"file": ("data.csv", b"lon,lat", "text/csv")},
    )
    assert resp.status_code == 400
    assert "不支持的文件格式" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /api/v1/elevation/records 端点（temp_file_id 路径）
# ---------------------------------------------------------------------------


def test_elevation_records_via_temp_file_id(monkeypatch) -> None:
    from app.api.v1 import elevation as elevation_api
    from app.schemas.elevation import ElevationFileRecordSummary, ElevationFileRecordUploadResponse

    temp_key = "lightning/tmp/user-1/abc1234_高程.tif"

    def fake_create_record(db, file, payload, *, actor, content=None, filename=None):
        assert file is None
        assert content == b"fake-tif-content"
        assert filename == "高程.tif"
        assert payload.source == "SRTM"
        return ElevationFileRecordUploadResponse(
            record=ElevationFileRecordSummary(
                id="r1",
                file_name=filename,
                file_path="/elevation/records/ab/cd/r1.tif",
                file_format="tif",
                file_size=len(content),
                mount_code="default",
                status="active",
                create_date=__import__("datetime").datetime.now(),
                update_date=__import__("datetime").datetime.now(),
            )
        )

    monkeypatch.setattr(elevation_api, "create_file_record_from_upload", fake_create_record)
    monkeypatch.setattr(minio_storage, "get_object", lambda key: b"fake-tif-content" if key == temp_key else b"")
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)

    client = _build_client()
    resp = client.post(
        "/api/v1/elevation/records",
        data={
            "temp_file_id": temp_key,
            "source": "SRTM",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["record"]["id"] == "r1"


def test_elevation_records_rejects_foreign_temp_file_id(monkeypatch) -> None:
    from app.api.v1 import elevation as elevation_api

    monkeypatch.setattr(
        elevation_api,
        "create_file_record_from_upload",
        lambda *args, **kwargs: None,
    )
    client = _build_client()
    resp = client.post(
        "/api/v1/elevation/records",
        data={"temp_file_id": "lightning/tmp/other-user/abc.tif"},
    )
    assert resp.status_code == 400


def test_elevation_records_requires_file_or_temp_id(monkeypatch) -> None:
    from app.api.v1 import elevation as elevation_api

    monkeypatch.setattr(
        elevation_api,
        "create_file_record_from_upload",
        lambda *args, **kwargs: None,
    )
    client = _build_client()
    resp = client.post("/api/v1/elevation/records", data={})
    assert resp.status_code == 400
