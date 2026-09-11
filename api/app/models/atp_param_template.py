"""ATP 参数模板（配置化）：规则表 + 全局槽位表。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AtpParamTemplate(Base):
    """一条参数模板规则（维度留空 = 通配；越细的规则覆盖越粗的）。"""

    __tablename__ = "atp_param_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    marker: Mapped[str | None] = mapped_column(String(64))
    tower_type: Mapped[str | None] = mapped_column(String(64))
    voltage_level: Mapped[str | None] = mapped_column(String(16))
    circuit_count: Mapped[int | None] = mapped_column(Integer)
    scene_type: Mapped[str | None] = mapped_column(String(32))
    arrester_config: Mapped[str | None] = mapped_column(String(64))
    structure_kind: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), default="merge", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fallback_to: Mapped[str | None] = mapped_column(String(64))
    fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    slots_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(64))


class AtpParamGlobal(Base):
    """全局槽位（电流/波形/接地/串长），所有塔型共用。"""

    __tablename__ = "atp_param_global"

    slot: Mapped[str] = mapped_column(String(32), primary_key=True)
    expr: Mapped[str | None] = mapped_column(Text())
    value: Mapped[str | None] = mapped_column(String(32))
    when_expr: Mapped[str | None] = mapped_column(Text())
    else_value: Mapped[str | None] = mapped_column(String(32))
    fmt: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(64))
