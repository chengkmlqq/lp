"""用户级「系统总览」可配置仪表盘布局（每个用户自己的卡片配置）。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .user import User


class UserOverviewConfig(Base):
    __tablename__ = "user_overview_config"

    id: Mapped[str] = mapped_column(
        "id",
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    # 卡片配置 JSON 数组：[{type,title,span,props}]
    widgets_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=False),
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updated_at",
        DateTime(timezone=False),
        default=utcnow,
        onupdate=utcnow,
    )
