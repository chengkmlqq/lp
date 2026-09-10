from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .dimension_item import DimensionItem


class DimensionType(Base):
    """维度类型（对齐 system_param_categories 的树形分类结构，使用 uuid 主键）。"""

    __tablename__ = "dimension_type"
    __table_args__ = (
        Index("idx_dimension_type_parent", "parent_id"),
        Index("idx_dimension_type_enabled", "is_enabled"),
        Index("idx_dimension_type_sort", "sort_order"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("dimension_type.id", ondelete="SET NULL"),
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    parent: Mapped[DimensionType | None] = relationship(
        "DimensionType",
        remote_side=lambda: [DimensionType.id],
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list[DimensionType]] = relationship(
        "DimensionType",
        back_populates="parent",
        lazy="selectin",
        order_by="DimensionType.sort_order",
    )

    # 类型被维度值引用（删除保护用）
    items: Mapped[list[DimensionItem]] = relationship(
        "DimensionItem",
        back_populates="type",
        lazy="selectin",
    )