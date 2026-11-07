from __future__ import annotations

import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from .config import get_settings

# 两段式上传的临时区（本机磁盘）。
# 2026-11-07：原实现把临时文件放对象存储（OSS），但线上 OSS 账号 line-protection
# 返回 UserDisable（PutObject/DeleteObject 全被拒），所有 upload-temp 上传必然失败；
# 且原来用 file.file.read() 整份进内存，1GB 级 DEM 会直接打爆容器。现在改为
# 落本机盘 + 流式拷贝：内存占用与文件大小无关，也不再依赖对象存储。
LOCAL_TEMP_PREFIX = "local:"
TEMP_TTL_SECONDS = 48 * 3600

# 各类上传的大小上限（MB）。2026-11-07 全面上传体检时统一制定：
# 线上 1GB DEM 暴露出「有的端点无上限、有的端点错用全局 50MB」两个极端，
# 改为按业务用途给显式限额，新增上传端点时从这里取值，不要再拍脑袋。
UPLOAD_LIMITS_MB: dict[str, int] = {
    "default": 50,      # 兜底（validate_upload 不传 purpose/max_mb 时）
    "text": 64,         # CSV/TXT 台账、波形、地闪、故障复现曲线
    "spreadsheet": 128, # xlsx/csv 线路台账
    "image": 10,        # 头像、杆塔图片
    "model": 512,       # ATP 模型包 / 杆塔模型包（zip 或散文件）
    "release": 512,     # MATLAB 引擎发布包
    "file": 2048,       # 文件管理器任意文件 / 通用临时上传
    "raster": 4096,     # DEM 栅格（tif/zip，线上最大 1.27GB）
}


def get_upload_limit_mb(purpose: str | None = None) -> int:
    """取某类上传的大小上限（MB）；未知用途回落到 default。"""
    if not purpose:
        return UPLOAD_LIMITS_MB["default"]
    return UPLOAD_LIMITS_MB.get(purpose, UPLOAD_LIMITS_MB["default"])


def _file_size_bytes(file: UploadFile) -> int:
    """获取上传文件大小（字节），不将整份内容读入内存。

    ``UploadFile.size`` 在部分 FastAPI/Starlette 版本可能为 None，这里通过
    底层 SpooledTemporaryFile 的 seek/tell 兜底测量，避免超大文件被读入内存。
    """
    size_hint = getattr(file, "size", None)
    if isinstance(size_hint, int) and size_hint >= 0:
        return size_hint
    current = file.file.tell()
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(current)
    return size


def _temp_root() -> Path:
    """临时区根目录：优先配置项，其次 VFS 数据盘同级目录，最后系统临时目录。"""
    settings = get_settings()
    configured = (settings.upload_temp_dir or "").strip()
    if configured:
        root = Path(configured)
    else:
        vfs_root = (settings.file_vfs_root or "").strip()
        base = Path(vfs_root).resolve().parent if vfs_root else Path(tempfile.gettempdir())
        root = base / "tmp" / "uploads"
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "lp_uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _safe_filename(name: str | None) -> str:
    """只保留文件名本身，去掉目录与首尾点，避免路径穿越。"""
    raw = (name or "").strip() or "upload"
    cleaned = Path(raw.replace("\\", "/")).name.strip().strip(".")
    return cleaned or "upload"


def _safe_user_segment(user_id: str) -> str:
    segment = "".join(ch for ch in str(user_id or "") if ch.isalnum() or ch in {"-", "_"})
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户标识非法，无法使用临时上传区",
        )
    return segment


def _user_temp_dir(user_id: str) -> Path:
    directory = _temp_root() / _safe_user_segment(user_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cleanup_stale(directory: Path) -> None:
    """顺手清理超过保留期的临时文件（TTL 兜底，避免长期堆积占盘）。"""
    cutoff = time.time() - TEMP_TTL_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _temp_path_from_id(temp_file_id: str, user_id: str) -> Path:
    """把 temp_file_id 还原为本地路径，并校验归属当前用户。"""
    raw = (temp_file_id or "").strip()
    if not raw.startswith(LOCAL_TEMP_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="temp_file_id 无效或已过期，请重新上传",
        )
    token = raw[len(LOCAL_TEMP_PREFIX):]
    expected = f"{_safe_user_segment(user_id)}/"
    if not token.startswith(expected):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="temp_file_id 无效或不属于当前用户",
        )
    name = token[len(expected):]
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="temp_file_id 无效",
        )
    return _user_temp_dir(user_id) / name


def _original_name(stored_name: str) -> str:
    """临时文件名形如 ``{uuid}_{原始文件名}``，还原原始文件名。"""
    return stored_name.split("_", 1)[1] if "_" in stored_name else stored_name


def save_temp_upload(file: UploadFile, user_id: str) -> tuple[str, str]:
    """两段式上传的第一步：把上传文件流式落到本机临时区。

    返回 ``(temp_file_id, file_name)``。写入时先落 ``.part`` 再原子替换，
    避免半截文件被提交端点消费；超过 48h 的旧文件在下次上传时顺手清理。
    """
    size_bytes = _file_size_bytes(file)
    if size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件为空",
        )

    file_name = _safe_filename(file.filename)
    directory = _user_temp_dir(user_id)
    _cleanup_stale(directory)

    token = f"{uuid4().hex}_{file_name}"
    final_path = directory / token
    part_path = directory / f"{token}.part"

    try:
        try:
            file.file.seek(0)
        except (OSError, ValueError):
            pass
        with part_path.open("wb") as output:
            shutil.copyfileobj(file.file, output, 1024 * 1024)
        if part_path.stat().st_size <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="上传文件为空",
            )
        os.replace(part_path, final_path)
    except HTTPException:
        try:
            part_path.unlink()
        except OSError:
            pass
        raise
    except OSError as exc:
        try:
            part_path.unlink()
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"文件暂存失败：{exc}",
        ) from exc

    return f"{LOCAL_TEMP_PREFIX}{_safe_user_segment(user_id)}/{token}", file_name


def save_temp_file(
    file: UploadFile,
    user_id: str,
    *,
    allowed_exts: set[str] | None = None,
) -> tuple[str, str]:
    """兼容旧调用：带扩展名校验的临时文件保存。"""
    validate_upload(file, allowed_exts=allowed_exts)
    return save_temp_upload(file, user_id)


def read_temp_upload(temp_file_id: str, user_id: str) -> bytes:
    """读取临时文件内容并删除（消费即删）。

    小文件场景（CSV/图片等）可直接用；GB 级文件请用 ``open_temp_upload_stream``
    或 ``copy_temp_upload_to_driver``，避免整份进内存。
    """
    path = _temp_path_from_id(temp_file_id, user_id)
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取临时文件失败：{exc}",
        ) from exc
    finally:
        try:
            path.unlink()
        except OSError:
            pass

    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    return content


def resolve_temp_upload(temp_file_id: str, user_id: str) -> tuple[bytes, str]:
    """读取临时文件并返回 ``(content, 原始文件名)``，读取后即删除。"""
    path = _temp_path_from_id(temp_file_id, user_id)
    file_name = _original_name(path.name)
    return read_temp_upload(temp_file_id, user_id), file_name


def resolve_temp_file(temp_file_id: str, user_id: str) -> tuple[bytes, str]:
    """``resolve_temp_upload`` 的旧名（保持向后兼容）。"""
    return resolve_temp_upload(temp_file_id, user_id)


def describe_temp_upload(temp_file_id: str, user_id: str) -> tuple[str, int]:
    """返回临时文件的 ``(原始文件名, 字节数)``，不读取内容。"""
    path = _temp_path_from_id(temp_file_id, user_id)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取临时文件失败：{exc}",
        ) from exc
    return _original_name(path.name), int(size)


def stage_temp_upload(temp_file_id: str, user_id: str) -> tuple[Path, str, int]:
    """把临时上传定位为本地文件，返回 ``(路径, 原始文件名, 字节数)``,不删除、不读取。

    大文件（ATP 模型包、DEM 等）不要用 ``resolve_temp_upload`` 整份读进内存，
    用本函数拿到路径后直接 ``open``/``zipfile.ZipFile`` 按流处理；
    处理完由调用方负责 ``path.unlink()``（或改用 ``discard_temp_upload``）。
    """
    path = _temp_path_from_id(temp_file_id, user_id)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取临时文件失败：{exc}",
        ) from exc
    if size <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    return path, _original_name(path.name), int(size)


def discard_temp_upload(path: Path) -> None:
    """删除 ``stage_temp_upload`` 返回的临时文件（尽力而为，不抛错）。"""
    try:
        path.unlink()
    except OSError:
        pass


@contextmanager
def open_temp_upload_stream(temp_file_id: str, user_id: str) -> Iterator[tuple[Any, str, int]]:
    """以流的方式打开临时文件，产出 ``(stream, 原始文件名, 字节数)``。

    使用后关闭句柄并删除临时文件（消费即删）。
    """
    path = _temp_path_from_id(temp_file_id, user_id)
    try:
        stream = path.open("rb")
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None
    try:
        yield stream, _original_name(path.name), int(path.stat().st_size)
    finally:
        try:
            stream.close()
        except Exception:
            pass
        try:
            path.unlink()
        except OSError:
            pass


def copy_temp_upload_to_driver(
    temp_file_id: str,
    user_id: str,
    driver: Any,
    dest_path: str,
    *,
    content_type: str | None = None,
) -> int:
    """把临时文件落地到目标存储，返回字节数。

    目标与临时区在同一块磁盘（本地 VFS）时直接 ``os.replace``——毫秒级，零拷贝；
    否则以流的方式写入（``driver.write_stream``），内存占用恒定。
    """
    path = _temp_path_from_id(temp_file_id, user_id)
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None

    local_target: str | None = None
    resolver = getattr(driver, "local_path_for", None)
    if callable(resolver):
        try:
            local_target = resolver(dest_path)
        except Exception:
            local_target = None

    if local_target:
        try:
            target = Path(local_target)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
            return int(target.stat().st_size)
        except OSError:
            # 跨设备或权限问题，退回流式拷贝
            pass

    with path.open("rb") as stream:
        driver.write_stream(dest_path, stream, content_type=content_type, size=size)

    try:
        path.unlink()
    except OSError:
        pass
    return size


def cleanup_expired_temp_uploads(ttl_hours: float = TEMP_TTL_SECONDS / 3600) -> int:
    """清理超过保留期的本地临时上传文件，返回删除数量（供定时任务调用）。"""
    root = _temp_root()
    cutoff = time.time() - max(ttl_hours, 1) * 3600
    deleted = 0
    try:
        user_dirs = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return 0
    for directory in user_dirs:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    deleted += 1
            except OSError:
                continue
    return deleted


def _check_upload(
    *,
    size_bytes: int,
    filename: str,
    max_mb: int | None,
    allowed_exts: set[str] | None,
    allowed_exts_label: str,
) -> None:
    """统一上传校验核心：大小上限（413）+ 扩展名白名单（400）。"""
    if max_mb is None:
        max_mb = get_settings().upload_max_file_size_mb
    if max_mb <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="上传大小限制配置非法：UPLOAD_MAX_FILE_SIZE_MB 必须 > 0",
        )

    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小 {size_bytes / (1024 * 1024):.1f}MB 超过限制 {max_mb}MB，请压缩后重新上传",
        )

    if allowed_exts:
        filename = (filename or "").strip()
        ext = Path(filename).suffix.lstrip(".").lower()
        normalized_allowed = {ex.lower().lstrip(".") for ex in allowed_exts}
        if ext not in normalized_allowed:
            if not allowed_exts_label:
                allowed_exts_label = "/".join(sorted(normalized_allowed))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式：{filename}，仅支持 .{allowed_exts_label}",
            )


def validate_upload(
    file: UploadFile | None,
    max_mb: int | None = None,
    allowed_exts: set[str] | None = None,
    *,
    allowed_exts_label: str = "",
    purpose: str | None = None,
) -> UploadFile | None:
    """统一的上传文件校验依赖：大小上限（413）+ 扩展名白名单（400）。

    可作 FastAPI ``Depends`` 使用，也可在端点内显式调用。校验通过后原样返回
    文件对象，上传链路不受影响。

    Parameters
    ----------
    file:
        上传文件对象。为 None 时直接放行返回 None（兼容 temp_file_id 路径：
        文件已上传到临时区，导入端点仅传临时文件 ID 不带 file）。
    max_mb:
        文件大小上限（MB）。为 None 且未给 purpose 时取全局配置
        ``UPLOAD_MAX_FILE_SIZE_MB``；给了 purpose 则取 ``UPLOAD_LIMITS_MB[purpose]``
        （见模块顶部预设表），max_mb 显式传值时优先于 purpose。
    allowed_exts:
        允许的扩展名集合（不含点，如 ``{"csv", "xlsx"}``），匹配前归一化为小写。
        为 None 时不做扩展名校验。
    allowed_exts_label:
        错误提示里的扩展名展示文案（如 "csv/xlsx"）。为空则自动从 allowed_exts 生成。
    purpose:
        上传用途（``UPLOAD_LIMITS_MB`` 的键），用于确定大小上限。
    """
    if file is None:
        return None
    if max_mb is None and purpose:
        max_mb = get_upload_limit_mb(purpose)
    _check_upload(
        size_bytes=_file_size_bytes(file),
        filename=file.filename or "",
        max_mb=max_mb,
        allowed_exts=allowed_exts,
        allowed_exts_label=allowed_exts_label,
    )
    return file


def validate_upload_bytes(
    filename: str,
    content: bytes,
    max_mb: int | None = None,
    allowed_exts: set[str] | None = None,
    *,
    allowed_exts_label: str = "",
) -> None:
    """校验已读取到内存的上传内容（temp_file_id 两段式路径复用）。

    直接上传路径用 ``validate_upload``（读文件对象）；临时文件在提交时已被消费
    读取为 ``(content, filename)``，扩展名与大小校验统一由本函数兜底，
    防止绕过前端 accept 直接构造请求。
    """
    _check_upload(
        size_bytes=len(content),
        filename=filename or "",
        max_mb=max_mb,
        allowed_exts=allowed_exts,
        allowed_exts_label=allowed_exts_label,
    )
