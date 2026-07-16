from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .user import User


class ScheduledTask(Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        Index("idx_scheduled_tasks_status", "status"),
        Index("idx_scheduled_tasks_enabled", "enabled"),
        Index("idx_scheduled_tasks_next_run", "next_run_at"),
        Index("idx_scheduled_tasks_task_type", "task_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text(), default="")
    cron_expression: Mapped[str] = mapped_column(String(128))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    retain_days: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_message: Mapped[str | None] = mapped_column(Text())
    last_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    create_user: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        index=True,
    )
    update_user: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        index=True,
    )
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    creator: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[create_user],
        lazy="selectin",
    )
    updater: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[update_user],
        lazy="selectin",
    )
