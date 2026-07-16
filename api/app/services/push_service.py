from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from ..models.base import utcnow
from ..schemas.ws import WsEventEnvelope, WsEventMeta
from .ws_manager import ws_connection_manager


async def publish_topic(
    topic: str,
    *,
    name: str,
    payload: dict,
    requires_refetch: list[str] | None = None,
    dedupe_key: str | None = None,
) -> None:
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
    await ws_connection_manager.publish(topic, event)


async def publish_to_user(
    user_id: str,
    *,
    topic: str,
    name: str,
    payload: dict,
    requires_refetch: list[str] | None = None,
    dedupe_key: str | None = None,
) -> None:
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
    await ws_connection_manager.publish_to_user(user_id, event)
