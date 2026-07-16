from __future__ import annotations

import io
from pathlib import Path
import zipfile

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import database as core_database
from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRelease, AtpAssetRun
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.schemas.atp_asset import AtpAssetCreateRequest, AtpAssetReleaseCreateRequest, AtpAssetRunRequest
from app.services import atp_asset_service


def _build_sessionmaker():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            FileStorageBackend.__table__,
            FileStorageMount.__table__,
            FileIndexEntry.__table__,
            User.__table__,
            AtpAsset.__table__,
            AtpAssetRelease.__table__,
            AtpAssetRun.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _seed_vfs_mount(session: Session, *, root_dir: Path) -> None:
    backend = FileStorageBackend(
        code="main",
        name="Main VFS",
        driver_type="VFS",
        status="enabled",
        is_default=True,
        config_json={"root_dir": str(root_dir)},
    )
    session.add(backend)
    session.flush()
    session.add(
        FileStorageMount(
            code="main",
            name="Main Mount",
            backend_id=backend.id,
            mount_path="/",
            root_path="/",
            is_enabled=True,
        )
    )
    session.commit()


def _build_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buffer.getvalue()


class _DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(content)


def test_create_release_auto_detects_entry_file_and_manifest(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        release_root = tmp_path / "vfs" / "atp-library" / "demo-release"
        release_root.mkdir(parents=True)
        (release_root / "work.atp").write_text("ATP INPUT", encoding="utf-8")
        (release_root / "README.txt").write_text("docs", encoding="utf-8")

        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-001", name="目录化ATP资产"),
            actor_user_id="tester",
        )
        assert asset is not None

        created = atp_asset_service.create_release(
            session,
            asset_id=asset.id,
            payload=AtpAssetReleaseCreateRequest(
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
                runner_kind="atp",
                storage_mount_code="main",
                storage_root_path="/atp-library/demo-release",
            ),
            actor_user_id="tester",
        )

        assert created.entry_file == "work.atp"
        assert created.is_active is True
        assert created.manifest_json["file_count"] == 2
        assert created.validation_json["entry_file_exists"] is True
    finally:
        session.close()


def test_create_release_from_archive_extracts_zip_and_inherits_asset_dimensions(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-UPLOAD",
                name="ZIP 导入模型",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset is not None

        created = atp_asset_service.create_release_from_archive(
            session,
            asset_id=asset.id,
            release_tag="首版",
            archive_filename="release.zip",
            archive_content=_build_zip(
                {
                    "work.atp": b"ATP INPUT",
                    "EGM/config.txt": b"egm",
                }
            ),
            actor_user_id="tester",
        )

        assert created.release_no == 1
        assert created.release_tag == "首版"
        assert created.storage_root_path == "/atp-library/220/sihuita/r1"
        assert created.entry_file == "work.atp"
        assert created.runner_kind == "hybrid"
        assert created.voltage_level == "220"
        assert created.tower_type == "sihuita"
        assert created.scene_type == "raoji3"
        assert (tmp_path / "vfs" / "atp-library" / "220" / "sihuita" / "r1" / "work.atp").exists()
        assert (tmp_path / "vfs" / "atp-library" / "220" / "sihuita" / "r1" / "EGM" / "config.txt").exists()
    finally:
        session.close()


def test_create_release_from_archive_requires_asset_dimensions(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-MISSING", name="缺维度模型"),
            actor_user_id="tester",
        )
        assert asset is not None

        with pytest.raises(HTTPException, match="电压等级、塔型和场景"):
            atp_asset_service.create_release_from_archive(
                session,
                asset_id=asset.id,
                release_tag="r1",
                archive_filename="release.zip",
                archive_content=_build_zip({"work.atp": b"ATP INPUT"}),
                actor_user_id="tester",
            )
    finally:
        session.close()


def test_create_release_from_archive_detects_storage_path_conflict(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")

        # Create first asset and upload a release
        asset1 = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-001",
                name="模型1",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset1 is not None

        release1 = atp_asset_service.create_release_from_archive(
            session,
            asset_id=asset1.id,
            release_tag="v1",
            archive_filename="release.zip",
            archive_content=_build_zip({"work.atp": b"ATP INPUT 1"}),
            actor_user_id="tester",
        )
        assert release1.storage_root_path == "/atp-library/220/sihuita/r1"

        # Create second asset with same voltage_level and tower_type
        asset2 = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-002",
                name="模型2",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset2 is not None

        # Try to upload a release for asset2 - should conflict because path is same
        with pytest.raises(HTTPException, match="存储路径冲突"):
            atp_asset_service.create_release_from_archive(
                session,
                asset_id=asset2.id,
                release_tag="v1",
                archive_filename="release.zip",
                archive_content=_build_zip({"work.atp": b"ATP INPUT 2"}),
                actor_user_id="tester",
            )
    finally:
        session.close()


def test_upload_asset_archive_and_list_asset_files(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-DIRECT-UPLOAD",
                name="直接上传模型",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset is not None

        uploaded = atp_asset_service.upload_asset_archive(
            session,
            asset_id=asset.id,
            archive_filename="model.zip",
            archive_content=_build_zip({"work.atp": b"ATP INPUT", "docs/readme.txt": b"docs"}),
            actor_user_id="tester",
        )

        assert uploaded.success is True
        assert uploaded.storage_root_path == "/atp-assets/ATP-ASSET-DIRECT-UPLOAD"

        files = atp_asset_service.list_asset_files(session, asset_id=asset.id)
        assert files.asset_id == asset.id
        assert files.release_id is None
        assert files.total == 3
        assert [item.relative_path for item in files.items] == ["docs", "docs/readme.txt", "work.atp"]
    finally:
        session.close()


def test_list_asset_files_falls_back_to_latest_release(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-LEGACY-FALLBACK",
                name="旧版本模型",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset is not None

        release = atp_asset_service.create_release_from_archive(
            session,
            asset_id=asset.id,
            release_tag="v1",
            archive_filename="release.zip",
            archive_content=_build_zip({"work.atp": b"ATP INPUT", "docs/readme.txt": b"docs"}),
            actor_user_id="tester",
        )

        files = atp_asset_service.list_asset_files(session, asset_id=asset.id)
        assert files.asset_id == asset.id
        assert files.release_id == release.id
        assert files.total == 3
        assert [item.relative_path for item in files.items] == ["docs", "docs/readme.txt", "work.atp"]
    finally:
        session.close()


def test_list_assets_paginates_after_filtering(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        for index in range(4):
            created = atp_asset_service.create_asset(
                session,
                AtpAssetCreateRequest(
                    code=f"ATP-ASSET-PAGE-{index}",
                    name=f"分页模型 {index}",
                    voltage_level="220",
                    tower_type="sihuita",
                    scene_type="fanji",
                    arrester_config="M123",
                ),
                actor_user_id="tester",
            )
            assert created is not None
            assert created.arrester_config == "M123"

        result = atp_asset_service.list_assets(
            session,
            keyword="分页模型",
            status_filter=None,
            voltage_level=None,
            tower_type=None,
            scene_type=None,
            limit=2,
            offset=1,
        )

        assert result.total == 4
        assert len(result.items) == 2
        assert [item.code for item in result.items] == ["ATP-ASSET-PAGE-2", "ATP-ASSET-PAGE-1"]
        assert [item.arrester_config for item in result.items] == ["M123", "M123"]
    finally:
        session.close()


def test_run_release_dry_run_materializes_directory(tmp_path, monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    monkeypatch.setattr(core_database, "SessionLocal", testing_session)
    session: Session = testing_session()
    try:
        release_root = tmp_path / "vfs" / "atp-library" / "runtime-release"
        release_root.mkdir(parents=True)
        (release_root / "work.atp").write_text("ATP INPUT", encoding="utf-8")
        (release_root / "tpbig.exe").write_text("binary", encoding="utf-8")

        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-DRY", name="Dry Run 资产"),
            actor_user_id="tester",
        )
        assert asset is not None
        release = atp_asset_service.create_release(
            session,
            asset_id=asset.id,
            payload=AtpAssetReleaseCreateRequest(
                voltage_level="500",
                tower_type="ganzi",
                scene_type="fanji",
                runner_kind="atp",
                storage_mount_code="main",
                storage_root_path="/atp-library/runtime-release",
            ),
            actor_user_id="tester",
        )

        allowed_root = tmp_path / "wine-root"
        allowed_root.mkdir(parents=True)
        monkeypatch.setattr(atp_asset_service.settings, "wine_allowed_root", str(allowed_root))
        monkeypatch.setattr(atp_asset_service.settings, "atp_engine_mode", "wine")
        monkeypatch.setattr(atp_asset_service, "_resolve_binary", lambda value: "/usr/bin/wine" if value == "wine" else None)
        monkeypatch.setattr(atp_asset_service, "_publish_change", lambda *args, **kwargs: None)

        result = atp_asset_service.run_release(
            session,
            release_id=release.id,
            payload=AtpAssetRunRequest(dry_run=True),
            actor_user_id="tester",
        )

        assert result.status == "success"
        assert result.engine_command is not None
        assert "tpbig.exe" in result.engine_command
        assert result.materialized_root_path is not None
        materialized_root = Path(result.materialized_root_path)
        assert materialized_root.exists()
        assert (materialized_root / "work.atp").exists()
        assert result.output_manifest_json["file_count"] >= 2
    finally:
        session.close()


def test_delete_asset_removes_storage_files(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-DELETE-TEST",
                name="删除测试模型",
                voltage_level="500",
                tower_type="danhuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset is not None

        # Create a release with files
        release = atp_asset_service.create_release_from_archive(
            session,
            asset_id=asset.id,
            release_tag="v1",
            archive_filename="release.zip",
            archive_content=_build_zip({
                "work.atp": b"ATP INPUT",
                "README.txt": b"documentation",
            }),
            actor_user_id="tester",
        )
        assert release.storage_root_path == "/atp-library/500/danhuita/r1"

        # Verify files exist before deletion
        storage_path = tmp_path / "vfs" / "atp-library" / "500" / "danhuita" / "r1"
        assert storage_path.exists()
        assert (storage_path / "work.atp").exists()
        assert (storage_path / "README.txt").exists()

        # Delete the asset
        deleted = atp_asset_service.delete_asset(session, asset.id)
        assert deleted is True

        # Verify files are deleted
        assert not storage_path.exists()
    finally:
        session.close()


def test_upload_asset_files_extracts_zip_and_removes_asset_root(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASSET-FILES",
                name="资产文件上传",
                voltage_level="220",
                tower_type="sihuita",
                scene_type="raoji3",
            ),
            actor_user_id="tester",
        )
        assert asset is not None

        updated = atp_asset_service.upload_asset_files(
            session,
            asset_id=asset.id,
            files=[
                _DummyUploadFile(
                    "model.zip",
                    _build_zip(
                        {
                            "work.atp": b"ATP INPUT",
                            "nested/config.txt": b"nested config",
                        }
                    ),
                )
            ],
            actor_user_id="tester",
        )

        assert updated.storage_mount_code == "main"
        assert updated.storage_root_path == "/atp-assets/ATP-ASSET-FILES"

        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-FILES"
        assert (asset_root / "work.atp").exists()
        assert (asset_root / "nested" / "config.txt").exists()

        files = atp_asset_service.list_asset_files(session, asset_id=asset.id)
        assert files.release_id is None
        assert files.storage_root_path == "/atp-assets/ATP-ASSET-FILES"
        assert any(entry.relative_path == "work.atp" and not entry.is_dir for entry in files.items)
        assert any(entry.relative_path == "nested/config.txt" and not entry.is_dir for entry in files.items)

        assert atp_asset_service.delete_asset(session, asset.id) is True
        assert not asset_root.exists()
    finally:
        session.close()
