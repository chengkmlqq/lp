"""「系统总览」可配置仪表盘 schema（lp 平台用户级卡片布局）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

OverviewWidgetType = Literal["asset_stats", "task_summary", "task_states", "quick_links"]


class OverviewQuickLink(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    href: str = Field(min_length=1, max_length=200)


class OverviewWidgetConfig(BaseModel):
    """一张卡片：类型 + 标题（空则用默认）+ 24 栅格宽度 + 类型专属 props。"""

    type: OverviewWidgetType
    title: str | None = None
    span: int = Field(default=24, ge=1, le=24)
    props: dict[str, Any] = Field(default_factory=dict)


class OverviewConfigRequest(BaseModel):
    widgets: list[OverviewWidgetConfig] = Field(default_factory=list, max_length=12)


class OverviewConfigResponse(BaseModel):
    widgets: list[OverviewWidgetConfig] = Field(default_factory=list)