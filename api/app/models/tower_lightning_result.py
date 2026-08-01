from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line_tower import LineTower


class TowerLightningResult(Base):
    """雷电计算结果表（tower_lightning_result）。

    由 tower.lightning_result_json 拆分而来，1:1（tower_id 唯一）。
    """

    __tablename__ = "tower_lightning_result"
    __table_args__ = (
        UniqueConstraint("tower_id", name="uq_tower_lightning_result_tower_id"),
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
    counterstroke_indicator: Mapped[int | None] = mapped_column(SmallInteger)
    counterstroke_withstand_ka: Mapped[float | None] = mapped_column(Float)
    counterstroke_trip_rate: Mapped[float | None] = mapped_column(Float)
    shielding_withstand_ka: Mapped[float | None] = mapped_column(Float)
    shielding_trip_rate: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float | None] = mapped_column(Float)
    current_a_ka: Mapped[float | None] = mapped_column(Float)
    current_b_ka: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(32), index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    tower: Mapped[LineTower] = relationship("LineTower", back_populates="lightning_result")
