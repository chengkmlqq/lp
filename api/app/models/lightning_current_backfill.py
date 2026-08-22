from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line
    from .line_tower import LineTower


class LightningCurrentBackfillTask(Base):
    __tablename__ = "lightning_current_backfill_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    line_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("power_line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prepared_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampled_event_count: Mapped[int] = mapped_column(Integer, default=0)

    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    updated_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    created_profile_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_amplitude_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    line: Mapped[Line] = relationship("Line", lazy="selectin")
    towers: Mapped[list[LightningCurrentBackfillTower]] = relationship(
        "LightningCurrentBackfillTower",
        back_populates="task",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="LightningCurrentBackfillTower.create_date.asc()",
    )


class LightningCurrentBackfillTower(Base):
    __tablename__ = "lightning_current_backfill_tower"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    task_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("lightning_current_backfill_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tower_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("power_line_tower.id", ondelete="CASCADE"), nullable=False, index=True
    )

    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_current_b: Mapped[float | None] = mapped_column(Float, nullable=True)

    action: Mapped[str] = mapped_column(String(32), default="updated")
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    task: Mapped[LightningCurrentBackfillTask] = relationship("LightningCurrentBackfillTask", lazy="selectin")
