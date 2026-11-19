"""公开的系统启动配置（无需鉴权）。"""

from fastapi import APIRouter

from ...core.config import get_settings
from ...schemas.system import SystemBootstrapResponse

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/bootstrap", response_model=SystemBootstrapResponse)
def get_bootstrap() -> SystemBootstrapResponse:
    """默认语言等启动配置，取自 ``APP_LANGUAGE``；前端首次访问据此决定界面语言。

    保持公开：登录页 / 注册页在未登录状态下也要能拿到默认语言。
    """
    return SystemBootstrapResponse(default_lang=get_settings().app_language)
