from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class TowerModel(Base):
    __tablename__ = "tower_model"
    __table_args__ = (
        Index("idx_tower_model_code", "code"),
        Index("idx_tower_model_name", "name"),
        Index("idx_tower_model_enabled", "is_enabled"),
        Index("idx_tower_model_tower_type", "tower_type"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    code: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tower_type: Mapped[str | None] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    image_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    image_path: Mapped[str | None] = mapped_column(String(2048))
    source_tag: Mapped[str | None] = mapped_column(String(64), index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)

    default_altitude_m: Mapped[float | None] = mapped_column(Float)
    default_terrain: Mapped[str | None] = mapped_column(String(64))
    default_ground_resistance_ohm: Mapped[float | None] = mapped_column(Float)
    default_lightning_density: Mapped[float | None] = mapped_column(Float)
    default_span_small_m: Mapped[float | None] = mapped_column(Float)
    default_span_large_m: Mapped[float | None] = mapped_column(Float)
    default_slope_1: Mapped[float | None] = mapped_column(Float)
    default_slope_2: Mapped[float | None] = mapped_column(Float)
    default_risk_level: Mapped[str | None] = mapped_column(String(32), index=True)
    default_raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)
