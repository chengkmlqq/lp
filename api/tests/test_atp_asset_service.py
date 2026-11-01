from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRun
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.schemas.atp_asset import AtpAssetCreateRequest, AtpAssetRunRequest
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


def test_create_asset_and_upload_archive(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-001", name="目录化ATP资产"),
            actor_user_id="tester",
        )
        assert asset is not None

        uploaded = atp_asset_service.upload_asset_archive(
            session,
            asset_id=asset.id,
            archive_filename="model.zip",
            archive_content=_build_zip(
                {
                    "work.atp": b"ATP INPUT",
                    "long.dat": b"1",
                    "short.dat": b"1",
                    "dahao.dat": b"1",
                    "xiaohao.dat": b"1",
                }
            ),
            actor_user_id="tester",
        )

        assert uploaded.success is True
        assert uploaded.storage_root_path == "/atp-assets/ATP-ASSET-001"
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
            archive_content=_build_zip(
                {
                    "work.atp": b"ATP INPUT",
                    "long.dat": b"1",
                    "short.dat": b"1",
                    "dahao.dat": b"1",
                    "xiaohao.dat": b"1",
                }
            ),
            actor_user_id="tester",
        )

        assert uploaded.success is True
        assert uploaded.storage_root_path == "/atp-assets/ATP-ASSET-DIRECT-UPLOAD"

        files = atp_asset_service.list_asset_files(session, asset_id=asset.id)
        assert files.asset_id == asset.id
        assert files.storage_mount_code == "main"
        assert files.total == 5
        assert [item.relative_path for item in files.items] == [
            "dahao.dat",
            "long.dat",
            "short.dat",
            "work.atp",
            "xiaohao.dat",
        ]
    finally:
        session.close()


def test_run_asset_dry_run_materializes_directory(tmp_path, monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    monkeypatch.setattr(atp_asset_service, "settings")
    session: Session = testing_session()
    try:
        asset_root = tmp_path / "vfs" / "atp-assets" / "runtime-asset"
        asset_root.mkdir(parents=True)
        (asset_root / "work.atp").write_text("ATP INPUT", encoding="utf-8")
        (asset_root / "tpbig.exe").write_text("binary", encoding="utf-8")

        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-DRY", name="Dry Run 资产"),
            actor_user_id="tester",
        )
        assert asset is not None
        atp_asset_service.upload_asset_archive(
            session,
            asset_id=asset.id,
            archive_filename="model.zip",
            archive_content=_build_zip(
                {
                    "work.atp": b"ATP INPUT",
                    "long.dat": b"1",
                    "short.dat": b"1",
                    "dahao.dat": b"1",
                    "xiaohao.dat": b"1",
                }
            ),
            actor_user_id="tester",
        )

        allowed_root = tmp_path / "wine-root"
        allowed_root.mkdir(parents=True)
        monkeypatch.setattr(atp_asset_service.settings, "wine_allowed_root", str(allowed_root))
        monkeypatch.setattr(atp_asset_service.settings, "atp_engine_mode", "wine")
        monkeypatch.setattr(atp_asset_service, "_resolve_binary", lambda value: "/usr/bin/wine" if value == "wine" else None)
        monkeypatch.setattr(atp_asset_service, "_publish_change", lambda *args, **kwargs: None)

        result = atp_asset_service.execute_asset_run_job(
            session,
            asset_id=asset.id,
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

        atp_asset_service.upload_asset_archive(
            session,
            asset_id=asset.id,
            archive_filename="model.zip",
            archive_content=_build_zip({
                "work.atp": b"ATP INPUT",
                "long.dat": b"1",
                "short.dat": b"1",
                "dahao.dat": b"1",
                "xiaohao.dat": b"1",
            }),
            actor_user_id="tester",
        )

        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-DELETE-TEST"
        assert asset_root.exists()
        assert (asset_root / "work.atp").exists()
        assert (asset_root / "long.dat").exists()

        deleted = atp_asset_service.delete_asset(session, asset.id)
        assert deleted is True

        assert not asset_root.exists()
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
                    tower_type="fanji",
                    scene_type="raoji3",
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


# ───────────── 列表接口列清单：serialize_asset 需要的列必须都在（防 500） ─────────────


def test_list_assets_columns_cover_serialize_asset_fields() -> None:
    """``list_assets`` 只查固定几列，``serialize_asset`` 读到的每个字段都必须在清单里。

    历史事故两次：2026-10-30 的 version/is_active/shield_wire、2026-11-01 的 test_line_id
    ——漏一列，整个资产列表接口直接 500 AttributeError（线上就是「ATP 模型管理页打不开」）。
    这条断言从源码层面兜住，新增字段忘了加列清单会立刻在这里失败。
    """
    import inspect
    import re

    from app.services import atp_asset_service as svc

    serialize_src = inspect.getsource(svc.serialize_asset)
    accessed = set(re.findall(r"\bitem\.([a-z_][a-z0-9_]*)", serialize_src))

    list_src = inspect.getsource(svc.list_assets)
    block = list_src[list_src.index("columns = (") : list_src.index("stmt = select(*columns)")]
    provided = set(re.findall(r"AtpAsset\.([a-z_][a-z0-9_]*)", block))

    missing = accessed - provided
    assert not missing, f"list_assets 少查了 serialize_asset 需要的列：{sorted(missing)}"


def test_list_assets_returns_test_line_id() -> None:
    """真实跑一遍列表：绑定测试线路的资产能正常序列化，不抛 AttributeError。"""
    from app.models.dimension_item import DimensionItem

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            AtpAsset.__table__,
            AtpAssetRun.__table__,
            DimensionItem.__table__,
        ],
    )
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    try:
        session.add(
            AtpAsset(
                code="TL-ASSET-1",
                name="测试线路绑定资产",
                status="enabled",
                voltage_level="220",
                tower_type="MT1",
                scene_type="plain",
                arrester_config="none",
                test_line_id="tl_demo_0001",
            )
        )
        session.commit()

        response = atp_asset_service.list_assets(
            session,
            keyword=None,
            status_filter=None,
            voltage_level=None,
            tower_type=None,
            scene_type=None,
        )

        assert response.total == 1
        assert response.items[0].test_line_id == "tl_demo_0001"
    finally:
        session.close()


# ───────────── 列表接口列清单：serialize_asset 需要的列必须都在（防 500） ─────────────


def test_list_assets_columns_cover_serialize_asset_fields() -> None:
    """``list_assets`` 只查固定几列，``serialize_asset`` 读到的每个字段都必须在清单里。

    历史事故两次：2026-10-30 的 version/is_active/shield_wire、2026-11-01 的 test_line_id
    ——漏一列，整个资产列表接口直接 500 AttributeError（线上就是「ATP 模型管理页打不开」）。
    这条断言从源码层面兜住，新增字段忘了加列清单会立刻在这里失败。
    """
    import inspect
    import re

    from app.services import atp_asset_service as svc

    serialize_src = inspect.getsource(svc.serialize_asset)
    accessed = set(re.findall(r"\bitem\.([a-z_][a-z0-9_]*)", serialize_src))

    list_src = inspect.getsource(svc.list_assets)
    block = list_src[list_src.index("columns = (") : list_src.index("stmt = select(*columns)")]
    provided = set(re.findall(r"AtpAsset\.([a-z_][a-z0-9_]*)", block))

    missing = accessed - provided
    assert not missing, f"list_assets 少查了 serialize_asset 需要的列：{sorted(missing)}"


def test_list_assets_returns_test_line_id() -> None:
    """真实跑一遍列表：绑定测试线路的资产能正常序列化，不抛 AttributeError。"""
    from app.models.dimension_item import DimensionItem

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            AtpAsset.__table__,
            AtpAssetRun.__table__,
            DimensionItem.__table__,
        ],
    )
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()
    try:
        session.add(
            AtpAsset(
                code="TL-ASSET-1",
                name="测试线路绑定资产",
                status="enabled",
                voltage_level="220",
                tower_type="MT1",
                scene_type="plain",
                arrester_config="none",
                test_line_id="tl_demo_0001",
            )
        )
        session.commit()

        response = atp_asset_service.list_assets(
            session,
            keyword=None,
            status_filter=None,
            voltage_level=None,
            tower_type=None,
            scene_type=None,
        )

        assert response.total == 1
        assert response.items[0].test_line_id == "tl_demo_0001"
    finally:
        session.close()
