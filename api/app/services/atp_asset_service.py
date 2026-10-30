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
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from ..core.config import get_settings
from ..models.atp_asset import AtpAsset, AtpAssetRun
from ..models.base import utcnow
from ..models.file_storage import FileStorageMount
from ..models.dimension_item import DimensionItem
from ..models.user import User
from ..schemas.atp_asset import (
    AtpAssetCreateRequest,
    AtpAssetDetail,
    AtpAssetFileContentResponse,
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
)
from .legacy_atp_adapter import build_legacy_atp_status_checks
from .push_service import publish_topic
from .atp_slot_scanner import DAT_GEOMETRY_NAMES, scan_model_slots
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

# ATP 模型包上传白名单：接受 .atp（仿真入口）、.dat（几何/LCC 源）、.pch。
# .pch 分两类：
#   ① 标准名 short.pch/long.pch/... —— geometry 每轮重算覆盖，上传无兜底价值
#   ② 序号名 short1.pch/long3.pch/... —— 「无避雷线变体」(ganzino/guxingno/...)
#      work.atp 用 `$INSERT` 按网络分段引用的几何（8 段各不相同，实测 md5 全异），
#      LP 的 geometry 只生成 4 个标准名，无法覆盖序号 pch → 必须随包上传，
#      否则 simulate 时 ATP 读 $INSERT 找不到文件 → Halt → time-step loop=0。
#     （2026-09-29 实测：ganzino 全量 80 个因此失败）
# .lib/.lis/.pl4/.log 等仍是运行产物，由 geometry/simulate 现场生成，不允许上传
# （2026-09-26 实测：geometry 每轮按当轮参数重算覆盖 .lib，上传的 .lib 无兜底价值；
# 删 .lib 后系统可从 .dat 自动重生成并跑通）。
# ⚠️ 若未来接入带 egm 引擎的资产包（egm 子目录 + .exe），需在此放开对应扩展名。
_ALLOWED_ATP_MODEL_EXTENSIONS: tuple[str, ...] = (".atp", ".dat", ".pch")
_DAT_MODEL_NAMES: tuple[str, ...] = ("long", "short", "dahao", "xiaohao")
_ENTRY_ATP_FILE = "work.atp"


def _decode_text_file(raw: bytes) -> str | None:
    """尝试把文件字节解码为文本；无法解码时返回 None（调用方按 binary 处理）。

    - ATP 引擎产出的文本（work.atp / work.lis 等）含 GBK 中文注释（如「采用周期」），
      strict UTF-8 会误判为二进制；故依次尝试 UTF-8 → GBK。
    - 真二进制（如 work.pl4 波形）含大量 NUL 字节，即使恰好按 GBK 双字节
      拆通也会被 NUL 占比检查拦下，避免乱码当文本展示。
    """
    if not raw:
        return ""
    # 二进制嗅探：NUL 字节占比 ≥ 0.1%（或至少 4 个）视为二进制，不再尝试解码
    if raw.count(b"\x00") * 1000 >= max(4, len(raw) * 0.001 * 1000):
        return None
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return None


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


def _validate_atp_model_members(relative_paths: list[str]) -> None:
    """校验上传的 ATP 模型文件清单（zip 成员或散文件，只读不写）。

    规则（2026-09-26 改造，见 _ALLOWED_ATP_MODEL_EXTENSIONS）：
    1. 白名单：只允许 .atp / .dat；发现其他扩展名 → 400 并列出
    2. 入口：必须存在 work.atp，或恰好一个 .atp
    3. 几何：long/short/dahao/xiaohao 四个 .dat 必须齐全（缺一 → 400 并列出）
    校验失败时调用方保证零写入（本函数只读清单）。
    """
    if not relative_paths:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传包内没有有效文件")
    lower_map = {path.lower(): path for path in relative_paths}
    illegal = sorted(path for path in relative_paths if not path.lower().endswith(_ALLOWED_ATP_MODEL_EXTENSIONS))
    if illegal:
        shown = ", ".join(illegal[:8])
        suffix = f" 等 {len(illegal)} 个" if len(illegal) > 8 else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ATP 模型只接受 .atp / .dat 文件，发现非法文件：{shown}{suffix}",
        )
    atp_files = sorted(path for path in relative_paths if path.lower().endswith(".atp"))
    if _ENTRY_ATP_FILE not in lower_map and len(atp_files) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"必须包含 work.atp，或恰好一个 .atp 入口文件（当前 {len(atp_files)} 个 .atp）",
        )
    missing_dats = [name for name in _DAT_MODEL_NAMES if f"{name}.dat" not in lower_map]
    if missing_dats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少几何文件（必须含 long/short/dahao/xiaohao 四个 .dat）："
            + ", ".join(f"{name}.dat" for name in missing_dats),
        )


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
    shield_wire: str = "with",
    version: str = "v1",
    fallback_code: str,
) -> str:
    """按 ATP 模型目录分层构建存储路径：
    /atp-assets/<电压>/<塔型>/<场景>/<避雷器组合>/<避雷线>/<version>。

    与桌面版 ATP 模型目录结构一致（如 500/ganzi/fanji/M1）。多版本改造（2026-10-29）
    追加避雷线维度与版本段，使同一维度组合可共存多版本而不冲突。
    任一层缺失时回退到按 code 平铺，避免路径歧义。
    """
    segments = [
        _sanitize_storage_segment(voltage_level or "", fallback=""),
        _sanitize_storage_segment(tower_type or "", fallback=""),
        _sanitize_storage_segment(scene_type or "", fallback=""),
        _sanitize_storage_segment(arrester_config or "", fallback=""),
        _sanitize_storage_segment(shield_wire or "", fallback=""),
        _sanitize_storage_segment(version or "", fallback=""),
    ]
    # 兼容存量 4 段路径：避雷线/版本缺省时仅保留维度前 4 段（旧资产不迁移路径）
    if all(segments[:4]) and segments[4] in ("", "with") and segments[5] in ("", "v1"):
        # 显式传入默认 with/v1 且维度齐全 → 仍用 4 段（保持旧资产路径稳定）
        return normalize_virtual_path(f"{ATP_ASSET_FILES_ROOT}/{'/'.join(segments[:4])}")
    if all(segments):
        return normalize_virtual_path(f"{ATP_ASSET_FILES_ROOT}/{'/'.join(segments)}")
    return _build_asset_storage_root(fallback_code)


def _asset_dim_group_where(*, voltage_level, tower_type, scene_type, arrester_config, shield_wire):
    """构建同维度组（电压/塔型/场景/避雷器/避雷线）的查询条件——定位资产版本组用。"""
    conds = []
    for col, val in (
        (AtpAsset.voltage_level, voltage_level),
        (AtpAsset.tower_type, tower_type),
        (AtpAsset.scene_type, scene_type),
        (AtpAsset.arrester_config, arrester_config),
        (AtpAsset.shield_wire, shield_wire),
    ):
        if val is not None:
            conds.append(col == val)
    return conds


def _check_asset_storage_path_conflict(db: Session, storage_root_path: str, current_asset_id: str | None = None) -> None:
    """同一存储路径 + 同一 version 才判冲突（多版本改造：同维度组允许不同版本共存）。"""
    asset_stmt = select(AtpAsset).where(AtpAsset.storage_root_path == storage_root_path)
    if current_asset_id:
        asset_stmt = asset_stmt.where(AtpAsset.id != current_asset_id)

    existing_asset = db.execute(asset_stmt).scalar_one_or_none()
    if existing_asset:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"存储路径冲突：该路径已被模型 {existing_asset.code}（version={existing_asset.version}）占用。",
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
            # 第一遍：收集全部成员路径并整体校验（失败时零写入，不留脏数据）
            members: list[tuple[str, zipfile.ZipInfo]] = []
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative_path = _normalize_archive_member_path(member.filename)
                if relative_path is None:
                    continue
                members.append((relative_path, member))
            _validate_atp_model_members([path for path, _ in members])
            # 第二遍：写入
            for relative_path, member in members:
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
    label_map: dict[tuple[str, str], str] | None = None,
) -> AtpAssetSummary:
    # 从维度项解析中文标签（code → name 映射）
    # label_map: 批量预加载的 (dimension_type, code) → name 映射（列表序列化传入，避免每条资产 N+1 查询）
    dimension_label_cache: dict[tuple[str, str], str] = {}
    def _resolve_label(dimension_type: str, code: str | None) -> str | None:
        if not code:
            return None
        cache_key = (dimension_type, code)
        if cache_key in dimension_label_cache:
            return dimension_label_cache[cache_key]
        if label_map is not None:
            label = label_map.get(cache_key) or code
            dimension_label_cache[cache_key] = label
            return label
        if not db:
            return None
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
        version=item.version or "v1",
        is_active=bool(item.is_active),
        shield_wire=item.shield_wire or "with",
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


def serialize_run(
    item: AtpAssetRun,
    *,
    create_user_name: str | None = None,
) -> AtpAssetRunSummary:
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
        create_user_name=create_user_name,
        result_summary_json=item.result_summary_json or {},
    )


def serialize_run_detail(
    item: AtpAssetRun,
    *,
    create_user_name: str | None = None,
) -> AtpAssetRunDetail:
    summary = serialize_run(item, create_user_name=create_user_name)
    return AtpAssetRunDetail(
        **summary.model_dump(),
        stdout_text=item.stdout_text,
        stderr_text=item.stderr_text,
        output_manifest_json=item.output_manifest_json or {},
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


def _load_dimension_label_map(db: Session) -> dict[tuple[str, str], str]:
    """一次查维度项建 (dimension_type, code) -> name 映射（列表序列化批量用，避免每条资产 4 次单行查询）"""
    rows = db.execute(
        select(DimensionItem.dimension_type, DimensionItem.code, DimensionItem.name).where(
            DimensionItem.dimension_type.in_(
                ("voltage_level", "tower_type", "scenario", "arrester_combination")
            )
        )
    ).all()
    return {(str(r[0]), str(r[1])): str(r[2]) for r in rows if r[0] and r[1] and r[2]}


def _load_asset_last_run_map(db: Session, asset_ids: list[str]) -> dict[str, tuple[str | None, datetime | None]]:
    if not asset_ids:
        return {}
    # 只取 (asset_id, status, create_date) 三列：不 joinedload asset、不拉 stdout/stderr/result_summary 等大列
    # 排序语义保持不变：每资产按 create_date/id desc 取最新一次
    rows = db.execute(
        select(AtpAssetRun.asset_id, AtpAssetRun.status, AtpAssetRun.create_date)
        .where(AtpAssetRun.asset_id.in_(asset_ids))
        .order_by(AtpAssetRun.asset_id.asc(), AtpAssetRun.create_date.desc(), AtpAssetRun.id.desc())
    ).all()
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
    arrester_config: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AtpAssetListResponse:
    # 只查列表接口需要的 15 列（避开 description/tags_json 等列全行读取，400ms+ → 8ms，实测）
    columns = (
        AtpAsset.id,
        AtpAsset.code,
        AtpAsset.name,
        AtpAsset.description,
        AtpAsset.status,
        AtpAsset.voltage_level,
        AtpAsset.tower_type,
        AtpAsset.scene_type,
        AtpAsset.arrester_config,
        AtpAsset.storage_mount_code,
        AtpAsset.storage_root_path,
        AtpAsset.create_date,
        AtpAsset.create_user,
        AtpAsset.update_date,
        AtpAsset.update_user,
    )
    stmt = select(*columns).select_from(AtpAsset)
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
    if arrester_config and arrester_config.strip():
        stmt = stmt.where(AtpAsset.arrester_config == arrester_config.strip())
        total_stmt = total_stmt.where(AtpAsset.arrester_config == arrester_config.strip())

    items = db.execute(
        stmt.order_by(AtpAsset.update_date.desc(), AtpAsset.code.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = int(db.scalar(total_stmt) or 0)
    asset_ids = [item.id for item in items]
    run_count_map = _load_asset_run_count_map(db, asset_ids)
    last_run_map = _load_asset_last_run_map(db, asset_ids)
    label_map = _load_dimension_label_map(db)

    return AtpAssetListResponse(
        items=[
            serialize_asset(
                item,
                run_count=run_count_map.get(item.id, 0),
                last_run_status=last_run_map.get(item.id, (None, None))[0],
                last_run_date=last_run_map.get(item.id, (None, None))[1],
                label_map=label_map,
            )
            for item in items
        ],
        total=total,
    )


# 左侧维度树：电压等级 → 杆塔类型 → 场景 → 避雷器组合（与前端 ATP_TREE_LEVELS 一致）
_ATP_TREE_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("vl", "voltage_level", "voltage_level"),
    ("tw", "tower_type", "tower_type"),
    ("sc", "scene_type", "scenario"),
    ("ar", "arrester_config", "arrester_combination"),
)


def _sort_tree(nodes: list[dict[str, Any]]) -> None:
    """按 label 排序（中文 locale 语义：与前端 sortAtpTreeNodes 一致），并递归子节点。"""
    nodes.sort(key=lambda item: (item.get("label") or "", item.get("code") or ""))
    for node in nodes:
        children = node.get("children")
        if isinstance(children, list) and children:
            _sort_tree(children)


def list_asset_tree_children(
    db: Session,
    *,
    path: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    """维度树懒加载：给定父路径（如 "vl:110|tw:guxing"），返回该路径下一层维度的去重节点。

    - path 为空 → 第一层（电压等级）
    - keyword 非空 → 树内搜索：返回过滤后的嵌套树（保留命中节点及其全部后代），
      与前端旧 filterAtpTreeNodes 语义一致（命中节点保留全部后代、未命中中间节点保留命中子分支）
    - 逐段解析路径，过滤出该路径下的资产，按下一层维度聚合（去重 code + 计数）
    - 每个节点带 has_children（该值下是否存在更深维度资产）供前端标记叶子
    - label 从 DimensionItem 解析（dimension_type 见 _ATP_TREE_LEVELS 第三元），缺失回落 code
    """
    # 树内搜索：查匹配资产 → 构建完整路径树 → 过滤保留命中分支 → 嵌套序列化
    if keyword and keyword.strip():
        kw = keyword.strip().lower()
        like = f"%{kw}%"
        assets = db.execute(
            select(AtpAsset).where(
                or_(
                    AtpAsset.code.ilike(like),
                    AtpAsset.name.ilike(like),
                    AtpAsset.description.ilike(like),
                )
            )
        ).scalars().all()

        # 构建完整路径树（与前端 buildAtpTreeNodes 同构）
        nodes: dict[str, dict[str, Any]] = {}
        for asset in assets:
            parent_key = ""
            for prefix, field, _dim_type in _ATP_TREE_LEVELS:
                code = getattr(asset, field)
                if not code or not str(code).strip():
                    break
                code_str = str(code).strip()
                key = f"{parent_key}|{prefix}:{code_str}" if parent_key else f"{prefix}:{code_str}"
                node = nodes.setdefault(
                    key,
                    {"key": key, "code": code_str, "label": code_str, "count": 0, "children": {}},
                )
                node["count"] += 1
                # 挂到父节点 children（search 模式需要完整父子关系做过滤）
                if parent_key and parent_key in nodes:
                    nodes[parent_key]["children"][key] = node
                parent_key = key

        # 批量解析 label
        all_codes: dict[str, str] = {}
        for prefix, field, dim_type in _ATP_TREE_LEVELS:
            level_codes = [node["code"] for node in nodes.values() if node["key"].split("|")[-1].startswith(f"{prefix}:")]
            if not level_codes:
                continue
            dim_rows = db.execute(
                select(DimensionItem.code, DimensionItem.name).where(
                    DimensionItem.dimension_type == dim_type,
                    DimensionItem.code.in_(level_codes),
                )
            ).all()
            for code, name in dim_rows:
                all_codes[code] = name
        for node in nodes.values():
            node["label"] = all_codes.get(node["code"], node["code"])

        # 过滤：命中节点保留全部后代；未命中中间节点保留命中子分支
        def filter_node(key: str) -> dict[str, Any] | None:
            node = nodes[key]
            label = (node["label"] or "").lower()
            code = (node["code"] or "").lower()
            self_match = kw in label or kw in code
            kept_children: list[dict[str, Any]] = []
            for child_key, child in node["children"].items():
                kept = filter_node(child_key)
                if kept is not None:
                    kept_children.append(kept)
            if not self_match and not kept_children:
                return None
            return {
                "key": node["key"],
                "code": node["code"],
                "label": node["label"],
                "count": node["count"],
                "has_children": len(kept_children) > 0,
                "children": kept_children,
            }

        roots = [filter_node(key) for key in nodes if "|" not in key]
        result = [r for r in roots if r is not None]
        _sort_tree(result)
        return result

    level_index = 0
    filters: dict[str, str] = {}
    if path:
        for segment in path.split("|"):
            prefix, _, code = segment.partition(":")
            if not prefix or not code:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid tree path: {path}")
            level = next((item for item in _ATP_TREE_LEVELS if item[0] == prefix), None)
            if level is None or level_index >= len(_ATP_TREE_LEVELS):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid tree path: {path}")
            field = level[1]
            if code != "*":
                filters[field] = code
            level_index += 1

    if level_index >= len(_ATP_TREE_LEVELS):
        # 已到最深维度：无下一层
        return []

    next_field, next_dimension_type = _ATP_TREE_LEVELS[level_index][1], _ATP_TREE_LEVELS[level_index][2]
    attr = getattr(AtpAsset, next_field)

    stmt = (
        select(attr, func.count())
        .select_from(AtpAsset)
        .where(attr.isnot(None))
        .group_by(attr)
    )
    for field, code in filters.items():
        stmt = stmt.where(getattr(AtpAsset, field) == code)

    rows = db.execute(stmt).all()
    if not rows:
        return []

    # 批量解析 label：dimension_type + code → name
    codes = [str(row[0]) for row in rows]
    label_map: dict[str, str] = {}
    if codes:
        dim_rows = db.execute(
            select(DimensionItem.code, DimensionItem.name).where(
                DimensionItem.dimension_type == next_dimension_type,
                DimensionItem.code.in_(codes),
            )
        ).all()
        label_map = {code: name for code, name in dim_rows}

    # has_children：该值下是否存在更深维度资产
    deeper_attr = None
    if level_index + 1 < len(_ATP_TREE_LEVELS):
        deeper_attr = getattr(AtpAsset, _ATP_TREE_LEVELS[level_index + 1][1])

    result: list[dict[str, Any]] = []
    for code, count in rows:
        code_str = str(code)
        # 计数修正：当前层 group_by 已按此值聚合，count 即该路径下资产数
        key_prefix = f"{_ATP_TREE_LEVELS[level_index][0]}:{code_str}"
        if path:
            full_key = f"{path}|{key_prefix}"
        else:
            full_key = key_prefix

        has_children = False
        if deeper_attr is not None:
            deeper_stmt = select(func.count()).select_from(AtpAsset).where(
                getattr(AtpAsset, next_field) == code_str,
                deeper_attr.isnot(None),
            )
            for field, code_filter in filters.items():
                deeper_stmt = deeper_stmt.where(getattr(AtpAsset, field) == code_filter)
            has_children = int(db.scalar(deeper_stmt) or 0) > 0

        result.append(
            {
                "key": full_key,
                "code": code_str,
                "label": label_map.get(code_str, code_str),
                "count": int(count),
                "has_children": has_children,
            }
        )

    result.sort(key=lambda item: (item["label"] or ""))
    return result


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
    version = (payload.version or "v1").strip() or "v1"
    shield_wire = (payload.shield_wire or "with").strip() or "with"
    storage_mount_code = _normalize_optional_str(payload.storage_mount_code) or "main"
    storage_root_path = _normalize_optional_str(payload.storage_root_path)
    if storage_root_path is None:
        storage_root_path = _build_asset_storage_root_by_dimensions(
            voltage_level=payload.voltage_level,
            tower_type=payload.tower_type,
            scene_type=payload.scene_type,
            arrester_config=payload.arrester_config,
            shield_wire=shield_wire,
            version=version,
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
        version=version,
        is_active=bool(payload.is_active),
        shield_wire=shield_wire,
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


def activate_asset(db: Session, *, asset_id: str, actor_user_id: str | None = None) -> AtpAssetSummary:
    """把指定资产设为「生效」（同维度组内其他版本自动失效）。

    事务内：先 SELECT ... FOR UPDATE 锁定同维度组行，组内全部 is_active=0，
    再置本资产 is_active=1。防止并发激活导致组内双生效（竞态）。
    """
    asset = db.scalar(
        select(AtpAsset).where(AtpAsset.id == asset_id).with_for_update()
    )
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    # 同维度组条件（维度字段可能为 None，逐项判定）
    dims = dict(
        voltage_level=asset.voltage_level,
        tower_type=asset.tower_type,
        scene_type=asset.scene_type,
        arrester_config=asset.arrester_config,
        shield_wire=asset.shield_wire or "with",
    )
    # 组内全部失效
    db.execute(
        update(AtpAsset)
        .where(AtpAsset.id != asset_id)
        .where(
            *[
                getattr(AtpAsset, key) == val
                for key, val in dims.items() if val is not None
            ]
        )
        .values(is_active=False)
    )
    asset.is_active = True
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _publish_change("asset.activated", {"action": "activated", "asset_id": asset.id})
    return serialize_asset(asset, run_count=0, last_run_status=None, last_run_date=None, db=db)


def deactivate_asset(db: Session, *, asset_id: str, actor_user_id: str | None = None) -> AtpAssetSummary:
    """取消指定资产的生效状态（组内可能无生效版本——由 _query 回退兜底）。"""
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset.is_active = False
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _publish_change("asset.deactivated", {"action": "deactivated", "asset_id": asset.id})
    return serialize_asset(asset, run_count=0, last_run_status=None, last_run_date=None, db=db)


def get_asset_overview_tree(db: Session) -> dict[str, Any]:
    """总览思维导图：电压→塔型→场景→避雷器→避雷线→版本，叶子标注生效状态。

    一次查出全部资产（仅需要列），按维度逐层聚合，返回嵌套树结构。
    """
    rows = db.execute(
        select(
            AtpAsset.voltage_level,
            AtpAsset.tower_type,
            AtpAsset.scene_type,
            AtpAsset.arrester_config,
            AtpAsset.shield_wire,
            AtpAsset.version,
            AtpAsset.is_active,
            AtpAsset.status,
            AtpAsset.name,
            AtpAsset.id,
        )
    ).all()

    def _label(dim_type: str, code: str | None) -> str:
        if not code:
            return ""
        return str(code)

    # 逐层聚合：voltage → tower → scene → arrester → shield_wire → version
    root: dict[str, Any] = {"label": "ATP 资产总览", "key": "root", "value": len(rows), "children": []}
    by_voltage: dict[str, list] = {}
    for r in rows:
        vol = r.voltage_level or ""
        bucket = by_voltage.setdefault(vol, [])
        bucket.append(r)
    for vol in sorted(by_voltage, reverse=True):
        vol_rows = by_voltage[vol]
        v_node = {"label": f"{vol} kV" if vol else "未知电压", "key": f"vl:{vol}",
                  "value": len(vol_rows), "children": []}
        by_tower: dict[str, list] = {}
        for r in vol_rows:
            by_tower.setdefault(r.tower_type or "", []).append(r)
        for tw in sorted(by_tower):
            tw_rows = by_tower[tw]
            t_node = {"label": _label("tower_type", tw), "key": f"vl:{vol}|tw:{tw}",
                      "value": len(tw_rows), "children": []}
            by_scene: dict[str, list] = {}
            for r in tw_rows:
                by_scene.setdefault(r.scene_type or "", []).append(r)
            for sc in sorted(by_scene):
                sc_rows = by_scene[sc]
                s_node = {"label": _label("scenario", sc), "key": f"vl:{vol}|tw:{tw}|sc:{sc}",
                          "value": len(sc_rows), "children": []}
                by_arr: dict[str, list] = {}
                for r in sc_rows:
                    by_arr.setdefault(r.arrester_config or "", []).append(r)
                for ar in sorted(by_arr):
                    ar_rows = by_arr[ar]
                    a_node = {"label": _label("arrester_combination", ar),
                              "key": f"vl:{vol}|tw:{tw}|sc:{sc}|ar:{ar}",
                              "value": len(ar_rows), "children": []}
                    by_sw: dict[str, list] = {}
                    for r in ar_rows:
                        by_sw.setdefault(r.shield_wire or "with", []).append(r)
                    for sw in sorted(by_sw):
                        sw_rows = by_sw[sw]
                        sw_node = {"label": "有避雷线" if sw == "with" else "无避雷线",
                                   "key": f"vl:{vol}|tw:{tw}|sc:{sc}|ar:{ar}|sw:{sw}",
                                   "value": len(sw_rows), "children": []}
                        for r in sorted(sw_rows, key=lambda x: x.version or ""):
                            active = bool(r.is_active)
                            sw_node["children"].append({
                                "label": f"{r.version or 'v1'} ({'生效' if active else '未生效'})",
                                "key": r.id,
                                "value": 1,
                                "is_active": active,
                                "asset_id": r.id,
                                "asset_name": r.name,
                                "status": r.status,
                            })
                        a_node["children"].append(sw_node)
                    s_node["children"].append(a_node)
                t_node["children"].append(s_node)
            v_node["children"].append(t_node)
        root["children"].append(v_node)
    return root


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
    if "version" in update_data and update_data["version"] is not None:
        item.version = str(update_data["version"]).strip() or "v1"
    if "shield_wire" in update_data and update_data["shield_wire"] is not None:
        item.shield_wire = str(update_data["shield_wire"]).strip() or "with"
    if "is_active" in update_data and update_data["is_active"] is not None:
        # 通过 PATCH 直接置生效 → 走与 activate 相同的组内清零事务，防双生效
        if bool(update_data["is_active"]):
            if not item.is_active:
                activate_asset(db, asset_id=asset_id, actor_user_id=actor_user_id)
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
        else:
            item.is_active = False
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
            modified_at=item.modified_at.isoformat() if item.modified_at else None,
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
            modified_at=None,
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


def read_asset_file_content(
    db: Session,
    *,
    asset_id: str,
    relative_path: str,
    offset: int = 0,
    limit: int | None = None,
) -> AtpAssetFileContentResponse:
    """读取资产目录下文本文件内容(供详情页在线查看等用途)。

    - 仅允许读取资产存储目录内的相对路径(防越权)。
    - 二进制(不可解码为 UTF-8)返回 content_type="binary",不返回内容。
    - 行级懒加载分页：传 offset/limit 只返回该行区间(content)，并带 total_lines /
      has_more，前端滚动到底部继续拉取，**不再截断**（可看全文）。
    - limit=None 时返回全文(兼容详情页等一次性读取场景)。
    - 备注：当前 storage driver 仅支持整文件读取，故每页请求均会读取完整文件后
      按行切片返回；ATP 模型文件体量通常较小，可接受；大文件场景后续可扩展
      driver 字节级 range 读。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    storage_mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    mount = _resolve_mount(db, storage_mount_code)
    driver = _build_driver_or_400(mount)

    # 防越权:拼接后必须仍在存储根目录内
    normalized_root = normalize_virtual_path(storage_root_path).rstrip("/")
    target = join_virtual_path(normalized_root, relative_path)
    if not target.startswith(f"{normalized_root}/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

    try:
        result = driver.read_file(target)
    except StoragePathNotFoundError:
        return AtpAssetFileContentResponse(
            asset_id=asset_id,
            relative_path=relative_path,
            name=relative_path.split("/")[-1],
            size=0,
            content_type="not-found",
        )
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    raw = result.content
    text = _decode_text_file(raw)
    if text is None:
        return AtpAssetFileContentResponse(
            asset_id=asset_id,
            relative_path=relative_path,
            name=result.name,
            size=len(raw),
            mime_type=result.mime_type,
            content_type="binary",
        )

    lines = text.splitlines()
    total_lines = len(lines)
    preview = [line for line in lines[:300] if len(line) <= 2000]
    start = max(0, offset)
    if limit is None:
        # 不分页:返回全文(受 max_bytes 保护)
        end = total_lines
    else:
        end = min(total_lines, start + max(0, limit))
    page = lines[start:end]
    has_more = end < total_lines
    return AtpAssetFileContentResponse(
        asset_id=asset_id,
        relative_path=relative_path,
        name=result.name,
        size=len(raw),
        mime_type=result.mime_type,
        content_type="text",
        content="\n".join(page),
        preview_lines=preview,
        offset=start,
        limit=end - start,
        total_lines=total_lines,
        has_more=has_more,
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

    def _collect_upload_file(upload: Any) -> list[tuple[str, bytes, str | None]]:
        """把单个上传（zip 或散文件）展开为 (相对路径, 内容, content_type) 列表，暂不写存储。

        收集完成后由 _validate_atp_model_members 统一校验（失败时零写入）。
        """
        raw_name = (getattr(upload, "filename", "") or "").strip()
        if not raw_name:
            return []
        collected: list[tuple[str, bytes, str | None]] = []
        try:
            content = upload.file.read()
        finally:
            try:
                upload.file.close()
            except Exception:
                pass
        content_type = getattr(upload, "content_type", None) or mimetypes.guess_type(raw_name)[0]
        if raw_name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    for member in archive.infolist():
                        if member.is_dir():
                            continue
                        relative_path = _normalize_archive_member_path(member.filename)
                        if relative_path is None:
                            continue
                        collected.append(
                            (relative_path, archive.read(member), mimetypes.guess_type(relative_path)[0])
                        )
            except zipfile.BadZipFile as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=f"ZIP 文件损坏: {exc}"
                ) from exc
            return collected
        relative_path = _normalize_archive_member_path(raw_name) or raw_name
        collected.append((relative_path, content, content_type))
        return collected

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

    pending: list[tuple[str, bytes, str | None]] = []
    for file in resolved_files:
        pending.extend(_collect_upload_file(file))
    # 统一校验：白名单扩展名 + .atp 入口 + 四个标准 .dat（失败时零写入）
    _validate_atp_model_members([path for path, _, _ in pending])
    for relative_path, content, content_type in pending:
        target_path = normalize_virtual_path(f"{storage_root_path.rstrip('/')}/{relative_path}")
        parent_path = _parent_virtual_path(target_path)
        driver.ensure_directory(parent_path)
        driver.write_file(target_path, content=content, content_type=content_type)

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
    if lower.endswith(("tpbig.exe", "mytpbig.exe", "rjtzl.exe")):
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
    # 批量解析操作人 username（一次查询避免 N+1），供前端「操作人」列显示可读名
    user_ids = {item.create_user for item in items if item.create_user}
    create_user_names: dict[str, str] = {}
    if user_ids:
        user_rows = db.execute(select(User.id, User.username).where(User.id.in_(list(user_ids)))).all()
        create_user_names = {str(row[0]): str(row[1]) for row in user_rows}
    return AtpAssetRunListResponse(
        items=[
            serialize_run(item, create_user_name=create_user_names.get(item.create_user))
            for item in items
        ],
        total=total,
    )


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
    create_user_name = _resolve_create_user_name(db, item.create_user)
    return serialize_run_detail(item, create_user_name=create_user_name)


def _resolve_create_user_name(db: Session, user_id: str | None) -> str | None:
    """批量查询 User.username 作为操作人可读名（与 elevation_service 同款做法，避免 N+1）。"""
    if not user_id:
        return None
    return db.scalar(select(User.username).where(User.id == user_id))


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


# ─────────────────────── ATP 场景解析（3D 可视化数据源） ───────────────────────
# 2026-09-30 新增：把 .atp 入口文件解析成「节点-支路」场景 JSON，
# 供前端 Three.js 绘制电路拓扑（见 services/atp_scene_service.py 与
# web 端 atp-scene-viewer.tsx）。纯离线解析，不依赖引擎。

from .atp_scene_service import parse_atp_scene  # noqa: E402


def get_asset_scene(db: Session, *, asset_id: str, entry_file: str = _ENTRY_ATP_FILE) -> dict[str, Any]:
    """读取资产目录下的 .atp 入口文件并解析为场景 JSON。

    - entry_file 默认 work.atp（上传校验已保证资产必有入口 .atp）；
      也可传其他 .atp 相对路径（如 .runs/<id>/work.atp 产物）。
    - 防越权：与 read_asset_file_content 同款路径白名单校验。
    - 解析不抛异常：任何段解析失败只会出现在 warnings 里（尽力而为策略）。
    - .atp 文件缺失或不可解码时返回 404（与文件读取语义一致）。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    storage_mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    mount = _resolve_mount(db, storage_mount_code)
    driver = _build_driver_or_400(mount)

    normalized_relative = _normalize_relative_path(entry_file)
    if normalized_relative is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path")
    normalized_root = normalize_virtual_path(storage_root_path).rstrip("/")
    target = join_virtual_path(normalized_root, normalized_relative)
    if not target.startswith(f"{normalized_root}/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

    try:
        result = driver.read_file(target)
    except StoragePathNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ATP entry file not found: {entry_file}",
        ) from None
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    text = _decode_text_file(result.content if hasattr(result, "content") else b"")
    if text is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ATP entry file is not text: {entry_file}",
        )
    return parse_atp_scene(text, source_file=normalized_relative)


# ---------------------------------------------------------------------------
# 目标 1/2/3：ATP 模型槽位扫描、查看、覆盖检测
# ---------------------------------------------------------------------------


def _read_asset_text(db: Session, asset: AtpAsset, relative_path: str) -> str | None:
    """从资产存储读取单个文本文件（UTF-8→GBK 兜底解码），找不到返回 None。"""
    mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    mount = _resolve_mount(db, mount_code)
    driver = _build_driver_or_400(mount)
    normalized_root = normalize_virtual_path(storage_root_path).rstrip("/")
    target = join_virtual_path(normalized_root, relative_path)
    if not target.startswith(f"{normalized_root}/"):
        return None
    try:
        result = driver.read_file(target)
    except StoragePathNotFoundError:
        return None
    except StorageDriverError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _decode_text_file(result.content if hasattr(result, "content") else b"")


def scan_asset_slots(db: Session, *, asset_id: str, actor_user_id: str | None = None) -> dict[str, Any]:
    """扫描模型槽位（work.atp $PARAMETER + 各 .dat 几何坐标），写回 AtpAsset.slots_json。"""
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    # 入口 .atp：优先 work.atp，缺失时从文件列表找唯一 .atp
    work_atp_text = _read_asset_text(db, asset, _ENTRY_ATP_FILE)
    if work_atp_text is None:
        files_resp = list_asset_files(db, asset_id=asset_id)
        atp_entries = [it for it in files_resp.items if it.relative_path.lower().endswith(".atp") and not it.is_dir]
        if not atp_entries:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="资产目录下未找到 .atp 入口文件，无法扫描槽位",
            )
        work_atp_text = _read_asset_text(db, asset, atp_entries[0].relative_path)

    dat_texts: dict[str, str] = {}
    for name in DAT_GEOMETRY_NAMES:
        text = _read_asset_text(db, asset, f"{name}.dat")
        if text is not None:
            dat_texts[name] = text

    result = scan_model_slots(work_atp_text=work_atp_text, dat_texts=dat_texts)
    asset.slots_json = result
    if actor_user_id:
        asset.update_user = actor_user_id
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return result


def get_asset_slots_view(db: Session, *, asset_id: str) -> dict[str, Any]:
    """返回缓存槽位 + 便捷视图（槽位名列表、几何模型清单）。"""
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    cache: dict[str, Any] = asset.slots_json or {}
    work_atp = cache.get("work_atp") or {}
    geometry = cache.get("geometry") or {}
    slot_names = sorted((work_atp.get("slots") or {}).keys())
    geometry_models = sorted(geometry.keys())
    return {
        "asset_id": asset_id,
        "scanned_at": cache.get("scanned_at"),
        "work_atp": work_atp,
        "geometry": geometry,
        "slot_names": slot_names,
        "geometry_models": geometry_models,
    }


def check_asset_slot_coverage(
    db: Session,
    *,
    asset_id: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    """检测模型槽位覆盖情况（目标 3）。

    - 模型 work.atp $PARAMETER 槽位名集合 M
    - 参数模板槽位名并集 T（template_id 给定→单模板；否则按资产维度匹配 enabled 模板取并集）
    - missing = M - T：模型有、模板未映射 → 仿真时用 .atp 默认值（潜在风险）
    - unused  = T - M：模板映射了、模型没有 → 废映射（配置错误）
    """
    from ..models.atp_param_template import AtpParamTemplate

    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    cache: dict[str, Any] = asset.slots_json or {}
    model_slots = set((cache.get("work_atp") or {}).get("slots", {}).keys())
    if not model_slots:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="模型尚未扫描槽位，请先执行扫描",
        )

    templates_used: list[dict[str, Any]] = []
    if template_id:
        tmpl = db.get(AtpParamTemplate, template_id)
        if not tmpl:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="参数模板不存在")
        templates_used = [{"id": tmpl.id, "name": tmpl.name}]
        template_slots = set((tmpl.slots_json or {}).keys())
    else:
        # 按资产维度匹配 enabled 模板，取槽位并集
        stmt = select(AtpParamTemplate).where(AtpParamTemplate.enabled.is_(True))
        matched: list[AtpParamTemplate] = []
        for tmpl in db.execute(stmt).scalars():
            if _template_matches_asset(tmpl, asset):
                matched.append(tmpl)
                templates_used.append({"id": tmpl.id, "name": tmpl.name})
        template_slots = set()
        for tmpl in matched:
            template_slots |= set((tmpl.slots_json or {}).keys())

    missing = sorted(model_slots - template_slots)
    unused = sorted(template_slots - model_slots)
    covered = sorted(model_slots & template_slots)
    return {
        "asset_id": asset_id,
        "template_id": template_id,
        "templates_used": templates_used,
        "model_slots": sorted(model_slots),
        "template_slots": sorted(template_slots),
        "missing": missing,
        "unused": unused,
        "covered": covered,
        "coverage_rate": round(len(covered) / max(1, len(model_slots)) * 100, 1),
    }


def _template_matches_asset(tmpl: Any, asset: AtpAsset) -> bool:
    """模板维度字段匹配资产（None = 通配）。"""
    pairs = (
        (tmpl.tower_type, asset.tower_type),
        (tmpl.voltage_level, asset.voltage_level),
        (tmpl.scene_type, asset.scene_type),
        (tmpl.arrester_config, asset.arrester_config),
        (tmpl.structure_kind, None),
    )
    for tmpl_val, asset_val in pairs:
        if tmpl_val and asset_val and tmpl_val != asset_val:
            return False
    return True


# ---------------------------------------------------------------------------
# 目标 2：维度过滤取模型槽位并集（参数模板编辑下拉候选）
# ---------------------------------------------------------------------------


def get_slot_options(
    db: Session,
    *,
    tower_type: str | None = None,
    voltage_level: str | None = None,
    scene_type: str | None = None,
    arrester_config: str | None = None,
) -> dict[str, Any]:
    """按维度过滤已扫描模型，返回 work.atp $PARAMETER 槽位名并集。

    用于参数模板编辑时的槽位下拉候选——不再手敲槽位名，直接从
    匹配维度的模型扫描缓存里取并集。返回每个槽位的出现次数和示例值。
    """
    stmt = select(AtpAsset).where(AtpAsset.slots_json.is_not(None))
    matched: list[AtpAsset] = []
    for asset in db.execute(stmt).scalars():
        pairs = (
            (tower_type, asset.tower_type),
            (voltage_level, asset.voltage_level),
            (scene_type, asset.scene_type),
            (arrester_config, asset.arrester_config),
        )
        ok = True
        for want, have in pairs:
            if want and have and want != have:
                ok = False
                break
        if ok:
            matched.append(asset)

    union: dict[str, list[dict[str, Any]]] = {}
    for asset in matched:
        cache = asset.slots_json or {}
        slots = (cache.get("work_atp") or {}).get("slots") or {}
        for name, value in slots.items():
            union.setdefault(name, []).append({"asset_code": asset.code, "asset_name": asset.name, "value": value})

    items = [
        {"name": name, "count": len(sources), "sources": sources}
        for name, sources in sorted(union.items())
    ]
    return {
        "matched_assets": len(matched),
        "total_slots": len(union),
        "slots": items,
        "dimensions": {
            "tower_type": tower_type,
            "voltage_level": voltage_level,
            "scene_type": scene_type,
            "arrester_config": arrester_config,
        },
    }
