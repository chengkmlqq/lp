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