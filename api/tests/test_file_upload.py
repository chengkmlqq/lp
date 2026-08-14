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