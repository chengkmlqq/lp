from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line_tower import LineTower


class TowerProfile(Base):
    __tablename__ = "tower_profile"
    __table_args__ = (
        UniqueConstraint("tower_id", name="uq_tower_profile_tower_id"),
        Index("idx_tower_profile_tower_id", "tower_id"),
        Index("idx_tower_profile_current_type", "current_type"),
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
    phase_sequence_1: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_2: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_3: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_4: Mapped[str | None] = mapped_column(String(32))
    arrester_a: Mapped[str | None] = mapped_column(String(64))
    arrester_b: Mapped[str | None] = mapped_column(String(64))
    arrester_c: Mapped[str | None] = mapped_column(String(64))
    protection_angle_left_deg: Mapped[float | None] = mapped_column(Float)
    protection_angle_right_deg: Mapped[float | None] = mapped_column(Float)
    shield_wire_height_m: Mapped[float | None] = mapped_column(Float)
    insulator_length_m: Mapped[float | None] = mapped_column(Float)
    call_height_m: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float | None] = mapped_column(Float)
    current_a: Mapped[float | None] = mapped_column(Float)
    current_b: Mapped[float | None] = mapped_column(Float)
    structure_kind: Mapped[str | None] = mapped_column(String(64), index=True)
    stroke_mode: Mapped[str | None] = mapped_column(String(32), index=True)
    current_type: Mapped[str | None] = mapped_column(String(32), index=True)
    current_head_time_us: Mapped[float | None] = mapped_column(Float)
    current_tail_time_us: Mapped[float | None] = mapped_column(Float)
    geometry_layers_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extra_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    tower: Mapped[LineTower] = relationship("LineTower", back_populates="profile", lazy="selectin")
