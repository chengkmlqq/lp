from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class WorkerRegistry(Base):
    __tablename__ = "worker_registry"
    __table_args__ = (
        Index("idx_worker_registry_worker", "worker_name"),
        Index("idx_worker_registry_status", "status"),
        Index("idx_worker_registry_last_seen", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    worker_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="online", index=True)
    queues_csv: Mapped[str | None] = mapped_column(String(2000))
    pid: Mapped[int | None] = mapped_column(Integer)
    heartbeat_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    metadata_json: Mapped[str | None] = mapped_column(String(4000))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)
