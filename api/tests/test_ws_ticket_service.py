"""
Unit tests for WsTicketService (无状态 JWT 短时票据).

背景：票据曾存于进程内 dict，uvicorn 多 worker 下跨进程不可见导致 SSE 偶发 401。
改为 JWT 后，签发与校验均无共享状态，任何 worker 都能校验任意 worker 签发的票据。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt as pyjwt

from app.core.config import get_settings
from app.services.ws_ticket_service import ws_ticket_service


def test_issue_returns_token_and_expires_in():
    token, expires_in = ws_ticket_service.issue("user-1")
    assert token
    assert expires_in == ws_ticket_service.expires_in_seconds


def test_consume_returns_user_id_for_valid_token():
    token, _ = ws_ticket_service.issue("user-2")
    assert ws_ticket_service.consume(token) == "user-2"


def test_consume_none_or_empty_returns_none():
    assert ws_ticket_service.consume(None) is None
    assert ws_ticket_service.consume("") is None


def test_consume_invalid_token_returns_none():
    assert ws_ticket_service.consume("not-a-jwt") is None
    assert ws_ticket_service.consume("abc.def.ghi") is None


def test_consume_expired_token_returns_none():
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": "user-3",
        "iat": int((now - timedelta(seconds=120)).timestamp()),
        "exp": int((now - timedelta(seconds=60)).timestamp()),
    }
    expired = pyjwt.encode(
        expired_payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    assert ws_ticket_service.consume(expired) is None


def test_consume_token_signed_with_other_secret_returns_none():
    token = pyjwt.encode(
        {"sub": "user-4", "exp": datetime.now(timezone.utc) + timedelta(seconds=30)},
        "another-secret",
        algorithm="HS256",
    )
    assert ws_ticket_service.consume(token) is None


def test_issue_and_consume_are_cross_worker_consistent():
    """模拟跨 worker：新实例（同一密钥）也能校验任意实例签发的票据。"""
    from app.services.ws_ticket_service import WsTicketService

    worker_a = WsTicketService()
    worker_b = WsTicketService()

    token, _ = worker_a.issue("user-5")
    assert worker_b.consume(token) == "user-5"
