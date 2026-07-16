from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TaskLogUploadRequest(BaseModel):
    task_id: str = Field(min_length=1, max_length=255)
    log_content: str


class TaskLogUploadResponse(BaseModel):
    task_id: str
    log_path: str
    uploaded_at: datetime


class TaskLogResponse(BaseModel):
    task_id: str
    log_content: str
    log_path: str
    exists: bool = True
