from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class FlowerWorkerItem(BaseModel):
    worker: str
    status: str
    queue_names: list[str] = Field(default_factory=list)
    registered_count: int = 0
    processed_count: int = 0
    concurrency: int = 0
    prefetch_count: int = 0
    active_count: int = 0
    reserved_count: int = 0
    scheduled_count: int = 0
    last_heartbeat_at: datetime | None = None


class FlowerWorkersSummary(BaseModel):
    total: int = 0
    online: int = 0
    offline: int = 0


class FlowerWorkersOverviewResponse(BaseModel):
    generated_at: datetime
    workers: list[FlowerWorkerItem] = Field(default_factory=list)
    summary: FlowerWorkersSummary = Field(default_factory=FlowerWorkersSummary)


class FlowerTaskItem(BaseModel):
    task_id: str
    name: str
    state: str
    source: str
    worker: str
    queue_name: str | None = None
    args_text: str | None = None
    kwargs_text: str | None = None
    eta: datetime | None = None
    received_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    runtime_seconds: float | None = None
    result_text: str | None = None
    exception_text: str | None = None


class FlowerWorkerTaskSummary(BaseModel):
    active: int = 0
    reserved: int = 0
    scheduled: int = 0
    recent: int = 0


class FlowerWorkerTaskOverviewResponse(BaseModel):
    generated_at: datetime
    worker: str
    active_tasks: list[FlowerTaskItem] = Field(default_factory=list)
    reserved_tasks: list[FlowerTaskItem] = Field(default_factory=list)
    scheduled_tasks: list[FlowerTaskItem] = Field(default_factory=list)
    recent_tasks: list[FlowerTaskItem] = Field(default_factory=list)
    summary: FlowerWorkerTaskSummary = Field(default_factory=FlowerWorkerTaskSummary)
