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

MATLAB_ENGINE_PREFIX = "matlab-engine/"
MATLAB_ENGINE_TOPIC = "admin.matlab-engine"

REQUIRED_FILES = ("RunWaveAnalysisModule", "run_RunWaveAnalysisModule.sh")


class MatlabEngineError(RuntimeError):
    pass


def _param_key_version_hash() -> str:
    return "matlab_engine.current_version"


def _param_key_versions() -> str:
    return "matlab_engine.versions"


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
            description=f"Auto-managed by MATLAB engine module",
            status="enabled",
            created_by_user_id=actor_user_id,
            updated_by_user_id=actor_user_id,
        )
        db.add(param)
    db.flush()


def _compute_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _validate_zip_content(data: bytes) -> tuple[bool, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            basenames = {Path(n).name for n in names}
            for required in REQUIRED_FILES:
                if required not in basenames:
                    return False, f"ZIP 包缺少必需文件: {required}"
            return True, ""
    except zipfile.BadZipFile:
        return False, "上传文件不是有效的 ZIP 包"


def _list_version_files(version_hash: str) -> list[str]:
    prefix = f"{MATLAB_ENGINE_PREFIX}{version_hash}/"
    try:
        keys = list_objects(prefix)
        return [k[len(prefix):] for k in keys if not k.endswith("/")]
    except MinioStorageError:
        logger.warning("Failed to list MATLAB engine version files for %s", version_hash)
        return []


def _upload_version_to_minio(data: bytes, version_hash: str) -> None:
    prefix = f"{MATLAB_ENGINE_PREFIX}{version_hash}/"
    try:
        put_object(
            f"{prefix}engine.zip",
            data,
            content_type="application/zip",
        )
    except MinioStorageError as exc:
        raise MatlabEngineError(f"Failed to upload engine ZIP to MinIO: {exc}") from exc


def upload_engine_version(
    db: Session,
    data: bytes,
    *,
    uploaded_by: str,
    uploaded_by_name: str = "",
) -> dict[str, Any]:
    valid, error_msg = _validate_zip_content(data)
    if not valid:
        raise MatlabEngineError(error_msg)

    version_hash = _compute_hash(data)
    _upload_version_to_minio(data, version_hash)

    file_list = _list_version_files(version_hash)
    now = datetime.now(timezone.utc).isoformat()

    versions_json = _get_param_value(db, _param_key_versions())
    try:
        versions = json.loads(versions_json) if versions_json else []
    except (json.JSONDecodeError, TypeError):
        versions = []

    version_entry = {
        "version_hash": version_hash,
        "upload_time": now,
        "uploaded_by": uploaded_by,
        "uploaded_by_name": uploaded_by_name,
        "file_list": file_list,
        "size_bytes": len(data),
    }

    existing_hashes = {v.get("version_hash") for v in versions}
    if version_hash not in existing_hashes:
        versions.append(version_entry)

    _set_param(db, _param_key_versions(), json.dumps(versions, ensure_ascii=False), actor_user_id=uploaded_by)

    current_hash = _get_param_value(db, _param_key_version_hash())
    if not current_hash:
        _set_param(db, _param_key_version_hash(), version_hash, actor_user_id=uploaded_by)

    db.commit()

    _publish_event(
        "engine.version_uploaded",
        {"version_hash": version_hash, "uploaded_by": uploaded_by},
    )

    return version_entry


def list_versions(db: Session) -> list[dict[str, Any]]:
    versions_json = _get_param_value(db, _param_key_versions())
    try:
        return json.loads(versions_json) if versions_json else []
    except (json.JSONDecodeError, TypeError):
        return []


def get_current_version_hash(db: Session) -> str:
    return _get_param_value(db, _param_key_version_hash())


def activate_version(
    db: Session,
    version_hash: str,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    versions = list_versions(db)
    target = next((v for v in versions if v.get("version_hash") == version_hash), None)
    if not target:
        raise MatlabEngineError(f"版本 {version_hash} 不存在")

    _set_param(db, _param_key_version_hash(), version_hash, actor_user_id=actor_user_id)
    db.commit()

    _publish_event(
        "engine.version_activated",
        {"version_hash": version_hash, "activated_by": actor_user_id},
    )

    return target


def trigger_sync(
    db: Session,
    *,
    actor_user_id: str,
) -> str:
    current_hash = get_current_version_hash(db)
    if not current_hash:
        raise MatlabEngineError("当前没有激活版本，请先上传并激活一个版本")

    from ..tasks.sync_matlab_engine_task import sync_matlab_engine

    result = sync_matlab_engine.delay(current_hash, actor_user_id)
    return result.id


def _publish_event(name: str, payload: dict[str, Any]) -> None:
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        coro = publish_topic(
            MATLAB_ENGINE_TOPIC,
            name=name,
            payload=payload,
            requires_refetch=["/api/v1/fault-matlab/versions"],
            dedupe_key=f"matlab-engine:{name}:{payload.get('version_hash', 'unknown')}",
        )
        loop.create_task(coro)
    except RuntimeError:
        pass
    except Exception:
        logger.debug("Failed to publish MATLAB engine event %s", name, exc_info=True)
