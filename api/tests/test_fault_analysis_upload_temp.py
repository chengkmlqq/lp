from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fault_analysis import FaultAnalysis
from app.models.user import User
from app.core import file_upload
from app.services import fault_analysis_service
from app.api.v1 import fault_analysis as fault_analysis_api


def _build_sessionmaker(tmp_path: Path) -> sessionmaker:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    SessionLocal = _build_sessionmaker(tmp_path)
    session = SessionLocal()
    shim = SimpleNamespace(file_vfs_root=str(tmp_path / "vfs"))
    monkeypatch.setattr(fault_analysis_service, "get_settings", lambda: shim)
    yield session
    session.close()


def _sample_user(session: Session) -> User:
    user = User(id="u1", username="tester", status="enabled", password_hash="x")
    session.add(user)
    session.commit()
    return user


def _make_upload_file(filename: str, content: bytes):
    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def tell(self) -> int:
            return 0

        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

    class _Upload:
        def __init__(self, name: str, data: bytes) -> None:
            self.filename = name
            self.file = _FakeFile(data)

    return _Upload(filename, content)


def test_store_and_resolve_temp_upload(monkeypatch) -> None:
    """temp_file_id 归属校验 + 消费后删除（通用 upload-temp 链路）。"""
    from app.services import minio_storage

    stored: dict[str, bytes] = {}

    def mock_put(key, data, content_type=None) -> str:
        stored[key] = data
        return key

    def mock_get(key):
        if key not in stored:
            raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")
        return stored[key]

    monkeypatch.setattr(minio_storage, "put_object", mock_put)
    monkeypatch.setattr(minio_storage, "get_object", mock_get)
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: stored.pop(key, None))

    upload = _make_upload_file("1_录波数据.txt", b"wave-form-data")
    temp_file_id, file_name = file_upload.save_temp_upload(upload, "u1")
    assert file_name == "1_录波数据.txt"
    assert temp_file_id.startswith("lightning/tmp/u1/")
    assert temp_file_id.endswith("1_录波数据.txt")

    content, resolved_name = file_upload.resolve_temp_upload(temp_file_id, "u1")
    assert content == b"wave-form-data"
    assert resolved_name == "1_录波数据.txt"
    # 消费后临时对象已删除
    assert temp_file_id not in stored


def test_resolve_temp_upload_wrong_user(monkeypatch) -> None:
    """temp_file_id 不属于当前用户时返回 400。"""
    from fastapi import HTTPException
    from app.services import minio_storage

    monkeypatch.setattr(minio_storage, "put_object", lambda key, data, content_type=None: key)

    with pytest.raises(HTTPException) as captured:
        file_upload.resolve_temp_upload(
            "lightning/tmp/other-user/abc123_test.csv",
            "u1",
        )
    assert captured.value.status_code == 400
    assert "不属于当前用户" in str(captured.value.detail)


def test_store_auto_classified_files_from_temp_ids(db_session, monkeypatch) -> None:
    """两段式上传：auto_classify_temp_file_ids 消费临时文件并按前缀归类。"""
    from app.services import minio_storage

    stored: dict[str, bytes] = {}

    def mock_put(key, data, content_type=None) -> str:
        stored[key] = data
        return key

    def mock_get(key):
        if key not in stored:
            raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")
        return stored[key]

    monkeypatch.setattr(minio_storage, "put_object", mock_put)
    monkeypatch.setattr(minio_storage, "get_object", mock_get)
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: stored.pop(key, None))
    monkeypatch.setattr(
        fault_analysis_service,
        "dispatch_fault_diagnosis",
        lambda db, analysis_id: None,
    )

    _sample_user(db_session)
    import asyncio

    temp_ids = []
    for name, data in (
        ("1_录波数据.txt", b"wave"),
        ("2_雷电定位.xlsx", b"lightning"),
        ("3_台账.csv", b"ledger"),
    ):
        temp_id, _ = file_upload.save_temp_upload(
            _make_upload_file(name, data),
            "u1",
        )
        temp_ids.append(temp_id)

    upload_files = asyncio.run(
        fault_analysis_api._store_auto_classified_files(
            "fa-temp-1",
            uploads=[],
            temp_file_ids=temp_ids,
            user_id="u1",
        )
    )
    assert upload_files["wave_data_file"].endswith("1_录波数据.txt")
    assert upload_files["lightning_data_file"].endswith("2_雷电定位.xlsx")
    assert upload_files["ledger_data_file"].endswith("3_台账.csv")
    # 所有临时对象均已被消费删除
    assert not stored


def test_resolve_temp_upload_missing(monkeypatch) -> None:
    """临时文件不存在/已过期时返回 400。"""
    from fastapi import HTTPException
    from app.services import minio_storage

    def mock_get(key):
        raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")

    monkeypatch.setattr(minio_storage, "get_object", mock_get)

    with pytest.raises(HTTPException) as captured:
        file_upload.resolve_temp_upload(
            "lightning/tmp/u1/abc_test.csv",
            "u1",
        )
    assert captured.value.status_code == 400
    assert "不存在或已过期" in str(captured.value.detail)