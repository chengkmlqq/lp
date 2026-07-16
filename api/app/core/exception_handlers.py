import traceback
from fastapi import Request, status
from fastapi.responses import JSONResponse

from .config import get_settings


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    全局异常处理器

    返回的错误响应包含：
    - detail: 错误描述信息（面向用户，前端会展示此字段）
    - type: 异常类型名称
    - stacktrace: 调用栈信息（仅在debug模式下返回，仅供开发人员调试使用，前端不应展示给用户）
    """
    settings = get_settings()

    error_response = {
        "detail": str(exc),
        "type": type(exc).__name__,
    }

    # stacktrace 仅用于开发调试，不应直接展示到页面给用户看
    if settings.debug_mode:
        error_response["stacktrace"] = traceback.format_exc()

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response,
    )
