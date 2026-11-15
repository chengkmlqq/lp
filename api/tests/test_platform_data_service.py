"""Integration test for LP-14 平台基础数据包导出/导入（sqlite + VFS 存储）。

覆盖验收点：
1. 导出生成顶层 manifest + 三类子目录，产物落存储可下载。
2. 导入按自然键幂等写入（维度 code / 参数 key / ATP code+version），重复导入不产生重复行。
3. schema_version 不符的包导入 -> 任务 failed 且报错原因明确。
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile

# 必须在导入任何 app 模块前固定 dialect 为 sqlite
os.environ["DATABASE_URL"] = "sqlite://"

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401  (注册所有表到 metadata)
from app.core.database import Base
from app.models.atp_asset import AtpAssetVersion
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.file_storage import FileStorageBackend, FileStorageMount
from app.models.param_category import SystemParamCategory
from app.models.platform_data_job import PlatformDataJob
from app.models.system_param import SystemParam
from app.services import platform_data_service as svc
from app.services.atp_asset_service import _publish_change as _atp_publish_change  # noqa: E402


def _new_session() -> tuple[Session, any]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _seed_storage(db: Session) -> None:
    backend = FileStorageBackend(
        code="local",
        name="Local VFS",
        driver_type="VFS",
        status="enabled",
        is_default=True,
        config_json={"root_dir": tempfile.mkdtemp(prefix="lp-pd-")},
    )
    db.add(backend)
    db.flush()
    mount = FileStorageMount(
        code="main",
        name="Main",
        backend_id=backend.id,
        mount_path="/",
        root_path="/",
        is_enabled=True,
    )
    db.add(mount)
    db.commit()


def _seed_business(db: Session) -> None:
    root = DimensionType(code="root", name="根维度", is_enabled=True, sort_order=0)
    db.add(root)
    db.flush()
    sub = DimensionType(code="sub", name="子维度", parent_id=root.id, is_enabled=True, sort_order=1)
    db.add(sub)
    db.flush()
    item = DimensionItem(
        code="item1",
        name="维度项1",
        dimension_type="sub",
        type_id=sub.id,
        is_enabled=True,
        sort_order=0,
        extra_json={"k": 1},
    )
    db.add(item)

    cat = SystemParamCategory(name="基础配置")
    db.add(cat)
    db.flush()
    db.add(
        SystemParam(
            param_key="site.name",
            param_name="站点名称",
            param_value="测试站",
            is_encrypted=False,
            description="站点名",
            status="enabled",
            category_id=cat.id,
        )
    )
    db.commit()


def _seed_asset(db: Session) -> None:
    """创建一个启用且带 work.atp 的 ATP 模型（VFS 存储），供导出/导入 ATP 使用。"""
    # 直接构造版本行（绕开 create_asset 的复杂依赖，专注导出/导入链路）
    asset = AtpAssetVersion(
        code="ATP66-test",
        version_code="ATP66-test-v1",
        name="测试模型",
        description="导出导入测试模型",
        status="enabled",
        voltage_level="500kV",
        tower_type="cathead",
        version="v1",
        is_active=True,
        is_published=True,
        model_format="legacy",
        storage_mount_code="main",
        storage_root_path="/atp/ATP66-test-v1",
        create_user="seed",
        update_user="seed",
    )
    db.add(asset)
    db.commit()
    # 写入 work.atp
    mount = db.scalar(select(FileStorageMount).where(FileStorageMount.code == "main"))
    from app.services.storage_driver import build_storage_driver

    driver = build_storage_driver(mount.backend, mount)
    driver.ensure_directory(asset.storage_root_path)
    driver.write_file(f"{asset.storage_root_path}/work.atp", content=b"TEST ATP CONTENT", content_type="text/plain")


def _seed_filter_assets(db: Session) -> None:
    """创建 4 个启用模型，覆盖电压/塔型/场景多值筛选的组合。"""
    specs = [
        ("M-500-CAT-PLAIN", "500kV", "cathead", "plain"),
        ("M-500-CAT-MTN", "500kV", "cathead", "mountain"),
        ("M-220-CAT-PLAIN", "220kV", "cathead", "plain"),
        ("M-500-CUP-PLAIN", "500kV", "cup", "plain"),
    ]
    mount = db.scalar(select(FileStorageMount).where(FileStorageMount.code == "main"))
    from app.services.storage_driver import build_storage_driver

    driver = build_storage_driver(mount.backend, mount)
    for code, voltage, tower, scene in specs:
        root = f"/atp/{code}-v1"
        db.add(
            AtpAssetVersion(
                code=code,
                version_code=f"{code}-v1",
                name=code,
                description=code,
                status="enabled",
                voltage_level=voltage,
                tower_type=tower,
                scene_type=scene,
                version="v1",
                is_active=True,
                is_published=True,
                model_format="legacy",
                storage_mount_code="main",
                storage_root_path=root,
                create_user="seed",
                update_user="seed",
            )
        )
        driver.ensure_directory(root)
        driver.write_file(f"{root}/work.atp", content=f"ATP {code}".encode(), content_type="text/plain")
    db.commit()


def _export_atp_manifest(db: Session, filters: dict) -> dict:
    """导出 atp_models 类别并返回内层 ATP manifest；无匹配时返回空 assets。"""
    content, _ = svc.build_export_bundle(db, categories=["atp_models"], filters=filters)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        if "atp_models/manifest.json" not in z.namelist():
            return {"assets": [], "filters": {}, "total_assets": 0}
        return json.loads(z.read("atp_models/manifest.json"))


def _run_export(db: Session, categories, filters=None) -> PlatformDataJob:
    job = PlatformDataJob(kind="export", status="pending", request_payload_json={"categories": categories, "filters": filters or {}})
    db.add(job)
    db.commit()
    try:
        svc.run_export_job(db, job.id)
    except Exception:
        # 任务失败信息已落到 job 行，celery 侧会再次抛出；测试以 job 行为准
        pass
    db.refresh(job)
    return job


def _run_import(db: Session, content: bytes) -> PlatformDataJob:
    job = PlatformDataJob(kind="import", status="pending", request_payload_json={"source": "upload"})
    db.add(job)
    db.commit()
    mount = db.scalar(select(FileStorageMount).where(FileStorageMount.code == "main"))
    path, fid = svc._store_artifact(db, mount=mount, content=content, storage_path=f"/platform-data/imports/test-{job.id}.zip", actor_user_id="tester")
    job.artifact_storage_path = path
    job.artifact_file_id = fid
    db.commit()
    try:
        svc.run_import_job(db, job.id)
    except Exception:
        pass
    db.refresh(job)
    return job


def test_export_bundle_structure():
    db = _new_session()
    _seed_storage(db)
    _seed_business(db)
    _seed_asset(db)

    content, manifest = svc.build_export_bundle(db, categories=["dimensions", "system_params", "atp_models"])
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = set(z.namelist())
        assert "manifest.json" in names
        assert "dimensions/dimensions.json" in names
        assert "system_params/system_params.json" in names
        assert "atp_models/manifest.json" in names
        assert "atp_models/ATP66-test_v1/work.atp" in names
    assert manifest["bundle_schema_version"] == svc.BUNDLE_SCHEMA_VERSION
    assert manifest["counts"]["dimensions"] == 3  # 2 类型 + 1 项
    assert manifest["counts"]["system_params"] == 1
    assert manifest["counts"]["atp_models"] == 1
    db.close()


def test_export_job_and_download():
    db = _new_session()
    _seed_storage(db)
    _seed_business(db)
    job = _run_export(db, ["dimensions", "system_params"])
    assert job.status == "success"
    assert job.artifact_storage_path is not None
    filename, content, mime = svc.download_job_artifact(db, job.id)
    assert content[:2] == b"PK"  # zip magic
    assert filename.startswith("platform-data-export-")
    db.close()


def test_import_idempotent():
    # 源库 A：导出
    db_a = _new_session()
    _seed_storage(db_a)
    _seed_business(db_a)
    export_job = _run_export(db_a, ["dimensions", "system_params"])
    assert export_job.status == "success"
    content = svc.download_job_artifact(db_a, export_job.id)[1]

    # 目标库 B：首次导入（应创建）
    db_b = _new_session()
    _seed_storage(db_b)
    import_job = _run_import(db_b, content)
    assert import_job.status == "success", import_job.error_message
    s = import_job.result_summary_json
    assert s["dimensions"]["created"] == 3, s
    assert s["system_params"]["created"] == 1, s
    assert db_b.scalar(select(func.count()).select_from(DimensionType)) == 2
    assert db_b.scalar(select(func.count()).select_from(DimensionItem)) == 1
    assert db_b.scalar(select(func.count()).select_from(SystemParam)) == 1
    # 父子关联保留
    sub = db_b.scalar(select(DimensionType).where(DimensionType.code == "sub"))
    assert sub.parent_id is not None

    # 目标库 B：再次导入同一包（应更新、不新增）
    import_job2 = _run_import(db_b, content)
    assert import_job2.status == "success", import_job2.error_message
    s2 = import_job2.result_summary_json
    assert s2["dimensions"]["created"] == 0, s2
    assert s2["dimensions"]["updated"] == 3, s2
    assert db_b.scalar(select(func.count()).select_from(DimensionType)) == 2
    assert db_b.scalar(select(func.count()).select_from(SystemParam)) == 1
    db_a.close()
    db_b.close()


def test_atp_import_idempotent():
    # A：带 ATP 模型
    db_a = _new_session()
    _seed_storage(db_a)
    _seed_asset(db_a)
    export_job = _run_export(db_a, ["atp_models"])
    assert export_job.status == "success"
    content = svc.download_job_artifact(db_a, export_job.id)[1]

    # B：首次导入（创建资产）；再次导入（幂等更新）
    db_b = _new_session()
    _seed_storage(db_b)
    with _patched_publish():
        job1 = _run_import(db_b, content)
        assert job1.status == "success", job1.error_message
        assert job1.result_summary_json["atp_models"]["created"] == 1, job1.result_summary_json
        assert db_b.scalar(select(func.count()).select_from(AtpAssetVersion)) == 1

        job2 = _run_import(db_b, content)
        assert job2.status == "success", job2.error_message
        assert job2.result_summary_json["atp_models"]["created"] == 0, job2.result_summary_json
        assert job2.result_summary_json["atp_models"]["updated"] == 1, job2.result_summary_json
        assert db_b.scalar(select(func.count()).select_from(AtpAssetVersion)) == 1
    db_a.close()
    db_b.close()


def test_atp_export_multi_value_filters():
    db = _new_session()
    _seed_storage(db)
    _seed_filter_assets(db)
    all_codes = {"M-500-CAT-PLAIN", "M-500-CAT-MTN", "M-220-CAT-PLAIN", "M-500-CUP-PLAIN"}

    # 同一维度多值为 OR（IN）
    manifest = _export_atp_manifest(db, {"voltage_level": ["500kV", "220kV"]})
    assert {entry["code"] for entry in manifest["assets"]} == all_codes
    manifest = _export_atp_manifest(db, {"scene": ["plain", "mountain"]})
    assert {entry["code"] for entry in manifest["assets"]} == all_codes

    # 不同维度之间为 AND
    manifest = _export_atp_manifest(db, {"voltage_level": ["500kV"], "scene": ["plain"]})
    assert {entry["code"] for entry in manifest["assets"]} == {"M-500-CAT-PLAIN", "M-500-CUP-PLAIN"}

    # 空维度值（不传 / 空数组）导出全部
    manifest = _export_atp_manifest(db, {})
    assert {entry["code"] for entry in manifest["assets"]} == all_codes
    manifest = _export_atp_manifest(db, {"scene": []})
    assert {entry["code"] for entry in manifest["assets"]} == all_codes
    db.close()


def test_atp_export_scene_filter_and_legacy_single_value():
    db = _new_session()
    _seed_storage(db)
    _seed_filter_assets(db)

    # 场景筛选此前失效，现单值/多值均应生效
    manifest = _export_atp_manifest(db, {"scene": "mountain"})
    assert [entry["code"] for entry in manifest["assets"]] == ["M-500-CAT-MTN"]
    assert manifest["filters"]["scene_type"] == ["mountain"]

    # 历史导出 job 复用的单值字符串格式仍按精确匹配工作
    manifest = _export_atp_manifest(db, {"voltage_level": "220kV", "tower_type": "cathead"})
    assert {entry["code"] for entry in manifest["assets"]} == {"M-220-CAT-PLAIN"}

    # 无匹配仍返回空（沿用 404 → platform_data_service 留空）
    manifest = _export_atp_manifest(db, {"scene": ["nonexistent"]})
    assert manifest["assets"] == []
    db.close()


def test_legacy_single_value_export_job_import():
    # 历史导出 job 的 request_payload_json.filters 为单值字符串，生成的包应能被导入
    db_a = _new_session()
    _seed_storage(db_a)
    _seed_asset(db_a)
    export_job = _run_export(db_a, ["atp_models"], filters={"voltage_level": "500kV", "tower_type": "cathead"})
    assert export_job.status == "success", export_job.error_message
    content = svc.download_job_artifact(db_a, export_job.id)[1]

    db_b = _new_session()
    _seed_storage(db_b)
    with _patched_publish():
        import_job = _run_import(db_b, content)
    assert import_job.status == "success", import_job.error_message
    assert db_b.scalar(select(func.count()).select_from(AtpAssetVersion)) == 1
    db_a.close()
    db_b.close()


def test_schema_version_mismatch_failed():
    db = _new_session()
    _seed_storage(db)
    # 构造一个 schema_version 不符的包
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"bundle_schema_version": "999"}))
        z.writestr("dimensions/dimensions.json", json.dumps({"types": [], "items": []}))
    bad = buf.getvalue()

    job = _run_import(db, bad)
    assert job.status == "failed"
    assert "bundle_schema_version" in (job.error_message or "")
    db.close()


class _patched_publish:
    def __enter__(self):
        self._orig = _atp_publish_change
        import app.services.atp_asset_service as m

        m._publish_change = lambda *a, **k: None
        return self

    def __exit__(self, *exc):
        import app.services.atp_asset_service as m

        m._publish_change = self._orig
