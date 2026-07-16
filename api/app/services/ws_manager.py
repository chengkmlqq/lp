from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import WebSocket

from ..schemas.ws import WsEventEnvelope
from .topic_registry import get_auto_topics, validate_topic_subscription


@dataclass
class WsConnection:
    websocket: WebSocket
    connection_id: str
    user_id: str
    role_codes: set[str]
    permission_codes: set[str]
    subscribed_topics: set[str] = field(default_factory=set)


class WsConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, WsConnection] = {}
        self._topic_connections: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        websocket: WebSocket,
        *,
        user_id: str,
        role_codes: set[str],
        permission_codes: set[str],
    ) -> WsConnection:
        connection = WsConnection(
            websocket=websocket,
            connection_id=str(uuid4()),
            user_id=user_id,
            role_codes=set(role_codes),
            permission_codes=set(permission_codes),
            subscribed_topics=set(get_auto_topics()),
        )
        async with self._lock:
            self._connections[connection.connection_id] = connection
            for topic in connection.subscribed_topics:
                self._topic_connections.setdefault(topic, set()).add(connection.connection_id)
        return connection

    async def unregister(self, connection_id: str) -> None:
        async with self._lock:
            self._remove_connection_locked(connection_id)

    async def subscribe(self, connection_id: str, topics: list[str]) -> list[str]:
        accepted: list[str] = []
        async with self._lock:
            connection = self._connections.get(connection_id)
            if not connection:
                return accepted
            for topic in topics:
                if topic in connection.subscribed_topics:
                    continue
                connection.subscribed_topics.add(topic)
                self._topic_connections.setdefault(topic, set()).add(connection_id)
                accepted.append(topic)
        return accepted

    async def unsubscribe(self, connection_id: str, topics: list[str]) -> list[str]:
        removed: list[str] = []
        async with self._lock:
            connection = self._connections.get(connection_id)
            if not connection:
                return removed
            for topic in topics:
                if topic not in connection.subscribed_topics or topic in get_auto_topics():
                    continue
                connection.subscribed_topics.discard(topic)
                subscribers = self._topic_connections.get(topic)
                if subscribers:
                    subscribers.discard(connection_id)
                    if not subscribers:
                        self._topic_connections.pop(topic, None)
                removed.append(topic)
        return removed

    async def refresh_user_authorization(
        self,
        user_id: str,
        *,
        role_codes: set[str],
        permission_codes: set[str],
    ) -> None:
        notifications: list[tuple[WsConnection, list[str]]] = []
        async with self._lock:
            connections = [
                connection
                for connection in self._connections.values()
                if connection.user_id == user_id
            ]
            for connection in connections:
                connection.role_codes = set(role_codes)
                connection.permission_codes = set(permission_codes)

                removed_topics: list[str] = []
                for topic in list(connection.subscribed_topics):
                    if topic in get_auto_topics():
                        continue
                    is_allowed, _ = validate_topic_subscription(
                        topic,
                        role_codes=connection.role_codes,
                        permission_codes=connection.permission_codes,
                    )
                    if is_allowed:
                        continue
                    connection.subscribed_topics.discard(topic)
                    subscribers = self._topic_connections.get(topic)
                    if subscribers:
                        subscribers.discard(connection.connection_id)
                        if not subscribers:
                            self._topic_connections.pop(topic, None)
                    removed_topics.append(topic)

                if removed_topics:
                    notifications.append((connection, sorted(removed_topics)))

        stale_ids: list[str] = []
        for connection, removed_topics in notifications:
            try:
                await connection.websocket.send_json(
                    {
                        "type": "unsubscribed",
                        "topics": removed_topics,
                        "reason": "permission_changed",
                    }
                )
            except Exception:
                stale_ids.append(connection.connection_id)

        for connection_id in stale_ids:
            await self.unregister(connection_id)

    async def disconnect_user(
        self,
        user_id: str,
        *,
        code: int = 4403,
        reason: str = "user_not_allowed",
    ) -> int:
        connections_to_close: list[WsConnection] = []
        async with self._lock:
            for connection_id, connection in list(self._connections.items()):
                if connection.user_id != user_id:
                    continue
                connections_to_close.append(connection)
                self._remove_connection_locked(connection_id)

        for connection in connections_to_close:
            try:
                await connection.websocket.close(code=code, reason=reason)
            except Exception:
                continue

        return len(connections_to_close)

    async def publish(self, topic: str, event: WsEventEnvelope) -> None:
        async with self._lock:
            connection_ids = list(self._topic_connections.get(topic, set()))
            connections = [
                self._connections[connection_id]
                for connection_id in connection_ids
                if connection_id in self._connections
            ]
        if not connections:
            return

        payload = {"type": "event", "event": event.model_dump(mode="json")}
        stale_ids: list[str] = []
        for connection in connections:
            try:
                await connection.websocket.send_json(payload)
            except Exception:
                stale_ids.append(connection.connection_id)
        for connection_id in stale_ids:
            await self.unregister(connection_id)

    async def publish_to_user(self, user_id: str, event: WsEventEnvelope) -> None:
        async with self._lock:
            connections = [
                connection
                for connection in self._connections.values()
                if connection.user_id == user_id
            ]
        if not connections:
            return
        payload = {"type": "event", "event": event.model_dump(mode="json")}
        stale_ids: list[str] = []
        for connection in connections:
            try:
                await connection.websocket.send_json(payload)
            except Exception:
                stale_ids.append(connection.connection_id)
        for connection_id in stale_ids:
            await self.unregister(connection_id)

    def _remove_connection_locked(self, connection_id: str) -> None:
        connection = self._connections.pop(connection_id, None)
        if not connection:
            return
        for topic in list(connection.subscribed_topics):
            subscribers = self._topic_connections.get(topic)
            if not subscribers:
                continue
            subscribers.discard(connection_id)
            if not subscribers:
                self._topic_connections.pop(topic, None)


ws_connection_manager = WsConnectionManager()
