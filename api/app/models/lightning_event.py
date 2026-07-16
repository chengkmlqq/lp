from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .lightning_sample import LightningCurrentSample


class LightningCurrentEvent(Base):
    __tablename__ = "lightning_current_event"
    __table_args__ = (
        Index("idx_lc_event_event_id", "event_id"),
        Index("idx_lc_event_time", "event_time"),
        Index("idx_lc_region", "region_id"),
        Index("idx_lc_location_tag", "location_tag"),
        Index("idx_lc_polarity", "polarity"),
        Index("idx_lc_wave_shape", "wave_shape"),
        Index("idx_lc_peak_abs", "peak_abs_current_ka"),
        Index("idx_lc_synthetic", "is_synthetic"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_interval_us: Mapped[float | None] = mapped_column(Float)
    sampling_frequency_hz: Mapped[float | None] = mapped_column(Float)

    peak_current_ka: Mapped[float | None] = mapped_column(Float)
    peak_abs_current_ka: Mapped[float | None] = mapped_column(Float)
    wavefront_time_t1_us: Mapped[float | None] = mapped_column(Float)
    half_value_time_t2_us: Mapped[float | None] = mapped_column(Float)
    steepness_ka_per_us: Mapped[float | None] = mapped_column(Float)
    action_integral_j_ohm: Mapped[float | None] = mapped_column(Float)
    wave_shape: Mapped[str | None] = mapped_column(String(32), index=True)
    polarity: Mapped[str] = mapped_column(String(16), default="unknown", index=True)
    stroke_count: Mapped[int] = mapped_column(Integer, default=1)
    stroke_peaks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    region_id: Mapped[str | None] = mapped_column(String(64), index=True)
    location_tag: Mapped[str | None] = mapped_column(String(255), index=True)
    city: Mapped[str | None] = mapped_column(String(128), index=True)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    sensor_model: Mapped[str | None] = mapped_column(String(128))
    install_position: Mapped[str | None] = mapped_column(String(128))
    weather_level: Mapped[str | None] = mapped_column(String(64))
    pressure_hpa: Mapped[float | None] = mapped_column(Float)
    humidity_percent: Mapped[float | None] = mapped_column(Float)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    samples: Mapped[list[LightningCurrentSample]] = relationship(
        "LightningCurrentSample",
        back_populates="event",
        lazy="noload",
        cascade="all, delete-orphan",
        order_by="LightningCurrentSample.seq_no.asc()",
    )
