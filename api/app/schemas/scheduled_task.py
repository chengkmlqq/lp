from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .auth import UserPublic


ScheduledTaskStatus = Literal["idle", "queued", "running", "success", "failed", "disabled"]
ScheduledTaskType = Literal["syslog_cleanup"]


class ScheduledTaskSummary(BaseModel):
    id: int
    task_key: str
    name: str
    task_type: ScheduledTaskType
    description: str | None = None
    cron_expression: str
    timezone: str
    retain_days: int
    enabled: bool
    status: ScheduledTaskStatus
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str | None = None
    last_result_json: dict[str, Any] = Field(default_factory=dict)
    run_count: int
    create_user: str | None = None
    update_user: str | None = None
    create_date: datetime
    update_date: datetime
    creator: UserPublic | None = None
    updater: UserPublic | None = None


class ScheduledTaskListResponse(BaseModel):
    items: list[ScheduledTaskSummary]
    total: int


class ScheduledTaskCreateRequest(BaseModel):
    task_key: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=2, max_length=128)
    task_type: ScheduledTaskType
    description: str | None = Field(default="", max_length=4000)
    cron_expression: str = Field(min_length=9, max_length=128)
    timezone: str = Field(default="Asia/Shanghai", min_length=2, max_length=64)
    retain_days: int = Field(default=30, ge=1, le=3650)
    enabled: bool = True


class ScheduledTaskUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    cron_expression: str | None = Field(default=None, min_length=9, max_length=128)
    timezone: str | None = Field(default=None, min_length=2, max_length=64)
    retain_days: int | None = Field(default=None, ge=1, le=3650)
    enabled: bool | None = None


class ScheduledTaskRunResponse(BaseModel):
    success: bool
    task: ScheduledTaskSummary
    celery_task_id: str | None = None
