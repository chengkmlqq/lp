from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class LightningDistributionPoint(Base):
    """地闪密度/雷电流分布点。

    与 LightningCurrentEvent（雷电流波形）分离的独立表，
    仅存储来自地闪密度导入的单点数据（纬/经/电流值），
    不包含波形采样或波形特征参数。
    """

    __tablename__ = "lightning_distribution_point"
    __table_args__ = (
        Index("idx_ldp_event_id", "event_id"),
        Index("idx_ldp_event_time", "event_time"),
        Index("idx_ldp_region", "region_id"),
        Index("idx_ldp_location_tag", "location_tag"),
        Index("idx_ldp_polarity", "polarity"),
        Index("idx_ldp_peak_abs", "peak_abs_current_ka"),
        Index("idx_ldp_synthetic", "is_synthetic"),
        Index("idx_ldp_coord", "latitude", "longitude"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    peak_current_ka: Mapped[float | None] = mapped_column(Float)
    peak_abs_current_ka: Mapped[float | None] = mapped_column(Float)
    polarity: Mapped[str] = mapped_column(String(16), default="unknown", index=True)

    region_id: Mapped[str | None] = mapped_column(String(64), index=True)
    location_tag: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(128), index=True)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)

    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)
