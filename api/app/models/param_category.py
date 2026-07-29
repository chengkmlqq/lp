from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    pass


class SystemParamCategory(Base):
    __tablename__ = "system_param_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("system_param_categories.id", ondelete="SET NULL"),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    parent: Mapped[SystemParamCategory | None] = relationship(
        "SystemParamCategory",
        remote_side=lambda: [SystemParamCategory.id],
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list[SystemParamCategory]] = relationship(
        "SystemParamCategory",
        back_populates="parent",
        lazy="selectin",
        order_by="SystemParamCategory.sort_order",
    )