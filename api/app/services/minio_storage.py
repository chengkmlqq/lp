from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..core.config import get_settings

# 对象 Key 业务前缀规划（按业务分区）
SOURCE_PREFIX = "lightning/distribution/source/"  # 原始文件
IMAGE_PREFIX = "lightning/distribution/image/"    # 密度图
AMPLITUDE_SOURCE_PREFIX = "lightning/amplitude/source/"  # 雷电流幅值原始波形文件


class MinioStorageError(RuntimeError):
    pass


class MinioObjectNotFoundError(MinioStorageError):
    pass


def _build_client() -> Any:
    """构造一个指向 MinIO 的 boto3 S3 客户端（与 task_log_service 同套路）。"""
    settings = get_settings()
    if not settings.minio_enabled:
        raise MinioStorageError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover
        raise MinioStorageError("boto3 library is required for MinIO storage") from exc

    client_config = Config(
        connect_timeout=3.0,
        read_timeout=30.0,
        retries={"max_attempts": 2},
    )
    session = boto3.session.Session(
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    return session.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        region_name=settings.minio_region,
        config=client_config,
    )


def put_object(key: str, data: bytes, content_type: str | None = None) -> str:
    """上传对象到 MinIO，返回对象 Key。"""
    try:
        client = _build_client()
        client.put_object(
            Bucket=get_settings().minio_bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return key
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to upload object {key}: {exc}") from exc


def get_object(key: str) -> bytes:
    """从 MinIO 下载对象，返回字节内容。"""
    settings = get_settings()
    try:
        client = _build_client()
        response = client.get_object(Bucket=settings.minio_bucket, Key=key)
        body = response.get("Body")
        if body is None:
            raise MinioStorageError("Object body is empty")
        return body.read()
    except MinioStorageError:
        raise
    except Exception as exc:
        error_code = getattr(getattr(exc, "response", None), "get", lambda *a: {})("Error", {}).get("Code", "")
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise MinioObjectNotFoundError(f"Object not found: {key}") from exc
        raise MinioStorageError(f"Failed to retrieve object {key}: {exc}") from exc


def presigned_url(key: str, expires: int = 3600) -> str:
    """生成带有效期的预签名 URL，供前端直接读图。"""
    settings = get_settings()
    try:
        client = _build_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.minio_bucket, "Key": key},
            ExpiresIn=max(int(expires), 60),
        )
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to generate presigned URL for {key}: {exc}") from exc


def delete_object(key: str) -> None:
    """删除 MinIO 上的对象（不存在时不报错）。"""
    settings = get_settings()
    try:
        client = _build_client()
        client.delete_object(Bucket=settings.minio_bucket, Key=key)
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to delete object {key}: {exc}") from exc


def build_source_key(source_file_name: str) -> str:
    """构造原始文件对象 Key：lightning/distribution/source/{uuid}_{file}"""
    safe_name = (source_file_name or "upload").strip() or "upload"
    return f"{SOURCE_PREFIX}{uuid4().hex}_{safe_name}"


def build_amplitude_source_key(source_file_name: str) -> str:
    """构造雷电流幅值源文件对象 Key：lightning/amplitude/source/{uuid}_{file}"""
    safe_name = (source_file_name or "upload").strip() or "upload"
    return f"{AMPLITUDE_SOURCE_PREFIX}{uuid4().hex}_{safe_name}"


def build_image_key(distribution_id: str) -> str:
    """构造密度图对象 Key：lightning/distribution/image/{distribution_id}.png"""
    return f"{IMAGE_PREFIX}{distribution_id}.png"
