from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class LightningImportBatch(Base):
    """地闪/波形文件导入批次状态跟踪。"""

    __tablename__ = "lightning_import_batch"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    import_type: Mapped[str] = mapped_column(String(32), default="distribution")  # "distribution" | "waveform"

    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | processing | completed | failed
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    create_user: Mapped[str | None] = mapped_column(String(64))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
