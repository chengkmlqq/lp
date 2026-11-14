from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.atp_asset import AtpAssetVersion
from ..models.dimension_item import DimensionItem
from ..models.dimension_type import DimensionType
from ..models.file_storage import FileIndexEntry, FileStorageMount
from ..models.param_category import SystemParamCategory
from ..models.platform_data_job import PlatformDataJob
from ..models.system_param import SystemParam
from ..schemas.platform_data import PLATFORM_DATA_CATEGORIES
from .atp_asset_service import (
    _parent_virtual_path,
    _write_archive_to_storage,
    create_asset,
    export_assets_zip,
    get_asset_by_id,
)
from .file_service import list_enabled_mounts
from .storage_driver import StorageDriverError, build_storage_driver, normalize_virtual_path

# 包结构 schema 版本：导入时校验，不兼容直接 failed。
BUNDLE_SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = {"1"}

PLATFORM_DATA_SOURCE_SITE = os.environ.get("LP_PLATFORM_SITE", "lp-platform")

ARTIFACT_MIME = "application/zip"
ARTIFACT_PREFIX = "/platform-data"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────
# 存储辅助：默认挂载 + 读写产物 + 登记 FileIndexEntry
# ─────────────────────────────────────────────────────────────
def _resolve_default_mount(db: Session) -> FileStorageMount:
    mounts = list_enabled_mounts(db)
    if not mounts:
        raise RuntimeError("没有可用的文件存储挂载点，无法读写基础数据包产物")
    return mounts[0]


def _build_driver(mount: FileStorageMount):
    try:
        return build_storage_driver(mount.backend, mount)
    except StorageDriverError as exc:
        raise RuntimeError(f"文件存储驱动初始化失败: {exc}") from exc


def _store_artifact(
    db: Session,
    *,
    mount: FileStorageMount,
    content: bytes,
    storage_path: str,
    actor_user_id: str | None,
) -> tuple[str, int]:
    """把产物字节写入默认挂载，并登记 FileIndexEntry，返回 (规范化路径, file_entry_id)。"""
    driver = _build_driver(mount)
    normalized = normalize_virtual_path(storage_path)
    driver.ensure_directory(_parent_virtual_path(normalized))
    obj = driver.write_file(normalized, content=content, content_type=ARTIFACT_MIME)
    entry = FileIndexEntry(
        mount_id=mount.id,
        path=normalized,
        parent_path=_parent_virtual_path(normalized),
        name=obj.name,
        is_dir=False,
        size=max(0, int(len(content))),
        mime_type=ARTIFACT_MIME,
        etag=obj.etag,
        storage_key=obj.storage_key,
        modified_at=obj.modified_at,
        synced_at=_utcnow(),
        last_synced_by_user_id=actor_user_id,
    )
    db.add(entry)
    db.flush()
    return normalized, entry.id


def _read_artifact_bytes(db: Session, *, storage_path: str) -> bytes:
    mount = _resolve_default_mount(db)
    driver = _build_driver(mount)
    result = driver.read_file(normalize_virtual_path(storage_path))
    return result.content


# ─────────────────────────────────────────────────────────────
# 序列化：维度 / 系统参数
# ─────────────────────────────────────────────────────────────
def serialize_dimensions(db: Session) -> dict[str, Any]:
    types = db.scalars(select(DimensionType)).all()
    items = db.scalars(select(DimensionItem)).all()
    type_by_id = {t.id: t for t in types}
    item_by_id = {i.id: i for i in items}
    return {
        "types": [
            {
                "code": t.code,
                "name": t.name,
                "parent_code": (type_by_id[t.parent_id].code if t.parent_id and t.parent_id in type_by_id else None),
                "description": t.description,
                "is_enabled": t.is_enabled,
                "sort_order": t.sort_order,
            }
            for t in types
        ],
        "items": [
            {
                "code": i.code,
                "name": i.name,
                "type_code": i.dimension_type,
                "parent_code": (item_by_id[i.parent_id].code if i.parent_id and i.parent_id in item_by_id else None),
                "description": i.description,
                "is_enabled": i.is_enabled,
                "sort_order": i.sort_order,
                "extra_json": i.extra_json,
            }
            for i in items
        ],
    }


def serialize_system_params(db: Session) -> dict[str, Any]:
    params = db.scalars(select(SystemParam)).all()
    cats = db.scalars(select(SystemParamCategory)).all()
    cat_by_id = {c.id: c for c in cats}
    return {
        "params": [
            {
                "param_key": p.param_key,
                "param_name": p.param_name,
                "param_value": p.param_value,
                "is_encrypted": p.is_encrypted,
                "description": p.description,
                "status": p.status,
                "category_name": (cat_by_id[p.category_id].name if p.category_id and p.category_id in cat_by_id else None),
            }
            for p in params
        ]
    }


# ─────────────────────────────────────────────────────────────
# 导出：组装单包 ZIP
# ─────────────────────────────────────────────────────────────
def build_export_bundle(
    db: Session,
    *,
    categories: list[str],
    filters: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """组装基础数据包：顶层 manifest.json + dimensions/ + system_params/ + atp_models/。

    返回 (zip 字节, 顶层 manifest 字典)。
    """
    filters = filters or {}
    bad = [c for c in categories if c not in PLATFORM_DATA_CATEGORIES]
    if bad:
        raise ValueError(f"不支持的导出类别: {bad}")

    parts: dict[str, bytes] = {}
    category_counts: dict[str, int] = {}
    category_checksums: dict[str, str] = {}

    # 维度
    if "dimensions" in categories:
        dim_bytes = json.dumps(serialize_dimensions(db), ensure_ascii=False, indent=2).encode("utf-8")
        parts["dimensions/dimensions.json"] = dim_bytes
        category_counts["dimensions"] = len(json.loads(dim_bytes)["types"]) + len(json.loads(dim_bytes)["items"])
        category_checksums["dimensions"] = _sha256(dim_bytes)

    # 系统参数
    if "system_params" in categories:
        sp_bytes = json.dumps(serialize_system_params(db), ensure_ascii=False, indent=2).encode("utf-8")
        parts["system_params/system_params.json"] = sp_bytes
        category_counts["system_params"] = len(json.loads(sp_bytes)["params"])
        category_checksums["system_params"] = _sha256(sp_bytes)

    # ATP 模型：复用 export_assets_zip（每模型一目录 + manifest.json），再整体 re-root 到 atp_models/
    if "atp_models" in categories:
        try:
            atp_bytes, _filename = export_assets_zip(
                db,
                voltage_level=filters.get("voltage_level"),
                tower_type=filters.get("tower_type"),
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                atp_bytes = None  # 没有匹配模型时，ATP 部分留空
            else:
                raise
        if atp_bytes:
            with zipfile.ZipFile(io.BytesIO(atp_bytes)) as inner:
                for name in inner.namelist():
                    parts[f"atp_models/{name}"] = inner.read(name)
            category_counts["atp_models"] = len(json.loads(parts["atp_models/manifest.json"])["assets"])
            category_checksums["atp_models"] = _sha256(atp_bytes)
        else:
            category_counts["atp_models"] = 0
            category_checksums["atp_models"] = _sha256(b"")

    manifest: dict[str, Any] = {
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_version": "1.0",
        "generated_at": _utcnow().isoformat(),
        "source_site": PLATFORM_DATA_SOURCE_SITE,
        "filters": filters,
        "categories": categories,
        "counts": category_counts,
        "checksums": category_checksums,
    }
    parts["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            archive.writestr(name, parts[name])
    return buf.getvalue(), manifest


# ─────────────────────────────────────────────────────────────
# 任务创建与入队
# ─────────────────────────────────────────────────────────────
def init_export(
    db: Session,
    *,
    categories: list[str],
    filters: dict[str, Any] | None,
    actor_user_id: str | None,
) -> PlatformDataJob:
    job = PlatformDataJob(
        kind="export",
        status="pending",
        request_payload_json={"categories": categories, "filters": filters or {}},
        create_user=actor_user_id,
        create_date=_utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    from ..tasks.platform_data_tasks import export_platform_data_job

    export_platform_data_job.delay(job.id)
    return job


def init_import(
    db: Session,
    *,
    upload_bytes: bytes | None = None,
    upload_filename: str | None = None,
    source_job_id: str | None = None,
    actor_user_id: str | None,
) -> PlatformDataJob:
    """创建导入任务：上传包（先落存储）+ 复用历史 export job 两种来源。

    - 上传：同步把字节写入存储（轻量、非阻塞接口语义之外的快速落盘），记录路径后立即入队。
    - 复用：仅记录来源 export job_id，包副本在 celery 任务内读取并落库。
    """
    if upload_bytes is None and not source_job_id:
        raise ValueError("导入必须提供上传包或指定复用的 export job_id")

    request_payload: dict[str, Any] = {}
    mount = _resolve_default_mount(db)
    artifact_path: str | None = None
    artifact_file_id: int | None = None

    if upload_bytes is not None:
        request_payload["source"] = "upload"
        request_payload["filename"] = upload_filename or "upload.zip"
        # 收到的包立即落存储（审计 + 便于再次导入）
        artifact_path, artifact_file_id = _store_artifact(
            db,
            mount=mount,
            content=upload_bytes,
            storage_path=f"{ARTIFACT_PREFIX}/imports/{_utcnow().strftime('%Y%m%d')}-{os.urandom(4).hex()}.upload.zip",
            actor_user_id=actor_user_id,
        )
    else:
        request_payload["source"] = "reuse"
        request_payload["source_job_id"] = source_job_id

    job = PlatformDataJob(
        kind="import",
        status="pending",
        request_payload_json=request_payload,
        artifact_storage_path=artifact_path,
        artifact_file_id=artifact_file_id,
        create_user=actor_user_id,
        create_date=_utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    from ..tasks.platform_data_tasks import import_platform_data_job

    import_platform_data_job.delay(job.id)
    return job


# ─────────────────────────────────────────────────────────────
# 导出任务执行（celery 内调用）
# ─────────────────────────────────────────────────────────────
def run_export_job(db: Session, job_id: str) -> None:
    job = db.get(PlatformDataJob, job_id)
    if job is None:
        return
    job.status = "running"
    db.commit()
    try:
        req = job.request_payload_json or {}
        content, manifest = build_export_bundle(
            db,
            categories=req.get("categories", []),
            filters=req.get("filters", {}),
        )
        mount = _resolve_default_mount(db)
        path, file_id = _store_artifact(
            db,
            mount=mount,
            content=content,
            storage_path=f"{ARTIFACT_PREFIX}/exports/{job.id}.zip",
            actor_user_id=job.create_user,
        )
        job.artifact_storage_path = path
        job.artifact_file_id = file_id
        job.manifest_json = manifest
        job.result_summary_json = {
            "file_size": len(content),
            "counts": manifest.get("counts", {}),
        }
        job.status = "success"
        job.finish_date = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.finish_date = _utcnow()
        db.commit()
        raise


# ─────────────────────────────────────────────────────────────
# 导入核心：按自然键幂等 upsert
# ─────────────────────────────────────────────────────────────
def _import_dimensions(db: Session, raw: bytes, summary: dict[str, int]) -> None:
    data = json.loads(raw)
    type_by_code: dict[str, DimensionType] = {}

    for t in data.get("types", []):
        code = t["code"]
        existing = db.scalar(select(DimensionType).where(DimensionType.code == code))
        if existing is not None:
            existing.name = t.get("name", existing.name)
            existing.description = t.get("description")
            existing.is_enabled = t.get("is_enabled", True)
            existing.sort_order = t.get("sort_order", 0)
            existing.parent_id = None  # 第二遍回填
            type_by_code[code] = existing
            summary["updated"] += 1
        else:
            nt = DimensionType(
                code=code,
                name=t.get("name", code),
                description=t.get("description"),
                is_enabled=t.get("is_enabled", True),
                sort_order=t.get("sort_order", 0),
            )
            db.add(nt)
            db.flush()
            type_by_code[code] = nt
            summary["created"] += 1

    # 第二遍：父级关联（先建父、后建子，跨序安全）
    for t in data.get("types", []):
        obj = type_by_code[t["code"]]
        parent_code = t.get("parent_code")
        if parent_code:
            parent = type_by_code.get(parent_code) or db.scalar(
                select(DimensionType).where(DimensionType.code == parent_code)
            )
            obj.parent_id = parent.id if parent is not None else None

    item_by_code: dict[str, DimensionItem] = {}
    for it in data.get("items", []):
        code = it["code"]
        existing = db.scalar(select(DimensionItem).where(DimensionItem.code == code))
        type_obj = type_by_code.get(it.get("type_code")) if it.get("type_code") else None
        if existing is not None:
            existing.name = it.get("name", existing.name)
            existing.dimension_type = it.get("type_code", existing.dimension_type)
            existing.type_id = type_obj.id if type_obj is not None else None
            existing.description = it.get("description")
            existing.is_enabled = it.get("is_enabled", True)
            existing.sort_order = it.get("sort_order", 0)
            existing.extra_json = it.get("extra_json") or {}
            existing.parent_id = None
            item_by_code[code] = existing
            summary["updated"] += 1
        else:
            ni = DimensionItem(
                code=code,
                name=it.get("name", code),
                dimension_type=it.get("type_code", ""),
                type_id=type_obj.id if type_obj is not None else None,
                description=it.get("description"),
                is_enabled=it.get("is_enabled", True),
                sort_order=it.get("sort_order", 0),
                extra_json=it.get("extra_json") or {},
            )
            db.add(ni)
            db.flush()
            item_by_code[code] = ni
            summary["created"] += 1

    for it in data.get("items", []):
        obj = item_by_code[it["code"]]
        parent_code = it.get("parent_code")
        if parent_code:
            parent = item_by_code.get(parent_code) or db.scalar(
                select(DimensionItem).where(DimensionItem.code == parent_code)
            )
            obj.parent_id = parent.id if parent is not None else None
    db.flush()


def _import_system_params(db: Session, raw: bytes, summary: dict[str, int]) -> None:
    data = json.loads(raw)
    cat_by_name: dict[str, SystemParamCategory] = {
        c.name: c for c in db.scalars(select(SystemParamCategory)).all()
    }
    for p in data.get("params", []):
        key = p["param_key"]
        cat_id = None
        cat_name = p.get("category_name")
        if cat_name:
            cat = cat_by_name.get(cat_name) or db.scalar(
                select(SystemParamCategory).where(SystemParamCategory.name == cat_name)
            )
            if cat is None:
                cat = SystemParamCategory(name=cat_name)
                db.add(cat)
                db.flush()
                cat_by_name[cat_name] = cat
            cat_id = cat.id

        existing = db.scalar(select(SystemParam).where(SystemParam.param_key == key))
        if existing is not None:
            existing.param_name = p.get("param_name", existing.param_name)
            existing.param_value = p.get("param_value", existing.param_value)
            existing.is_encrypted = p.get("is_encrypted", False)
            existing.description = p.get("description")
            existing.status = p.get("status", "enabled")
            existing.category_id = cat_id
            summary["updated"] += 1
        else:
            np = SystemParam(
                param_key=key,
                param_name=p.get("param_name", key),
                param_value=p.get("param_value", ""),
                is_encrypted=p.get("is_encrypted", False),
                description=p.get("description"),
                status=p.get("status", "enabled"),
                category_id=cat_id,
            )
            db.add(np)
            summary["created"] += 1
    db.flush()


def _import_atp_models(
    db: Session,
    bundle: zipfile.ZipFile,
    summary: dict[str, int],
    actor_user_id: str | None,
) -> None:
    names = bundle.namelist()
    if "atp_models/manifest.json" not in names:
        return
    atp_manifest = json.loads(bundle.read("atp_models/manifest.json"))
    mount = _resolve_default_mount(db)
    driver = _build_driver(mount)

    for entry in atp_manifest.get("assets", []):
        code = entry.get("code")
        version = entry.get("version")
        dir_name = entry.get("storage_dir") or f"{code}_{version}"
        prefix = f"atp_models/{dir_name}/"
        members = [(n, bundle.read(n)) for n in names if n.startswith(prefix)]
        if not members:
            summary["skipped"] = summary.get("skipped", 0) + 1
            continue

        sub_buf = io.BytesIO()
        with zipfile.ZipFile(sub_buf, "w", zipfile.ZIP_DEFLATED) as sz:
            for n, data in members:
                sz.writestr(n[len("atp_models/"):], data)
        sub_bytes = sub_buf.getvalue()

        existing = None
        if code and version:
            existing = db.scalar(
                select(AtpAssetVersion).where(
                    AtpAssetVersion.code == code, AtpAssetVersion.version == version
                )
            )
        try:
            if existing is not None:
                _write_archive_to_storage(
                    driver,
                    storage_root_path=existing.storage_root_path,
                    archive_filename=f"{dir_name}.zip",
                    archive_content=sub_bytes,
                )
                summary["updated"] += 1
            else:
                from ..schemas.atp_asset import AtpAssetCreateRequest

                req = AtpAssetCreateRequest(
                    code=code,
                    name=entry.get("name") or code,
                    description=entry.get("description") or (entry.get("name") or code),
                    status=entry.get("status") or "enabled",
                    voltage_level=entry.get("voltage_level"),
                    tower_type=entry.get("tower_type"),
                    scene_type=entry.get("scene_type"),
                    arrester_config=entry.get("arrester_config"),
                    version=version,
                    is_active=bool(entry.get("is_active", False)),
                    is_published=bool(entry.get("is_published", False)),
                    shield_wire=entry.get("shield_wire") or "with",
                    tags=entry.get("tags"),
                )
                created = create_asset(db, req, actor_user_id=actor_user_id or "platform-data-import")
                if created is None:
                    summary["failed"] += 1
                    summary.setdefault("errors", []).append(
                        {"code": code, "version": version, "error": "创建资产失败（code 已存在但版本不匹配）"}
                    )
                    continue
                asset = get_asset_by_id(db, created.id)
                if asset is None:
                    summary["failed"] += 1
                    continue
                _write_archive_to_storage(
                    driver,
                    storage_root_path=asset.storage_root_path,
                    archive_filename=f"{dir_name}.zip",
                    archive_content=sub_bytes,
                )
                summary["created"] += 1
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            summary.setdefault("errors", []).append(
                {"code": code, "version": version, "error": str(exc)[:300]}
            )


def run_import_job(db: Session, job_id: str) -> None:
    job = db.get(PlatformDataJob, job_id)
    if job is None:
        return
    job.status = "running"
    db.commit()
    try:
        req = job.request_payload_json or {}
        mount = _resolve_default_mount(db)

        # 解析源字节
        if req.get("source") == "reuse":
            source_job = db.get(PlatformDataJob, req["source_job_id"])
            if source_job is None or source_job.kind != "export" or not source_job.artifact_storage_path:
                raise ValueError("复用的 export job 不存在或没有可用产物")
            content = _read_artifact_bytes(db, storage_path=source_job.artifact_storage_path)
            # 把副本落库（审计 + 便于再次导入）
            path, file_id = _store_artifact(
                db,
                mount=mount,
                content=content,
                storage_path=f"{ARTIFACT_PREFIX}/imports/{job.id}.zip",
                actor_user_id=job.create_user,
            )
            job.artifact_storage_path = path
            job.artifact_file_id = file_id
        else:
            if not job.artifact_storage_path:
                raise ValueError("上传包未落库，无法导入")
            content = _read_artifact_bytes(db, storage_path=job.artifact_storage_path)

        # 校验顶层 manifest schema_version
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as bundle:
                manifest = json.loads(bundle.read("manifest.json"))
                sv = manifest.get("bundle_schema_version")
                if sv not in SUPPORTED_SCHEMA_VERSIONS:
                    raise ValueError(
                        f"不兼容的包版本 bundle_schema_version={sv!r}；"
                        f"当前支持 {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
                    )

                summary: dict[str, Any] = {
                    "dimensions": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
                    "system_params": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
                    "atp_models": {"created": 0, "updated": 0, "skipped": 0, "failed": 0},
                }

                if "dimensions/dimensions.json" in bundle.namelist():
                    _import_dimensions(db, bundle.read("dimensions/dimensions.json"), summary["dimensions"])
                if "system_params/system_params.json" in bundle.namelist():
                    _import_system_params(db, bundle.read("system_params/system_params.json"), summary["system_params"])
                if "atp_models/manifest.json" in bundle.namelist():
                    _import_atp_models(db, bundle, summary["atp_models"], job.create_user)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"上传的包不是合法的 ZIP 文件: {exc}") from exc

        job.manifest_json = manifest
        job.result_summary_json = summary
        job.status = "success"
        job.finish_date = _utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.finish_date = _utcnow()
        db.commit()
        raise


# ─────────────────────────────────────────────────────────────
# 查询 / 下载
# ─────────────────────────────────────────────────────────────
def get_job(db: Session, job_id: str) -> PlatformDataJob | None:
    return db.get(PlatformDataJob, job_id)


def list_jobs(
    db: Session,
    *,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[int, list[PlatformDataJob]]:
    stmt = select(PlatformDataJob)
    if kind:
        stmt = stmt.where(PlatformDataJob.kind == kind)
    if status:
        stmt = stmt.where(PlatformDataJob.status == status)
    total = db.scalar(select(func.count()).select_from(PlatformDataJob))
    rows = db.scalars(
        stmt.order_by(PlatformDataJob.create_date.desc()).limit(limit).offset(offset)
    ).all()
    return total or 0, list(rows)


def download_job_artifact(db: Session, job_id: str) -> tuple[str, bytes, str]:
    job = db.get(PlatformDataJob, job_id)
    if job is None or not job.artifact_storage_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务产物不存在")
    content = _read_artifact_bytes(db, storage_path=job.artifact_storage_path)
    filename = f"platform-data-{job.kind}-{job.id}.zip"
    return filename, content, ARTIFACT_MIME
