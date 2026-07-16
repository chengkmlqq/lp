from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class WineRun(Base):
    __tablename__ = "wine_run"
    __table_args__ = (
        Index("idx_wine_run_status", "status"),
        Index("idx_wine_run_create_date", "create_date"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    exe_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    arguments_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    working_dir: Mapped[str] = mapped_column(String(1000), nullable=False)
    environment_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    wine_binary: Mapped[str | None] = mapped_column(String(255))
    resolved_binary: Mapped[str | None] = mapped_column(String(1000))
    command_text: Mapped[str | None] = mapped_column(String(2000))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stdout_text: Mapped[str | None] = mapped_column(Text)
    stderr_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)
