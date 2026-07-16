from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .user import UserPublic


class SystemParamSummary(BaseModel):
    id: int
    param_key: str
    param_name: str
    param_value: str
    description: str | None = None
    status: str
    created_by_user_id: str | None = None
    updated_by_user_id: str | None = None
    created_at: datetime
    updated_at: datetime
    created_by: UserPublic | None = None
    updated_by: UserPublic | None = None


class SystemParamListResponse(BaseModel):
    items: list[SystemParamSummary]
    total: int


class SystemParamCreateRequest(BaseModel):
    param_key: str = Field(min_length=2, max_length=128)
    param_name: str = Field(min_length=2, max_length=128)
    param_value: str = Field(default="", max_length=20000)
    description: str | None = Field(default=None, max_length=20000)
    status: str = Field(default="enabled", pattern="^(enabled|disabled)$")


class SystemParamUpdateRequest(BaseModel):
    param_name: str | None = Field(default=None, min_length=2, max_length=128)
    param_value: str | None = Field(default=None, max_length=20000)
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, pattern="^(enabled|disabled)$")
