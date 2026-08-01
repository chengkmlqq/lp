from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line_tower import LineTower


class TowerAnalysis(Base):
    """分析建议表（tower_analysis）。

    由 profile.extra_profile_json 中的 cause_analysis / mitigation_recommendation
    拆分而来，1:1（tower_id 唯一）。
    """

    __tablename__ = "tower_analysis"
    __table_args__ = (
        UniqueConstraint("tower_id", name="uq_tower_analysis_tower_id"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    tower_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("power_line_tower.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cause_analysis: Mapped[str | None] = mapped_column(Text)
    mitigation_recommendation: Mapped[str | None] = mapped_column(Text)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    tower: Mapped[LineTower] = relationship("LineTower", back_populates="analysis")
