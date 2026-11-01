from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .dimension_type import DimensionType


class DimensionItem(Base):
    __tablename__ = "dimension_item"
    __table_args__ = (
        Index("idx_dimension_item_type", "dimension_type"),
        Index("idx_dimension_item_parent", "parent_id"),
        Index("idx_dimension_item_code", "code"),
        Index("idx_dimension_item_enabled", "is_enabled"),
        Index("idx_dimension_item_sort", "sort_order"),
        Index("idx_dimension_item_type_id", "type_id"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    dimension_type: Mapped[str] = mapped_column(String(64), nullable=False)
    type_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("dimension_type.id", ondelete="RESTRICT"),
        index=True,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 维度项的工程默认值载体：让「选 500kV」不只拿到标签，还能拿到
    # 「绝缘子串长该填多少 / 默认相间距 / 回路数 / 避雷器 A-B-C」等派生依据。
    # 约定（按 dimension_type.code）：
    #   voltage_level        → {"insulator_length_mm": 4450, "phase_spacing_default": {...}}
    #   tower_type           → {"circuit_count": 2, "call_height_m": 45.0}
    #   scenario             → {"stroke_mode": "raoji", "slope_default": 10.0}
    #   arrester_combination → {"arrester": {"a": true, "b": true, "c": true}}
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    type: Mapped[DimensionType | None] = relationship(
        "DimensionType",
        back_populates="items",
        lazy="selectin",
    )
