from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskMonitorBucketItem(BaseModel):
    key: str
    label: str
    count: int


class TaskMonitorWorkerItem(BaseModel):
    worker: str
    online: bool = True
    queue_names: list[str] = Field(default_factory=list)
    max_concurrency: int = 0
    prefetch_count: int = 0
    uptime_seconds: int = 0
    processed_total: int = 0
    active_count: int = 0
    reserved_count: int = 0
    scheduled_count: int = 0


class TaskMonitorQueueItem(BaseModel):
    name: str
    pending_count: int = 0
    consumer_count: int = 0
    active_count: int = 0
    reserved_count: int = 0
    scheduled_count: int = 0


class TaskMonitorTaskItem(BaseModel):
    task_id: str
    name: str
    state: str
    queue_name: str | None = None
    worker: str | None = None
    retries: int = 0
    eta: datetime | None = None
    started_at: datetime | None = None
    done_at: datetime | None = None
    runtime_seconds: float | None = None
    error: str | None = None


class TaskMonitorOverviewResponse(BaseModel):
    generated_at: datetime
    broker_url: str = ""
    result_backend: str = ""
    workers_online: int = 0
    worker_concurrency_total: int = 0
    queue_pending_total: int = 0
    task_state_buckets: list[TaskMonitorBucketItem] = Field(default_factory=list)
    workers: list[TaskMonitorWorkerItem] = Field(default_factory=list)
    queues: list[TaskMonitorQueueItem] = Field(default_factory=list)
    tasks: list[TaskMonitorTaskItem] = Field(default_factory=list)
