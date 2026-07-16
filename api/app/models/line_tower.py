from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line
    from .tower_profile import TowerProfile


class LineTower(Base):
    __tablename__ = "power_line_tower"
    __table_args__ = (
        UniqueConstraint("line_id", "seq_no", name="uq_power_line_tower_line_seq"),
        UniqueConstraint("line_id", "tower_no", name="uq_power_line_tower_line_tower_no"),
        Index("idx_power_line_tower_line_type", "line_id", "tower_type"),
        Index("idx_power_line_tower_line_risk", "line_id", "risk_level"),
        Index("idx_power_line_tower_geo", "longitude", "latitude"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    line_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("power_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tower_no: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tower_model: Mapped[str | None] = mapped_column(String(128), index=True)
    tower_type: Mapped[str | None] = mapped_column(String(32), index=True)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    terrain: Mapped[str | None] = mapped_column(String(64), index=True)
    ground_resistance_ohm: Mapped[float | None] = mapped_column(Float)
    lightning_density: Mapped[float | None] = mapped_column(Float)
    span_small_m: Mapped[float | None] = mapped_column(Float)
    span_large_m: Mapped[float | None] = mapped_column(Float)
    slope_1: Mapped[float | None] = mapped_column(Float)
    slope_2: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str | None] = mapped_column(String(32), index=True)
    circuit_geometry_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lightning_result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    line: Mapped[Line] = relationship("Line", back_populates="towers", lazy="selectin")
    profile: Mapped[TowerProfile | None] = relationship(
        "TowerProfile",
        back_populates="tower",
        lazy="selectin",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
    )
