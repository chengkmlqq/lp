from __future__ import annotations

import asyncio
import hashlib
import io
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..core.config import get_settings
from ..models.atp_asset import AtpAsset, AtpAssetRun
from ..models.base import utcnow
from ..models.file_storage import FileStorageMount
from ..models.dimension_item import DimensionItem
from ..schemas.atp_asset import (
    AtpAssetCreateRequest,
    AtpAssetDetail,
    AtpAssetFileEntry,
    AtpAssetFileListResponse,
    AtpAssetFileUploadResponse,
    AtpAssetListResponse,
    AtpAssetRunDetail,
    AtpAssetRunListResponse,
    AtpAssetRunRequest,
    AtpAssetRunSummary,
    AtpAssetSummary,
    AtpAssetUpdateRequest,
    AtpEngineStatusResponse,
    AtpTopology,
    AtpTopologyEdge,
    AtpTopologyNode,
    AtpTopologyResponse,
)
from .atp_topology_parser import parse_atp_topology_from_bytes
from .legacy_atp_adapter import build_legacy_atp_status_checks
from .push_service import publish_topic
from .storage_driver import (
    StorageDriver,
    StorageDriverError,
    StorageInvalidPathError,
    StorageObject,
    StoragePathNotFoundError,
    build_storage_driver,
    join_virtual_path,
    normalize_virtual_path,
)


settings = get_settings()
ATP_ASSET_TOPIC = "admin.atp-assets"
VALID_ASSET_STATUS = {"draft", "enabled", "disabled", "archived"}
VALID_RUNNER_KIND = {"atp", "egm", "hybrid"}
VALID_RUN_STATUS = {"pending", "running", "success", "failed"}
LOG_MAX_CHARS = 200_000
ATP_ASSET_FILES_ROOT = "/atp-assets"


@dataclass(slots=True)
class StorageTree:
    files: list[StorageObject]
    directories: list[str]
    file_paths: set[str]
    dir_paths: set[str]
    max_depth: int


@dataclass(slots=True)
class CommandStep:
    label: str
    command: list[str]
    cwd: Path


class _ResolvedTempUpload:
    """将两段式上传解析出的 (content, file_name) 包装成上传文件兼容对象。"""

    def __init__(self, *, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = mimetypes.guess_type(filename)[0]
        self.file = io.BytesIO(content)


def _fire_and_forget(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_relative_path(value: str | None) -> str | None:
    normalized = _normalize_optional_str(value)
    if normalized is None:
        return None
    candidate = normalized.replace("\\", "/").strip("/")
    if not candidate or candidate in {".", ".."}:
        return None
    parts: list[str] = []
    for part in candidate.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Relative path cannot escape asset root")
        parts.append(part)
    return "/".join(parts) or None


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _truncate_output(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= LOG_MAX_CHARS:
        return value
    return f"{value[:LOG_MAX_CHARS]}\n...[truncated]"


def _resolve_timeout(payload_timeout: int | None) -> int:
    timeout_seconds = payload_timeout or settings.atp_engine_default_timeout_seconds
    if timeout_seconds > settings.atp_engine_max_timeout_seconds:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"timeout_seconds cannot exceed {settings.atp_engine_max_timeout_seconds}",
        )
    return timeout_seconds


def _resolve_engine_mode() -> str:
    mode = settings.atp_engine_mode.strip().lower()
    return "native" if mode == "native" else "wine"


def _resolve_binary(raw_path: str) -> str | None:
    configured = raw_path.strip()
    if not configured:
        return None

    resolved = shutil.which(configured)
    if resolved:
        return resolved

    candidate = Path(configured).expanduser()
    if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate.resolve())
    return None


def _resolve_storage_root() -> Path:
    root = Path(settings.atp_storage_root).expanduser()
    return root.resolve(strict=False)


def _resolve_engine_workdir() -> Path:
    configured = Path(settings.atp_engine_workdir).expanduser()
    if configured.is_absolute():
        return configured.resolve(strict=False)
    return (_resolve_storage_root() / configured).resolve(strict=False)


def _resolve_wine_engine_executable() -> tuple[str | None, str | None, str | None]:
    # API 容器不再安装 wine：wine 由 worker 容器提供，此处仅做配置/路径级
    # 检查（不探测二进制）。实际可用性由 worker 侧执行时验证。
    wine_binary = settings.wine_binary_path.strip() or "wine"

    allowed_root = Path(settings.wine_allowed_root).expanduser().resolve(strict=False)
    configured = Path(settings.atp_engine_executable).expanduser()
    if not configured.is_absolute():
        configured = (allowed_root / configured).resolve(strict=False)
    else:
        configured = configured.resolve(strict=False)

    if not configured.is_relative_to(allowed_root):
        return wine_binary, None, f"ATP engine executable must be inside {allowed_root}"
    if not configured.exists() or not configured.is_file():
        return wine_binary, None, f"ATP engine executable not found: {configured}"

    return wine_binary, str(configured), None


def _resolve_native_engine_executable() -> tuple[str | None, str | None]:
    resolved = _resolve_binary(settings.atp_engine_executable)
    if not resolved:
        return None, "ATP engine executable not found"
    return resolved, None


def get_engine_status() -> AtpEngineStatusResponse:
    mode = _resolve_engine_mode()
    storage_root = str(_resolve_storage_root())
    workdir = str(_resolve_engine_workdir())
    checks = build_legacy_atp_status_checks()

    if mode == "wine":
        wine_binary, resolved_engine, error = _resolve_wine_engine_executable()
        available = error is None
        executable_path = settings.atp_engine_executable.strip()
        resolved_binary = f"{wine_binary} -> {resolved_engine}" if wine_binary and resolved_engine else wine_binary
        return AtpEngineStatusResponse(
            mode="wine",
            available=available,
            executable_path=executable_path,
            resolved_executable=resolved_binary,
            storage_root=storage_root,
            workdir=workdir,
            default_timeout_seconds=settings.atp_engine_default_timeout_seconds,
            max_timeout_seconds=settings.atp_engine_max_timeout_seconds,
            checks=checks,
            error=error,
        )

    resolved_engine, error = _resolve_native_engine_executable()
    return AtpEngineStatusResponse(
        mode="native",
        available=error is None,
        executable_path=settings.atp_engine_executable.strip(),
        resolved_executable=resolved_engine,
        storage_root=storage_root,
        workdir=workdir,
        default_timeout_seconds=settings.atp_engine_default_timeout_seconds,
        max_timeout_seconds=settings.atp_engine_max_timeout_seconds,
        checks=checks,
        error=error,
    )


def _resolve_mount(db: Session, mount_code: str) -> FileStorageMount:
    mount = db.execute(
        select(FileStorageMount)
        .options(joinedload(FileStorageMount.backend))
        .where(
            FileStorageMount.code == mount_code,
            FileStorageMount.is_enabled.is_(True),
        )
    ).scalar_one_or_none()
    if not mount:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Storage mount not found: {mount_code}")
    return mount


def _build_driver_or_400(mount: FileStorageMount) -> StorageDriver:
    try:
        return build_storage_driver(mount.backend, mount)
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


def _relative_from_root(root_path: str, path: str) -> str:
    normalized_root = normalize_virtual_path(root_path).rstrip("/")
    normalized_path = normalize_virtual_path(path)
    if not normalized_root or normalized_root == "/":
        return normalized_path.lstrip("/")
    return normalized_path[len(normalized_root) + 1 :]


def _walk_storage_tree(driver: StorageDriver, root_path: str) -> StorageTree:
    normalized_root = normalize_virtual_path(root_path)
    stack: list[tuple[str, int]] = [(normalized_root, 0)]
    files: list[StorageObject] = []
    directories: list[str] = []
    file_paths: set[str] = set()
    dir_paths: set[str] = set()
    max_depth = 0

    while stack:
        current_path, depth = stack.pop()
        max_depth = max(max_depth, depth)
        try:
            entries = driver.list_dir(current_path)
        except StoragePathNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except StorageInvalidPathError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except StorageDriverError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

        for entry in entries:
            relative_path = _relative_from_root(normalized_root, entry.path)
            if not relative_path:
                continue
            normalized_relative = relative_path.replace("\\", "/")
            if entry.is_dir:
                directories.append(normalized_relative)
                dir_paths.add(normalized_relative)
                stack.append((entry.path, depth + 1))
                continue
            files.append(entry)
            file_paths.add(normalized_relative)

    files.sort(key=lambda item: _relative_from_root(normalized_root, item.path))
    directories.sort()
    return StorageTree(
        files=files,
        directories=directories,
        file_paths=file_paths,
        dir_paths=dir_paths,
        max_depth=max_depth,
    )


def _parent_virtual_path(path: str) -> str:
    normalized = normalize_virtual_path(path)
    if normalized == "/":
        return "/"
    parent = normalized.rsplit("/", 1)[0]
    return parent if parent else "/"


def _normalize_archive_member_path(value: str) -> str | None:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return None

    parts: list[str] = []
    for part in PurePosixPath(normalized).parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Archive entry escapes target path: {value}")
        parts.append(part)
    return "/".join(parts) or None


def _sanitize_storage_segment(value: str, *, fallback: str) -> str:
    normalized = _normalize_optional_str(value) or fallback
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip(".-")
    return normalized or fallback


def _build_asset_storage_root(asset_code: str) -> str:
    asset_segment = _sanitize_storage_segment(asset_code, fallback="asset")
    return normalize_virtual_path(f"{ATP_ASSET_FILES_ROOT}/{asset_segment}")


def _build_asset_storage_root_by_dimensions(
    *,
    voltage_level: str | None,
    tower_type: str | None,
    scene_type: str | None,
    arrester_config: str | None,
    fallback_code: str,
) -> str:
    """按 ATP 模型目录分层构建存储路径：/atp-assets/<电压>/<塔型>/<场景>/<避雷器组合>。

    与桌面版 ATP 模型目录结构一致（如 500/ganzi/fanji/M1）。
    任一层缺失时回退到按 code 平铺，避免路径歧义。
    """
    segments = [
        _sanitize_storage_segment(voltage_level or "", fallback=""),
        _sanitize_storage_segment(tower_type or "", fallback=""),
        _sanitize_storage_segment(scene_type or "", fallback=""),
        _sanitize_storage_segment(arrester_config or "", fallback=""),
    ]
    if all(segments):
        return normalize_virtual_path(f"{ATP_ASSET_FILES_ROOT}/{'/'.join(segments)}")
    return _build_asset_storage_root(fallback_code)


def _check_asset_storage_path_conflict(db: Session, storage_root_path: str, current_asset_id: str | None = None) -> None:
    asset_stmt = select(AtpAsset).where(AtpAsset.storage_root_path == storage_root_path)
    if current_asset_id:
        asset_stmt = asset_stmt.where(AtpAsset.id != current_asset_id)

    existing_asset = db.execute(asset_stmt).scalar_one_or_none()
    if existing_asset:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"存储路径冲突：该路径已被模型 {existing_asset.code} 占用。",
        )


def _resolve_asset_file_location(db: Session, asset: AtpAsset) -> tuple[str, str]:
    storage_mount_code = asset.storage_mount_code or "main"
    storage_root_path = asset.storage_root_path
    if storage_root_path is None:
        storage_root_path = _build_asset_storage_root(asset.code)
    return storage_mount_code, storage_root_path


def _write_archive_to_storage(
    driver: StorageDriver,
    *,
    storage_root_path: str,
    archive_filename: str,
    archive_content: bytes,
) -> int:
    filename = (archive_filename or "").strip().lower()
    if filename and not filename.endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ZIP 包必须是 zip 格式")
    if not archive_content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ZIP 包不能为空")

    driver.ensure_directory(storage_root_path)
    ensured_directories = {normalize_virtual_path(storage_root_path)}
    extracted_count = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative_path = _normalize_archive_member_path(member.filename)
                if relative_path is None:
                    continue
                target_path = normalize_virtual_path(f"{storage_root_path.rstrip('/')}/{relative_path}")
                parent_path = _parent_virtual_path(target_path)
                if parent_path not in ensured_directories:
                    driver.ensure_directory(parent_path)
                    ensured_directories.add(parent_path)
                try:
                    content = archive.read(member)
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"读取 ZIP 条目失败: {member.filename}: {exc}",
                    ) from exc
                driver.write_file(
                    target_path,
                    content=content,
                    content_type=mimetypes.guess_type(relative_path)[0],
                )
                extracted_count += 1
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"ZIP 文件损坏: {exc}") from exc

    if extracted_count <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ZIP 包中没有可导入文件")
    return extracted_count


def _read_upload_file_bytes(file: Any) -> tuple[str, bytes, str | None]:
    filename = (getattr(file, "filename", None) or "").strip() or "upload.zip"
    content_type = getattr(file, "content_type", None)
    try:
        content = file.file.read()
    finally:
        try:
            file.file.close()
        except Exception:
            pass
    return filename, content, content_type


def _write_archive_to_asset_storage(
    driver: StorageDriver,
    *,
    asset_storage_root: str,
    archive_filename: str,
    archive_content: bytes,
) -> int:
    return _write_archive_to_storage(
        driver,
        storage_root_path=asset_storage_root,
        archive_filename=archive_filename,
        archive_content=archive_content,
    )


def _resolve_runner_kind_from_tree(tree: StorageTree) -> str:
    detected_entry = _auto_detect_entry_file(tree)
    detected_egm_subdir = _auto_detect_egm_subdir(tree)
    if detected_entry and detected_egm_subdir:
        return "hybrid"
    if detected_egm_subdir:
        return "egm"
    return "atp"


def _auto_detect_entry_file(tree: StorageTree) -> str | None:
    preferred = "work.atp"
    if preferred in tree.file_paths:
        return preferred
    atp_files = [path for path in tree.file_paths if path.lower().endswith(".atp")]
    if len(atp_files) == 1:
        return atp_files[0]
    return None


def _auto_detect_egm_subdir(tree: StorageTree) -> str | None:
    candidates = [path for path in tree.dir_paths if path.lower().endswith("/egm") or path.lower() == "egm"]
    if not candidates:
        return None
    candidates.sort(key=len)
    return candidates[0]


def _assert_script_path(path: str | None, *, tree: StorageTree, field_name: str) -> str | None:
    normalized = _normalize_relative_path(path)
    if normalized is None:
        return None
    if not normalized.lower().endswith(".py"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} only supports .py scripts")
    if normalized not in tree.file_paths:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field_name} not found: {normalized}")
    return normalized


def serialize_asset(
    item: AtpAsset,
    *,
    run_count: int,
    last_run_status: str | None,
    last_run_date: datetime | None,
    db: Session | None = None,
) -> AtpAssetSummary:
    # 从维度项解析中文标签（code → name 映射）
    dimension_label_cache: dict[tuple[str, str], str] = {}
    def _resolve_label(dimension_type: str, code: str | None) -> str | None:
        if not code or not db:
            return None
        cache_key = (dimension_type, code)
        if cache_key in dimension_label_cache:
            return dimension_label_cache[cache_key]
        label = db.scalar(
            select(DimensionItem.name).where(
                DimensionItem.dimension_type == dimension_type,
                DimensionItem.code == code,
            )
        )
        dimension_label_cache[cache_key] = label if label else code
        return dimension_label_cache[cache_key]
    
    return AtpAssetSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        description=item.description,
        status=item.status,  # type: ignore[arg-type]
        voltage_level=item.voltage_level,
        voltage_level_label=_resolve_label("voltage_level", item.voltage_level),
        tower_type=item.tower_type,
        tower_type_label=_resolve_label("tower_type", item.tower_type),
        scene_type=item.scene_type,
        scene_type_label=_resolve_label("scenario", item.scene_type),
        arrester_config=item.arrester_config,
        arrester_config_label=_resolve_label("arrester_combination", item.arrester_config),
        storage_mount_code=item.storage_mount_code or "main",
        storage_root_path=item.storage_root_path,
        run_count=run_count,
        last_run_status=last_run_status,  # type: ignore[arg-type]
        last_run_date=last_run_date,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_run(item: AtpAssetRun) -> AtpAssetRunSummary:
    stdout_text = item.stdout_text or ""
    stderr_text = item.stderr_text or ""
    return AtpAssetRunSummary(
        id=item.id,
        asset_id=item.asset_id,
        asset_code=item.asset.code,
        asset_name=item.asset.name,
        status=item.status,  # type: ignore[arg-type]
        engine_mode=item.engine_mode,  # type: ignore[arg-type]
        runner_kind=item.runner_kind,  # type: ignore[arg-type]
        task_id=item.task_id,
        storage_mount_code=item.storage_mount_code,
        storage_root_path=item.storage_root_path,
        materialized_root_path=item.materialized_root_path,
        engine_command=item.engine_command,
        working_dir=item.working_dir,
        timeout_seconds=item.timeout_seconds,
        exit_code=item.exit_code,
        started_at=item.started_at,
        finished_at=item.finished_at,
        duration_ms=item.duration_ms,
        error_message=item.error_message,
        stdout_size=len(stdout_text),
        stderr_size=len(stderr_text),
        create_date=item.create_date,
        create_user=item.create_user,
    )


def serialize_run_detail(item: AtpAssetRun) -> AtpAssetRunDetail:
    summary = serialize_run(item)
    return AtpAssetRunDetail(
        **summary.model_dump(),
        stdout_text=item.stdout_text,
        stderr_text=item.stderr_text,
        output_manifest_json=item.output_manifest_json or {},
        result_summary_json=item.result_summary_json or {},
    )


def _load_asset_run_count_map(db: Session, asset_ids: list[str]) -> dict[str, int]:
    if not asset_ids:
        return {}
    rows = db.execute(
        select(AtpAssetRun.asset_id, func.count())
        .where(AtpAssetRun.asset_id.in_(asset_ids))
        .group_by(AtpAssetRun.asset_id)
    ).all()
    return {str(asset_id): int(count) for asset_id, count in rows}


def _load_asset_last_run_map(db: Session, asset_ids: list[str]) -> dict[str, tuple[str | None, datetime | None]]:
    if not asset_ids:
        return {}
    rows = db.execute(
        select(AtpAssetRun)
        .options(joinedload(AtpAssetRun.asset))
        .where(AtpAssetRun.asset_id.in_(asset_ids))
        .order_by(AtpAssetRun.asset_id.asc(), AtpAssetRun.create_date.desc(), AtpAssetRun.id.desc())
    ).scalars().all()
    result: dict[str, tuple[str | None, datetime | None]] = {}
    for row in rows:
        if row.asset_id in result:
            continue
        result[row.asset_id] = (row.status, row.create_date)
    return result


def list_assets(
    db: Session,
    *,
    keyword: str | None,
    status_filter: str | None,
    voltage_level: str | None,
    tower_type: str | None,
    scene_type: str | None,
    limit: int = 50,
    offset: int = 0,
) -> AtpAssetListResponse:
    stmt = select(AtpAsset)
    total_stmt = select(func.count()).select_from(AtpAsset)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = or_(AtpAsset.code.ilike(like), AtpAsset.name.ilike(like), AtpAsset.description.ilike(like))
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    normalized_status = (status_filter or "").strip().lower()
    if normalized_status:
        if normalized_status not in VALID_ASSET_STATUS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid status filter: {status_filter}")
        stmt = stmt.where(AtpAsset.status == normalized_status)
        total_stmt = total_stmt.where(AtpAsset.status == normalized_status)

    if voltage_level and voltage_level.strip():
        stmt = stmt.where(AtpAsset.voltage_level == voltage_level.strip())
        total_stmt = total_stmt.where(AtpAsset.voltage_level == voltage_level.strip())
    if tower_type and tower_type.strip():
        stmt = stmt.where(AtpAsset.tower_type == tower_type.strip())
        total_stmt = total_stmt.where(AtpAsset.tower_type == tower_type.strip())
    if scene_type and scene_type.strip():
        stmt = stmt.where(AtpAsset.scene_type == scene_type.strip())
        total_stmt = total_stmt.where(AtpAsset.scene_type == scene_type.strip())

    items = db.execute(
        stmt.order_by(AtpAsset.update_date.desc(), AtpAsset.code.asc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    total = int(db.scalar(total_stmt) or 0)
    asset_ids = [item.id for item in items]
    run_count_map = _load_asset_run_count_map(db, asset_ids)
    last_run_map = _load_asset_last_run_map(db, asset_ids)

    return AtpAssetListResponse(
        items=[
            serialize_asset(
                item,
                run_count=run_count_map.get(item.id, 0),
                last_run_status=last_run_map.get(item.id, (None, None))[0],
                last_run_date=last_run_map.get(item.id, (None, None))[1],
                db=db,
            )
            for item in items
        ],
        total=total,
    )


def get_asset_by_id(db: Session, asset_id: str) -> AtpAsset | None:
    return db.execute(select(AtpAsset).where(AtpAsset.id == asset_id)).scalar_one_or_none()


def get_asset_by_code(db: Session, code: str) -> AtpAsset | None:
    normalized = code.strip().lower()
    if not normalized:
        return None
    return db.execute(select(AtpAsset).where(func.lower(AtpAsset.code) == normalized)).scalar_one_or_none()


def create_asset(db: Session, payload: AtpAssetCreateRequest, *, actor_user_id: str) -> AtpAssetSummary | None:
    if get_asset_by_code(db, payload.code):
        return None

    now = utcnow()
    storage_mount_code = _normalize_optional_str(payload.storage_mount_code) or "main"
    storage_root_path = _normalize_optional_str(payload.storage_root_path)
    if storage_root_path is None:
        storage_root_path = _build_asset_storage_root_by_dimensions(
            voltage_level=payload.voltage_level,
            tower_type=payload.tower_type,
            scene_type=payload.scene_type,
            arrester_config=payload.arrester_config,
            fallback_code=payload.code.strip(),
        )
    item = AtpAsset(
        code=payload.code.strip(),
        name=payload.name.strip(),
        description=payload.description.strip(),
        status=payload.status,
        voltage_level=_normalize_optional_str(payload.voltage_level),
        tower_type=_normalize_optional_str(payload.tower_type),
        scene_type=_normalize_optional_str(payload.scene_type),
        arrester_config=_normalize_optional_str(payload.arrester_config),
        storage_mount_code=storage_mount_code,
        storage_root_path=storage_root_path,
        create_user=actor_user_id,
        update_user=actor_user_id,
        create_date=now,
        update_date=now,
    )
    _check_asset_storage_path_conflict(db, storage_root_path)
    db.add(item)
    db.commit()

    saved = get_asset_by_id(db, item.id)
    if not saved:
        return None

    _publish_change("asset.created", {"action": "created", "asset_id": saved.id})
    return serialize_asset(saved, run_count=0, last_run_status=None, last_run_date=None, db=db)


def upload_asset_archive(
    db: Session,
    *,
    asset_id: str,
    archive_filename: str,
    archive_content: bytes,
    actor_user_id: str,
) -> AtpAssetFileUploadResponse:
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    storage_mount_code = "main"
    # 用资产创建时确定的存储路径（分层维度路径或 code 平铺），避免与 create 时不一致
    storage_root_path = asset.storage_root_path or _build_asset_storage_root(asset.code)
    mount = _resolve_mount(db, storage_mount_code)
    driver = _build_driver_or_400(mount)
    root_parent = _parent_virtual_path(storage_root_path)
    root_name = PurePosixPath(storage_root_path).name or asset.id
    staging_root_path = normalize_virtual_path(f"{root_parent}/{root_name}.__upload__{uuid4().hex}")
    backup_root_path = normalize_virtual_path(f"{root_parent}/{root_name}.__backup__{uuid4().hex}")
    backup_exists = False
    try:
        uploaded_count = _write_archive_to_asset_storage(
            driver,
            asset_storage_root=staging_root_path,
            archive_filename=archive_filename,
            archive_content=archive_content,
        )

        try:
            driver.list_dir(storage_root_path)
            backup_exists = True
        except StoragePathNotFoundError:
            backup_exists = False

        if backup_exists:
            driver.move_path(
                storage_root_path,
                is_dir=True,
                target_parent_path=root_parent,
                new_name=PurePosixPath(backup_root_path).name,
            )

        try:
            driver.move_path(
                staging_root_path,
                is_dir=True,
                target_parent_path=root_parent,
                new_name=root_name,
            )
        except Exception:
            if backup_exists:
                try:
                    driver.move_path(
                        backup_root_path,
                        is_dir=True,
                        target_parent_path=root_parent,
                        new_name=root_name,
                    )
                except Exception:
                    pass
            raise
    finally:
        try:
            driver.delete_path(staging_root_path, is_dir=True, recursive=True)
        except Exception:
            pass
        if backup_exists:
            try:
                driver.delete_path(backup_root_path, is_dir=True, recursive=True)
            except Exception:
                pass

    try:
        tree = _walk_storage_tree(driver, storage_root_path)
    except HTTPException:
        tree = StorageTree(files=[], directories=[], file_paths=set(), dir_paths=set(), max_depth=0)

    asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.commit()

    _publish_change(
        "asset.files_uploaded",
        {
            "action": "files_uploaded",
            "asset_id": asset.id,
            "storage_root_path": storage_root_path,
            "file_count": len(tree.files),
        },
    )

    return AtpAssetFileUploadResponse(
        asset_id=asset.id,
        storage_mount_code=storage_mount_code,
        storage_root_path=storage_root_path,
        uploaded_count=uploaded_count,
        success=True,
    )


def update_asset(
    db: Session,
    asset_id: str,
    payload: AtpAssetUpdateRequest,
    *,
    actor_user_id: str,
) -> AtpAssetSummary | None:
    item = get_asset_by_id(db, asset_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        item.name = str(update_data["name"]).strip()
    if "description" in update_data and update_data["description"] is not None:
        item.description = str(update_data["description"]).strip()
    if "status" in update_data and update_data["status"] is not None:
        item.status = str(update_data["status"])
    if "voltage_level" in update_data:
        item.voltage_level = _normalize_optional_str(update_data["voltage_level"])
    if "tower_type" in update_data:
        item.tower_type = _normalize_optional_str(update_data["tower_type"])
    if "scene_type" in update_data:
        item.scene_type = _normalize_optional_str(update_data["scene_type"])
    if "arrester_config" in update_data:
        item.arrester_config = _normalize_optional_str(update_data["arrester_config"])
    if "storage_mount_code" in update_data:
        item.storage_mount_code = _normalize_optional_str(update_data["storage_mount_code"])
    if "storage_root_path" in update_data:
        next_storage_root_path = _normalize_optional_str(update_data["storage_root_path"])
        if next_storage_root_path is not None:
            _check_asset_storage_path_conflict(db, next_storage_root_path, asset_id)
        item.storage_root_path = next_storage_root_path

    item.update_user = actor_user_id
    item.update_date = utcnow()
    db.commit()

    saved = get_asset_by_id(db, asset_id)
    if not saved:
        return None
    _publish_change("asset.updated", {"action": "updated", "asset_id": saved.id})
    return serialize_asset(
        saved,
        run_count=len(saved.runs),
        last_run_status=saved.runs[0].status if saved.runs else None,
        last_run_date=saved.runs[0].create_date if saved.runs else None,
        db=db,
    )


def delete_asset(db: Session, asset_id: str) -> bool:
    item = get_asset_by_id(db, asset_id)
    if not item:
        return False

    if item.storage_root_path:
        try:
            mount_code = item.storage_mount_code or "main"
            mount = _resolve_mount(db, mount_code)
            driver = _build_driver_or_400(mount)
            driver.delete_path(item.storage_root_path, is_dir=True, recursive=True)
        except Exception:
            pass

    try:
        asset_mount = _resolve_mount(db, item.storage_mount_code or "main")
        asset_driver = _build_driver_or_400(asset_mount)
        asset_driver.delete_path(_build_asset_storage_root(item.code), is_dir=True, recursive=True)
    except Exception:
        pass

    db.delete(item)
    db.commit()
    _publish_change("asset.deleted", {"action": "deleted", "asset_id": asset_id})
    return True


def list_asset_files(db: Session, *, asset_id: str) -> AtpAssetFileListResponse:
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    storage_mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    mount = _resolve_mount(db, storage_mount_code)
    driver = _build_driver_or_400(mount)
    try:
        tree = _walk_storage_tree(driver, storage_root_path)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset storage path not found",
        )
    items = [
        AtpAssetFileEntry(
            relative_path=_relative_from_root(storage_root_path, item.path),
            name=item.name,
            is_dir=False,
            size=item.size,
            mime_type=item.mime_type,
            file_role=_infer_asset_file_role(asset, _relative_from_root(storage_root_path, item.path), False),
        )
        for item in tree.files
    ]
    dir_items = [
        AtpAssetFileEntry(
            relative_path=path,
            name=path.split("/")[-1],
            is_dir=True,
            size=0,
            mime_type=None,
            file_role=_infer_asset_file_role(asset, path, True),
        )
        for path in tree.directories
    ]
    merged_items = sorted([*dir_items, *items], key=lambda entry: (not entry.is_dir, entry.relative_path))
    return AtpAssetFileListResponse(
        asset_id=asset.id,
        storage_mount_code=storage_mount_code,
        storage_root_path=storage_root_path,
        items=merged_items,
        total=len(merged_items),
    )


def get_asset_topology(db: Session, *, asset_id: str) -> AtpTopologyResponse:
    """读取 ATP 模型入口文件并解析电路拓扑。

    读取 ``entry_file``（默认 work.atp）的原始字节，交给 ``atp_topology_parser`` 解析，返回拓扑数据。

    文件缺失或内容无法解析时抛出 404/502 HTTP 异常。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    entry_file = _normalize_relative_path(asset.entry_file) or "work.atp"
    entry_path = normalize_virtual_path(f"{asset.storage_root_path.rstrip('/')}/{entry_file}")

    mount = _resolve_mount(db, asset.storage_mount_code or "main")
    driver = _build_driver_or_400(mount)
    try:
        result = driver.read_file(entry_path)
    except StoragePathNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Entry file not found: {entry_file}") from exc
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    topology = parse_atp_topology_from_bytes(result.content)
    if not topology.nodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No topology found in ATP file")

    return AtpTopologyResponse(
        asset_id=asset.id,
        topology=AtpTopology(
            nodes=[AtpTopologyNode(id=n.id, label=n.label, node_type=n.node_type, params=n.params) for n in topology.nodes],
            edges=[AtpTopologyEdge(id=e.id, source=e.source, target=e.target, label=e.label, edge_type=e.edge_type) for e in topology.edges],
            parameters=topology.parameters,
            metadata=topology.metadata,
        ),
    )


def upload_asset_files(
    db: Session,
    *,
    asset_id: str,
    files: list[Any] | None = None,
    temp_file_id: str | None = None,
    actor_user_id: str,
) -> AtpAssetSummary:
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    if asset.storage_root_path is None:
        storage_root_path = _build_asset_storage_root(asset.code)
    _check_asset_storage_path_conflict(db, storage_root_path, asset_id)
    mount = _resolve_mount(db, mount_code)
    driver = _build_driver_or_400(mount)
    driver.ensure_directory(storage_root_path)

    def _write_upload_file(upload: Any, *, base_root: str) -> None:
        raw_name = (getattr(upload, "filename", "") or "").strip()
        if not raw_name:
            return
        try:
            content = upload.file.read()
        finally:
            try:
                upload.file.close()
            except Exception:
                pass

        content_type = getattr(upload, "content_type", None) or mimetypes.guess_type(raw_name)[0]
        lower_name = raw_name.lower()
        if lower_name.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    relative_path = _normalize_archive_member_path(member.filename)
                    if relative_path is None:
                        continue
                    target_path = normalize_virtual_path(f"{base_root.rstrip('/')}/{relative_path}")
                    parent_path = _parent_virtual_path(target_path)
                    driver.ensure_directory(parent_path)
                    driver.write_file(
                        target_path,
                        content=archive.read(member),
                        content_type=mimetypes.guess_type(relative_path)[0],
                    )
            return

        relative_path = _normalize_archive_member_path(raw_name) or raw_name
        target_path = normalize_virtual_path(f"{base_root.rstrip('/')}/{relative_path}")
        parent_path = _parent_virtual_path(target_path)
        driver.ensure_directory(parent_path)
        driver.write_file(target_path, content=content, content_type=content_type)

    resolved_files = list(files or [])
    if temp_file_id:
        from ..core.file_upload import resolve_temp_upload

        content, source_file_name = resolve_temp_upload(temp_file_id, actor_user_id)
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="临时文件为空，请重新上传")
        resolved_files.append(
            _ResolvedTempUpload(
                filename=source_file_name or "model.zip",
                content=content,
            )
        )

    if not resolved_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少文件，请提供 files 或 temp_file_id",
        )

    for file in resolved_files:
        _write_upload_file(file, base_root=storage_root_path)

    asset.storage_mount_code = mount.code
    asset.storage_root_path = storage_root_path
    asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.commit()

    saved = get_asset_by_id(db, asset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Asset load failed")
    return serialize_asset(
        saved,
        run_count=len(saved.runs),
        last_run_status=saved.runs[0].status if saved.runs else None,
        last_run_date=saved.runs[0].create_date if saved.runs else None,
        db=db,
    )


def _infer_asset_file_role(asset: AtpAsset, relative_path: str, is_dir: bool) -> str | None:
    if is_dir:
        return None
    lower = relative_path.lower()
    if lower.endswith(".atp"):
        return "atp"
    if lower.endswith(".py"):
        return "script"
    if lower.endswith(("tpbig.exe", "rjtzl.exe")):
        return "executable"
    if lower.endswith((".doc", ".docx", ".txt", ".md", ".pdf")):
        return "doc"
    return "other"


def list_runs(
    db: Session,
    *,
    asset_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AtpAssetRunListResponse:
    stmt = select(AtpAssetRun).options(joinedload(AtpAssetRun.asset))
    total_stmt = select(func.count()).select_from(AtpAssetRun)
    if asset_id:
        stmt = stmt.where(AtpAssetRun.asset_id == asset_id)
        total_stmt = total_stmt.where(AtpAssetRun.asset_id == asset_id)
    items = db.execute(
        stmt.order_by(AtpAssetRun.create_date.desc(), AtpAssetRun.id.desc()).offset(offset).limit(limit)
    ).scalars().all()
    total = int(db.scalar(total_stmt) or 0)
    return AtpAssetRunListResponse(items=[serialize_run(item) for item in items], total=total)


def get_run_by_id(db: Session, run_id: str) -> AtpAssetRun | None:
    return db.execute(
        select(AtpAssetRun)
        .options(joinedload(AtpAssetRun.asset))
        .where(AtpAssetRun.id == run_id)
    ).scalar_one_or_none()


def get_run_detail(db: Session, *, run_id: str) -> AtpAssetRunDetail:
    item = get_run_by_id(db, run_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return serialize_run_detail(item)


def execute_asset_run_job(*, run_id: str, payload_data: dict[str, Any], actor_user_id: str | None) -> None:
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        run = get_run_by_id(db, run_id)
        if run is None or run.status in {"success", "failed"}:
            return
        asset = run.asset
        payload = AtpAssetRunRequest.model_validate(payload_data)

        run.started_at = utcnow()
        run.status = "running"
        run.error_message = None
        run.finished_at = None
        run.duration_ms = None
        run.update_date = utcnow()
        run.update_user = actor_user_id
        db.commit()

        try:
            materialized = _prepare_materialized_asset(db, asset=asset, run_id=run.id, extra_args=payload.extra_args)
        except HTTPException as exc:
            _mark_run_failed(db, run=run, actor_user_id=actor_user_id, reason=str(exc.detail))
            return
        except RuntimeError as exc:
            _mark_run_failed(db, run=run, actor_user_id=actor_user_id, reason=str(exc))
            return

        run.materialized_root_path = str(materialized.payload_root)
        run.working_dir = str(materialized.working_dir)
        run.engine_command = "\n".join(" ".join(step.command) for step in materialized.command_steps)

        if payload.dry_run:
            run.status = "success"
            run.exit_code = 0
            run.stdout_text = json.dumps(
                {
                    "dry_run": True,
                    "commands": [
                        {"label": step.label, "command": step.command, "cwd": str(step.cwd)}
                        for step in materialized.command_steps
                    ],
                    "materialized_root_path": str(materialized.payload_root),
                },
                ensure_ascii=False,
                indent=2,
            )
            run.stderr_text = ""
            run.output_manifest_json = _collect_output_manifest(materialized.payload_root)
            run.finished_at = utcnow()
            run.duration_ms = 0
            run.update_user = actor_user_id
            run.update_date = utcnow()
            db.commit()
            _publish_change(
                "run.finished",
                {"action": "dry_finished", "asset_id": asset.id, "run_id": run.id, "status": run.status},
            )
            return

        env = os.environ.copy()
        env.update(payload.environment)
        started_perf = time.perf_counter()
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        try:
            last_returncode = 0
            for step in materialized.command_steps:
                result = subprocess.run(
                    step.command,
                    cwd=str(step.cwd),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=run.timeout_seconds,
                    check=False,
                )
                stdout_chunks.append(f"[{step.label}]\n{result.stdout}")
                stderr_chunks.append(f"[{step.label}]\n{result.stderr}")
                last_returncode = result.returncode
                if result.returncode != 0:
                    raise RuntimeError(f"{step.label} exited with code {result.returncode}")
            run.exit_code = last_returncode
            run.status = "success"
            run.error_message = None
        except subprocess.TimeoutExpired:
            run.status = "failed"
            run.exit_code = None
            run.error_message = f"Execution timed out after {run.timeout_seconds} seconds"
        except OSError as exc:
            run.status = "failed"
            run.exit_code = None
            run.error_message = str(exc)
        except RuntimeError as exc:
            run.status = "failed"
            run.exit_code = run.exit_code if run.exit_code is not None else 1
            run.error_message = str(exc)

        run.duration_ms = max(int((time.perf_counter() - started_perf) * 1000), 0)
        run.stdout_text = _truncate_output("\n\n".join(chunk for chunk in stdout_chunks if chunk))
        run.stderr_text = _truncate_output("\n\n".join(chunk for chunk in stderr_chunks if chunk))
        run.output_manifest_json = _collect_output_manifest(materialized.payload_root)
        run.finished_at = utcnow()
        run.update_user = actor_user_id
        run.update_date = utcnow()
        db.commit()
        _publish_change(
            "run.finished",
            {
                "action": "finished",
                "asset_id": asset.id,
                "run_id": run.id,
                "status": run.status,
                "exit_code": run.exit_code,
            },
        )
    finally:
        db.close()


def _dispatch_asset_run_task(*, run_id: str, payload_data: dict[str, Any], actor_user_id: str | None):
    from ..tasks.atp_asset_tasks import execute_atp_asset_run_job

    return execute_atp_asset_run_job.delay(run_id, payload_data, actor_user_id)


def _mark_run_failed(db: Session, *, run: AtpAssetRun, actor_user_id: str | None, reason: str) -> None:
    run.status = "failed"
    run.error_message = reason
    run.finished_at = utcnow()
    run.duration_ms = 0 if run.duration_ms is None else run.duration_ms
    run.update_user = actor_user_id
    run.update_date = utcnow()
    db.commit()
    _publish_change(
        "run.failed",
        {"action": "failed", "asset_id": run.asset_id,  "run_id": run.id, "reason": reason},
    )


def _resolve_engine_prefix(payload_root: Path, *, step_kind: str) -> list[str]:
    mode = _resolve_engine_mode()
    if step_kind == "egm":
        materialized_candidate = _find_materialized_engine(payload_root, "rjtzl.exe")
        configured = settings.atp_rjtzl_executable
    else:
        materialized_candidate = _find_materialized_engine(payload_root, "tpbig.exe")
        configured = settings.atp_tpbig_executable

    if mode == "wine":
        wine_binary = _resolve_binary(settings.wine_binary_path)
        if not wine_binary:
            raise RuntimeError("Wine binary not found")
        executable = materialized_candidate or _resolve_configured_wine_executable(configured)
        if not executable:
            raise RuntimeError(f"{step_kind.upper()} executable not found")
        return [wine_binary, executable]

    executable = materialized_candidate or _resolve_binary(configured)
    if not executable:
        raise RuntimeError(f"{step_kind.upper()} executable not found")
    return [executable]


def _find_materialized_engine(payload_root: Path, filename: str) -> str | None:
    matches = sorted(
        (path for path in payload_root.rglob("*") if path.is_file() and path.name.lower() == filename.lower()),
        key=lambda path: (len(path.parts), str(path)),
    )
    if not matches:
        return None
    return str(matches[0])


def _resolve_configured_wine_executable(raw_path: str) -> str | None:
    configured = raw_path.strip()
    if not configured:
        return None
    allowed_root = Path(settings.wine_allowed_root).expanduser().resolve(strict=False)
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = (allowed_root / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    if candidate != allowed_root and allowed_root not in candidate.parents:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return str(candidate)


def _collect_output_manifest(payload_root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path in sorted(payload_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(payload_root).as_posix()
        mime_type = mimetypes.guess_type(path.name)[0]
        items.append({"path": relative_path, "size": int(path.stat().st_size), "mime_type": mime_type})
    return {"file_count": len(items), "files": items[:500]}


def _publish_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            ATP_ASSET_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=[],
            dedupe_key=f"atp-asset:{event_name}:{payload.get('asset_id', '-')}",
        )
    )
