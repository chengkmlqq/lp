"""Tests for traveling-wave two-phase temp upload (LP-371)."""
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


def _make_upload(filename: str, content: bytes = b"DataLen=1\nCurrentDataInput=1.0\n") -> UploadFile:
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
        permission_codes={"traveling_wave.manage"},
    )


def _build_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.traveling_wave import router as tw_router
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(tw_router, prefix="/api/v1")

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _current_user()
    return TestClient(app)


# ---------------------------------------------------------------------------
# 通用临时文件保存 / 读取（core/file_upload.py）
# ---------------------------------------------------------------------------


def test_save_temp_upload_stores_and_returns_id(monkeypatch) -> None:
    written: list[tuple[str, bytes]] = []
    monkeypatch.setattr(
        minio_storage,
        "build_temp_key",
        lambda name, uid: f"lightning/tmp/{uid}/{name}",
    )
    monkeypatch.setattr(
        minio_storage,
        "put_object",
        lambda key, data, content_type=None: written.append((key, data)) or key,
    )

    f = _make_upload("A相.txt", "内容".encode("utf-8"))
    temp_file_id, file_name = file_upload.save_temp_upload(f, "user-1")

    assert file_name == "A相.txt"
    assert temp_file_id == "lightning/tmp/user-1/A相.txt"
    assert written == [("lightning/tmp/user-1/A相.txt", "内容".encode("utf-8"))]


def test_save_temp_upload_rejects_empty(monkeypatch) -> None:
    monkeypatch.setattr(minio_storage, "build_temp_key", lambda name, uid: f"lightning/tmp/{uid}/{name}")
    monkeypatch.setattr(minio_storage, "put_object", lambda key, data, content_type=None: key)

    f = _make_upload("empty.txt", b"")
    with pytest.raises(HTTPException) as exc:
        file_upload.save_temp_upload(f, "user-1")
    assert exc.value.status_code == 400


def test_read_temp_upload_consumes_and_deletes(monkeypatch) -> None:
    temp_key = "lightning/tmp/user-1/abc.txt"
    deleted: list[str] = []
    monkeypatch.setattr(minio_storage, "get_object", lambda key: b"content" if key == temp_key else b"")
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: deleted.append(key))

    content = file_upload.read_temp_upload(temp_key, "user-1")
    assert content == b"content"
    assert deleted == [temp_key]


def test_read_temp_upload_wrong_user(monkeypatch) -> None:
    with pytest.raises(HTTPException) as exc:
        file_upload.read_temp_upload("lightning/tmp/other-user/abc.txt", "user-1")
    assert exc.value.status_code == 400
    assert "不属于当前用户" in str(exc.value.detail) or "无效" in str(exc.value.detail)


def test_read_temp_upload_missing_object(monkeypatch) -> None:
    def raise_not_found(key: str):
        raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")

    monkeypatch.setattr(minio_storage, "get_object", raise_not_found)
    with pytest.raises(HTTPException) as exc:
        file_upload.read_temp_upload("lightning/tmp/user-1/ghost.txt", "user-1")
    assert exc.value.status_code == 400
    assert "不存在" in str(exc.value.detail) or "过期" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# /api/v1/traveling-wave/analyze/upload 端点（temp_file_id 路径）
# ---------------------------------------------------------------------------


def test_analyze_upload_via_temp_ids(monkeypatch) -> None:
    from app.api.v1 import traveling_wave as tw_api
    from app.schemas.traveling_wave import TravelingWaveAnalyzeResponse

    temp_content_a = "PhaseAContent\n".encode("utf-8")

    def fake_create_job(db, content_a=None, content_b=None, content_c=None, sample_rate_hz=1_000_000,
                        fault_distance_km=None, tower_no=None, created_by=None):
        assert content_a == "PhaseAContent\n"
        assert content_c == "PhaseCContent\n"
        return ("job-1", TravelingWaveAnalyzeResponse(id="job-1", status="pending", sample_rate_hz=sample_rate_hz))

    monkeypatch.setattr(tw_api, "create_analysis_job", fake_create_job)
    monkeypatch.setattr(
        minio_storage,
        "get_object",
        lambda key: {
            "lightning/tmp/user-1/a.dat": temp_content_a,
            "lightning/tmp/user-1/c.dat": b"PhaseCContent\n",
        }[key],
    )
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)

    client = _build_client()
    resp = client.post(
        "/api/v1/traveling-wave/analyze/upload",
        data={
            "file_a_temp_id": "lightning/tmp/user-1/a.dat",
            "file_c_temp_id": "lightning/tmp/user-1/c.dat",
            "sample_rate_hz": "1000",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == "job-1"
    assert resp.json()["sample_rate_hz"] == 1000


def test_analyze_upload_missing_all_sources(monkeypatch) -> None:
    from app.api.v1 import traveling_wave as tw_api

    monkeypatch.setattr(tw_api, "create_analysis_job", lambda **kwargs: ("job-x", None))
    client = _build_client()
    resp = client.post(
        "/api/v1/traveling-wave/analyze/upload",
        data={"sample_rate_hz": "1000"},
    )
    assert resp.status_code == 400


def test_analyze_upload_rejects_foreign_temp_id(monkeypatch) -> None:
    from app.api.v1 import traveling_wave as tw_api

    monkeypatch.setattr(tw_api, "create_analysis_job", lambda **kwargs: ("job-x", None))
    client = _build_client()
    resp = client.post(
        "/api/v1/traveling-wave/analyze/upload",
        data={"file_a_temp_id": "lightning/tmp/other-user/a.dat"},
    )
    assert resp.status_code == 400