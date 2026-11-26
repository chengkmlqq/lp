from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class WindTurbineModel(Base):
    """机组型号 → 轮毂中心高度。

    风电数据准备页面在线维护；单风机计算选择型号时据此自动带出 ``hub_height``。
    与维度管理无关，独立表 + 独立接口。
    """

    __tablename__ = "wind_turbine_model"
    __table_args__ = (
        Index("ux_wind_turbine_model_code", "code", unique=True),
        Index("idx_wind_turbine_model_enabled", "is_enabled"),
        Index("idx_wind_turbine_model_sort", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hub_height_m: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WindBladeModel(Base):
    """叶片型号 → 叶片长度。

    风电数据准备页面在线维护；单风机计算选择型号时据此自动带出 ``blade_length``。
    """

    __tablename__ = "wind_blade_model"
    __table_args__ = (
        Index("ux_wind_blade_model_code", "code", unique=True),
        Index("idx_wind_blade_model_enabled", "is_enabled"),
        Index("idx_wind_blade_model_sort", "sort_order"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    blade_length_m: Mapped[float] = mapped_column(Float, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
