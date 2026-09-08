from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line


class LightningDensityBackfillTask(Base):
    """地闪密度回填历史记录（每次回填生成一条，最新在上）。

    与雷电流回填历史（lightning_current_backfill_task）对齐；回填操作本身是同步的
    （prepare-density 直接改塔的 raw_extra_json.lightning_density），这里只保留
    「哪次回填、用了哪个分布、回填了多少塔、Ng 范围」的历史快照，供回填记录 tab 展示。
    """

    __tablename__ = "lightning_density_backfill_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    line_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("power_line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distribution_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prepared_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_years: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_geo_count: Mapped[int] = mapped_column(Integer, default=0)

    avg_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    line: Mapped[Line] = relationship("Line", lazy="selectin")