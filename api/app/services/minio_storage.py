from __future__ import annotations

import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.config import get_settings

# 对象 Key 业务前缀规划（按业务分区）
SOURCE_PREFIX = "lightning/distribution/source/"  # 原始文件
IMAGE_PREFIX = "lightning/distribution/image/"    # 密度图
AMPLITUDE_SOURCE_PREFIX = "lightning/amplitude/source/"  # 雷电流幅值原始波形文件
TEMP_PREFIX = "lightning/tmp/"                    # 导入临时文件（选择文件后先上传，确认导入后再消费）
FAULT_ANALYSIS_PREFIX = "fault-analysis/"          # 故障分析输入/输出归档
MATLAB_ENGINE_PREFIX = "matlab-engine/"            # MATLAB 引擎包（模块化多版本）

# matlab-engine/
#   modules/{module_slug}.json
#   draft/{module_slug}/{version_hash}/engine.zip + manifest.json
#   release/{module_slug}/{version_hash}/engine.zip + manifest.json
MATLAB_ENGINE_MODULES_PREFIX = f"{MATLAB_ENGINE_PREFIX}modules/"
MATLAB_ENGINE_DRAFT_PREFIX = f"{MATLAB_ENGINE_PREFIX}draft/"
MATLAB_ENGINE_RELEASE_PREFIX = f"{MATLAB_ENGINE_PREFIX}release/"


def build_matlab_engine_module_key(slug: str) -> str:
    return f"{MATLAB_ENGINE_MODULES_PREFIX}{slug}.json"


def build_matlab_engine_draft_prefix(slug: str, version_hash: str) -> str:
    return f"{MATLAB_ENGINE_DRAFT_PREFIX}{slug}/{version_hash}/"


def build_matlab_engine_release_prefix(slug: str, version_hash: str) -> str:
    return f"{MATLAB_ENGINE_RELEASE_PREFIX}{slug}/{version_hash}/"


def build_matlab_engine_legacy_prefix(version_hash: str) -> str:
    return f"{MATLAB_ENGINE_PREFIX}{version_hash}/"


class MinioStorageError(RuntimeError):
    pass


class MinioObjectNotFoundError(MinioStorageError):
    pass


# ---------------------------------------------------------------------------
# 后端选择：local（本机磁盘，默认） / s3（S3 兼容对象存储）
#
# 2026-11-08：OSS 账号 line-protection 除 GET 外全被 UserDisable 拒（Put/Delete/
# List/分片均不可用），且跨公网单次请求 1.5s+，业务对象存储整体切到数据盘本地
# 目录（settings.object_storage_root，默认 <file_vfs_root 同级>/objects）。
# "s3" 分支完整保留原 boto3 实现，作为回滚开关（OBJECT_STORAGE_BACKEND=s3）。
# ---------------------------------------------------------------------------


def _use_local_backend() -> bool:
    return (getattr(get_settings(), "object_storage_backend", "local") or "local") != "s3"


def _local_root() -> Path:
    return Path(get_settings().resolved_object_storage_root)


def _local_object_path(key: str) -> Path:
    """把对象 Key 映射到本地文件路径，拒绝目录穿越。"""
    root = _local_root().resolve()
    candidate = (root / key).resolve()
    if candidate != root and root not in candidate.parents:
        raise MinioStorageError(f"Illegal object key: {key}")
    return candidate


def _local_exists(key: str) -> Path:
    path = _local_object_path(key)
    if not path.is_file():
        raise MinioObjectNotFoundError(f"Object not found: {key}")
    return path


def _local_put_bytes(key: str, data: bytes) -> None:
    path = _local_object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _local_put_fileobj(key: str, stream: Any, size: int | None) -> int:
    path = _local_object_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    written = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return written


def _local_copy(src_key: str, dst_key: str, *, source_bucket: str | None = None) -> None:
    if source_bucket not in (None, get_settings().minio_bucket):
        raise MinioStorageError("local 后端不支持跨存储桶拷贝")
    src = _local_exists(src_key)
    dst = _local_object_path(dst_key)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def _local_list(prefix: str) -> list[str]:
    root = _local_root().resolve()
    base = _local_object_path(prefix.rstrip("/") if prefix else ".") if prefix.strip("/") else root
    if not base.exists():
        return []
    keys: list[str] = []
    if base.is_file():
        keys.append(os.path.relpath(base, root).replace(os.sep, "/"))
        return keys
    for path in sorted(base.rglob("*")):
        if path.is_file():
            keys.append(os.path.relpath(path, root).replace(os.sep, "/"))
    return keys


def _local_delete(key: str) -> None:
    path = _local_object_path(key)
    if path.is_file():
        path.unlink()


def _local_delete_prefix(prefix: str) -> int:
    if not _local_root().exists():
        return 0
    base = _local_object_path(prefix.rstrip("/")) if prefix.strip("/") else _local_root()
    if not base.exists():
        return 0
    deleted = 0
    if base.is_file():
        base.unlink()
        return 1
    for path in sorted(base.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
            deleted += 1
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return deleted


def _local_cleanup_expired_temp(
    ttl_hours: float,
    *,
    now: datetime,
    dry_run: bool = False,
) -> int:
    root = _local_root()
    base = root / TEMP_PREFIX.rstrip("/")
    if not base.exists() or ttl_hours <= 0:
        return 0
    cutoff_epoch = now.timestamp() - ttl_hours * 3600
    deleted = 0
    for path in sorted(base.rglob("*"), reverse=True):
        if path.is_file():
            if path.stat().st_mtime < cutoff_epoch:
                if not dry_run:
                    path.unlink()
                deleted += 1
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    return deleted


# ---------------------------------------------------------------------------
# S3 后端（原实现，object_storage_backend="s3" 时使用）
# ---------------------------------------------------------------------------

# boto3 client 线程安全，可全局复用。此前每次调用都重建客户端（含 TLS 握手），
# 一次删除最多 5 个对象串行 5 次握手，跨公网访问 OSS 时延迟成倍放大。
_client_cache: dict[tuple[str, str, str, str, str], Any] = {}
_client_cache_lock = threading.Lock()


def _build_client() -> Any:
    """构造一个指向 MinIO 的 boto3 S3 客户端（与 task_log_service 同套路）。

    同一配置（endpoint/凭据/region/bucket）下复用已建客户端，避免重复握手。
    """
    settings = get_settings()
    if not settings.minio_enabled:
        raise MinioStorageError("MinIO storage is not enabled")

    cache_key = (
        settings.minio_endpoint,
        settings.minio_access_key,
        settings.minio_secret_key,
        settings.minio_region,
        settings.minio_bucket,
    )
    with _client_cache_lock:
        cached = _client_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover
        raise MinioStorageError("boto3 library is required for MinIO storage") from exc

    client_config = Config(
        connect_timeout=3.0,
        read_timeout=30.0,
        retries={"max_attempts": 2},
        # 兼容阿里云 OSS S3 兼容接口：
        # - virtual hosted style（OSS 拒绝 path style 的对象级操作）
        # - when_required 校验：规避 botocore 默认 STREAMING-UNSIGNED-PAYLOAD-TRAILER 流式上传
        s3={"addressing_style": "virtual"},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    session = boto3.session.Session(
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key,
    )
    client = session.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        region_name=settings.minio_region,
        config=client_config,
    )
    with _client_cache_lock:
        _client_cache[cache_key] = client
    return client


def put_object(key: str, data: bytes, content_type: str | None = None) -> str:
    """上传对象到对象存储，返回对象 Key。"""
    if _use_local_backend():
        _local_put_bytes(key, data)
        return key
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


SINGLE_PUT_MAX_BYTES = 5 * 1024 * 1024 * 1024


def normalize_endpoint(endpoint: str | None) -> str:
    """归一化 endpoint 便于比较（去掉尾部斜杠、统一小写）。"""
    return (endpoint or "").strip().rstrip("/").lower()


def storage_identity() -> tuple[str, str]:
    """对象存储的 (endpoint, bucket) 标识，用于判断能否跨存储服务端拷贝。

    local 后端返回 ("local", "")，与任何 S3 挂载恒不相等，安全降级为应用层拷贝。
    """
    settings = get_settings()
    if _use_local_backend():
        return "local", ""
    return normalize_endpoint(settings.minio_endpoint), settings.minio_bucket


def _resolve_stream_size(stream: Any, size: int | None) -> tuple[Any, int]:
    """确定流的长度；不可 seek 且未给 size 时才退化为读入内存。"""
    if isinstance(size, int) and size >= 0:
        return stream, size
    try:
        position = stream.tell()
        stream.seek(0, 2)
        measured = stream.tell()
        stream.seek(position)
        return stream, int(measured)
    except Exception:
        pass
    import io as _io

    data = stream.read()
    return _io.BytesIO(data), len(data)


def upload_stream(
    client: Any,
    bucket: str,
    key: str,
    stream: Any,
    content_type: str | None = None,
    size: int | None = None,
) -> int:
    """把可读流写入 S3 兼容对象存储，返回写入字节数。

    使用带 ``ContentLength`` 的单次 PUT：botocore 边读边发，内存占用与文件大小无关；
    分片上传（CreateMultipartUpload）在该 OSS 账号上被禁用，故不采用。
    """
    resolved_type = content_type or "application/octet-stream"
    stream, resolved_size = _resolve_stream_size(stream, size)
    if resolved_size > SINGLE_PUT_MAX_BYTES:
        raise MinioStorageError(
            f"对象 {key} 超过单次 PUT 上限 {SINGLE_PUT_MAX_BYTES // (1024 ** 3)}GB，"
            "当前存储账号不支持分片上传，请压缩或拆分后上传"
        )
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=stream,
        ContentLength=resolved_size,
        ContentType=resolved_type,
    )
    return resolved_size


def put_fileobj(
    key: str,
    stream: Any,
    content_type: str | None = None,
    size: int | None = None,
) -> int:
    """把文件流上传到对象存储，返回字节数（不把整份内容读进内存）。"""
    if _use_local_backend():
        return _local_put_fileobj(key, stream, size)
    try:
        client = _build_client()
        return upload_stream(
            client,
            get_settings().minio_bucket,
            key,
            stream,
            content_type=content_type,
            size=size,
        )
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to upload stream {key}: {exc}") from exc


def _is_not_found_error(exc: Exception) -> bool:
    error_code = getattr(getattr(exc, "response", None), "get", lambda *a: {})("Error", {}).get("Code", "")
    return error_code in {"404", "NoSuchKey", "NotFound"}


def head_object_size(key: str) -> int:
    """读取对象大小，对象不存在抛 ``MinioObjectNotFoundError``。"""
    if _use_local_backend():
        try:
            return _local_exists(key).stat().st_size
        except MinioObjectNotFoundError:
            raise
        except Exception as exc:
            raise MinioStorageError(f"Failed to head object {key}: {exc}") from exc
    try:
        client = _build_client()
        response = client.head_object(Bucket=get_settings().minio_bucket, Key=key)
        return int(response.get("ContentLength") or 0)
    except MinioStorageError:
        raise
    except Exception as exc:
        if _is_not_found_error(exc):
            raise MinioObjectNotFoundError(f"Object not found: {key}") from exc
        raise MinioStorageError(f"Failed to head object {key}: {exc}") from exc


def open_object_stream(key: str) -> tuple[Any, int]:
    """以流的方式打开对象，返回 ``(body, size)``；调用方负责 close。

    大文件（GB 级 DEM）必须用本函数，不要用 ``get_object`` 全量读入内存。
    """
    if _use_local_backend():
        try:
            path = _local_exists(key)
            body = path.open("rb")
            return body, path.stat().st_size
        except MinioObjectNotFoundError:
            raise
        except Exception as exc:
            raise MinioStorageError(f"Failed to open object {key}: {exc}") from exc
    try:
        client = _build_client()
        response = client.get_object(Bucket=get_settings().minio_bucket, Key=key)
    except MinioStorageError:
        raise
    except Exception as exc:
        if _is_not_found_error(exc):
            raise MinioObjectNotFoundError(f"Object not found: {key}") from exc
        raise MinioStorageError(f"Failed to open object {key}: {exc}") from exc

    body = response.get("Body")
    if body is None:
        raise MinioStorageError(f"Object body is empty: {key}")
    return body, int(response.get("ContentLength") or 0)


def copy_object(src_key: str, dst_key: str, *, source_bucket: str | None = None) -> None:
    """拷贝对象（local 后端为同盘文件复制），用于临时区转正式区。"""
    if _use_local_backend():
        try:
            _local_copy(src_key, dst_key, source_bucket=source_bucket)
        except MinioStorageError:
            raise
        except Exception as exc:
            raise MinioStorageError(f"Failed to copy object {src_key} -> {dst_key}: {exc}") from exc
        return
    try:
        client = _build_client()
        bucket = get_settings().minio_bucket
        client.copy_object(
            Bucket=bucket,
            Key=dst_key,
            CopySource={"Bucket": source_bucket or bucket, "Key": src_key},
            MetadataDirective="COPY",
        )
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to copy object {src_key} -> {dst_key}: {exc}") from exc


def list_objects(prefix: str) -> list[str]:
    """按前缀列举对象 Key，返回所有匹配对象 Key 列表（无分页上限）。

    用于导出场景按 ``Output/matlab/<run_id>/`` 前缀兜底拉取全部引擎产物。
    """
    if _use_local_backend():
        try:
            return _local_list(prefix)
        except Exception as exc:
            raise MinioStorageError(f"Failed to list objects under {prefix}: {exc}") from exc
    settings = get_settings()
    try:
        client = _build_client()
        paginator = client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=settings.minio_bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                if key:
                    keys.append(key)
        return keys
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to list objects under {prefix}: {exc}") from exc


def get_object(key: str) -> bytes:
    """读取对象，返回字节内容。"""
    if _use_local_backend():
        try:
            return _local_exists(key).read_bytes()
        except MinioObjectNotFoundError:
            raise
        except Exception as exc:
            raise MinioStorageError(f"Failed to retrieve object {key}: {exc}") from exc
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
    """生成带有效期的预签名 URL（仅 s3 后端支持）。"""
    if _use_local_backend():
        raise MinioStorageError("local 对象存储不支持预签名 URL，请通过应用接口读取对象")
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
    """删除对象（不存在时不报错）。"""
    if _use_local_backend():
        try:
            _local_delete(key)
        except Exception as exc:
            raise MinioStorageError(f"Failed to delete object {key}: {exc}") from exc
        return
    settings = get_settings()
    try:
        client = _build_client()
        client.delete_object(Bucket=settings.minio_bucket, Key=key)
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to delete object {key}: {exc}") from exc


def delete_prefix(prefix: str) -> int:
    """删除指定前缀下的所有对象，返回删除数量。"""
    if _use_local_backend():
        try:
            return _local_delete_prefix(prefix)
        except Exception as exc:
            raise MinioStorageError(f"Failed to delete objects under {prefix}: {exc}") from exc
    settings = get_settings()
    try:
        client = _build_client()
        paginator = client.get_paginator("list_objects_v2")
        deleted_count = 0
        for page in paginator.paginate(Bucket=settings.minio_bucket, Prefix=prefix):
            objects = [{"Key": item.get("Key", "")} for item in page.get("Contents", []) if item.get("Key")]
            if not objects:
                continue
            client.delete_objects(Bucket=settings.minio_bucket, Delete={"Objects": objects, "Quiet": True})
            deleted_count += len(objects)
        return deleted_count
    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to delete objects under {prefix}: {exc}") from exc


def download_object_to_file(key: str, target: Path) -> Path:
    """下载对象到本地文件，创建父目录并返回目标路径。"""
    if _use_local_backend():
        try:
            src = _local_exists(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".part")
            shutil.copyfile(src, tmp)
            os.replace(tmp, target)
            return target
        except MinioObjectNotFoundError:
            raise
        except Exception as exc:
            raise MinioStorageError(f"Failed to download object {key}: {exc}") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(get_object(key))
    return target


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


def build_temp_key(file_name: str, user_id: str) -> str:
    """构造临时文件对象 Key：lightning/tmp/{user_id}/{uuid}_{file_name}

    嵌入 user_id 用于导入时的所有权校验。
    """
    safe_name = (file_name or "upload").strip() or "upload"
    return f"{TEMP_PREFIX}{user_id}/{uuid4().hex}_{safe_name}"


def build_fault_analysis_input_key(analysis_id: str, field: str, file_name: str) -> str:
    safe_name = Path((file_name or "upload").strip() or "upload").name
    return f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Input/{field}/{safe_name}"


def build_fault_analysis_generated_key(analysis_id: str, file_name: str) -> str:
    safe_name = Path((file_name or "generated.bin").strip() or "generated.bin").name
    return f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Input/generated/{safe_name}"


def build_fault_analysis_output_key(analysis_id: str, file_name: str, sub_dir: str | None = None) -> str:
    """构造 Output 产物对象 Key：fault-analysis/{id}/Output[/sub_dir]/{file_name}"""
    safe_name = Path((file_name or "artifact.bin").strip() or "artifact.bin").name
    base = f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Output"
    if sub_dir:
        base = f"{base}/{str(sub_dir).strip().strip('/')}"
    return f"{base}/{safe_name}"


def build_fault_analysis_matlab_output_key(
    analysis_id: str, file_name: str, sub_dir: str | None = None
) -> str:
    """构造 MATLAB 引擎产物对象 Key：fault-analysis/{id}/Output/matlab[/sub_dir]/{file_name}

    sub_dir 为单次运行的 run_id 或其下的相对路径，用于保留模块输出目录的
    原始目录结构（如 Output/matlab/<run_id>/nested/<file>）。
    """
    safe_name = Path((file_name or "wave_module_prediction.txt").strip() or "wave_module_prediction.txt").name
    base = f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/Output/matlab"
    if sub_dir:
        base = f"{base}/{str(sub_dir).strip().strip('/')}"
    return f"{base}/{safe_name}"


def build_fault_analysis_prefix(analysis_id: str) -> str:
    return f"{FAULT_ANALYSIS_PREFIX}{analysis_id}/"


def cleanup_expired_temp_files(
    ttl_hours: float,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> int:
    """删除超过 TTL 的 lightning/tmp/ 前缀临时对象，返回被删对象数量。

    - local 后端按文件 mtime 判断超期；s3 后端按对象 ``LastModified``
    - ``dry_run=True`` 时仅统计不删除
    - ``now`` 仅用于测试注入时间点，默认取当前 UTC
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise MinioStorageError("MinIO storage is not enabled")

    if ttl_hours <= 0:
        return 0  # 0=永久保留，不清理

    if now is None:
        now = datetime.now(timezone.utc)

    if _use_local_backend():
        try:
            return _local_cleanup_expired_temp(ttl_hours, now=now, dry_run=dry_run)
        except Exception as exc:
            raise MinioStorageError(f"Failed to clean up temp files: {exc}") from exc

    cutoff = now - timedelta(hours=ttl_hours)

    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise MinioStorageError("boto3 library is required for MinIO storage") from exc

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
            s3={"addressing_style": "virtual"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        session = boto3.session.Session(
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
        )
        client = session.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            region_name=settings.minio_region,
            config=client_config,
        )

        deleted_count = 0
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=settings.minio_bucket, Prefix=TEMP_PREFIX)

        for page in pages:
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                if not key:
                    continue
                last_modified = item.get("LastModified")
                if last_modified is None:
                    continue
                if last_modified >= cutoff:
                    continue
                if not dry_run:
                    client.delete_object(Bucket=settings.minio_bucket, Key=key)
                deleted_count += 1

        return deleted_count

    except MinioStorageError:
        raise
    except Exception as exc:
        raise MinioStorageError(f"Failed to clean up temp files: {exc}") from exc
