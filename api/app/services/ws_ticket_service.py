from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from ..core.config import get_settings


class WsTicketService:
    """
    WS/SSE 短时一次性能力凭证（无状态 JWT）。

    EventSource 无法自定义 Authorization header，因此认证走"先签发票、再带票访问"：
    ``issue()`` 签发一个携带 user_id 的短时效 JWT，``consume()`` 只做
    签名与时效校验。票据无共享状态，天然兼容 uvicorn 多 worker —— 修复此前把票据
    存在进程内 dict 导致 SSE 偶发 401 的问题（票在 worker A 签发，请求落到 worker B
    时校验不到）。

    有效期默认 300 秒（LP-295）：日志 SSE 断线后由前端重新签发 ticket 并重建连接，
    过期时刻由前端根据 ``expires_in`` 主动换票；放宽有效期用于兜底时间差，避免网络
    抖动或前端退避间隙恰好落在旧票已过期的时间窗内。
    """

    def __init__(self, *, expires_in_seconds: int = 300) -> None:
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
