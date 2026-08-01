from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line_tower import LineTower


class TowerCircuit(Base):
    """回路几何表（tower_circuit）。

    由 tower.circuit_geometry_json 与 profile.geometry_layers_json 双写结构拆分而来，
    1:N（每基杆塔最多 4 回），(tower_id, circuit_no) 唯一。
    """

    __tablename__ = "tower_circuit"
    __table_args__ = (
        UniqueConstraint("tower_id", "circuit_no", name="uq_tower_circuit_tower_circuit_no"),
        UniqueConstraint("id", name="uq_tower_circuit_id"),
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
    circuit_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    phase_sequence: Mapped[str | None] = mapped_column(String(32))
    spacing_upper_m: Mapped[float | None] = mapped_column(Float)
    spacing_middle_m: Mapped[float | None] = mapped_column(Float)
    spacing_lower_m: Mapped[float | None] = mapped_column(Float)
    height_upper_m: Mapped[float | None] = mapped_column(Float)
    height_middle_m: Mapped[float | None] = mapped_column(Float)
    height_lower_m: Mapped[float | None] = mapped_column(Float)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    tower: Mapped[LineTower] = relationship("LineTower", back_populates="circuits")
