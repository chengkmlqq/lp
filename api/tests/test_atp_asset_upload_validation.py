"""ATP 模型上传白名单校验测试（2026-09-26 改造）。

覆盖：
1. _validate_atp_model_members：白名单扩展名 / .atp 入口 / 四个标准 .dat
2. upload_asset_files（zip 与散文件）：非法包 400 且**零写入**（校验失败不留脏数据）
3. upload_asset_archive（staging + 原子替换路径）同样受白名单约束
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRun
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.schemas.atp_asset import AtpAssetCreateRequest
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
            DimensionType.__table__,
            DimensionItem.__table__,
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


def _valid_entries() -> dict[str, bytes]:
    return {
        "work.atp": b"ATP INPUT",
        "long.dat": b"1",
        "short.dat": b"1",
        "dahao.dat": b"1",
        "xiaohao.dat": b"1",
    }


def _create_asset(session: Session, code: str = "ATP-ASSET-VALIDATE") -> AtpAsset:
    created = atp_asset_service.create_asset(
        session,
        AtpAssetCreateRequest(code=code, name="校验测试模型", description="上传校验测试"),
        actor_user_id="tester",
    )
    assert created is not None
    asset = session.query(AtpAsset).filter(AtpAsset.code == code).first()
    assert asset is not None
    return asset


# ---------------------------------------------------------------------------
# 纯函数：_validate_atp_model_members
# ---------------------------------------------------------------------------


def test_validate_accepts_valid_model_members() -> None:
    atp_asset_service._validate_atp_model_members(list(_valid_entries()))


def test_validate_rejects_illegal_extension() -> None:
    paths = ["work.atp", "long.dat", "short.dat", "dahao.dat", "xiaohao.dat", "short.lib"]
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members(paths)
    assert exc.value.status_code == 400
    assert "short.lib" in exc.value.detail
    assert ".atp / .dat" in exc.value.detail


def test_validate_rejects_no_atp_entry() -> None:
    paths = ["long.dat", "short.dat", "dahao.dat", "xiaohao.dat"]
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members(paths)
    assert exc.value.status_code == 400
    assert "work.atp" in exc.value.detail


def test_validate_rejects_multiple_atp_without_work_atp() -> None:
    paths = ["a.atp", "b.atp", "long.dat", "short.dat", "dahao.dat", "xiaohao.dat"]
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members(paths)
    assert exc.value.status_code == 400
    assert "2 个 .atp" in exc.value.detail


def test_validate_accepts_single_atp_without_work_atp() -> None:
    atp_asset_service._validate_atp_model_members(["model.atp", "long.dat", "short.dat", "dahao.dat", "xiaohao.dat"])


def test_validate_rejects_missing_standard_dat() -> None:
    paths = ["work.atp", "long.dat", "short.dat", "dahao.dat"]
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members(paths)
    assert exc.value.status_code == 400
    assert "xiaohao.dat" in exc.value.detail


def test_validate_rejects_empty() -> None:
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members([])
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 集成：upload_asset_files（zip 与散文件）
# ---------------------------------------------------------------------------


def test_upload_files_valid_zip_writes_all(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)

        updated = atp_asset_service.upload_asset_files(
            session,
            asset_id=asset.id,
            files=[_DummyUploadFile("model.zip", _build_zip(_valid_entries()))],
            actor_user_id="tester",
        )
        assert updated is not None

        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-VALIDATE"
        for name in ("work.atp", "long.dat", "short.dat", "dahao.dat", "xiaohao.dat"):
            assert (asset_root / name).is_file(), name
    finally:
        session.close()


def test_upload_files_zip_with_lib_rejected_zero_write(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)
        entries = dict(_valid_entries())
        entries["short.lib"] = b"lib"

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=asset.id,
                files=[_DummyUploadFile("model.zip", _build_zip(entries))],
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "short.lib" in exc.value.detail
        # 零写入：校验失败时存储目录不应残留任何文件
        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-VALIDATE"
        written = list(asset_root.rglob("*")) if asset_root.exists() else []
        assert written == []
    finally:
        session.close()


def test_upload_files_zip_missing_dat_rejected(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=asset.id,
                files=[_DummyUploadFile("model.zip", _build_zip({"work.atp": b"x", "long.dat": b"1"}))],
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "short.dat" in exc.value.detail
    finally:
        session.close()


def test_upload_files_loose_valid_pack(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)

        updated = atp_asset_service.upload_asset_files(
            session,
            asset_id=asset.id,
            files=[_DummyUploadFile(name, content) for name, content in _valid_entries().items()],
            actor_user_id="tester",
        )
        assert updated is not None
        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-VALIDATE"
        assert (asset_root / "work.atp").is_file()
    finally:
        session.close()


def test_upload_files_loose_single_file_rejected(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=asset.id,
                files=[_DummyUploadFile("work.atp", b"x")],
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "long.dat" in exc.value.detail
    finally:
        session.close()


def test_upload_files_loose_lib_rejected(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=asset.id,
                files=[_DummyUploadFile("short.lib", b"x")],
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "short.lib" in exc.value.detail
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 集成：upload_asset_archive（staging + 原子替换）同样受白名单约束
# ---------------------------------------------------------------------------


def test_upload_archive_rejects_lib_pack(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)
        entries = dict(_valid_entries())
        entries["work.pch"] = b"pch"

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_archive(
                session,
                asset_id=asset.id,
                archive_filename="model.zip",
                archive_content=_build_zip(entries),
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "work.pch" in exc.value.detail
        # staging 目录被清理，正式目录零残留
        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-VALIDATE"
        written = list(asset_root.rglob("*")) if asset_root.exists() else []
        assert written == []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 入口 .atp 形态校验：$INSERT / $INCLUDE+lib / Embed（2026-11-02）
# 判据是「几何引用形态」而非版本指纹大小写：指纹对应 6.x / 7.x 两代模板，
# 7.1 属于「7.x 模板 + 仍用 DBM」→ 混合大小写指纹 + $INCLUDE+lib，必须放行。
# ---------------------------------------------------------------------------

# 7.2+ 的 INSERT 形态（D:\ATP\110\ganzi\fanji\M123\work.atp 摘录）
_NEW_ATPDRAW_ATP = (
    b"BEGIN NEW DATA CASE\r\n"
    b"C ------------------------------------------------------------------------------\r\n"
    b"C Generated by ATPDraw \xca\xae\xd4\xc2, 3, 2026\r\n"
    b"C from project D:\\ATP\\110\\ganzi\\fanji\\M123\\work.acp\r\n"
    b"$INSERT, D:\\ATP\\110\\ganzi\\fanji\\M123\\short1.pch\r\n"
)

# 6.x 的 DBM 形态（D:\ATP\110\guxing\fanji\M123\work.atp 摘录）
_OLD_ATPDRAW_ATP = (
    b"BEGIN NEW DATA CASE\r\n"
    b"C --------------------------------------------------------\r\n"
    b"C Generated by ATPDRAW  \xca\xae\xd2\xbb\xd4\xc2, \xd0\xc7\xc6\xda\xb6\xfe 11, 2025\r\n"
    b"$INCLUDE, D:\\ATP\\110\\guxing\\fanji\\M123\\short.lib, X0202A, X0202B, X0202C $$\r\n"
)

# 7.1 的 DBM 形态：7.x 模板（混合大小写指纹）+ 仍走 $INCLUDE+lib
_SEVENTY_ONE_ATPDRAW_ATP = (
    b"BEGIN NEW DATA CASE\r\n"
    b"C ------------------------------------------------------------------------------\r\n"
    b"C Generated by ATPDraw \xca\xae\xd4\xc2, 3, 2026\r\n"
    b"C ATPDraw developed by H. K. H\xf8idalen at NTNU - NORWAY 1999-2020\r\n"
    b"$INCLUDE, D:\\ATP\\110\\guxing\\fanji\\M123\\short.lib, X0202A, X0202B, X0202C $$\r\n"
)

# 7.2+ 的 Embed 形态：punch 数据内嵌，无 $INSERT 也无 $INCLUDE
_EMBED_ATPDRAW_ATP = (
    b"BEGIN NEW DATA CASE\r\n"
    b"C ------------------------------------------------------------------------------\r\n"
    b"C Generated by ATPDraw \xca\xae\xd4\xc2, 3, 2026\r\n"
    b"C ATPDraw developed by H. K. H\xf8idalen at NTNU - NORWAY 1999-2020\r\n"
    b"LINE CONSTANTS\r\n"
    b"     1     3     3     0     0     0     0     0     0     0\r\n"
)


def test_entry_content_rejects_insert_form() -> None:
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_entry_content("work.atp", _NEW_ATPDRAW_ATP)
    assert exc.value.status_code == 400
    assert "$INSERT" in exc.value.detail
    assert "7.2" in exc.value.detail


def test_entry_content_accepts_old_atpdraw_fingerprint() -> None:
    atp_asset_service._validate_atp_entry_content("work.atp", _OLD_ATPDRAW_ATP)


def test_entry_content_accepts_71_include_form() -> None:
    """7.1：7.x 模板 + 混合大小写指纹，但仍是 DBM 的 $INCLUDE+lib → 必须放行。"""
    atp_asset_service._validate_atp_entry_content("work.atp", _SEVENTY_ONE_ATPDRAW_ATP)


def test_entry_content_rejects_embed_form() -> None:
    """7.2+ Embed：无 $INSERT 也无 $INCLUDE，几何内嵌 → 拒。"""
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_entry_content("work.atp", _EMBED_ATPDRAW_ATP)
    assert exc.value.status_code == 400
    assert "Embed" in exc.value.detail


def test_entry_content_accepts_no_fingerprint() -> None:
    # 手写 .atp（无版本指纹、无 LCC 引用）不拦截
    atp_asset_service._validate_atp_entry_content("work.atp", b"ATP INPUT\n")


def test_entry_content_rejects_insert_card() -> None:
    # 老版指纹 + $INSERT（手改或混合产物）：INSERT 型必须有序号 pch，一律拒绝
    insert_only = _OLD_ATPDRAW_ATP + b"$INSERT, D://ATP//110//guxing//fanji//M123//short1.pch/r/n"
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_entry_content("work.atp", insert_only)
    assert exc.value.status_code == 400
    assert "$INSERT" in exc.value.detail


def test_validate_rejects_pch_extension() -> None:
    # 2026-11-02：白名单收紧为 .atp / .dat，.pch 不再接受
    paths = ["work.atp", "long.dat", "short.dat", "dahao.dat", "xiaohao.dat", "short1.pch"]
    with pytest.raises(HTTPException) as exc:
        atp_asset_service._validate_atp_model_members(paths)
    assert exc.value.status_code == 400
    assert "short1.pch" in exc.value.detail


def test_upload_files_zip_new_atpdraw_rejected_zero_write(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)
        entries = dict(_valid_entries())
        entries["work.atp"] = _NEW_ATPDRAW_ATP

        with pytest.raises(HTTPException) as exc:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=asset.id,
                files=[_DummyUploadFile("model.zip", _build_zip(entries))],
                actor_user_id="tester",
            )
        assert exc.value.status_code == 400
        assert "ATPDraw" in exc.value.detail
        # 零写入：校验失败时存储目录不应残留任何文件
        asset_root = tmp_path / "vfs" / "atp-assets" / "ATP-ASSET-VALIDATE"
        written = list(asset_root.rglob("*")) if asset_root.exists() else []
        assert written == []
    finally:
        session.close()
