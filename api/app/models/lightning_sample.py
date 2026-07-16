from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base

if TYPE_CHECKING:
    from .lightning_event import LightningCurrentEvent


class LightningCurrentSample(Base):
    __tablename__ = "lightning_current_sample"
    __table_args__ = (
        UniqueConstraint("event_ref_id", "seq_no", name="uq_lc_sample_event_seq"),
        Index("idx_lc_sample_event_seq", "event_ref_id", "seq_no"),
        Index("idx_lc_sample_event_time", "event_ref_id", "time_us"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_ref_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("lightning_current_event.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    time_us: Mapped[float] = mapped_column(Float, nullable=False)
    current_ka: Mapped[float] = mapped_column(Float, nullable=False)

    event: Mapped[LightningCurrentEvent] = relationship(
        "LightningCurrentEvent",
        back_populates="samples",
        lazy="selectin",
    )
