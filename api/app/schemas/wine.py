from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

WineRunStatus = Literal["pending", "running", "success", "failed"]


class WineStatusResponse(BaseModel):
    wine_binary: str
    resolved_binary: str | None = None
    available: bool
    version: str | None = None
    allowed_root: str
    default_timeout_seconds: int
    max_timeout_seconds: int
    error: str | None = None


class WineRunRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    exe_path: str = Field(min_length=1, max_length=1000)
    arguments: list[str] = Field(default_factory=list, max_length=64)
    working_dir: str | None = Field(default=None, max_length=1000)
    timeout_seconds: int | None = Field(default=None, ge=1)
    environment: dict[str, str] = Field(default_factory=dict, max_length=32)

    @field_validator("arguments")
    @classmethod
    def validate_arguments(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if not isinstance(value, str):
                msg = "Arguments must be strings"
                raise ValueError(msg)
            if "\x00" in value:
                msg = "Arguments cannot contain null bytes"
                raise ValueError(msg)
            if len(value) > 2000:
                msg = "Each argument must be 2000 characters or fewer"
                raise ValueError(msg)
            normalized.append(value)
        return normalized

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, values: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in values.items():
            env_key = key.strip()
            if not env_key or "=" in env_key or "\x00" in env_key:
                msg = "Environment keys cannot be empty or contain '=' / null bytes"
                raise ValueError(msg)
            if "\x00" in value:
                msg = "Environment values cannot contain null bytes"
                raise ValueError(msg)
            normalized[env_key] = value
        return normalized


class WineRunSummary(BaseModel):
    id: str
    task_id: str | None = None
    status: WineRunStatus
    exe_path: str
    arguments: list[str] = Field(default_factory=list)
    working_dir: str
    timeout_seconds: int
    command_text: str | None = None
    resolved_binary: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    stdout_size: int = 0
    stderr_size: int = 0
    create_date: datetime
    create_user: str | None = None


class WineRunDetail(WineRunSummary):
    stdout_text: str | None = None
    stderr_text: str | None = None


class WineRunListResponse(BaseModel):
    items: list[WineRunSummary]
    total: int
