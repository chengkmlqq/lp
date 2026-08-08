from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .lightning_amplitude import LightningAmplitude
    from .line import Line


class LineAmplitudeBackfill(Base):
    """雷电流幅值 → 线路回填关联表（LP-265）。

    记录一次「线路雷电流幅值回填」实际使用到的一组雷电流幅值记录集合。
    - 唯一约束 (line_id, amplitude_id)：同一线路对同一幅值重复回填时幂等覆盖（以最近一次为准）。
    - 不做历史数据迁移，只记录方案落地后新发生的回填。
    """

    __tablename__ = "line_amplitude_backfill"
    __table_args__ = (
        UniqueConstraint("line_id", "amplitude_id", name="uq_line_amplitude_backfill_pair"),
        Index("idx_lab_amplitude_id", "amplitude_id"),
        Index("idx_lab_line_id", "line_id"),
        Index("idx_lab_prepared_at", "prepared_at"),
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
    amplitude_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("lightning_amplitude.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prepared_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sampled_event_count: Mapped[int] = mapped_column(Integer, default=0)
    current_a: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_b: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)

    line: Mapped[Line] = relationship("Line", lazy="selectin")
    amplitude: Mapped[LightningAmplitude] = relationship("LightningAmplitude", lazy="selectin")