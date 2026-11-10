from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRun
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
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


def test_create_asset_and_upload_archive(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-001", name="目录化ATP资产", description="测试资产"),
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


def test_create_asset_auto_increments_version_per_dimension_group(tmp_path) -> None:
    """未传 version 时按同维度组合递增（表单已去掉版本号，2026-11-03）。"""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        dims = {
            "voltage_level": "110kV",
            "tower_type": "猫头塔",
            "scene_type": "反击",
            "arrester_config": "双侧",
        }
        first = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-AUTO-V1", name="自动版本 1", description="测试", **dims),
            actor_user_id="tester",
        )
        second = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-AUTO-V2", name="自动版本 2", description="测试", **dims),
            actor_user_id="tester",
        )
        other_group = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-AUTO-OTHER",
                name="其它组合",
                description="测试",
                **{**dims, "voltage_level": "220kV"},
            ),
            actor_user_id="tester",
        )
        # 显式指定版本仍然尊重入参，不参与自动递增
        explicit = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-AUTO-EXPLICIT",
                name="显式版本",
                description="测试",
                version="v9-rc1",
                **dims,
            ),
            actor_user_id="tester",
        )

        assert first is not None and second is not None
        assert other_group is not None and explicit is not None
        assert first.version == "v1"
        assert second.version == "v2"
        assert other_group.version == "v1"
        assert explicit.version == "v9-rc1"
        assert second.storage_root_path != first.storage_root_path
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
                description="测试资产",
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


@pytest.mark.skip(
    reason="存量失效：dry-run 已改为 POST /assets/{id}/test-runs + worker execute_asset_run_job(run_id) 异步链路，"
    "旧的同步 execute_asset_run_job(session, asset_id=...) 入口已删除（2026-11-02 记录，待按新链路重写）"
)
def test_run_asset_dry_run_materializes_directory(tmp_path, monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        asset_root = tmp_path / "vfs" / "atp-assets" / "runtime-asset"
        asset_root.mkdir(parents=True)
        (asset_root / "work.atp").write_text("ATP INPUT", encoding="utf-8")
        (asset_root / "tpbig.exe").write_text("binary", encoding="utf-8")

        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ATP-ASSET-DRY", name="Dry Run 资产", description="测试资产"),
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
                description="测试资产",
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
                    description="测试资产",
                    voltage_level="220",
                    tower_type="fanji",
                    scene_type="raoji3",
                    arrester_config="M123",
                    version=f"v{index}",
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
    # 两种读取方式都要覆盖：
    #   ① 直接属性访问 `item.xxx`
    #   ② 容错读取 `_row_field(item, "xxx")` —— 2026-11-02 起新增列走这条，
    #      若只匹配 ①，改动后就再也守不住「漏加列」这类事故
    accessed = set(re.findall(r"\bitem\.([a-z_][a-z0-9_]*)", serialize_src))
    accessed |= set(re.findall(r'_row_field\(\s*item\s*,\s*"([a-z_][a-z0-9_]*)"', serialize_src))

    list_src = inspect.getsource(svc.list_assets)
    block = list_src[list_src.index("columns = (") : list_src.index("stmt = select(*columns)")]
    provided = set(re.findall(r"AtpAsset\.([a-z_][a-z0-9_]*)", block))

    missing = accessed - provided
    assert not missing, f"list_assets 少查了 serialize_asset 需要的列：{sorted(missing)}"


def test_list_assets_returns_test_line_id() -> None:
    """真实跑一遍列表：绑定测试线路的资产能正常序列化，不抛 AttributeError。"""
    from app.models.dimension_item import DimensionItem
    from app.models.dimension_type import DimensionType

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


def test_list_assets_returns_model_format_and_check() -> None:
    """列表接口必须带出形态标记与预检报告（2026-11-02 事故回归）。

    事故：新增 model_format / format_check_json 后忘了加进 list_assets 的列白名单，
    Row 取不到列抛 KeyError → 列表 500 → 线上「ATP 模型管理页加载失败」。
    这里既验证值能取到，也验证存量行（未写过该字段）回落 legacy 而不是空。
    """
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
        session.add_all(
            [
                AtpAsset(
                    code="FMT-INSERT-1",
                    name="7.3 INSERT 形态资产",
                    status="enabled",
                    voltage_level="110",
                    tower_type="MT1",
                    scene_type="plain",
                    arrester_config="M123",
                    model_format="insert",
                    format_check_json={
                        "model_format": "insert",
                        "error_count": 0,
                        "warning_count": 1,
                        "issues": [{"code": "W001", "level": "warning", "message": "参数段有 $$", "fix_hint": "系统自动处理"}],
                    },
                ),
                AtpAsset(
                    code="FMT-STORE-1",
                    name="存量资产（未写形态字段）",
                    status="enabled",
                    voltage_level="110",
                    tower_type="MT1",
                    scene_type="plain",
                    arrester_config="none",
                ),
            ]
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

        by_code = {item.code: item for item in response.items}
        insert_item = by_code["FMT-INSERT-1"]
        assert insert_item.model_format == "insert"
        assert insert_item.model_format_label  # 有中文标签，不能是 None
        assert insert_item.format_check is not None
        assert insert_item.format_check["warning_count"] == 1

        legacy_item = by_code["FMT-STORE-1"]
        assert legacy_item.model_format == "legacy"
        assert legacy_item.format_check is None
    finally:
        session.close()


# 2026-11-03 生产事故回归：model_format 列是后来加的，DB 迁移给存量行填了默认值
# legacy；存量里的 7.2+ $INSERT 模型于是显示成「老版」。recheck_asset_format 必须按
# 存储里的真实 work.atp 重判，而不是继续沿用默认值。
_INSERT_FORM_ATP = b"""C Generated by ATPDraw 10 3, 2026
C ATPDraw developed by H. K. Hoidalen
$INSERT, D://ATP//work//results//long3.pch
$PARAMETER
RER001=5. $$
U2I =500 $$
PHAGA_____=U2I
BLANK
"""
_INSERT_FORM_PCH = b"-1X0133AXXSS2A\n-1X0133BXXSS2B\n"


def test_recheck_asset_format_overrides_legacy_default(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-RECHECK-INSERT",
                name="存量新版模型",
                description="存量行为：库里默认 legacy，文件是 $INSERT",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
            ),
            actor_user_id="tester",
        )
        assert asset is not None
        # 库里此时是列默认值
        assert asset.model_format == "legacy"

        mount = atp_asset_service._resolve_mount(session, "main")
        driver = atp_asset_service._build_driver_or_400(mount)
        storage_root = asset.storage_root_path or ""
        driver.ensure_directory(storage_root)
        driver.write_file(f"{storage_root}/work.atp", content=_INSERT_FORM_ATP, content_type="text/plain")
        driver.write_file(f"{storage_root}/long3.pch", content=_INSERT_FORM_PCH, content_type="text/plain")

        updated = atp_asset_service.recheck_asset_format(
            session,
            asset_id=asset.id,
            actor_user_id="tester",
        )

        assert updated.model_format == "insert"
        assert updated.format_check is not None
        assert updated.format_check["model_format"] == "insert"
        assert updated.format_check["error_count"] == 0
        assert "long3.pch" in updated.format_check["insert_refs"]

        persisted = session.get(AtpAsset, asset.id)
        assert persisted is not None
        assert persisted.model_format == "insert"
    finally:
        session.close()


def test_recheck_asset_format_without_model_files_reports_conflict(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-RECHECK-EMPTY",
                name="空目录模型",
                description="没有任何模型文件",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
            ),
            actor_user_id="tester",
        )
        assert asset is not None
        mount = atp_asset_service._resolve_mount(session, "main")
        driver = atp_asset_service._build_driver_or_400(mount)
        storage_root = asset.storage_root_path or ""
        driver.ensure_directory(storage_root)

        with pytest.raises(atp_asset_service.HTTPException) as excinfo:
            atp_asset_service.recheck_asset_format(session, asset_id=asset.id, actor_user_id="tester")
        # 空目录不能静默写成 plain，要明确告诉人工「先传文件」
        assert excinfo.value.status_code == 409
        assert "没有 .atp" in str(excinfo.value.detail)
    finally:
        session.close()


# ===== 异步分析（形态识别 + 槽位扫描）=====
# 2026-11-03：上传后自动触发的 Celery 任务。这组用例覆盖四个关键行为：
#   1) 调度后立刻落 pending + 换 token；2) broker 不可用时落 failed 而不是 500；
#   3) 任务主体一次读包同时写形态与槽位；4) token 被换掉后旧任务不覆盖新结果。


def _make_asset_with_insert_package(session: Session, root_dir: Path, code: str) -> AtpAsset:
    _seed_vfs_mount(session, root_dir=root_dir)
    asset = atp_asset_service.create_asset(
        session,
        AtpAssetCreateRequest(
            code=code,
            name="异步分析样本",
            description="7.3 $INSERT 形态",
            voltage_level="110",
            tower_type="M123",
            scene_type="fanji",
        ),
        actor_user_id="tester",
    )
    assert asset is not None
    mount = atp_asset_service._resolve_mount(session, "main")
    driver = atp_asset_service._build_driver_or_400(mount)
    storage_root = asset.storage_root_path or ""
    driver.ensure_directory(storage_root)
    driver.write_file(f"{storage_root}/work.atp", content=_INSERT_FORM_ATP, content_type="text/plain")
    driver.write_file(f"{storage_root}/long3.pch", content=_INSERT_FORM_PCH, content_type="text/plain")
    driver.write_file(f"{storage_root}/long.dat", content=b"  1.000     0.000\n", content_type="text/plain")
    # create_asset 返回的是 pydantic 摘要，这里取 ORM 行以便用例直接改分析状态
    db_asset = session.get(AtpAsset, asset.id)
    assert db_asset is not None
    return db_asset


def test_schedule_asset_analysis_marks_pending(monkeypatch, tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        asset = _make_asset_with_insert_package(session, tmp_path / "vfs", "ATP-ASYNC-PENDING")
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            atp_asset_service,
            "_enqueue_asset_analysis",
            lambda asset_id, token: calls.append((asset_id, token)) or "task-1",
        )

        summary = atp_asset_service.schedule_asset_analysis(
            session, asset_id=asset.id, actor_user_id="tester"
        )

        assert summary.analysis_status == "pending"
        assert summary.analysis_error is None
        assert len(calls) == 1 and calls[0][0] == asset.id
        persisted = session.get(AtpAsset, asset.id)
        assert persisted is not None
        # token 必须落库，任务回写前要拿它比对
        assert persisted.analysis_token == calls[0][1]
    finally:
        session.close()


def test_schedule_asset_analysis_marks_failed_when_broker_unavailable(monkeypatch, tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        asset = _make_asset_with_insert_package(session, tmp_path / "vfs", "ATP-ASYNC-BROKER")
        monkeypatch.setattr(atp_asset_service, "_enqueue_asset_analysis", lambda asset_id, token: None)

        summary = atp_asset_service.schedule_asset_analysis(session, asset_id=asset.id)

        # broker 挂了不能让上传/重判请求 500，要落成可读的失败态
        assert summary.analysis_status == "failed"
        assert "入队失败" in (summary.analysis_error or "")
        assert summary.analysis_finished_at is not None
    finally:
        session.close()


def test_run_asset_analysis_writes_format_and_slots(monkeypatch, tmp_path) -> None:
    import app.core.database as database_module

    testing_session = _build_sessionmaker()
    monkeypatch.setattr(database_module, "SessionLocal", testing_session)
    session: Session = testing_session()
    try:
        asset = _make_asset_with_insert_package(session, tmp_path / "vfs", "ATP-ASYNC-RUN")
        asset.analysis_status = "pending"
        asset.analysis_token = "tok-run"
        session.commit()

        outcome = atp_asset_service.run_asset_analysis(asset_id=asset.id, token="tok-run")

        assert outcome["status"] == "success"
        persisted = session.get(AtpAsset, asset.id)
        assert persisted is not None
        session.refresh(persisted)
        assert persisted.analysis_status == "success"
        assert persisted.analysis_error is None
        assert persisted.analysis_finished_at is not None
        # 形态与槽位在同一次读包里产出
        assert persisted.model_format == "insert"
        assert (persisted.slots_json or {}).get("work_atp", {}).get("count")
    finally:
        session.close()


def test_run_asset_analysis_skips_stale_token(monkeypatch, tmp_path) -> None:
    import app.core.database as database_module

    testing_session = _build_sessionmaker()
    monkeypatch.setattr(database_module, "SessionLocal", testing_session)
    session: Session = testing_session()
    try:
        asset = _make_asset_with_insert_package(session, tmp_path / "vfs", "ATP-ASYNC-STALE")
        asset.analysis_status = "pending"
        asset.analysis_token = "tok-new"  # 已经被更新的调度换过
        session.commit()

        outcome = atp_asset_service.run_asset_analysis(asset_id=asset.id, token="tok-old")

        assert outcome == {"status": "skipped", "reason": "stale_token"}
        persisted = session.get(AtpAsset, asset.id)
        assert persisted is not None
        session.refresh(persisted)
        # 旧任务不得改写状态与形态
        assert persisted.analysis_status == "pending"
        assert persisted.model_format == "legacy"
    finally:
        session.close()


def test_run_asset_analysis_marks_failed_without_files(monkeypatch, tmp_path) -> None:
    import app.core.database as database_module

    testing_session = _build_sessionmaker()
    monkeypatch.setattr(database_module, "SessionLocal", testing_session)
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASYNC-EMPTY",
                name="空目录",
                description="没有模型文件",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
            ),
            actor_user_id="tester",
        )
        assert asset is not None
        db_asset = session.get(AtpAsset, asset.id)
        assert db_asset is not None
        db_asset.analysis_status = "pending"
        db_asset.analysis_token = "tok-empty"
        session.commit()

        outcome = atp_asset_service.run_asset_analysis(asset_id=asset.id, token="tok-empty")

        assert outcome["status"] == "failed"
        # 从未传过文件 → 目录不存在；空目录 → 没有 .atp。两种情况都要引导「先传文件」
        assert "请先上传模型文件" in outcome["error"]
        persisted = session.get(AtpAsset, asset.id)
        assert persisted is not None
        session.refresh(persisted)
        assert persisted.analysis_status == "failed"
        assert "请先上传模型文件" in (persisted.analysis_error or "")
    finally:
        session.close()


def test_upload_asset_files_triggers_async_analysis(monkeypatch, tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="ATP-ASYNC-UPLOAD",
                name="上传触发",
                description="上传后应自动入队",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
            ),
            actor_user_id="tester",
        )
        assert asset is not None
        calls: list[str] = []
        monkeypatch.setattr(
            atp_asset_service,
            "_enqueue_asset_analysis",
            lambda asset_id, token: calls.append(asset_id) or "task-upload",
        )

        summary = atp_asset_service.upload_asset_files(
            session,
            asset_id=asset.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
        )

        assert calls == [asset.id]
        assert summary.analysis_status == "pending"
        # 上传口仍然同步落形态（内容已在内存，毫秒级），异步任务负责复检 + 槽位
        assert summary.model_format == "insert"
    finally:
        session.close()


def test_stale_pending_analysis_is_downgraded_to_failed(tmp_path) -> None:
    """队列没有消费者时 pending 会永远挂着，列表会无限轮询 —— 超时按失败展示。"""
    from datetime import datetime, timedelta, timezone

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        asset = _make_asset_with_insert_package(session, tmp_path / "vfs", "ATP-ASYNC-STALE-PENDING")
        asset.analysis_status = "pending"
        asset.analysis_token = "tok-slow"
        asset.analysis_started_at = datetime.now(timezone.utc) - timedelta(minutes=11)
        session.commit()

        summary = atp_asset_service.serialize_asset(
            asset, run_count=0, last_run_status=None, last_run_date=None, db=session
        )

        assert summary.analysis_status == "failed"
        assert "10 分钟" in (summary.analysis_error or "")

        # 刚入队的 pending 不受影响
        asset.analysis_started_at = datetime.now(timezone.utc)
        session.commit()
        fresh = atp_asset_service.serialize_asset(
            asset, run_count=0, last_run_status=None, last_run_date=None, db=session
        )
        assert fresh.analysis_status == "pending"
    finally:
        session.close()


def test_list_assets_filters_by_publish_status() -> None:
    """发布状态过滤（2026-11-10）：true=已发布 / false=未发布 / 不传=全部。

    ATP 模型管理页是服务端分页，过滤必须落在 SQL 上并同时收窄 total，
    否则翻页与卡片数会对不上。
    """
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        session.add_all(
            [
                AtpAsset(code="PUB-1", name="已发布模型", status="enabled", is_published=True),
                AtpAsset(code="PUB-2", name="未发布模型", status="enabled", is_published=False),
            ]
        )
        session.commit()

        def snapshot(**filters):
            response = atp_asset_service.list_assets(
                session,
                keyword=None,
                status_filter=None,
                voltage_level=None,
                tower_type=None,
                scene_type=None,
                **filters,
            )
            return response.total, {item.code for item in response.items}

        assert snapshot() == (2, {"PUB-1", "PUB-2"})
        assert snapshot(is_published=True) == (1, {"PUB-1"})
        assert snapshot(is_published=False) == (1, {"PUB-2"})
    finally:
        session.close()


# ===== 发布生命周期四态 + 变更版本派生（2026-11-10）=====


def test_publish_state_lifecycle(tmp_path) -> None:
    """新建 → 已发布 → 下线 → 重新发布，publish_state 与 is_published 同步维护。"""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        created = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="STATE-1", name="状态流转", description="测试"),
            actor_user_id="tester",
        )
        assert created is not None
        assert created.publish_state == "new"
        assert created.is_published is False

        published = atp_asset_service.publish_asset(session, asset_id=created.id, actor_user_id="tester")
        assert published.publish_state == "published"
        assert published.is_published is True

        offline = atp_asset_service.unpublish_asset(session, asset_id=created.id, actor_user_id="tester")
        assert offline.publish_state == "offline"
        assert offline.is_published is False

        online = atp_asset_service.publish_asset(session, asset_id=created.id, actor_user_id="tester")
        assert online.publish_state == "published"
    finally:
        session.close()


def test_upload_to_published_asset_forks_changed_version(monkeypatch, tmp_path) -> None:
    """已发布模型再次上传文件 → 派生 changed 新版本；旧版本文件与状态保持可用。"""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        monkeypatch.setattr(
            atp_asset_service, "_enqueue_asset_analysis", lambda asset_id, token: "task"
        )
        dims = {
            "voltage_level": "110",
            "tower_type": "M123",
            "scene_type": "fanji",
            "arrester_config": "M1",
        }
        created = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="FORK-1", name="覆盖上传", description="测试", **dims),
            actor_user_id="tester",
        )
        assert created is not None
        first = atp_asset_service.upload_asset_files(
            session,
            asset_id=created.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
        )
        assert first.id == created.id
        assert first.publish_state == "new"

        published = atp_asset_service.publish_asset(
            session, asset_id=created.id, set_active=True, actor_user_id="tester"
        )
        assert published.publish_state == "published"
        assert published.is_active is True
        old_root = published.storage_root_path
        assert old_root

        forked = atp_asset_service.upload_asset_files(
            session,
            asset_id=created.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
            replace=True,
        )

        # 新版本：变更态、未发布、不生效、版本号递增、目录独立
        assert forked.id != created.id
        assert forked.publish_state == "changed"
        assert forked.is_published is False
        assert forked.is_active is False
        assert forked.version == "v2"
        assert forked.code == "FORK-1-v2"
        assert forked.storage_root_path != old_root

        # 旧版本：文件、发布状态、生效标记全部原样，仿真不会断档
        old = atp_asset_service.get_asset_by_id(session, created.id)
        assert old is not None
        assert old.publish_state == "published"
        assert old.is_published is True
        assert old.is_active is True
        assert old.storage_root_path == old_root
        assert atp_asset_service.list_asset_files(session, asset_id=old.id).total > 0
        assert atp_asset_service.list_asset_files(session, asset_id=forked.id).total > 0

        # 再次上传「变更版本」的文件仍派生出更新的版本（不会原地覆盖变更版本本身）
        again = atp_asset_service.upload_asset_files(
            session,
            asset_id=forked.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
            replace=True,
        )
        assert again.id == forked.id  # changed 不是已发布态，原地覆盖自己的目录
        assert again.publish_state == "changed"
    finally:
        session.close()


def test_activate_requires_published_version(tmp_path) -> None:
    """版本切换只允许切到已发布版本，未发布/变更/下线版本一律拒绝。"""
    from fastapi import HTTPException

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(code="ACT-1", name="生效校验", description="测试"),
            actor_user_id="tester",
        )
        assert asset is not None
        with pytest.raises(HTTPException) as excinfo:
            atp_asset_service.activate_asset(session, asset_id=asset.id, actor_user_id="tester")
        assert excinfo.value.status_code == 400

        atp_asset_service.publish_asset(session, asset_id=asset.id, actor_user_id="tester")
        activated = atp_asset_service.activate_asset(session, asset_id=asset.id, actor_user_id="tester")
        assert activated.is_active is True
    finally:
        session.close()


def test_list_assets_filter_by_publish_state(tmp_path) -> None:
    """四态过滤：含 publish_state=NULL 的存量行按 is_published/published_date 兜底归类。"""
    from datetime import datetime, timezone

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        session.add_all(
            [
                AtpAsset(code="PS-NEW", name="新建", status="enabled", is_published=False, publish_state="new"),
                AtpAsset(code="PS-CHG", name="变更", status="enabled", is_published=False, publish_state="changed"),
                AtpAsset(code="PS-PUB", name="已发布", status="enabled", is_published=True, publish_state="published"),
                AtpAsset(code="PS-OFF", name="下线", status="enabled", is_published=False, publish_state="offline"),
                # 加列前的存量行：只有 is_published / published_date
                AtpAsset(code="PS-LEGACY-PUB", name="存量已发布", status="enabled", is_published=True),
                AtpAsset(
                    code="PS-LEGACY-OFF",
                    name="存量下线",
                    status="enabled",
                    is_published=False,
                    published_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                AtpAsset(code="PS-LEGACY-NEW", name="存量未发布", status="enabled", is_published=False),
            ]
        )
        session.commit()

        def snapshot(state: str):
            response = atp_asset_service.list_assets(
                session,
                keyword=None,
                status_filter=None,
                voltage_level=None,
                tower_type=None,
                scene_type=None,
                publish_state=state,
            )
            return response.total, {item.code for item in response.items}

        assert snapshot("new") == (2, {"PS-NEW", "PS-LEGACY-NEW"})
        assert snapshot("changed") == (1, {"PS-CHG"})
        assert snapshot("published") == (2, {"PS-PUB", "PS-LEGACY-PUB"})
        assert snapshot("offline") == (2, {"PS-OFF", "PS-LEGACY-OFF"})

        # 四态合计覆盖全部资产，不重不漏
        totals = {state: snapshot(state)[0] for state in ("new", "changed", "published", "offline")}
        assert sum(totals.values()) == 7
    finally:
        session.close()


def test_failed_upload_rolls_back_forked_changed_version(monkeypatch, tmp_path) -> None:
    """预检失败的上传不能留下空「变更」版本（否则列表里会多出 0 文件的脏版本）。"""
    from fastapi import HTTPException
    from sqlalchemy import func, select

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        monkeypatch.setattr(
            atp_asset_service, "_enqueue_asset_analysis", lambda asset_id, token: "task"
        )
        created = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="FORK-FAIL",
                name="失败回滚",
                description="测试",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
                arrester_config="M1",
            ),
            actor_user_id="tester",
        )
        assert created is not None
        atp_asset_service.upload_asset_files(
            session,
            asset_id=created.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
        )
        atp_asset_service.publish_asset(session, asset_id=created.id, set_active=True, actor_user_id="tester")

        with pytest.raises(HTTPException) as excinfo:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=created.id,
                # 只有 pch、没有 work.atp 入口 → 校验 400
                files=[_DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
                actor_user_id="tester",
                replace=True,
            )
        assert excinfo.value.status_code == 400

        # 派生的变更版本已被撤回：资产总数仍为 1，原版本仍是已发布 + 生效
        total = session.execute(select(func.count()).select_from(AtpAsset)).scalar()
        assert int(total or 0) == 1
        old = atp_asset_service.get_asset_by_id(session, created.id)
        assert old is not None
        assert old.publish_state == "published"
        assert old.is_active is True
        assert atp_asset_service.list_asset_files(session, asset_id=old.id).total > 0
    finally:
        session.close()


def test_failed_upload_rolls_back_forked_changed_version(monkeypatch, tmp_path) -> None:
    """预检失败的上传不能留下空「变更」版本（否则列表里会多出 0 文件的脏版本）。"""
    from fastapi import HTTPException
    from sqlalchemy import func, select

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        monkeypatch.setattr(
            atp_asset_service, "_enqueue_asset_analysis", lambda asset_id, token: "task"
        )
        created = atp_asset_service.create_asset(
            session,
            AtpAssetCreateRequest(
                code="FORK-FAIL",
                name="失败回滚",
                description="测试",
                voltage_level="110",
                tower_type="M123",
                scene_type="fanji",
                arrester_config="M1",
            ),
            actor_user_id="tester",
        )
        assert created is not None
        atp_asset_service.upload_asset_files(
            session,
            asset_id=created.id,
            files=[_DummyUploadFile("work.atp", _INSERT_FORM_ATP), _DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
            actor_user_id="tester",
        )
        atp_asset_service.publish_asset(session, asset_id=created.id, set_active=True, actor_user_id="tester")

        with pytest.raises(HTTPException) as excinfo:
            atp_asset_service.upload_asset_files(
                session,
                asset_id=created.id,
                # 只有 pch、没有 work.atp 入口 → 校验 400
                files=[_DummyUploadFile("long3.pch", _INSERT_FORM_PCH)],
                actor_user_id="tester",
                replace=True,
            )
        assert excinfo.value.status_code == 400

        # 派生的变更版本已被撤回：资产总数仍为 1，原版本仍是已发布 + 生效
        total = session.execute(select(func.count()).select_from(AtpAsset)).scalar()
        assert int(total or 0) == 1
        old = atp_asset_service.get_asset_by_id(session, created.id)
        assert old is not None
        assert old.publish_state == "published"
        assert old.is_active is True
        assert atp_asset_service.list_asset_files(session, asset_id=old.id).total > 0
    finally:
        session.close()
