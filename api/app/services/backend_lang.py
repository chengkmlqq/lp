"""后端产物（任务日志 / WS 阶段文案 / Word 报告）的语言解析。

语言来源与优先级（LP-22 方案 B）：
1. **任务级 lang**：创建任务的 HTTP 请求带 ``X-Lang``，在任务发布时注入 Celery
   消息头，worker 在任务启动时读入并快照 —— 每个任务的语言在启动后固定不变。
2. **全局 ``app.language`` 系统参数**：缺省回落值，``zh`` / ``en``，默认 ``zh``；
   仅 ``status == "enabled"`` 生效，非法值回落 ``zh``。
3. 都拿不到时回落 ``zh``。

全局参数按「任务启动时读一次并缓存」：进程内缓存带 TTL（兼容 API / worker 分进程，
参数更新后新任务最多一个 TTL 后生效），同进程内 ``system_params.changed`` 事件
立即失效缓存。任务级 lang 不缓存、不查库。
"""

from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

PARAM_KEY = "app.language"
DEFAULT_LANG = "zh"
VALID_LANGS = frozenset({"zh", "en"})
# 参数变更跨进程可见的兜底窗口（秒）；同进程由 system_params.changed 立即失效。
CACHE_TTL_SECONDS = 30.0

_LANG_ALIASES: dict[str, str] = {
    "zh-cn": "zh",
    "zh_cn": "zh",
    "zh-hans": "zh",
    "cn": "zh",
    "chinese": "zh",
    "en-us": "en",
    "en_us": "en",
    "en-gb": "en",
    "english": "en",
}

# 当前 HTTP 请求的语言（API 进程，由 BackendLangMiddleware 写入）。
_request_lang_var: ContextVar[str | None] = ContextVar("lp_request_lang", default=None)


def normalize_lang(value: Any) -> str | None:
    """把任意输入规整成 ``zh`` / ``en``；无法识别返回 None。"""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in VALID_LANGS:
        return normalized
    return _LANG_ALIASES.get(normalized)


class _DefaultLangCache:
    """``app.language`` 的进程内缓存：读一次，TTL 到期或显式失效才重查库。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: str | None = None
        self._expires_at = 0.0

    def get(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._value is not None and now < self._expires_at:
                return self._value
            value = self._read_db()
            self._value = value
            self._expires_at = now + CACHE_TTL_SECONDS
            return value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None
            self._expires_at = 0.0

    @staticmethod
    def _read_db() -> str:
        try:
            from ..core.database import SessionLocal
            from .system_param_service import get_system_param_decrypted

            db = SessionLocal()
            try:
                raw = get_system_param_decrypted(db, PARAM_KEY)
            finally:
                db.close()
        except Exception:  # noqa: BLE001 —— DB 不可用不应阻断任务启动
            logger.debug("read %s failed; falling back to %s", PARAM_KEY, DEFAULT_LANG, exc_info=True)
            return DEFAULT_LANG
        return normalize_lang(raw) or DEFAULT_LANG


_cache = _DefaultLangCache()


def get_default_lang() -> str:
    """全局 ``app.language``（缓存）；缺失 / 停用 / 非法值一律回落 ``zh``。"""
    return _cache.get()


def invalidate_default_lang_cache() -> None:
    """``system_params.changed`` 事件到达时调用：下一次读取重新查库。"""
    _cache.invalidate()


def resolve_backend_lang(task_lang: Any = None) -> str:
    """任务级 lang 优先于全局参数；两者都无效时回落 ``zh``。"""
    explicit = normalize_lang(task_lang)
    return explicit if explicit is not None else get_default_lang()


def bind_request_lang(value: Any):  # noqa: ANN201 —— 返回 ContextVar token
    """绑定当前 HTTP 请求的 ``X-Lang``，返回用于 reset 的 token。"""
    return _request_lang_var.set(normalize_lang(value))


def reset_request_lang(token) -> None:  # noqa: ANN001
    _request_lang_var.reset(token)


def get_request_lang() -> str | None:
    """API 进程中当前请求的语言（供任务发布时注入消息头）。"""
    return _request_lang_var.get()


def current_backend_lang() -> str:
    """当前后端产物的语言：请求级 > 活动任务级 > 全局参数。

    worker 内没有 HTTP 请求上下文，优先取进程内唯一活动日志缓冲上快照的 lang
    （任务启动时写入），确保 WS 阶段事件 / Word 报告与日志同源。
    """
    request_lang = _request_lang_var.get()
    if request_lang is not None:
        return request_lang
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get_single_active()
        if buffer is not None and getattr(buffer, "lang", None):
            return str(buffer.lang)
    except Exception:  # noqa: BLE001 —— 采集器未安装时回落全局参数
        pass
    return get_default_lang()


def ensure_app_language_param(db) -> bool:  # noqa: ANN001
    """幂等地补建 ``app.language`` 系统参数（zh / enabled）。

    返回是否新建。启动自动播种与 seed-defaults 端点调用；不覆盖管理员改动。
    """
    from ..models.system_param import SystemParam
    from .system_param_service import get_system_param_by_key

    if get_system_param_by_key(db, PARAM_KEY) is not None:
        return False
    db.add(
        SystemParam(
            param_key=PARAM_KEY,
            param_name="系统语言",
            param_value=DEFAULT_LANG,
            is_encrypted=False,
            status="enabled",
            description="后端产物（任务日志 / 阶段文案 / Word 报告）默认语言：zh=中文，en=英文；仅 enabled 生效，非法值回落 zh。",
        )
    )
    db.flush()
    return True


class BackendLangMiddleware:
    """纯 ASGI 中间件：把每个 HTTP 请求的 ``X-Lang`` 放进上下文变量。

    用纯 ASGI（而非 BaseHTTPMiddleware）保证与端点处于同一执行上下文，
    任务发布时的 ``before_task_publish`` 信号能可靠读到请求语言。
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw = ""
        for key, value in scope.get("headers") or ():
            if key.lower() == b"x-lang":
                raw = value.decode("latin-1") if isinstance(value, bytes) else str(value)
                break
        token = bind_request_lang(raw)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_request_lang(token)
