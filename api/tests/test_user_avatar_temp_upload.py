"""Tests for user avatar two-phase temp upload (LP-373)."""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.users import router as users_router
from app.core.database import get_db
from app.core.dependencies import CurrentUser, get_current_user, require_enabled_menu_route, require_permission
from app.models.user import User
from app.schemas.user import UserPublic
from app.services import minio_storage


def _current_user(uid: str = "admin-1") -> CurrentUser:
    return CurrentUser(
        user=User(
            id=uid,
            email="admin@example.com",
            username="admin",
            password_hash="secret",
            status="ENABLED",
        ),
        role_codes={"admin"},
        permission_codes={"user.manage"},
    )


class _FakeSession:
    def commit(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass


def _build_client(tmp_dir: str, *, uid: str = "admin-1") -> TestClient:
    import app.api.v1.users as users_api

    users_api.AVATAR_STORAGE_DIR = tmp_dir
    users_api.get_user_by_id = lambda db, user_id: User(
        id=user_id,
        email="u@example.com",
        username="u",
        password_hash="secret",
        status="ENABLED",
    )
    users_api.serialize_user = lambda user: UserPublic(
        id=user.id,
        email=user.email or "",
        username=user.username,
        status="active",
        role_codes=[],
        permission_codes=[],
        created_at=datetime.now(timezone.utc),
        avatar_url=f"/api/v1/users/{user.id}/avatar" if user.avatar_path else None,
    )

    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: _FakeSession()
    app.dependency_overrides[get_current_user] = lambda: _current_user(uid)
    app.dependency_overrides[require_enabled_menu_route] = lambda: _current_user(uid)
    app.dependency_overrides[require_permission] = lambda perm: _current_user(uid)
    return TestClient(app)


def test_upload_avatar_via_temp_file_id(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_key = "lightning/tmp/admin-1/abc1234_avatar.png"
        png_content = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        )
        monkeypatch.setattr(
            minio_storage,
            "get_object",
            lambda key: png_content if key == temp_key else b"",
        )
        deleted: list[str] = []
        monkeypatch.setattr(minio_storage, "delete_object", lambda key: deleted.append(key))

        client = _build_client(tmp_dir)
        resp = client.post(
            "/api/v1/users/user-x/avatar",
            data={"temp_file_id": temp_key},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["avatar_url"] == "/api/v1/users/user-x/avatar"
        assert deleted == [temp_key]
        saved = os.path.join(tmp_dir, "user-x.png")
        assert os.path.exists(saved)
        with open(saved, "rb") as f:
            assert f.read() == png_content


def test_upload_avatar_rejects_foreign_temp_file_id(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        client = _build_client(tmp_dir)
        resp = client.post(
            "/api/v1/users/user-x/avatar",
            data={"temp_file_id": "lightning/tmp/other-user/abc1234_avatar.png"},
        )
        assert resp.status_code == 400
        assert "temp_file_id 无效" in resp.json()["detail"]


def test_upload_avatar_requires_file_or_temp_file_id() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        client = _build_client(tmp_dir)
        resp = client.post("/api/v1/users/user-x/avatar", data={})
        assert resp.status_code == 400
        assert "缺少文件" in resp.json()["detail"]
