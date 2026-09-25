"""ATP 模型计算参数注册表（独立页面管理的参数定义）。

三种来源（source_type）：
- ``line_binding``：参数来自线路导入的杆塔属性。``binding_json`` 记录
  「杆塔属性路径 ↔ 参数名」的关联（如 profile 字段 / circuit 几何 / 扩展 JSON 键），
  运行时由 ``atp_param_resolver.resolve_definitions`` 从 base_tower/profile/options 抽取。
- ``script``：Python 计算脚本（沙箱求值）。``script_code`` 为纯数学函数体，
  ``deps_json`` 声明依赖的其他参数 code（求值前按依赖序拓扑排序）。
- ``constant``：字面量（如 C# 常量 rk=0.0055）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base


class AtpParamDefinition(Base):
    __tablename__ = "atp_param_definition"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(32))
    data_type: Mapped[str] = mapped_column(String(16), default="number", nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    binding_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    script_code: Mapped[str | None] = mapped_column(Text)
    deps_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str | None] = mapped_column(String(64))
