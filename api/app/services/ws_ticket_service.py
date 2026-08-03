from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..core.config import get_settings


class WsTicketService:
    """
    WS/SSE 短时一次性能力凭证（无状态 JWT）。

    EventSource 无法自定义 Authorization header，因此认证走"先签发票、再带票访问"：
    ``issue()`` 签发一个携带 user_id 的短时效 JWT（默认 30s），``consume()`` 只做
    签名与时效校验。票据无共享状态，天然兼容 uvicorn 多 worker —— 修复此前把票据
    存在进程内 dict 导致 SSE 偶发 401 的问题（票在 worker A 签发，请求落到 worker B
    时校验不到）。同时 EventSource 断线重连复用的是同一 URL（同一票据），无状态票据
    在有效期内可重复校验，与 SSE 的 Last-Event-ID 断线补偿机制兼容。
    """

    def __init__(self, *, expires_in_seconds: int = 30) -> None:
        self.expires_in_seconds = expires_in_seconds

    def issue(self, user_id: str) -> tuple[str, int]:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": user_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.expires_in_seconds)).timestamp()),
        }
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        return token, self.expires_in_seconds

    def consume(self, token: str | None) -> str | None:
        if not token:
            return None
        settings = get_settings()
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.PyJWTError:
            return None
        user_id = payload.get("sub")
        return str(user_id) if user_id else None


ws_ticket_service = WsTicketService()
