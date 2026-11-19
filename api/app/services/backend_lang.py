"""后端产物（任务日志 / WS 阶段文案 / Word 报告）的语言解析。

语言来源与优先级（LP-34）：
1. **任务级 lang**：创建任务的 HTTP 请求带 ``X-Lang``，在任务发布时注入 Celery
   消息头，worker 在任务启动时读入并快照 —— 每个任务的语言在启动后固定不变。
2. **``APP_LANGUAGE`` 环境变量**：进程启动时由 ``Settings`` 读取一次，运行期不再
   查库、不热更新；取值 ``zh`` / ``en``，默认 ``zh``。
3. 都拿不到时回落 ``zh``。

历史遗留的系统参数 ``app.language`` 已废弃，存量行在启动时清理。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from ..core.config import DEFAULT_APP_LANGUAGE, get_settings, normalize_lang

logger = logging.getLogger(__name__)

__all__ = [
    "BackendLangMiddleware",
    "bind_request_lang",
    "current_backend_lang",
    "get_default_lang",
    "get_request_lang",
    "normalize_lang",
    "reset_request_lang",
    "resolve_backend_lang",
]

# 当前 HTTP 请求的语言（API 进程，由 BackendLangMiddleware 写入）。
_request_lang_var: ContextVar[str | None] = ContextVar("lp_request_lang", default=None)


def get_default_lang() -> str:
    """全局默认语言：``APP_LANGUAGE``（启动时读取一次，默认 ``zh``）。"""
    return get_settings().app_language or DEFAULT_APP_LANGUAGE


def resolve_backend_lang(task_lang: Any = None) -> str:
    """任务级 lang 优先于全局配置；两者都无效时回落 ``zh``。"""
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
    """当前后端产物的语言：请求级 > 活动任务级 > 全局配置。

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
    except Exception:  # noqa: BLE001 —— 采集器未安装时回落全局配置
        pass
    return get_default_lang()


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
