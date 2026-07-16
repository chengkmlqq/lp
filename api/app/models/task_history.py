from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class TaskHistory(Base):
    __tablename__ = "celery_task_history"
    __table_args__ = (
        Index("idx_celery_task_history_state", "state"),
        Index("idx_celery_task_history_name", "name"),
        Index("idx_celery_task_history_create_date", "create_date"),
        Index("idx_celery_task_history_done_at", "done_at"),
        Index("idx_celery_task_history_worker", "worker"),
    )

    task_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), default="")
    state: Mapped[str] = mapped_column(String(32), default="PENDING")
    queue_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    worker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    create_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
