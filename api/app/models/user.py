from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.config import get_settings
from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .auth_session import AuthSession
    from .audit_log import AuditLog
    from .rbac import Role

settings = get_settings()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        "user_id",
        String(36),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    email: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    username: Mapped[str] = mapped_column(
        settings.user_username_column,
        String(64),
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        settings.user_password_column,
        String(255),
    )
    status: Mapped[str] = mapped_column(
        settings.user_status_column,
        String(32),
        default="ENABLED",
        index=True,
    )
    avatar_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # 手机号(短信验证码登录用, 可空: 短信开关开启时未绑定手机号的账号无法登录)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
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
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_login_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )
    @property
    def last_login_at(self) -> datetime | None:
        return self.updated_at

    @last_login_at.setter
    def last_login_at(self, value: datetime | None) -> None:
        if value is not None:
            self.updated_at = value

    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        "AuthSession",
        back_populates="user",
        lazy="selectin",
        passive_deletes=True,
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(
        "AuditLog",
        back_populates="user",
        lazy="selectin",
        passive_deletes=True,
    )
