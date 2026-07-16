from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .user import User


class SystemMessage(Base):
    __tablename__ = "system_messages"

    id: Mapped[str] = mapped_column(
        "message_id",
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(
        String(32),
        default="info",
        index=True,
    )
    target_user_id: Mapped[str | None] = mapped_column(
        String(36),
        index=True,
        nullable=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        "created_at",
        DateTime(timezone=False),
        default=utcnow,
        index=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        "read_at",
        DateTime(timezone=False),
        nullable=True,
    )
