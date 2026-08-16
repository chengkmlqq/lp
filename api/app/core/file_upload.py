from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import get_settings


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


def save_temp_file(
    file: UploadFile,
    user_id: str,
    *,
    allowed_exts: set[str] | None = None,
) -> tuple[str, str]:
    """校验并保存上传文件到 MinIO 临时目录，返回 ``(temp_file_id, file_name)``。

    供通用 upload-temp 端点 / 业务模块两段式上传复用：
    选择文件后先落地临时目录（按 user_id 隔离），确认导入时再通过
    ``resolve_temp_file`` 读取并删除，兜底由 24h 清理任务处理。
    """
    from ..services.minio_storage import build_temp_key, put_object

    validate_upload(file, allowed_exts=allowed_exts)
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    file_name = (file.filename or "upload").strip() or "upload"
    temp_file_id = build_temp_key(file_name, user_id)
    put_object(temp_file_id, content, content_type="text/plain")
    return temp_file_id, file_name


def resolve_temp_file(temp_file_id: str, user_id: str) -> tuple[bytes, str]:
    """从 MinIO 临时目录读取并删除临时文件，返回 ``(content, source_file_name)``。

    - 校验 ``temp_file_id`` 归属当前用户（key 前缀 ``TEMP_PREFIX/{user_id}/``）
    - 读取后立即删除，避免定时清理任务在处理完成前误删
    - ``temp_file_id`` 格式非法 / 不属于当前用户时返回 400
    """
    from ..services import minio_storage as _ms

    temp_key = temp_file_id.strip()
    expected_prefix = f"{_ms.TEMP_PREFIX}{user_id}/"
    if not temp_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="temp_file_id 无效或不属于当前用户",
        )
    try:
        content = _ms.get_object(temp_key)
    except _ms.MinioObjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    # 从 key 中提取原始文件名：TEMP_PREFIX/{user_id}/{uuid}_{file_name}
    last_segment = temp_key.rsplit("/", 1)[-1]
    source_file_name = last_segment.split("_", 1)[1] if "_" in last_segment else last_segment
    # 读取后删除临时对象（避免定时清理任务在处理完成前误删的风险）
    try:
        _ms.delete_object(temp_key)
    except Exception:
        pass
    return content, source_file_name


def validate_upload(
    file: UploadFile | None,
    max_mb: int | None = None,
    allowed_exts: set[str] | None = None,
    *,
    allowed_exts_label: str = "",
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
        文件大小上限（MB）。为 None 时取全局配置 ``UPLOAD_MAX_FILE_SIZE_MB``（默认 50）。
    allowed_exts:
        允许的扩展名集合（不含点，如 ``{"csv", "xlsx"}``），匹配前归一化为小写。
        为 None 时不做扩展名校验。
    allowed_exts_label:
        错误提示里的扩展名展示文案（如 "csv/xlsx"）。为空则自动从 allowed_exts 生成。
    """
    if file is None:
        return None
    if max_mb is None:
        max_mb = get_settings().upload_max_file_size_mb
    if max_mb <= 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="上传大小限制配置非法：UPLOAD_MAX_FILE_SIZE_MB 必须 > 0",
        )

    size_bytes = _file_size_bytes(file)
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小 {size_bytes / (1024 * 1024):.1f}MB 超过限制 {max_mb}MB，请压缩后重新上传",
        )

    if allowed_exts:
        filename = (file.filename or "").strip()
        ext = Path(filename).suffix.lstrip(".").lower()
        normalized_allowed = {ex.lower().lstrip(".") for ex in allowed_exts}
        if ext not in normalized_allowed:
            if not allowed_exts_label:
                allowed_exts_label = "/".join(sorted(normalized_allowed))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式：{filename}，仅支持 .{allowed_exts_label}",
            )

    return file


def save_temp_upload(file: UploadFile, user_id: str) -> tuple[str, str]:
    """通用两段式上传的第一步：把上传文件保存到临时目录。

    返回 ``(temp_file_id, file_name)``，供业务端点在确认提交时引用。
    临时文件由消费方在读取后删除，或由定时清理任务兜底清理（见
    ``minio_storage.cleanup_expired_temp_files``）。
    """
    from ..services.minio_storage import build_temp_key, put_object

    content = file.file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件为空",
        )

    file_name = (file.filename or "upload").strip() or "upload"
    temp_file_id = build_temp_key(file_name, user_id)
    put_object(temp_file_id, content, content_type="text/plain")
    return temp_file_id, file_name


def read_temp_upload(temp_file_id: str, user_id: str) -> bytes:
    """通用两段式上传的第二步：按 temp_file_id 读取临时文件内容并消费删除。

    临时 Key 中嵌入了 user_id，读取前校验所有权，防止跨用户引用。
    读取成功后即删除临时对象（消费即删，清理任务兜底孤儿文件）。
    """
    from ..services.minio_storage import (
        TEMP_PREFIX,
        MinioObjectNotFoundError,
        delete_object,
        get_object,
    )

    temp_key = (temp_file_id or "").strip()
    expected_prefix = f"{TEMP_PREFIX}{user_id}/"
    if not temp_key.startswith(expected_prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="temp_file_id 无效或不属于当前用户",
        )

    try:
        content = get_object(temp_key)
    except MinioObjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="临时文件不存在或已过期，请重新上传",
        ) from None

    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    try:
        delete_object(temp_key)
    except Exception:
        pass

    return content


def resolve_temp_upload(temp_file_id: str, user_id: str) -> tuple[bytes, str]:
    """从临时目录读取并消费临时文件，返回 (content, source_file_name)。

    基于 ``read_temp_upload`` 追加原始文件名解析：临时 Key 形如
    ``lightning/tmp/{user_id}/{uuid}_{file_name}``，从最后一段还原原始文件名。
    """
    content = read_temp_upload(temp_file_id, user_id)
    last_segment = (temp_file_id or "").strip().rsplit("/", 1)[-1]
    source_file_name = last_segment.split("_", 1)[1] if "_" in last_segment else last_segment
    return content, source_file_name
