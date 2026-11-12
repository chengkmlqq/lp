from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    Generate the fixed log object path: logs/{task_id}.log
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


def _ensure_storage_enabled() -> None:
    settings = get_settings()
    if not settings.minio_enabled:
        raise TaskLogServiceError("Object storage is not enabled")


def upload_task_log(task_id: str, log_content: str) -> tuple[str, datetime]:
    """
    Upload task execution log at the fixed path logs/{task_id}.log.

    2026-11-08：改经 minio_storage 双后端（local 本机磁盘 / s3 对象存储）。
    此前本模块用裸 boto3 直连阿里云 OSS，OSS 账号被禁（UserDisable）后
    任务日志上传/读取全部失败——这正是「任务日志打开看不到」的根因之一。
    Returns: (log_path, uploaded_at)
    """
    _ensure_storage_enabled()

    uploaded_at = datetime.now(timezone.utc)
    log_path = _get_log_path(task_id, uploaded_at)

    from . import minio_storage

    try:
        minio_storage.put_object(
            log_path,
            log_content.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
        )
        return log_path, uploaded_at
    except Exception as exc:
        raise TaskLogServiceError(f"Failed to upload task log: {exc}") from exc


def get_task_log(task_id: str, log_date: datetime | None = None, log_path: str | None = None) -> tuple[str, str]:
    """
    Retrieve task execution log from object storage (minio_storage 双后端).
    If an explicit log_path is provided, tries that first (primary seek path written
    back to celery_task_history.log_path at task end).
    If log_date is provided, tries the legacy date-based fallback path.
    Returns: (log_content, log_path)
    """
    _ensure_storage_enabled()

    candidates: list[str] = []
    if log_path:
        candidates.append(log_path)
    if log_date is None:
        log_date = datetime.now(timezone.utc)
    # 固定路径（新约定）在前，旧日期路径（历史日志兼容）兜底
    candidates.append(_get_log_path(task_id, log_date))
    candidates.append(_get_legacy_log_path(task_id, log_date))

    from . import minio_storage

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            content = minio_storage.get_object(candidate)
            return content.decode("utf-8"), candidate
        except minio_storage.MinioObjectNotFoundError as exc:
            last_error = exc
            continue
        except UnicodeDecodeError as exc:
            raise TaskLogServiceError(f"Failed to read log content: {exc}") from exc
        except Exception as exc:
            raise TaskLogServiceError(f"Failed to retrieve task log: {exc}") from exc

    raise TaskLogNotFoundError(
        f"Log not found for task {task_id} at any of {candidates}"
    ) from last_error


def get_task_log_by_path(task_id: str, log_path_value: str) -> tuple[str, str]:
    """Retrieve a task log by an explicit path (no fallback inference)."""
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
    # 注意：这里不要再带 maxlen 截断，否则会在写入结束标记时把前面已经落盘的
    # 诊断日志行（5000 行以内）一并砍掉，导致前端 SSE 最终收到的日志"前半段被清空"。
    client.xadd(key, {"field": "__end__"})
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
            # ⚠️ redis-py XREAD 返回的 fields 字典 key 是 bytes（b"line"/b"field"），
            # 必须用 bytes key 取，否则 .get("line") 恒 None → 全部行被 continue 丢弃，
            # SSE 只发心跳不发日志（2026-09-11 实测：XADD 用 str key 但读侧混用）。
            field = fields.get(b"field")
            line = fields.get(b"line")
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


def read_full_task_log_from_stream(task_id: str) -> str | None:
    """
    从 Redis Stream 一次性读取全部日志行（XRANGE，不依赖 MinIO）。

    用途：任务结束瞬间，SSE 收尾包若改读 MinIO（upload_task_log 在 on_task_postrun
    里异步上传，且 DB 的 log_path 在上传之后才写回），会出现"终态已到、MinIO 还没传完"
    的竞态 → get_task_log 抛 TaskLogNotFoundError → 终态收尾包 log_content 为空 →
    前端整块替换把运行期已流式推送的日志清空（即"先打印一部分，最后把之前的覆盖掉"）。

    而 Redis Stream 在 TaskLogCapture.stop() 里 flush_incremental() 同步写完、再写
    __end__，SSE 读到 __end__ 时流内日志已完整，故终态收尾包直接读流即可，无竞态、
    无需回源 MinIO。流内最多保留 append_task_log_lines 的 maxlen（默认 5000）行，
    对诊断类任务足够；更大的历史日志仍走 MinIO 持久化路径（finished 分支）。
    Returns: 拼接后的全量文本；流不存在/为空/Redis 不可用时返回 None。
    """
    client = _get_redis_client()
    key = task_log_redis_key(task_id)
    try:
        entries = client.xrange(key)
    except Exception:  # noqa: BLE001 —— Redis 不可用降级为 None（调用方据此只推 done）
        return None
    if not entries:
        return None
    lines: list[str] = []
    for _entry_id, fields in entries:
        line = fields.get(b"line")
        if line is None:
            continue
        lines.append(line.decode() if isinstance(line, bytes) else line)
    if not lines:
        return None
    return "\n".join(lines)


def list_task_logs(task_id: str) -> list[str]:
    """
    List all available logs for a task across all dates.
    Returns: list of log paths
    """
    _ensure_storage_enabled()

    from . import minio_storage

    try:
        keys = minio_storage.list_objects("logs/")
    except Exception as exc:
        raise TaskLogServiceError(f"Failed to list task logs: {exc}") from exc

    suffix = f"/{task_id}.log"
    log_paths = [key for key in keys if key.endswith(suffix)]
    return sorted(log_paths, reverse=True)  # Most recent first


def cleanup_expired_task_logs(
    retain_days: int,
    *,
    now: datetime | None = None,
    dry_run: bool = False,
) -> int:
    """删除超过保留期的 ``logs/`` 前缀任务日志对象，返回被删对象数量。

    - 遍历 ``logs/`` 前缀，按对象 ``LastModified`` 与 ``retain_days`` 判断是否超期
    - ``dry_run=True`` 时仅统计不删除（用于生产先观察对象数量级）
    - ``now`` 仅用于测试注入时间点，默认取当前 UTC
    """
    _ensure_storage_enabled()

    if retain_days <= 0:
        return 0  # 0=永久保留，不清理

    if now is None:
        now = datetime.now(timezone.utc)

    from . import minio_storage

    try:
        items = minio_storage.list_object_mtimes("logs/")
    except Exception as exc:
        raise TaskLogServiceError(f"Failed to list task logs for cleanup: {exc}") from exc

    cutoff = now - timedelta(days=retain_days)
    deleted_count = 0
    for key, last_modified in items:
        if last_modified >= cutoff:
            # 未过期，保留
            continue
        if not dry_run:
            try:
                minio_storage.delete_object(key)
            except Exception as exc:  # noqa: BLE001 —— 单个删除失败不阻断整体清理
                continue
        deleted_count += 1

    return deleted_count
