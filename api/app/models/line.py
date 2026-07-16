from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line_tower import LineTower


class Line(Base):
    __tablename__ = "power_line"
    __table_args__ = (
        Index("idx_power_line_code", "code"),
        Index("idx_power_line_status", "status"),
        Index("idx_power_line_voltage", "voltage_kv"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    voltage_kv: Mapped[int | None] = mapped_column(Integer, index=True)
    tower_shape: Mapped[str | None] = mapped_column(String(64))
    phase_sequence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    arrester_install_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lightning_param_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="enabled", index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    towers: Mapped[list[LineTower]] = relationship(
        "LineTower",
        back_populates="line",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="LineTower.seq_no.asc()",
    )
