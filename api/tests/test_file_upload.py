from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile, status


@pytest.fixture(autouse=True)
def _reset_config():
    from app.core.config import get_settings
    s = get_settings()
    orig = s.upload_max_file_size_mb
    s.upload_max_file_size_mb = 50
    yield
    s.upload_max_file_size_mb = orig


def _make_upload(filename: str, content: bytes = b"hello") -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


class TestValidateUpload:
    def test_accepts_normal_file(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.csv", b"a,b,c\n1,2,3")
        result = validate_upload(f, allowed_exts={"csv"})
        assert result is f

    def test_rejects_oversized_file(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.csv", b"x" * (51 * 1024 * 1024))
        with pytest.raises(HTTPException) as exc:
            validate_upload(f, max_mb=50, allowed_exts={"csv"})
        assert exc.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def test_rejects_illegal_extension(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.exe")
        with pytest.raises(HTTPException) as exc:
            validate_upload(f, allowed_exts={"csv"})
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "exe" in exc.value.detail

    def test_accepts_no_extension_check(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.exe", b"small")
        result = validate_upload(f, max_mb=50)
        assert result is f

    def test_normalizes_extension_case(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.CSV")
        result = validate_upload(f, allowed_exts={"csv"})
        assert result is f

    def test_rejects_empty_extension_check(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data")
        with pytest.raises(HTTPException) as exc:
            validate_upload(f, allowed_exts={"csv"})
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_allowed_exts_label(self):
        from app.core.file_upload import validate_upload

        f = _make_upload("data.bin")
        with pytest.raises(HTTPException) as exc:
            validate_upload(f, allowed_exts={"tif", "tiff", "zip"}, allowed_exts_label="tif/tiff/zip")
        assert "tif/tiff/zip" in exc.value.detail

    def test_default_max_mb_from_config(self):
        from app.core.config import get_settings
        from app.core.file_upload import validate_upload

        get_settings().upload_max_file_size_mb = 5
        f = _make_upload("data.csv", b"x" * (6 * 1024 * 1024))
        with pytest.raises(HTTPException) as exc:
            validate_upload(f, allowed_exts={"csv"})
        assert exc.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE

    def test_aliased_upload_write(self):
        """验证模块内的逻辑别名不破坏原有上传链路。"""
        from app.core.file_upload import validate_upload

        content = b"a,b,c\n1,2,3"
        f = _make_upload("towers.csv", content)
        result = validate_upload(f, allowed_exts={"csv"})
        assert result.file.read() == content


class TestTempUpload:
    def test_save_temp_upload_returns_temp_file_id(self, monkeypatch):
        from app.core import file_upload
        from app.services import minio_storage

        written: dict[str, bytes] = {}
        monkeypatch.setattr(
            minio_storage,
            "put_object",
            lambda key, data, content_type=None: written.__setitem__(key, data),
        )
        monkeypatch.setattr(
            minio_storage,
            "build_temp_key",
            lambda name, uid: f"lightning/tmp/{uid}/abc_{name}",
        )

        f = _make_upload("data.csv", b"a,b,c\n1,2,3")
        temp_file_id, file_name = file_upload.save_temp_upload(f, "user-1")

        assert temp_file_id == "lightning/tmp/user-1/abc_data.csv"
        assert file_name == "data.csv"
        assert written[temp_file_id] == b"a,b,c\n1,2,3"

    def test_save_temp_upload_rejects_empty_file(self, monkeypatch):
        from app.core import file_upload
        from app.services import minio_storage

        monkeypatch.setattr(minio_storage, "build_temp_key", lambda name, uid: f"lightning/tmp/{uid}/x_{name}")

        f = _make_upload("empty.csv", b"")
        with pytest.raises(HTTPException) as exc:
            file_upload.save_temp_upload(f, "user-1")
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "为空" in exc.value.detail

    def test_resolve_temp_upload_rejects_other_user(self, monkeypatch):
        from app.core import file_upload

        with pytest.raises(HTTPException) as exc:
            file_upload.resolve_temp_upload("lightning/tmp/other-user/abc_data.csv", "user-1")
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "不属于当前用户" in exc.value.detail

    def test_resolve_temp_upload_missing_object(self, monkeypatch):
        from app.core import file_upload
        from app.services import minio_storage

        def missing(key: str) -> bytes:
            raise minio_storage.MinioObjectNotFoundError("Object not found")

        monkeypatch.setattr(minio_storage, "get_object", missing)

        with pytest.raises(HTTPException) as exc:
            file_upload.resolve_temp_upload("lightning/tmp/user-1/abc_data.csv", "user-1")
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "不存在或已过期" in exc.value.detail

    def test_resolve_temp_upload_reads_and_deletes(self, monkeypatch):
        from app.core import file_upload
        from app.services import minio_storage

        deleted: list[str] = []
        monkeypatch.setattr(minio_storage, "get_object", lambda key: b"a,b,c\n1,2,3")
        monkeypatch.setattr(minio_storage, "delete_object", lambda key: deleted.append(key))

        content, source_file_name = file_upload.resolve_temp_upload(
            "lightning/tmp/user-1/abc_data.csv", "user-1"
        )

        assert content == b"a,b,c\n1,2,3"
        assert source_file_name == "data.csv"
        assert deleted == ["lightning/tmp/user-1/abc_data.csv"]

    def test_resolve_temp_upload_delete_failure_is_swallowed(self, monkeypatch):
        from app.core import file_upload
        from app.services import minio_storage

        monkeypatch.setattr(minio_storage, "get_object", lambda key: b"a,b,c")
        monkeypatch.setattr(
            minio_storage,
            "delete_object",
            lambda key: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        content, source_file_name = file_upload.resolve_temp_upload(
            "lightning/tmp/user-1/abc_data.csv", "user-1"
        )
        assert content == b"a,b,c"
        assert source_file_name == "data.csv"