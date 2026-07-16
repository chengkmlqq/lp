from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from ..models.base import utcnow
from ..core.security import create_refresh_token, hash_token


@dataclass
class _WsTicketRecord:
    user_id: str
    expires_at_ts: float


class WsTicketService:
    def __init__(self, *, expires_in_seconds: int = 30) -> None:
        self.expires_in_seconds = expires_in_seconds
        self._tickets: dict[str, _WsTicketRecord] = {}
        self._lock = Lock()

    def issue(self, user_id: str) -> tuple[str, int]:
        token = create_refresh_token()
        expires_at_ts = utcnow().timestamp() + self.expires_in_seconds
        token_hash = hash_token(token)
        with self._lock:
            self._cleanup_locked()
            self._tickets[token_hash] = _WsTicketRecord(
                user_id=user_id,
                expires_at_ts=expires_at_ts,
            )
        return token, self.expires_in_seconds

    def consume(self, token: str | None) -> str | None:
        if not token:
            return None
        token_hash = hash_token(token)
        now_ts = utcnow().timestamp()
        with self._lock:
            self._cleanup_locked(now_ts)
            record = self._tickets.pop(token_hash, None)
            if not record:
                return None
            if record.expires_at_ts <= now_ts:
                return None
            return record.user_id

    def _cleanup_locked(self, now_ts: float | None = None) -> None:
        current_ts = now_ts if now_ts is not None else utcnow().timestamp()
        expired = [
            token_hash
            for token_hash, record in self._tickets.items()
            if record.expires_at_ts <= current_ts
        ]
        for token_hash in expired:
            self._tickets.pop(token_hash, None)


ws_ticket_service = WsTicketService()
