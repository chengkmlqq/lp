from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.system_param import SystemParam
from ..schemas.system_param import SystemParamSummary
from ..services.audit_service import compose_audit_detail, write_audit_log
from ..services.minio_storage import (
    MinioStorageError,
    build_matlab_engine_draft_prefix,
    build_matlab_engine_module_key,
    build_matlab_engine_release_prefix,
    delete_prefix,
    get_object,
    list_objects,
    put_object,
)
from ..services.push_service import publish_topic
from ..services.system_param_service import (
    get_system_param_by_key,
    serialize_system_param,
)

logger = logging.getLogger(__name__)

MATLAB_ENGINE_TOPIC = "admin.matlab-engine"
REQUIRED_FILES = ("RunWaveAnalysisModule", "run_RunWaveAnalysisModule.sh")


class MatlabEngineError(RuntimeError):
    pass


def _param_key_modules() -> str:
    return "matlab_engine.modules"


def _param_key_versions(slug: str) -> str:
    return f"matlab_engine.versions.{slug}"


def _param_key_legacy_versions() -> str:
    return "matlab_engine.versions"


def _param_key_legacy_current() -> str:
    return "matlab_engine.current_version"


def _get_param(db: Session, key: str) -> SystemParam | None:
    return get_system_param_by_key(db, key)


def _get_param_value(db: Session, key: str) -> str:
    param = _get_param(db, key)
    if not param or param.status != "enabled":
        return ""
    return (param.param_value or "").strip()


def _set_param(db: Session, key: str, value: str, *, actor_user_id: str | None = None) -> None:
    param = _get_param(db, key)
    if param:
        param.param_value = value
        if actor_user_id:
            param.updated_by_user_id = actor_user_id
    else:
        param = SystemParam(
            param_key=key,
            param_name=key.replace(".", " ").replace("_", " ").title(),
            param_value=value,
            is_encrypted=False,
            description="Auto-managed by MATLAB engine module",
            status="enabled",
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.add(param)
    db.flush()
    db.commit()


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _validate_zip_content(data: bytes, required_files: list[str] | None = None) -> tuple[bool, str]:
    required = required_files if required_files is not None else list(REQUIRED_FILES)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            basenames = {Path(n).name for n in names}
            for file_name in required:
                if file_name not in basenames:
                    return False, f"ZIP 包缺少必需文件: {file_name}"
            return True, ""
    except zipfile.BadZipFile:
        return False, "上传文件不是有效的 ZIP 包"


def _list_objects_keys(prefix: str) -> list[str]:
    try:
        return list_objects(prefix)
    except MinioStorageError:
        logger.warning("Failed to list objects under %s", prefix)
        return []


def _publish_event(name: str, payload: dict[str, Any]) -> None:
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        coro = publish_topic(
            MATLAB_ENGINE_TOPIC,
            name=name,
            payload=payload,
            requires_refetch=["/api/v1/fault-matlab/modules", "/api/v1/fault-matlab/modules/{slug}/versions"],
            dedupe_key=f"matlab-engine:{name}:{payload.get('version_hash') or payload.get('slug') or 'unknown'}",
        )
        loop.create_task(coro)
    except RuntimeError:
        pass
    except Exception:
        logger.debug("Failed to publish MATLAB engine event %s", name, exc_info=True)


def _normalize_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value.strip().lower()) or "module"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_modules(db: Session) -> list[dict[str, Any]]:
    raw = _get_param_value(db, _param_key_modules())
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _save_modules(db: Session, modules: list[dict[str, Any]], *, actor_user_id: str | None = None) -> None:
    _set_param(db, _param_key_modules(), json.dumps(modules, ensure_ascii=False), actor_user_id=actor_user_id)


def _load_versions(db: Session, slug: str) -> dict[str, Any]:
    raw = _get_param_value(db, _param_key_versions(slug))
    if not raw:
        return {"releases": [], "draft": None}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"releases": [], "draft": None}


def _save_versions(db: Session, slug: str, payload: dict[str, Any], *, actor_user_id: str | None = None) -> None:
    _set_param(db, _param_key_versions(slug), json.dumps(payload, ensure_ascii=False), actor_user_id=actor_user_id)


def list_modules(db: Session) -> list[dict[str, Any]]:
    return _load_modules(db)


def get_module(db: Session, slug: str) -> dict[str, Any] | None:
    for item in _load_modules(db):
        if item.get("slug") == slug:
            return item
    return None


def create_module(db: Session, payload: dict[str, Any], *, actor_user_id: str) -> dict[str, Any]:
    slug = _normalize_slug(str(payload.get("slug") or payload.get("name") or "module"))
    modules = _load_modules(db)
    if any(item.get("slug") == slug for item in modules):
        raise MatlabEngineError(f"模块标识已存在: {slug}")
    module = {
        "slug": slug,
        "name": str(payload.get("name") or slug),
        "description": str(payload.get("description") or ""),
        "required_files": list(payload.get("required_files") or list(REQUIRED_FILES)),
        "worker_deploy_path": str(payload.get("worker_deploy_path") or ""),
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
    }
    modules.append(module)
    _save_modules(db, modules, actor_user_id=actor_user_id)
    _publish_event("module.created", {"slug": slug})
    return module


def update_module(db: Session, slug: str, payload: dict[str, Any], *, actor_user_id: str) -> dict[str, Any] | None:
    modules = _load_modules(db)
    target = None
    for item in modules:
        if item.get("slug") == slug:
            target = item
            break
    if not target:
        return None
    if payload.get("name") is not None:
        target["name"] = str(payload["name"])
    if payload.get("description") is not None:
        target["description"] = str(payload["description"])
    if payload.get("required_files") is not None:
        target["required_files"] = list(payload["required_files"])
    if payload.get("worker_deploy_path") is not None:
        target["worker_deploy_path"] = str(payload["worker_deploy_path"])
    target["updated_at"] = _utcnow_iso()
    _save_modules(db, modules, actor_user_id=actor_user_id)
    _publish_event("module.updated", {"slug": slug})
    return target


def delete_module(db: Session, slug: str, *, actor_user_id: str) -> bool:
    modules = _load_modules(db)
    filtered = [item for item in modules if item.get("slug") != slug]
    if len(filtered) == len(modules):
        return False
    _save_modules(db, filtered, actor_user_id=actor_user_id)
    _publish_event("module.deleted", {"slug": slug})
    return True


def _version_manifest(version: dict[str, Any], file_list: list[str]) -> dict[str, Any]:
    return {
        "version_hash": version.get("version_hash"),
        "version_tag": version.get("version_tag"),
        "changelog": version.get("changelog"),
        "uploaded_by": version.get("uploaded_by"),
        "uploaded_by_name": version.get("uploaded_by_name"),
        "upload_time": version.get("upload_time"),
        "size_bytes": version.get("size_bytes"),
        "file_list": file_list,
    }


def _list_zip_files(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return [n for n in zf.namelist() if not n.endswith("/")]
    except zipfile.BadZipFile:
        return []


def _upload_draft_package(db: Session, module: dict[str, Any], data: bytes, version_hash: str) -> list[str]:
    prefix = build_matlab_engine_draft_prefix(module["slug"], version_hash)
    put_object(f"{prefix}engine.zip", data, content_type="application/zip")
    file_list = _list_zip_files(data)
    manifest = _version_manifest({
        "version_hash": version_hash,
        "version_tag": "",
        "changelog": "",
        "uploaded_by": "",
        "uploaded_by_name": "",
        "upload_time": _utcnow_iso(),
        "size_bytes": len(data),
    }, file_list)
    put_object(f"{prefix}manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"), content_type="application/json")
    return file_list


def _copy_package(src_slug: str, dst_slug: str, version_hash: str, scope: str) -> None:
    if scope == "draft":
        src_prefix = build_matlab_engine_release_prefix(src_slug, version_hash)
        dst_prefix = build_matlab_engine_draft_prefix(dst_slug, version_hash)
    else:
        src_prefix = build_matlab_engine_draft_prefix(src_slug, version_hash)
        dst_prefix = build_matlab_engine_release_prefix(dst_slug, version_hash)
    keys = _list_objects_keys(src_prefix)
    for key in keys:
        rel = key[len(src_prefix):]
        if not rel:
            continue
        data = get_object(key)
        put_object(f"{dst_prefix}{rel}", data)


def _write_manifest(module: dict[str, Any], version_hash: str, scope: str, version: dict[str, Any]) -> None:
    if scope == "draft":
        prefix = build_matlab_engine_draft_prefix(module["slug"], version_hash)
    else:
        prefix = build_matlab_engine_release_prefix(module["slug"], version_hash)
    manifest = _version_manifest(version, [])
    put_object(f"{prefix}manifest.json", json.dumps(manifest, ensure_ascii=False).encode("utf-8"), content_type="application/json")


def _load_manifest(module: dict[str, Any], version_hash: str, scope: str) -> dict[str, Any] | None:
    if scope == "draft":
        prefix = build_matlab_engine_draft_prefix(module["slug"], version_hash)
    else:
        prefix = build_matlab_engine_release_prefix(module["slug"], version_hash)
    try:
        raw = get_object(f"{prefix}manifest.json")
        return json.loads(raw)
    except Exception:
        return None


def _delete_scope(module: dict[str, Any], version_hash: str, scope: str) -> None:
    if scope == "draft":
        prefix = build_matlab_engine_draft_prefix(module["slug"], version_hash)
    else:
        prefix = build_matlab_engine_release_prefix(module["slug"], version_hash)
    delete_prefix(prefix)


def upload_draft(db: Session, slug: str, data: bytes, *, uploaded_by: str, uploaded_by_name: str = "") -> dict[str, Any]:
    module = get_module(db, slug)
    if not module:
        raise MatlabEngineError(f"模块不存在: {slug}")
    valid, error_msg = _validate_zip_content(data, module.get("required_files"))
    if not valid:
        raise MatlabEngineError(error_msg)
    version_hash = _compute_hash(data)
    file_list = _upload_draft_package(db, module, data, version_hash)
    versions = _load_versions(db, slug)
    draft = {
        "version_hash": version_hash,
        "version_tag": "",
        "changelog": "",
        "uploaded_by": uploaded_by,
        "uploaded_by_name": uploaded_by_name,
        "upload_time": _utcnow_iso(),
        "size_bytes": len(data),
        "file_list": file_list,
    }
    versions["draft"] = draft
    _save_versions(db, slug, versions, actor_user_id=uploaded_by)
    _publish_event("engine.draft_uploaded", {"slug": slug, "version_hash": version_hash})
    return draft


def publish_draft(db: Session, slug: str, version_hash: str, version_tag: str, changelog: str, *, actor_user_id: str) -> dict[str, Any]:
    module = get_module(db, slug)
    if not module:
        raise MatlabEngineError(f"模块不存在: {slug}")
    versions = _load_versions(db, slug)
    draft = versions.get("draft")
    if not draft or draft.get("version_hash") != version_hash:
        raise MatlabEngineError("草稿不存在或已发布")
    if not version_tag or not str(version_tag).strip():
        raise MatlabEngineError("版本号不能为空")
    tag = str(version_tag).strip()
    releases = versions.get("releases", [])
    if any(item.get("version_tag") == tag for item in releases):
        raise MatlabEngineError(f"版本号已存在: {tag}")
    _copy_package(slug, slug, version_hash, "release")
    release = dict(draft)
    release["version_tag"] = tag
    release["changelog"] = str(changelog or "")
    manifest = _load_manifest(module, version_hash, "draft")
    if manifest:
        release["file_list"] = manifest.get("file_list") or release.get("file_list") or []
    _write_manifest(module, version_hash, "release", release)
    releases.insert(0, release)
    versions["releases"] = releases
    versions["draft"] = None
    _save_versions(db, slug, versions, actor_user_id=actor_user_id)
    _publish_event("engine.published", {"slug": slug, "version_hash": version_hash, "version_tag": tag})
    return release


def rollback_to_version(db: Session, slug: str, version_hash: str, *, actor_user_id: str) -> dict[str, Any]:
    module = get_module(db, slug)
    if not module:
        raise MatlabEngineError(f"模块不存在: {slug}")
    versions = _load_versions(db, slug)
    releases = versions.get("releases", [])
    target = next((item for item in releases if item.get("version_hash") == version_hash), None)
    if not target:
        raise MatlabEngineError("历史版本不存在")
    _copy_package(slug, slug, version_hash, "draft")
    draft = dict(target)
    draft["version_tag"] = ""
    draft["changelog"] = ""
    draft["upload_time"] = _utcnow_iso()
    manifest = _load_manifest(module, version_hash, "release")
    if manifest:
        draft["file_list"] = manifest.get("file_list") or target.get("file_list") or []
    _write_manifest(module, version_hash, "draft", draft)
    versions["draft"] = draft
    _save_versions(db, slug, versions, actor_user_id=actor_user_id)
    _publish_event("engine.rollbacked", {"slug": slug, "version_hash": version_hash})
    return draft


def get_version_files(db: Session, slug: str, version_hash: str) -> dict[str, Any]:
    module = get_module(db, slug)
    if not module:
        raise MatlabEngineError(f"模块不存在: {slug}")
    versions = _load_versions(db, slug)
    version = None
    scope = "draft"
    draft = versions.get("draft")
    if draft and draft.get("version_hash") == version_hash:
        version = draft
    else:
        for item in versions.get("releases", []):
            if item.get("version_hash") == version_hash:
                version = item
                scope = "release"
                break
    if not version:
        raise MatlabEngineError("版本不存在")
    manifest = _load_manifest(module, version_hash, scope)
    file_list = (manifest or {}).get("file_list") or version.get("file_list") or []
    return {
        "slug": slug,
        "version_hash": version_hash,
        "scope": scope,
        "version_tag": version.get("version_tag"),
        "file_list": file_list,
    }


def list_versions(db: Session, slug: str) -> dict[str, Any]:
    module = get_module(db, slug)
    versions = _load_versions(db, slug)
    draft = versions.get("draft")
    if draft:
        manifest = _load_manifest(module or {"slug": slug, "required_files": list(REQUIRED_FILES)}, draft.get("version_hash", ""), "draft")
        if manifest:
            draft = dict(draft)
            draft["file_list"] = manifest.get("file_list") or draft.get("file_list") or []
    releases = versions.get("releases", [])
    for index, item in enumerate(releases):
        manifest = _load_manifest(module or {"slug": slug, "required_files": list(REQUIRED_FILES)}, item.get("version_hash", ""), "release")
        if manifest:
            releases[index] = dict(item)
            releases[index]["file_list"] = manifest.get("file_list") or item.get("file_list") or []
    return {
        "slug": slug,
        "draft": draft,
        "releases": releases,
    }


def trigger_sync_for_module(db: Session, slug: str, *, actor_user_id: str) -> str:
    module = get_module(db, slug)
    if not module:
        raise MatlabEngineError(f"模块不存在: {slug}")
    versions = _load_versions(db, slug)
    releases = versions.get("releases", [])
    current = releases[0] if releases else None
    if not current:
        raise MatlabEngineError(f"模块 {slug} 没有已发布版本")
    from ..tasks.sync_matlab_engine_task import sync_matlab_engine_module

    result = sync_matlab_engine_module.delay(
        slug,
        current.get("version_hash", ""),
        current.get("worker_deploy_path") or module.get("worker_deploy_path") or "",
        actor_user_id,
    )
    return result.id
