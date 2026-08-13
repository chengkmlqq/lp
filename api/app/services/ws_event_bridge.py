from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from ..core.config import get_settings
from ..models.base import utcnow
from ..schemas.ws import WsEventEnvelope, WsEventMeta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery 任务 -> Web 进程 的 WS 事件桥
#
# Celery worker 与 FastAPI(Web) 进程分离运行，而 WebSocket 连接持有在 Web
# 进程内存的 ws_connection_manager 中，worker 无法直接调用其 publish()。
# 直接调用 publish_topic()/_fire_and_forget() 只会把事件投递到 worker 自己
# 进程里一个空的连接管理器中，消息被静默丢弃，前端永收不到。
#
# 这里复刻任务日志 SSE 的既有跨进程方案（Redis Stream）：
#   - worker 侧 publish_ws_event_from_worker() 把事件 JSON XADD 到流 ws_events；
#   - Web 进程启动时 ws_event_forwarder() 用 XREAD 持续读取该流，并以
#     WsEventEnvelope 调用 ws_connection_manager.publish() 推给 topic 订阅者。
# ---------------------------------------------------------------------------

_WS_EVENTS_STREAM = "ws_events"
_WS_EVENTS_TTL_SECONDS = 3600


def _redis_client():
    """延迟构造 redis 客户端，复用 celery broker 连接（与任务日志一致）。"""
    import redis as redis_lib

    settings = get_settings()
    broker = settings.resolved_celery_broker_url
    if broker and broker.startswith("redis://"):
        return redis_lib.from_url(broker)
    return redis_lib.Redis(db=settings.task_log_redis_db)


def publish_ws_event_from_worker(
    topic: str,
    *,
    name: str,
    payload: dict,
    requires_refetch: list[str] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """
    同步把 WS 事件写入 Redis Stream（供 Celery worker 进程调用）。
    失败仅告警不抛出，避免影响任务主体逻辑。
    """
    event = WsEventEnvelope(
        id=f"evt_{uuid4().hex}",
        topic=topic,
        name=name,
        timestamp=utcnow(),
        payload=payload,
        meta=WsEventMeta(
            dedupe_key=dedupe_key,
            requires_refetch=requires_refetch or [],
        ),
    )
    try:
        client = _redis_client()
        client.xadd(
            _WS_EVENTS_STREAM,
            {"topic": topic, "event": event.model_dump_json()},
            maxlen=2000,
        )
        client.expire(_WS_EVENTS_STREAM, _WS_EVENTS_TTL_SECONDS)
    except Exception:  # noqa: BLE001 —— 推送桥不可用不阻断任务
        logger.warning("ws_event_bridge: failed to publish ws event to stream", exc_info=True)


def _read_ws_events(
    last_id: str,
    block_ms: int = 1000,
    count: int = 128,
) -> list[dict[str, Any]]:
    """XREAD 增量读取 ws_events 流，返回解析后的 {"id","topic":"event"} """
    client = _redis_client()
    try:
        response = client.xread(streams={_WS_EVENTS_STREAM: last_id}, count=count, block=block_ms)
    except Exception:  # noqa: BLE001 —— Redis 不可用降级为空，forwarder 循环兜底
        return []
    if not response:
        return []

    parsed: list[dict[str, Any]] = []
    for _stream_name, entries in response:
        for entry_id, fields in entries:
            entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else str(entry_id)
            # redis-py XREAD 返回的 fields dict 键为 bytes（b"topic"/b"event"），
            # 需兼容 bytes 与 str 两种键，否则 get 永远 None 导致事件全部被跳过
            topic = fields.get(b"topic") or fields.get("topic")
            event_json = fields.get(b"event") or fields.get("event")
            if not topic or not event_json:
                continue
            topic_str = topic.decode() if isinstance(topic, bytes) else topic
            event_json_str = event_json.decode() if isinstance(event_json, bytes) else event_json
            try:
                event = WsEventEnvelope.model_validate_json(event_json_str)
            except Exception:  # noqa: BLE001
                logger.warning("ws_event_bridge: malformed event in stream, skipping", exc_info=True)
                continue
            parsed.append({"id": entry_id_str, "topic": topic_str, "event": event})
    return parsed


async def ws_event_forwarder() -> None:
    """
    Web 进程后台任务：持续读取 ws_events 流并调用 ws_connection_manager.publish()。
    读取成功推进游标；异常则继续，避免单个坏事件卡死循环。
    """
    from .ws_manager import ws_connection_manager

    last_id = "0"
    while True:
        messages = await asyncio.to_thread(_read_ws_events, last_id, 1000)
        if not messages:
            continue
        for message in messages:
            last_id = message["id"]
            event = message["event"]
            try:
                await ws_connection_manager.publish(event.topic, event)
            except Exception:  # noqa: BLE001
                logger.warning("ws_event_bridge: publish failed for topic=%s", event.topic, exc_info=True)
        await asyncio.sleep(0)