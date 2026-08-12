from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class TravelingWaveJob(Base):
    __tablename__ = "traveling_wave_job"
    __table_args__ = (
        Index("idx_traveling_wave_job_status", "status"),
        Index("idx_traveling_wave_job_created_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    created_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_rate_hz: Mapped[int | None] = mapped_column(Integer)
    fault_distance_km: Mapped[float | None] = mapped_column(Float)
    tower_no: Mapped[str | None] = mapped_column(String(128))
    file_a_path: Mapped[str | None] = mapped_column(String(512))
    file_b_path: Mapped[str | None] = mapped_column(String(512))
    file_c_path: Mapped[str | None] = mapped_column(String(512))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    error_message: Mapped[str | None] = mapped_column(Text)
    log_text: Mapped[str | None] = mapped_column(Text)
