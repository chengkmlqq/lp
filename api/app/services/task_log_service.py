from __future__ import annotations

from datetime import datetime, timezone

from ..core.config import get_settings


class TaskLogServiceError(RuntimeError):
    pass


class TaskLogNotFoundError(TaskLogServiceError):
    pass


def get_task_state_and_log_path(task_id: str) -> tuple[str | None, str | None]:
    """
    Look up a task record and return (state, log_path).
    state / log_path are None when no record exists yet.
    """
    from ..core.database import SessionLocal
    from ..models.task_history import TaskHistory

    db = SessionLocal()
    try:
        record = db.query(TaskHistory).filter(TaskHistory.task_id == task_id).first()
        if record is None:
            return None, None
        return record.state, record.log_path
    except Exception:  # noqa: BLE001 —— DB 不可用不应让日志端点崩溃
        return None, None
    finally:
        db.close()


def _get_log_path(task_id: str, timestamp: datetime | None = None) -> str:
    """
    Generate the fixed MinIO log path: logs/{task_id}.log
    (idempotent overwrite; no longer date-based to avoid midnight rollover 404s)
    """
    return f"logs/{task_id}.log"


def _get_legacy_log_path(task_id: str, timestamp: datetime | None = None) -> str:
    """
    Legacy date-based path for backward compatibility with old persisted logs:
    logs/YYYY/MM/DD/{task_id}.log
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    year = timestamp.strftime("%Y")
    month = timestamp.strftime("%m")
    day = timestamp.strftime("%d")

    return f"logs/{year}/{month}/{day}/{task_id}.log"


def upload_task_log(task_id: str, log_content: str) -> tuple[str, datetime]:
    """
    Upload task execution log to MinIO at the fixed path logs/{task_id}.log.
    Returns: (log_path, uploaded_at)
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    uploaded_at = datetime.now(timezone.utc)
    log_path = _get_log_path(task_id, uploaded_at)

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
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

        # Upload log content as text file
        client.put_object(
            Bucket=settings.minio_bucket,
            Key=log_path,
            Body=log_content.encode("utf-8"),
            ContentType="text/plain; charset=utf-8",
        )

        return log_path, uploaded_at

    except (BotoCoreError, ClientError) as exc:
        raise TaskLogServiceError(f"Failed to upload log to MinIO: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log upload: {exc}") from exc


def get_task_log(task_id: str, log_date: datetime | None = None, log_path: str | None = None) -> tuple[str, str]:
    """
    Retrieve task execution log from MinIO.
    If an explicit log_path is provided, tries that first (primary seek path written
    back to celery_task_history.log_path at task end).
    If log_date is provided, tries the legacy date-based fallback path.
    Returns: (log_content, log_path)
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    candidates: list[str] = []
    if log_path:
        candidates.append(log_path)
    if log_date is None:
        log_date = datetime.now(timezone.utc)
    # 固定路径（新约定）在前，旧日期路径（历史日志兼容）兜底
    candidates.append(_get_log_path(task_id, log_date))
    candidates.append(_get_legacy_log_path(task_id, log_date))

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
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

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                response = client.get_object(
                    Bucket=settings.minio_bucket,
                    Key=candidate,
                )
                body = response.get("Body")
                if body is None:
                    raise TaskLogServiceError("Log file body is empty")
                log_content = body.read().decode("utf-8")
                return log_content, candidate
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code", "")
                if error_code in {"404", "NoSuchKey", "NotFound"}:
                    last_error = exc
                    continue
                raise TaskLogServiceError(f"Failed to retrieve log from MinIO: {exc}") from exc

        raise TaskLogNotFoundError(
            f"Log not found for task {task_id} at any of {candidates}"
        ) from last_error

    except (BotoCoreError, UnicodeDecodeError) as exc:
        raise TaskLogServiceError(f"Failed to read log content: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log retrieval: {exc}") from exc


def get_task_log_by_path(task_id: str, log_path_value: str) -> tuple[str, str]:
    """Retrieve a task log from MinIO by an explicit path (no fallback inference)."""
    return get_task_log(task_id, log_path=log_path_value)


# ---------------------------------------------------------------------------
# Redis Stream 实时通道（XADD/XREAD）
# 注意：使用 Stream 而非 pub/sub —— Stream 持久化 + ID 游标，EventSource 断线重连时
# 断线期间的日志可通过 Last-Event-ID 续读补齐，pub/sub 无法做到。
# ---------------------------------------------------------------------------
def _get_redis_client():
    """延迟构造 redis 客户端，broker 为 redis:// 时复用其连接串，否则用 task_log_redis_db。"""
    import redis as redis_lib

    settings = get_settings()
    broker = settings.resolved_celery_broker_url
    if broker and broker.startswith("redis://"):
        return redis_lib.from_url(broker)
    return redis_lib.Redis(db=settings.task_log_redis_db)


def task_log_redis_key(task_id: str) -> str:
    """Redis Stream key：{prefix}:{task_id}"""
    settings = get_settings()
    return f"{settings.task_log_redis_key_prefix}:{task_id}"


def append_task_log_lines(task_id: str, lines: list[str]) -> None:
    """XADD 批量写入新增日志行到 Redis Stream（MAXLEN ~5000 截断 + 设 TTL）。"""
    settings = get_settings()
    client = _get_redis_client()
    key = task_log_redis_key(task_id)
    pipeline = client.pipeline(transaction=False)
    for line in lines:
        pipeline.xadd(key, {"line": line}, maxlen=5000)
    pipeline.expire(key, settings.task_log_redis_ttl_seconds)
    pipeline.execute()


def mark_task_log_end(task_id: str) -> None:
    """任务结束时写入 __end__ 结束标记并设 TTL 收尾（SSE 收到即推 event: done 并关闭）。"""
    settings = get_settings()
    client = _get_redis_client()
    key = task_log_redis_key(task_id)
    client.xadd(key, {"field": "__end__"}, maxlen=100)
    client.expire(key, settings.task_log_redis_ttl_seconds)


def read_task_log_messages(task_id: str, last_id: str = "0", block_ms: int = 1000) -> list[dict]:
    """
    XREAD 增量读取 Redis Stream。

    Returns: list of {"id": str, "line": str | None, "field": str | None}
    按 Stream 消息顺序返回；空流或 Redis 不可用返回 []（调用方据此发送心跳）。
    """
    client = _get_redis_client()
    key = task_log_redis_key(task_id)
    try:
        # last_id 为 "$" 时只收新消息；EventSource 断线续读时传入 Last-Event-ID
        response = client.xread(streams={key: last_id}, count=100, block=block_ms)
    except Exception:  # noqa: BLE001 —— Redis 不可用时降级为空（SSE 走心跳）
        return []
    if not response:
        return []

    messages: list[dict] = []
    for _stream_name, entries in response:
        for entry_id, fields in entries:
            # Redis 返回 bytes；decode 成 str 后与 Last-Event-ID（str）才能匹配
            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            field = fields.get("field")
            line = fields.get("line")
            field_str = field.decode() if isinstance(field, bytes) else field
            line_str = line.decode() if isinstance(line, bytes) else line
            if field_str is None and line_str is None:
                continue
            messages.append(
                {
                    "id": entry_id_str,
                    "line": line_str,
                    "field": field_str,
                }
            )
    return messages


def list_task_logs(task_id: str) -> list[str]:
    """
    List all available logs for a task across all dates.
    Returns: list of log paths
    """
    settings = get_settings()

    if not settings.minio_enabled:
        raise TaskLogServiceError("MinIO storage is not enabled")

    try:
        import boto3
        from botocore.config import Config
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:
        raise TaskLogServiceError("boto3 library is required for MinIO storage") from exc

    try:
        client_config = Config(
            connect_timeout=3.0,
            read_timeout=10.0,
            retries={"max_attempts": 2},
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

        # Search for all logs matching the task_id pattern
        prefix = "logs/"
        suffix = f"/{task_id}.log"

        log_paths: list[str] = []
        paginator = client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=settings.minio_bucket, Prefix=prefix)

        for page in pages:
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                if key.endswith(suffix):
                    log_paths.append(key)

        return sorted(log_paths, reverse=True)  # Most recent first

    except (BotoCoreError, ClientError) as exc:
        raise TaskLogServiceError(f"Failed to list logs from MinIO: {exc}") from exc
    except Exception as exc:
        raise TaskLogServiceError(f"Unexpected error during log listing: {exc}") from exc
