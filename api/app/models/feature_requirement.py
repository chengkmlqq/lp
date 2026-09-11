"""功能需求单：表模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FeatureRequirement(Base):
    __tablename__ = "feature_requirement"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    module: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="\u4e2d")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="\u5f85\u5904\u7406")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
