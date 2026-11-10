"""鉴权结果短缓存（Redis，尽力而为）。

背景（2026-11-10）：线上 MySQL 走公网，单次往返 25–45ms，且 `pool_pre_ping` 每次取连
还要多吃一次 `SELECT 1`。一次请求的鉴权链路要查「用户行 + 角色 + 权限」2–4 次，
实测 `/api/v1/auth/me` 363ms、任意业务接口被固定摊上 250–300ms 的鉴权成本。

这里把「用户快照 + 角色码 + 权限码」整体缓存 `CACHE_TTL_SECONDS` 秒，命中时整条鉴权
链路不再访问数据库，只剩一次 Redis GET（阿里云 Redis 单次 ~25–30ms）。

一致性约定：
- TTL 45s 是最坏延迟上限：改角色/权限后最长 45 秒内旧缓存仍生效。
- 用户被改/被删/退出登录时通过 `invalidate()` 立即失效（见 `queue_user_auth_refresh`）。
- Redis 不可用、超时、返回脏数据时一律视为 miss 并静默降级，绝不阻塞鉴权。

缓存里的用户对象是**脱离会话的临时实例**，只有标量字段；业务代码不得通过它访问
`roles / sessions / audit_logs` 等关系（现有代码只读 `current_user.user.id` 与
`serialize_user` 用到的标量字段）。关系属性被预置为空集合，误用只会拿到空值而不会抛
`DetachedInstanceError`。
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

# 权限变更最长生效延迟（秒）
CACHE_TTL_SECONDS = 45
_KEY_PREFIX = "lp:auth:v1"

_client: Any | None = None
_client_broken = False
# Redis 故障后的静默窗口：避免每次请求都白等 socket_timeout
_disabled_until = 0.0
_FAILURE_BACKOFF_SECONDS = 60


def _trip_breaker() -> None:
    global _disabled_until
    _disabled_until = time.monotonic() + _FAILURE_BACKOFF_SECONDS


def _breaker_open() -> bool:
    return time.monotonic() < _disabled_until


def _get_client() -> Any | None:
    """惰性创建带连接池的 Redis 客户端；失败后本次进程内不再重试。"""
    global _client, _client_broken
    if _breaker_open():
        return None
    if _client is not None:
        return _client
    if _client_broken:
        return None
    try:
        import redis as redis_lib

        settings = get_settings()
        broker = settings.resolved_celery_broker_url
        # socket_timeout 取 0.5s：Redis 抖动时宁可降级回数据库，也不要把请求挂住
        kwargs = {
            "socket_timeout": 0.5,
            "socket_connect_timeout": 0.5,
            "health_check_interval": 30,
            "max_connections": 16,
            "decode_responses": True,
        }
        if broker and broker.startswith("redis://"):
            _client = redis_lib.from_url(broker, **kwargs)
        else:
            _client = redis_lib.Redis(db=settings.task_log_redis_db, **kwargs)
    except Exception:  # pragma: no cover - 环境缺 Redis 时静默降级
        logger.warning("auth cache disabled: cannot build redis client", exc_info=True)
        _client_broken = True
        return None
    return _client


def _key(user_id: str) -> str:
    return f"{_KEY_PREFIX}:{user_id}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load(user_id: str) -> dict[str, Any] | None:
    """取缓存条目；任何异常或脏数据都返回 None（等同 miss）。"""
    client = _get_client()
    if client is None:
        return None
    try:
        raw = client.get(_key(user_id))
    except Exception:
        logger.debug("auth cache get failed", exc_info=True)
        _trip_breaker()
        return None
    if not raw:
        return None
    try:
        entry = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(entry, dict) or not isinstance(entry.get("u"), dict):
        return None
    return entry


def store(user: Any, *, role_codes: set[str], permission_codes: set[str]) -> None:
    """写入缓存；写失败不影响请求。"""
    client = _get_client()
    if client is None:
        return
    payload = {
        "u": {
            "id": str(getattr(user, "id", "") or ""),
            "email": getattr(user, "email", None),
            "username": getattr(user, "username", None),
            "status": getattr(user, "status", None),
            "avatar_path": getattr(user, "avatar_path", None),
            "phone": getattr(user, "phone", None),
            "created_at": _iso(getattr(user, "created_at", None)),
            "updated_at": _iso(getattr(user, "updated_at", None)),
        },
        "r": sorted(role_codes or ()),
        "p": sorted(permission_codes or ()),
    }
    if not payload["u"]["id"]:
        return
    try:
        client.setex(_key(payload["u"]["id"]), CACHE_TTL_SECONDS, json.dumps(payload, ensure_ascii=False))
    except Exception:
        logger.debug("auth cache set failed", exc_info=True)
        _trip_breaker()


def invalidate(user_id: str | None) -> None:
    """主动失效（用户资料/角色变化、退出登录、账号停用）。"""
    if not user_id:
        return
    client = _get_client()
    if client is None:
        return
    try:
        client.delete(_key(str(user_id)))
    except Exception:
        logger.debug("auth cache delete failed", exc_info=True)
        _trip_breaker()


def build_user(entry: dict[str, Any]) -> Any:
    """用缓存快照还原一个脱离会话的 User 实例（仅标量字段 + 空关系）。"""
    from ..models.user import User

    data = entry.get("u") or {}
    user = User()
    user.id = str(data.get("id") or "")
    user.email = data.get("email")
    user.username = data.get("username") or ""
    user.status = data.get("status") or "ENABLED"
    user.avatar_path = data.get("avatar_path")
    user.phone = data.get("phone")
    created_at = _parse_dt(data.get("created_at"))
    updated_at = _parse_dt(data.get("updated_at"))
    if created_at is not None:
        user.created_at = created_at
    if updated_at is not None:
        # last_login_at 是 updated_at 的同义属性，直接写列属性避免触发 setter
        user.updated_at = updated_at
    # 预置关系为空集合：缓存对象不在会话里，真去懒加载会抛 DetachedInstanceError
    for relation in ("roles", "sessions", "audit_logs"):
        try:
            setattr(user, relation, [])
        except Exception:  # pragma: no cover - 模型改结构时不应影响鉴权
            pass
    return user


def role_codes(entry: dict[str, Any]) -> set[str]:
    return {str(code) for code in (entry.get("r") or []) if code}


def permission_codes(entry: dict[str, Any]) -> set[str]:
    return {str(code) for code in (entry.get("p") or []) if code}
