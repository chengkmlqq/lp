from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SystemBootstrapResponse(BaseModel):
    """公开启动配置：登录页（未登录）也要能拿到默认语言。"""

    default_lang: Literal["zh", "en"]
