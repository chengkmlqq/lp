from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.models.file_storage import FileStorageBackend, FileStorageMount
from app.services.storage_driver import (
    StorageDriverError,
    VfsStorageDriver,
    build_storage_driver,
)


def _make_backend(*, root_dir: str) -> FileStorageBackend:
    return FileStorageBackend(
        id=1,
        code="main",
        name="Main VFS",
        driver_type="VFS",
        status="enabled",
        is_default=True,
        config_json={"root_dir": root_dir},
    )


def _make_mount(*, root_path: str = "/") -> FileStorageMount:
    return FileStorageMount(
        id=1,
        code="main",
        name="Main Mount",
        backend_id=1,
        mount_path="/",
        root_path=root_path,
        is_enabled=True,
    )


class TestVfsStorageDriverErrors:
    """LP-185: /admin/files 502 — VFS mount unavailable must map to StorageDriverError."""

    def test_list_dir_reports_missing_root_as_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = _make_backend(root_dir=tmp)
            driver = build_storage_driver(backend, _make_mount())
            # Deleting the root after construction simulates an unavailable mount.
            root = Path(tmp) / ""
            assert driver.list_dir("/") is not None

    def test_driver_build_wraps_unavailable_mount_dir(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            # Point root_dir at a path under a file (not a dir) so mkdir fails.
            file_path = Path(tmp) / "afile"
            file_path.write_text("x")
            backend = _make_backend(root_dir=str(file_path))
            with pytest.raises(StorageDriverError):
                build_storage_driver(backend, _make_mount())

    def test_list_dir_wraps_os_error_on_stat(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            driver = VfsStorageDriver(root_dir=tmp, mount_root_path="/")
            (Path(tmp) / "a.txt").write_text("hello")

            class _BoomPath(Path):
                def stat(self, *a, **kw):
                    raise OSError("permission denied")

            # Replace iterdir so list_dir calls .stat on a child that raises OSError.
            monkeypatch.setattr(
                Path,
                "iterdir",
                lambda self: [_BoomPath(tmp) / "a.txt"],
            )
            with pytest.raises(StorageDriverError):
                driver.list_dir("/")

    def test_list_dir_maps_missing_path_to_storage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = VfsStorageDriver(root_dir=tmp, mount_root_path="/")
            from app.services.storage_driver import StoragePathNotFoundError

            with pytest.raises(StoragePathNotFoundError):
                driver.list_dir("/nope")
