from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line
    from .lightning_distribution import LightningDistribution


class LightningDensityBackfillTask(Base):
    __tablename__ = "lightning_density_backfill_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    line_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("power_line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distribution_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("lightning_distribution.id", ondelete="SET NULL"), nullable=True, index=True
    )
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prepared_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    radius_km: Mapped[float] = mapped_column(Float, nullable=False)
    avg_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_years: Mapped[float | None] = mapped_column(Float, nullable=True)

    missing_geo_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    line: Mapped[Line] = relationship("Line", lazy="selectin")
    distribution: Mapped[LightningDistribution | None] = relationship("LightningDistribution", lazy="selectin")