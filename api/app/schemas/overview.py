from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .task_monitor import TaskMonitorBucketItem


class AssetStatItem(BaseModel):
    key: str
    label: str
    count: int
    route: str | None = None


class OverviewTasksSummary(BaseModel):
    total: int = 0
    queue_pending_total: int = 0
    scheduled_tasks: int = 0
    state_buckets: list[TaskMonitorBucketItem] = Field(default_factory=list)


class SystemOverviewResponse(BaseModel):
    generated_at: datetime
    assets: list[AssetStatItem] = Field(default_factory=list)
    tasks: OverviewTasksSummary = Field(default_factory=OverviewTasksSummary)