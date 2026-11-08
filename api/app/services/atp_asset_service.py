from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
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
from datetime import timezone
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
from .atp_model_format import FORMAT_LABELS as _MODEL_FORMAT_LABELS
from .atp_model_format import (
    FORMAT_INSERT,
    FORMAT_LEGACY,
    FORMAT_PLAIN,
    PackageInspection,
    detect_model_format,
    inspect_package,
)
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
# 测试结论三档（2026-11-07）：passed 通过 / failed 未通过 / suspect 可疑
VALID_TEST_STATUS = {"passed", "failed", "suspect"}
VALID_RUNNER_KIND = {"atp", "egm", "hybrid"}
VALID_RUN_STATUS = {"pending", "running", "success", "failed"}
LOG_MAX_CHARS = 200_000
ATP_ASSET_FILES_ROOT = "/atp-assets"

# ATP 模型包上传白名单：.atp（仿真入口）/ .dat（几何源）/ .pch（7.2+ 几何载体）。
# 2026-11-02 放宽（D:\ATP 全量 1101 模型实测结论）：
#   - 老版 ATPDraw（7.2 前，work.atp 形态 `$INCLUDE ... .lib`）4944 行 $INCLUDE 全部指向
#     4 个标准名 .lib / .pch。.lib 由 regenerate_line_models 每轮从 .dat 重算
#     （LCC → .pch → pch_to_lib），.pch 本身是中间产物 → 老版包里的 .pch 一律不收
#     （入库即丢，见 upload_asset_files 的 legacy 裁剪）。
#   - 新版 ATPDraw（7.2+，work.atp 形态 `$INSERT <name><序号>.pch`）**必须**带上全部 pch：
#     pch 由 ATPDraw 内置 LCC 生成、LP 无法命令行复现，且节点名的唯一载体就是 pch 脚卡。
#     全库 483 个此类模型里 204 个跑不起来的首要原因就是 pch 缺失/被覆盖（见 E010）。
# .lib/.lis/.pl4/.log 仍为运行产物，由 geometry/simulate 现场生成，不允许上传
# （2026-09-26 实测：geometry 每轮按当轮参数重算覆盖 .lib，上传的 .lib 无兜底价值）。
# ⚠️ 若未来接入带 egm 引擎的资产包（egm 子目录 + .exe），需在此放开对应扩展名。
_ALLOWED_ATP_MODEL_EXTENSIONS: tuple[str, ...] = (".atp", ".dat", ".pch")
# 老版模型的四个标准几何源名（仅作文档/日志引用；完整性校验已移到
# atp_model_format.inspect_package 的 E002，因为只有先判定形态才知道该不该要求 .dat）
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


def _validate_test_line_ref(db: Session, test_line_id: str | None) -> str | None:
    """校验模型级绑定的测试线路（None/空 → 视为解绑）。"""
    value = _normalize_optional_str(test_line_id)
    if not value:
        return None
    from ..models.atp_test_line import AtpTestLine  # noqa: PLC0415

    row = db.get(AtpTestLine, value)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"测试线路不存在：{value}"
        )
    return row.id


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

    规则（2026-11-08 收紧，见 _ALLOWED_ATP_MODEL_EXTENSIONS）：
    1. 白名单：只允许 .atp / .dat / .pch；发现其他扩展名 → 400 并列出
       · .lib 是 LCC 派生件（由 .dat 重算），单独给提示而不是笼统报「非法文件」
       · .acp / .lis / .pl4 / .dbg 属于 ATPDraw 工程或运行输出，一律不收
    2. 入口：必须存在 work.atp，或恰好一个 .atp
    3. 几何完整性 / 形态判定 / 参数段可解析性 → 由 atp_model_format.inspect_package
       按形态分级判定（老版要四个 .dat，新版要 pch 齐全），不在此处硬卡

    校验失败时调用方保证零写入（本函数只读清单）。
    """
    if not relative_paths:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传包内没有有效文件")
    lower_map = {path.lower(): path for path in relative_paths}
    # .lib 单独提示：它是 dat 经 LCC 生成的派生文件，平台每轮重算，
    # 上传上来只会变成运行目录里的「旧件」，掩盖重算失败（静默沿用旧几何）。
    derived_lib = sorted(path for path in relative_paths if path.lower().endswith(".lib"))
    if derived_lib:
        shown = ", ".join(derived_lib[:8])
        suffix = f" 等 {len(derived_lib)} 个" if len(derived_lib) > 8 else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"不要上传 .lib（LCC 派生文件，平台会按 .dat 重新生成）：{shown}{suffix}。"
                "旧版模型只需 work.atp + long/short/dahao/xiaohao.dat；"
                "新版（$INSERT）模型另需它引用的 .pch"
            ),
        )
    illegal = sorted(path for path in relative_paths if not path.lower().endswith(_ALLOWED_ATP_MODEL_EXTENSIONS))
    if illegal:
        shown = ", ".join(illegal[:8])
        suffix = f" 等 {len(illegal)} 个" if len(illegal) > 8 else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ATP 模型只接受 .atp / .dat / .pch 文件，发现非法文件：{shown}{suffix}。"
                ".acp 是 ATPDraw 工程文件、.lis/.pl4/.dbg 是运行输出，均不参与计算，请勿上传"
            ),
        )
    atp_files = sorted(path for path in relative_paths if path.lower().endswith(".atp"))
    if _ENTRY_ATP_FILE not in lower_map and len(atp_files) != 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"必须包含 work.atp，或恰好一个 .atp 入口文件（当前 {len(atp_files)} 个 .atp）",
        )


# ── ATPDraw 形态判定与上传预检（2026-11-02 D:\ATP 全量 1101 模型实测） ──
# ⚠️ 版本指纹的**大小写对应的是 ATPDraw 6.x / 7.x 两代输出模板，不是 DBM 是否被移除**：
#   6.x 模板：`C Generated by ATPDRAW  十一月, 星期二 11, 2025`
#             + `C by H. K. Høidalen at SEfAS/NTNU - NORWAY 1994-2015`  → 618 个，全为 $INCLUDE+lib
#   7.x 模板：`C Generated by ATPDraw 十月, 3, 2026`
#             + `C ATPDraw developed by ... NTNU - NORWAY 1999-2020`     → 483 个，全为 $INSERT+序号pch
# 而 DBM 被移除发生在 **7.2**（官方 7.2 release note：New LCC approach without DBM、$INSERT 序号 punch 文件），
# 即 7.1 属于「7.x 模板 + 仍然 DBM」→ 会写出混合大小写指纹但仍是 $INCLUDE+lib 形态。
# 因此**不能**用指纹大小写做判据，必须按引用形态判。判定与逐项校验统一在
# `services/atp_model_format.py`（纯函数、可单测），本处只负责「转 HTTP 错误 + 落库」。
#
# 2026-11-02 策略变更：7.2+ 的 `$INSERT` 形态**不再拒收**，改为「校验通过就接收」——
# 只要 pch 齐全、参数段能解析，规范化后引擎实测可跑通（110/ganzi M123：rc=0、pl4 369665 字节）。
# 拒收只保留给真无法修复的形态（Enbed / 混合 / 依赖缺失）。


def _find_entry_atp_content(members: list[tuple[str, bytes]]) -> tuple[str, bytes] | None:
    """从 (相对路径, 内容) 列表中定位入口 .atp：优先 work.atp，否则唯一 .atp。"""
    lower_map = {path.lower(): (path, content) for path, content in members}
    hit = lower_map.get(_ENTRY_ATP_FILE)
    if hit is not None:
        return hit
    atp_members = sorted((path, content) for path, content in members if path.lower().endswith(".atp"))
    if len(atp_members) == 1:
        return atp_members[0]
    return None


# 参与预检的扩展名（.pch 会整份读入做分支头检查，单文件 8~16KB，量级可忽略）
_CHECKED_SUFFIXES: tuple[str, ...] = (".atp", ".dat", ".pch")

logger = logging.getLogger(__name__)


def _zip_members_for_check(archive_content: bytes) -> dict[str, bytes]:
    """从 ZIP 中只读取参与预检的成员（.atp/.dat/.pch），避免把大文件全解进内存。

    ZIP 损坏时返回空 dict，由调用方按「没有入口」报 E001（与真实缺文件同一出口）。
    """
    out: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(archive_content)) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative_path = _normalize_archive_member_path(member.filename)
                if relative_path is None or not relative_path.lower().endswith(_CHECKED_SUFFIXES):
                    continue
                try:
                    out[relative_path] = archive.read(member)
                except Exception:  # noqa: BLE001 - 单个成员读失败不阻断其余成员的检查
                    continue
    except zipfile.BadZipFile:
        return {}
    return out


def _format_check_detail(report: PackageInspection) -> str:
    """把预检报告拼成人工可读的多行文本（前端直接展示 detail）。

    每条都带「哪里不对 + 怎么改」，因为模型问题是人工去修的，不能只给错误码。
    """
    fmt_label = _MODEL_FORMAT_LABELS.get(report.model_format, report.model_format)
    lines = [
        f"模型预检未通过（形态：{fmt_label}），共 {len(report.errors)} 个错误"
        + (f"、{len(report.warnings)} 个提示" if report.warnings else ""),
    ]
    for issue in report.errors:
        where = f"（{issue.file}）" if issue.file else ""
        lines.append(f"[{issue.code}] {issue.message}{where}")
        lines.append(f"    → 修复：{issue.fix_hint}")
    if report.warnings:
        lines.append("已通过的提示项：")
        for issue in report.warnings[:5]:
            lines.append(f"[{issue.code}] {issue.message}")
    return "\n".join(lines)


def _inspect_atp_package_or_400(members: dict[str, bytes]) -> PackageInspection:
    """上传包整体预检：形态判定 + 依赖闭合 + 参数段可解析性。

    error 级问题抛 400（调用方保证零写入），warning 级随报告返回供落库展示。
    """
    report = inspect_package(members)
    if report.has_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_format_check_detail(report),
        )
    return report


def _apply_format_report(asset: AtpAsset, report: PackageInspection) -> None:
    """把预检结果写到资产行上（形态标记 + warning 清单）。"""
    asset.model_format = report.model_format
    asset.format_check_json = report.as_dict()


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
            # 内容级预检（形态判定 + pch 闭合 + 参数段可解析性）已由
            # upload_asset_archive 在写盘前完成，此处只做清单校验，
            # 避免同一份 zip 解析两遍（pch 合计几十 KB，但没必要重复读）。
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


def _row_field(item: Any, name: str, default: Any = None) -> Any:
    """安全读取 ORM 对象 / SQLAlchemy Row 上的字段，取不到返回 default。

    ⚠️ 为什么需要这个：`list_assets` 为了避开 tags_json 等大列走显式列白名单
    （`select(*columns)`），一旦某列忘了加进白名单，Row 取不到列时抛的是
    **KeyError 而不是 AttributeError**，`getattr(..., default)` 兜不住 → 列表接口
    直接 500（页面表现「加载失败」）。2026-11-01 的 test_line_id、2026-11-02 的
    model_format 都是这么挂的，这里统一兜一层，新增列漏加白名单最多是显示回落，
    不会再整页挂掉。
    """
    try:
        return getattr(item, name)
    except (AttributeError, KeyError):
        return default


def _analysis_fields_for_display(item: Any) -> tuple[str | None, str | None]:
    """返回 (analysis_status, analysis_error)，把「卡死的 pending/running」降级成失败。

    队列没有消费者（worker 挂了 / 部署忘了重启）时任务永远不会跑，库里会一直停在
    pending —— 前端会 2 秒轮询不止。超过 10 分钟没回写就按失败展示，提示人工重试，
    轮询也随之停止。DB 取回的时间可能没时区（MySQL DATETIME），按 UTC 补齐后再比。
    """
    status = _row_field(item, "analysis_status") or None
    error = _row_field(item, "analysis_error") or None
    if status not in (ANALYSIS_STATUS_PENDING, ANALYSIS_STATUS_RUNNING):
        return status, error
    reference = _row_field(item, "analysis_started_at") or _row_field(item, "update_date")
    if reference is None:
        return status, error
    try:
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        if (utcnow() - reference).total_seconds() > ANALYSIS_STALE_SECONDS:
            return (
                ANALYSIS_STATUS_FAILED,
                "分析任务超过 10 分钟未回写（队列可能没有消费者或任务已丢失），请重新检测",
            )
    except TypeError:  # 时区信息不一致时不影响展示，按原状态返回
        pass
    return status, error


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

    _analysis_status, _analysis_error = _analysis_fields_for_display(item)

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
        # 发布状态（2026-11-05）：存量行/旧列表 Row 可能没有该列 → 回落已发布（历史行为）
        is_published=bool(_row_field(item, "is_published") if _row_field(item, "is_published") is not None else True),
        published_date=_row_field(item, "published_date") or None,
        shield_wire=item.shield_wire or "with",
        test_line_id=item.test_line_id,
        # 形态标记（2026-11-02）：存量行没有该字段值时回落 legacy —— 改造前入口只放行
        # $INCLUDE 形态，历史数据必然是 legacy，不能显示成空。
        # 用 _row_field：本函数既接收 ORM 对象（详情/写接口）也接收列白名单 Row（列表接口），
        # Row 里若没有该列必须回落而不是抛 KeyError（见 _row_field 注释）。
        model_format=(_row_field(item, "model_format") or "legacy"),  # type: ignore[arg-type]
        model_format_label=_MODEL_FORMAT_LABELS.get(_row_field(item, "model_format") or "legacy"),
        format_check=(_row_field(item, "format_check_json") or None),
        # 异步分析状态（2026-11-03）：上传后自动触发的形态识别 + 槽位扫描
        analysis_status=_analysis_status,
        analysis_error=_analysis_error,
        analysis_started_at=_row_field(item, "analysis_started_at") or None,
        analysis_finished_at=_row_field(item, "analysis_finished_at") or None,
        # 测试结论（2026-11-07）：实跑仿真后的三档标记；未测试保持 None
        test_status=_row_field(item, "test_status") or None,
        test_message=_row_field(item, "test_message") or None,
        test_date=_row_field(item, "test_date") or None,
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
    test_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AtpAssetListResponse:
    # 只查列表接口需要的列（避开 tags_json 等列全行读取，400ms+ → 8ms，实测）
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
        # 多版本 + 生效 + 避雷线（2026-10-30：serialize_asset 访问这三列，缺则 AttributeError）
        AtpAsset.version,
        AtpAsset.is_active,
        # 2026-11-05：发布状态（serialize_asset 会读，漏列抛 KeyError，同上事故）
        AtpAsset.is_published,
        AtpAsset.published_date,
        AtpAsset.shield_wire,
        # 2026-11-01：serialize_asset 访问 test_line_id（测试线路），缺则 500：
        #   KeyError: 'test_line_id'（select 列白名单漏列 → Row.__getattr__ 抛 KeyError）
        AtpAsset.test_line_id,
        # 2026-11-02：serialize_asset 访问 model_format / format_check_json（形态标记 +
        #   上传预检报告），漏加同样 500 → ATP 模型管理页「加载失败」。新增列务必同步此处。
        AtpAsset.model_format,
        AtpAsset.format_check_json,
        # 2026-11-03：异步分析状态（形态识别 + 槽位扫描），serialize_asset 会读，
        # 漏列同样抛 KeyError（见上方 2026-11-02 的同款事故）。
        AtpAsset.analysis_status,
        AtpAsset.analysis_error,
        AtpAsset.analysis_started_at,
        AtpAsset.analysis_finished_at,
        # 2026-11-07：测试结论三档标记，serialize_asset 会读，漏列同样 KeyError
        AtpAsset.test_status,
        AtpAsset.test_message,
        AtpAsset.test_date,
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
    # 测试结论筛选（2026-11-07）：untested 是伪值，表示"从未测过"（列为 NULL）
    normalized_test = (test_status or "").strip().lower()
    if normalized_test:
        if normalized_test == "untested":
            stmt = stmt.where(AtpAsset.test_status.is_(None))
            total_stmt = total_stmt.where(AtpAsset.test_status.is_(None))
        elif normalized_test in VALID_TEST_STATUS:
            stmt = stmt.where(AtpAsset.test_status == normalized_test)
            total_stmt = total_stmt.where(AtpAsset.test_status == normalized_test)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail=f"Invalid test_status filter: {test_status}")

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


def _next_asset_version(db: Session, payload: AtpAssetCreateRequest, shield_wire: str) -> str:
    """未显式指定版本号时，按同维度组合内已有版本自动取下一个 vN。

    版本号从表单里去掉后（2026-11-03），同一维度组合重复上传不能都落 v1
    —— 否则存储路径冲突直接 400。这里按 v1/v2... 递增，非 vN 格式的版本
    （如 v2-rev3）不参与计数，只保证不与现有版本重名。
    """
    stmt = select(AtpAsset.version).where(
        AtpAsset.voltage_level == _normalize_optional_str(payload.voltage_level),
        AtpAsset.tower_type == _normalize_optional_str(payload.tower_type),
        AtpAsset.scene_type == _normalize_optional_str(payload.scene_type),
        AtpAsset.arrester_config == _normalize_optional_str(payload.arrester_config),
        AtpAsset.shield_wire == shield_wire,
    )
    existing = {v for v in db.scalars(stmt).all() if v}
    numbers = [int(m.group(1)) for v in existing if (m := re.fullmatch(r"v(\d+)", v.strip(), re.IGNORECASE))]
    candidate = f"v{max(numbers, default=0) + 1}"
    while candidate in existing:
        numbers.append(int(candidate[1:]))
        candidate = f"v{max(numbers) + 1}"
    return candidate


def create_asset(db: Session, payload: AtpAssetCreateRequest, *, actor_user_id: str) -> AtpAssetSummary | None:
    if get_asset_by_code(db, payload.code):
        return None

    now = utcnow()
    shield_wire = (payload.shield_wire or "with").strip() or "with"
    version = (payload.version or "").strip() or _next_asset_version(db, payload, shield_wire)
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
        # 版本发布（2026-11-05）：新建默认未发布（CreateRequest.is_published=False），
        # 显式传 True 的入口（脚本导入等）同步记录发布时间。
        is_published=bool(payload.is_published),
        published_date=now if payload.is_published else None,
        shield_wire=shield_wire,
        test_line_id=_validate_test_line_ref(db, payload.test_line_id),
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


def publish_asset(db: Session, *, asset_id: str, actor_user_id: str | None = None) -> AtpAssetSummary:
    """发布该版本（2026-11-05）：置 is_published=1 并记录发布时间。

    发布后版本参与仿真定位（fl_analysis 资产 _query 只在已发布版本中选取）。
    幂等：已发布的资产再次发布只刷新 published_date。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.status == "archived":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已归档的模型不能发布，请先恢复")
    asset.is_published = True
    asset.published_date = utcnow()
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _publish_change("asset.published", {"action": "published", "asset_id": asset.id})
    return serialize_asset(asset, run_count=0, last_run_status=None, last_run_date=None, db=db)


def unpublish_asset(db: Session, *, asset_id: str, actor_user_id: str | None = None) -> AtpAssetSummary:
    """下线该版本（2026-11-05）：置 is_published=0，不再参与仿真定位。

    不清除 is_active（生效标记保留，重新发布后立即恢复原生效语义）。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset.is_published = False
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _publish_change("asset.unpublished", {"action": "unpublished", "asset_id": asset.id})
    return serialize_asset(asset, run_count=0, last_run_status=None, last_run_date=None, db=db)


def mark_asset_test_status(
    db: Session,
    *,
    asset_id: str,
    test_status: str | None,
    message: str | None = None,
    actor_user_id: str | None = None,
) -> AtpAssetSummary:
    """写入「测试通过与否」标记（2026-11-07）。

    test_status: "passed" 通过 / "failed" 未通过 / "suspect" 可疑；
                 None = 清除标记，回到「未测试」。
    message    : 结论说明（失败原因、可疑点），超长截断 512 字。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    normalized = (test_status or "").strip().lower() or None
    if normalized is not None and normalized not in VALID_TEST_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Invalid test_status: {test_status}")
    asset.test_status = normalized
    asset.test_message = (message or "").strip()[:512] or None if normalized else None
    asset.test_date = utcnow() if normalized else None
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.add(asset)
    db.commit()
    db.refresh(asset)
    _publish_change("asset.test_status", {"action": "test_status", "asset_id": asset.id,
                                          "test_status": normalized})
    return serialize_asset(asset, run_count=0, last_run_status=None, last_run_date=None, db=db)


def get_asset_overview_tree(db: Session) -> dict[str, Any]:
    """总览思维导图：电压→塔型→场景→避雷器→避雷线→版本，叶子标注发布状态。

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
            AtpAsset.is_published,
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
                            published = bool(r.is_published)
                            sw_node["children"].append({
                                "label": f"{r.version or 'v1'} ({'已发布' if published else '未发布'})",
                                "key": r.id,
                                "value": 1,
                                "is_published": published,
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
    # 写盘前先做内容级预检：形态判定 + pch 闭合 + 参数段可解析性。
    # 失败时零写入（连 staging 目录都不建），避免留下半包。
    # 空结果 = zip 损坏或包内没有模型文件 → 交给下面的写盘阶段报 BadZipFile / 空包。
    members_for_check = _zip_members_for_check(archive_content)
    format_report = _inspect_atp_package_or_400(members_for_check) if members_for_check else None
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

        # 2026-11-05 修复：S3 存储上 list_dir 对"不存在的目录"不报错、返回空列表，
        # 旧逻辑据此误判 backup_exists=True，随后 move 一个不存在的 source 直接抛
        # Path not found，导致全新维度的首次上传必挂。备份的前提是目录下确有内容；
        # VFS 上若存在空壳目录也顺手清掉，避免 staging move 时撞 "Path already exists"。
        try:
            backup_exists = bool(driver.list_dir(storage_root_path))
        except StoragePathNotFoundError:
            backup_exists = False

        if not backup_exists:
            try:
                driver.delete_path(storage_root_path, is_dir=True, recursive=True)
            except StoragePathNotFoundError:
                pass

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
    if format_report is not None:
        # 形态标记 + 预检报告（warning 清单）随本次上传一起落库，前端据此展示标记与待办
        _apply_format_report(asset, format_report)
    db.commit()

    _publish_change(
        "asset.files_uploaded",
        {
            "action": "files_uploaded",
            "asset_id": asset.id,
            "storage_root_path": storage_root_path,
            "file_count": len(tree.files),
            "model_format": asset.model_format,
        },
    )

    # 上传后自动触发异步分析（形态复检 + 槽位扫描），与散文件上传同一口径
    schedule_asset_analysis(db, asset_id=asset.id, actor_user_id=actor_user_id)

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
    if "test_line_id" in update_data:
        # 模型级绑定测试线路（单塔基准）：传 null 表示解绑
        item.test_line_id = _validate_test_line_ref(db, update_data["test_line_id"])
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

    # 2026-11-07 全面上传体检：旧实现把整份 zip 读进内存（BytesIO）且所有成员
    # archive.read() 全量驻留在 pending 列表里，几百 MB 模型包内存峰值翻倍。
    # 改为流式：zip 直接在（Starlette 已 spool 到磁盘的）上传流上打开，
    # 成员逐个 archive.open → driver.write_stream；只有参与预检的小文本
    # （.atp/.dat/.pch，合计几十 KB）才读进内存。校验仍在写盘前完成
    # （失败时零写入），语义与旧实现一致。
    staged_paths: list[Path] = []
    opened_streams: list[Any] = []
    archives: list[zipfile.ZipFile] = []
    dropped_pch: list[str] = []
    # (相对路径, reader, 字节数, content_type)；reader=("zip", ZipFile, ZipInfo) 或 ("stream", fileobj, None)
    entries: list[tuple[str, tuple[str, Any, Any], int | None, str | None]] = []

    try:
        if temp_file_id:
            from ..core.file_upload import discard_temp_upload, stage_temp_upload

            temp_path, source_file_name, temp_size = stage_temp_upload(temp_file_id, actor_user_id)
            staged_paths.append(temp_path)
            temp_stream = temp_path.open("rb")
            opened_streams.append(temp_stream)
            default_name = source_file_name or "model.zip"
            entries.append(
                (
                    _normalize_archive_member_path(default_name) or default_name,
                    ("stream", temp_stream, None),
                    temp_size,
                    mimetypes.guess_type(default_name)[0],
                )
            )
        for upload in files or []:
            raw_name = (getattr(upload, "filename", "") or "").strip()
            if not raw_name:
                continue
            content_type = getattr(upload, "content_type", None) or mimetypes.guess_type(raw_name)[0]
            stream = upload.file
            try:
                stream.seek(0)
                stream.seek(0, 2)
                upload_size: int | None = int(stream.tell())
                stream.seek(0)
            except (OSError, ValueError):
                upload_size = None
            if upload_size == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"上传文件为空：{raw_name}")
            opened_streams.append(stream)
            if raw_name.lower().endswith(".zip"):
                try:
                    archive = zipfile.ZipFile(stream)
                except zipfile.BadZipFile as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail=f"ZIP 文件损坏: {exc}"
                    ) from exc
                archives.append(archive)
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    relative_path = _normalize_archive_member_path(member.filename)
                    if relative_path is None:
                        continue
                    entries.append(
                        (
                            relative_path,
                            ("zip", archive, member),
                            int(member.file_size),
                            mimetypes.guess_type(relative_path)[0],
                        )
                    )
            else:
                entries.append(
                    (
                        _normalize_archive_member_path(raw_name) or raw_name,
                        ("stream", stream, None),
                        upload_size,
                        content_type,
                    )
                )

        if not entries:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="缺少文件，请提供 files 或 temp_file_id",
            )

        # 统一校验：白名单扩展名 + .atp 入口（失败时零写入）
        _validate_atp_model_members([relative_path for relative_path, _, _, _ in entries])
        # 内容级预检（形态判定/pch 闭合/参数段）只读小文本成员，避免整包进内存
        checked: dict[str, bytes] = {}
        for relative_path, (kind, source, member), _size, _content_type in entries:
            if not relative_path.lower().endswith(_CHECKED_SUFFIXES):
                continue
            if kind == "zip":
                checked[relative_path] = source.read(member)
            else:
                checked[relative_path] = source.read()
                source.seek(0)
        format_report = _inspect_atp_package_or_400(checked)

        # 2026-11-08：旧版（$INCLUDE .lib）形态的 .pch 是纯中间产物。若留在资产里，
        # 每轮 _materialize_asset_files 都会把它带进运行目录 —— LCC 一旦没跑成功
        # （KILL=84 坐标重合、缺几何跳过重算等），ATP 就直接把这份旧 pch 当本轮产物用，
        # 结果看起来"成功"但几何是上一次的。入库即丢弃，链路固定为 dat→LCC→pch→lib，
        # 缺件时在 LCC 阶段报错，而不是静默算出一个假数。
        dropped_pch = []
        if format_report.model_format == FORMAT_LEGACY:
            kept_entries: list[tuple[str, tuple[str, Any, Any], int | None, str | None]] = []
            for entry in entries:
                if entry[0].lower().endswith(".pch"):
                    dropped_pch.append(entry[0])
                else:
                    kept_entries.append(entry)
            entries = kept_entries

        for relative_path, (kind, source, member), member_size, content_type in entries:
            target_path = normalize_virtual_path(f"{storage_root_path.rstrip('/')}/{relative_path}")
            parent_path = _parent_virtual_path(target_path)
            driver.ensure_directory(parent_path)
            if kind == "zip":
                with source.open(member) as member_stream:
                    driver.write_stream(target_path, member_stream, content_type=content_type, size=member_size)
            else:
                source.seek(0)
                driver.write_stream(target_path, source, content_type=content_type, size=member_size)
    finally:
        for archive in archives:
            try:
                archive.close()
            except Exception:
                pass
        for stream_handle in opened_streams:
            try:
                stream_handle.close()
            except Exception:
                pass
        for temp_path in staged_paths:
            discard_temp_upload(temp_path)

    asset.storage_mount_code = mount.code
    asset.storage_root_path = storage_root_path
    if dropped_pch:
        logger.info(
            "[ATP] 资产 %s 为旧版形态，已丢弃 %d 个 .pch（改由 .dat 经 LCC 重算）：%s",
            asset.code, len(dropped_pch), ", ".join(dropped_pch[:8]),
        )
    # 形态标记 + 预检报告（warning 清单）随本次上传落库
    _apply_format_report(asset, format_report)
    asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.commit()

    saved = get_asset_by_id(db, asset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Asset load failed")
    # 上传后自动触发异步分析（2026-11-03）：形态预检已在内存里算过并落库（毫秒级），
    # 这里补「按存储真实文件复检 + 槽位扫描」——要读 OSS，放后台跑，别拖慢上传响应。
    return schedule_asset_analysis(db, asset_id=asset_id, actor_user_id=actor_user_id)


def collect_check_members_from_storage(
    driver: Any,
    storage_root_path: str,
    tree: StorageTree,
) -> dict[str, bytes]:
    """从资产存储目录收集参与预检的成员（相对路径 → 原始字节）。

    只取 .atp / .dat / .pch（与上传预检同口径），单文件读失败跳过而不是整条失败：
    存量目录里可能有历史残留的坏文件，个别读不出来不应挡住其余文件的判定。
    返回的 key 是**相对**存储根的路径，与 upload 侧 members 语义一致。
    """
    root = storage_root_path.rstrip("/")
    members: dict[str, bytes] = {}
    for relative_path in sorted(tree.file_paths):
        if not relative_path.lower().endswith(_CHECKED_SUFFIXES):
            continue
        try:
            members[relative_path] = driver.read_file(f"{root}/{relative_path}").content
        except Exception:  # noqa: BLE001 - 单个成员读失败不阻断其余成员
            continue
    return members


def _analyze_asset_storage(
    db: Session,
    asset: AtpAsset,
    *,
    include_slots: bool = True,
) -> dict[str, Any]:
    """把资产目录读一遍，同时算出形态预检报告（可选槽位扫描结果）。

    I/O 只做一次：形态判定要用 work.atp 全文 + 被 $INSERT 引用的 pch，槽位扫描要用
    work.atp 的 $PARAMETER 段 + 四个几何 .dat —— 两边都要读同一批文件，合并成一趟，
    避免「重判形态」和「扫槽位」各读一遍（存储是 OSS，每个文件一次 HTTPS 往返）。

    返回 {"report": PackageInspection, "slots": dict | None}；目录空/读不动直接 409。
    """
    mount_code, storage_root_path = _resolve_asset_file_location(db, asset)
    mount = _resolve_mount(db, mount_code)
    driver = _build_driver_or_400(mount)
    try:
        tree = _walk_storage_tree(driver, storage_root_path)
    except HTTPException as exc:
        # 从未上传过文件的资产，存储目录根本不存在：这是「还没传模型」而不是存储故障，
        # 给人工一句能照做的提示，别把 404 原样抛给前端。
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="资产目录不存在（尚未上传模型文件），无法分析模型；请先上传模型文件",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"资产目录读取失败，无法分析模型：{exc.detail}",
        ) from exc

    members = collect_check_members_from_storage(driver, storage_root_path, tree)
    if not members:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="资产目录里没有 .atp / .dat / .pch 文件，无法判定形态；请先上传模型文件",
        )

    report = inspect_package(members)
    slots: dict[str, Any] | None = None
    if include_slots and report.entry_path and report.entry_path in members:
        work_atp_text = _decode_text_file(members[report.entry_path])
        dat_texts: dict[str, str] = {}
        for name in DAT_GEOMETRY_NAMES:
            wanted = f"{name}.dat"
            for relative_path, content in members.items():
                if relative_path.rsplit("/", 1)[-1].lower() != wanted:
                    continue
                text = _decode_text_file(content)
                if text is not None:
                    dat_texts[name] = text
                break
        if work_atp_text is not None:
            slots = scan_model_slots(work_atp_text=work_atp_text, dat_texts=dat_texts)
    return {"report": report, "slots": slots}


def recheck_asset_format(
    db: Session,
    *,
    asset_id: str,
    actor_user_id: str | None = None,
) -> AtpAssetSummary:
    """按存储里的真实模型文件重判形态，回写 model_format 与预检报告（同步）。

    存在的理由（2026-11-03 生产事故）：`model_format` 列是 2026-11-02 上传预检上线时
    才加的，DB 迁移给存量行统一填了默认值 `legacy`，而存量里本来就有 $INSERT（7.2+）
    模型 —— 于是「老版」标记是**列默认值**而不是判定结果，与文件真实形态不符。
    上传口只在上传/更新文件时判定，存量不会自动重判，故提供这条显式重判路径。

    与上传不同：这里**不因 error 级问题抛 400**，而是把报告原样落库 —— 存量模型可能
    本来就有缺 pch / 混合形态等问题，需要显示给人工去修，而不是让重判本身失败。

    ⚠️ 接口层不再直接调用本函数（会阻塞请求，单资产 2~3 秒），改走
    `schedule_asset_analysis` 异步任务；本函数保留给批量回填脚本
    （scripts/backfill_atp_model_format.py）与需要同步结果的运维场景。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    analyzed = _analyze_asset_storage(db, asset, include_slots=False)
    _apply_format_report(asset, analyzed["report"])
    asset.update_user = actor_user_id or asset.update_user
    asset.update_date = utcnow()
    db.commit()

    saved = get_asset_by_id(db, asset_id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Asset load failed")
    _publish_change(
        "asset.format_rechecked",
        {
            "action": "format_rechecked",
            "asset_id": asset_id,
            "model_format": saved.model_format,
        },
    )
    return serialize_asset(
        saved,
        run_count=len(saved.runs),
        last_run_status=saved.runs[0].status if saved.runs else None,
        last_run_date=saved.runs[0].create_date if saved.runs else None,
        db=db,
    )


# ===== 异步分析：形态识别 + 槽位扫描（2026-11-03）=====
# 为什么异步：判定本身 7ms，但读模型包走 OSS，单资产端到端 2~3 秒（实测 10 文件
# 1.37MB：walk 0.28s + read 0.73s + 客户端初始化约 1s）。同步跑会把上传响应和
# 「重新检测」按钮一起拖住，资产越多越明显。改为 Celery 任务（默认队列，worker 已消费
# celery/scheduled/default）+ 前端轮询 analysis_status。
# 超过这个时长还没有回写就按失败展示（队列无消费者时前端会一直轮询）
ANALYSIS_STALE_SECONDS = 600
ANALYSIS_STATUS_PENDING = "pending"
ANALYSIS_STATUS_RUNNING = "running"
ANALYSIS_STATUS_SUCCESS = "success"
ANALYSIS_STATUS_FAILED = "failed"


def _enqueue_asset_analysis(asset_id: str, token: str) -> str | None:
    """投递分析任务；broker 不可用时返回 None（由调用方落成 failed，不让请求 500）。"""
    try:
        # 延迟导入：tasks 模块反向依赖本服务，顶层导入会成环
        from ..tasks.atp_asset_tasks import analyze_atp_asset_job

        result = analyze_atp_asset_job.delay(asset_id, token)
        return getattr(result, "id", None)
    except Exception:  # noqa: BLE001 - 入队失败不能影响上传/重判本身
        logger.exception("ATP 资产分析任务入队失败 asset_id=%s", asset_id)
        return None


def schedule_asset_analysis(
    db: Session,
    *,
    asset_id: str,
    actor_user_id: str | None = None,
) -> AtpAssetSummary:
    """把「形态识别 + 槽位扫描」丢给后台任务，立即返回当前资产状态。

    token 防覆盖：每次调度换新 token，任务回写前比对；上传/重判期间若又来了新调度，
    旧任务直接放弃，不会把新结果覆盖成旧结论。
    """
    asset = get_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    token = uuid4().hex
    asset.analysis_status = ANALYSIS_STATUS_PENDING
    asset.analysis_error = None
    asset.analysis_token = token
    asset.analysis_started_at = None
    asset.analysis_finished_at = None
    if actor_user_id:
        asset.update_user = actor_user_id
    asset.update_date = utcnow()
    db.commit()

    task_id = _enqueue_asset_analysis(asset_id, token)
    if task_id is None:
        asset.analysis_status = ANALYSIS_STATUS_FAILED
        asset.analysis_error = "分析任务入队失败：消息队列不可用，请稍后重试"
        asset.analysis_finished_at = utcnow()
        db.commit()
    else:
        _publish_change(
            "asset.analysis_scheduled",
            {"action": "analysis_scheduled", "asset_id": asset_id, "task_id": task_id},
        )

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


def run_asset_analysis(*, asset_id: str, token: str) -> dict[str, Any]:
    """任务主体：形态识别 + 槽位扫描，一次读包，结果整体回写。

    状态机：pending → running → success | failed；任一步失败都落 failed + 原因，
    不抛给 Celery（避免无意义重试把一个坏包反复读十几次）。
    """
    from ..core.database import SessionLocal

    db = SessionLocal()
    try:
        asset = get_asset_by_id(db, asset_id)
        if asset is None:
            return {"status": "skipped", "reason": "asset_not_found"}
        if (asset.analysis_token or "") != token:
            # 入队后用户又传了新文件 / 又点了一次重判，这次的结果已经过期
            return {"status": "skipped", "reason": "stale_token"}

        asset.analysis_status = ANALYSIS_STATUS_RUNNING
        asset.analysis_started_at = utcnow()
        asset.analysis_error = None
        asset.analysis_finished_at = None
        db.commit()

        try:
            analyzed = _analyze_asset_storage(db, asset, include_slots=True)
        except HTTPException as exc:
            return _finish_analysis_failed(db, asset_id, token, str(exc.detail))
        except Exception as exc:  # noqa: BLE001 - 分析失败要落库给人工看，不能只留在日志
            logger.exception("ATP 资产分析异常 asset_id=%s", asset_id)
            return _finish_analysis_failed(db, asset_id, token, f"{type(exc).__name__}: {exc}")

        # 分析期间可能又有新调度（上传了新文件），此时本次结果作废
        db.refresh(asset)
        if (asset.analysis_token or "") != token:
            return {"status": "skipped", "reason": "stale_token"}

        report = analyzed["report"]
        _apply_format_report(asset, report)
        if analyzed["slots"]:
            asset.slots_json = analyzed["slots"]
        asset.analysis_status = ANALYSIS_STATUS_SUCCESS
        asset.analysis_error = None
        asset.analysis_finished_at = utcnow()
        asset.update_date = utcnow()
        db.commit()

        _publish_change(
            "asset.analysis_finished",
            {
                "action": "analysis_finished",
                "asset_id": asset_id,
                "model_format": asset.model_format,
                "status": ANALYSIS_STATUS_SUCCESS,
            },
        )
        return {
            "status": ANALYSIS_STATUS_SUCCESS,
            "model_format": report.model_format,
            "errors": len(report.errors),
            "slots": (analyzed["slots"] or {}).get("work_atp", {}).get("count"),
        }
    finally:
        db.close()


def _finish_analysis_failed(db: Session, asset_id: str, token: str, message: str) -> dict[str, Any]:
    """把失败落库（不改形态、不动槽位缓存），返回给任务日志。"""
    asset = get_asset_by_id(db, asset_id)
    if asset is None:
        return {"status": "skipped", "reason": "asset_not_found"}
    if (asset.analysis_token or "") != token:
        return {"status": "skipped", "reason": "stale_token"}
    asset.analysis_status = ANALYSIS_STATUS_FAILED
    asset.analysis_error = (message or "分析失败")[:512]
    asset.analysis_finished_at = utcnow()
    asset.update_date = utcnow()
    db.commit()
    _publish_change(
        "asset.analysis_finished",
        {
            "action": "analysis_finished",
            "asset_id": asset_id,
            "status": ANALYSIS_STATUS_FAILED,
            "error": asset.analysis_error,
        },
    )
    return {"status": ANALYSIS_STATUS_FAILED, "error": asset.analysis_error}



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


# 资产包自带引擎时的取用优先级：大表版优先（2026-11-02 全局切 mytpbig 后补）。
# 包里同时躺着两个 exe 时若取到 tpbig.exe（1.3MB 小表），四回路 / $PARAMETER 较多的
# 模型会重新踩 List 8 溢出（KILL=1）与 JTOKEN 溢出（KONST=120），且退出码仍为 0。
_ENGINE_PREFERENCE = ("mytpbig.exe", "tpbig.exe")


def _resolve_engine_prefix(payload_root: Path, *, step_kind: str) -> list[str]:
    mode = _resolve_engine_mode()
    if step_kind == "egm":
        materialized_candidate = _find_materialized_engine(payload_root, "rjtzl.exe")
        configured = settings.atp_rjtzl_executable
    else:
        materialized_candidate = None
        for engine_name in _ENGINE_PREFERENCE:
            materialized_candidate = _find_materialized_engine(payload_root, engine_name)
            if materialized_candidate:
                break
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
        # 异步分析状态：前端据此显示「扫描中」并在 pending/running 时轮询
        "analysis_status": asset.analysis_status,
        "analysis_error": asset.analysis_error,
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
