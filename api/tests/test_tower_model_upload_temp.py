"""Tests for tower-model two-phase temp upload (LP-368)."""
from __future__ import annotations

import os
from io import BytesIO

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import UploadFile  # noqa: E402

from app.core.dependencies import CurrentUser, get_current_user  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import minio_storage  # noqa: E402


def _make_upload(filename: str, content: bytes = b"\x89PNG\r\n\x1a\n") -> UploadFile:
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
        permission_codes={"tower_model.manage"},
    )


def _build_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.v1.tower_models import router as tm_router
    from app.core.database import get_db
    from app.core.dependencies import require_enabled_menu_route

    app = FastAPI()
    app.include_router(tm_router, prefix="/api/v1")

    def override_get_db():
        yield None

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _current_user()
    app.dependency_overrides[require_enabled_menu_route] = lambda: _current_user()
    return TestClient(app)


# ---------------------------------------------------------------------------
# /api/v1/tower-models/upload-temp 端点
# ---------------------------------------------------------------------------


def test_upload_temp_returns_temp_file_id(monkeypatch) -> None:
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

    client = _build_client()
    resp = client.post(
        "/api/v1/tower-models/upload-temp",
        files={"file": ("tower.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["temp_file_id"] == "lightning/tmp/user-1/tower.png"
    assert payload["file_name"] == "tower.png"
    assert written[0][0] == "lightning/tmp/user-1/tower.png"


def test_upload_temp_rejects_empty_file(monkeypatch) -> None:
    monkeypatch.setattr(minio_storage, "build_temp_key", lambda name, uid: f"lightning/tmp/{uid}/{name}")

    client = _build_client()
    resp = client.post(
        "/api/v1/tower-models/upload-temp",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/v1/tower-models/{model_id}/image 端点（temp_file_id 路径）
# ---------------------------------------------------------------------------


def test_image_upload_via_temp_id(monkeypatch) -> None:
    from app.api.v1 import tower_models as tm_api
    from app.schemas.tower_model import TowerModelImageUploadResponse, TowerModelSummary

    model = TowerModelSummary(
        id="model-1",
        code="TM-1",
        name="Tower 1",
        create_date="2026-01-01T00:00:00Z",
        update_date="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(
        minio_storage,
        "get_object",
        lambda key: b"\x89PNG\r\n\x1a\n",
    )
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)
    monkeypatch.setattr(
        tm_api,
        "upload_tower_model_image",
        lambda db, *, model_id, mount_code, content, filename, content_type=None, actor: TowerModelImageUploadResponse(
            model=model,
            mount_code=mount_code,
            image_path=f"/tower-models/images/{filename}",
        ),
    )

    client = _build_client()
    resp = client.post(
        "/api/v1/tower-models/model-1/image?mount_code=mount-a",
        data={"temp_file_id": "lightning/tmp/user-1/uuid_tower.png"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["model"]["code"] == "TM-1"
    assert payload["mount_code"] == "mount-a"


def test_image_upload_missing_all_sources(monkeypatch) -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/tower-models/model-1/image?mount_code=mount-a",
        data={},
    )
    assert resp.status_code == 400


def test_image_upload_rejects_foreign_temp_id(monkeypatch) -> None:
    client = _build_client()
    resp = client.post(
        "/api/v1/tower-models/model-1/image?mount_code=mount-a",
        data={"temp_file_id": "lightning/tmp/other-user/abc.png"},
    )
    assert resp.status_code == 400
