from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .user import UserPublic


class SystemParamSummary(BaseModel):
    id: int
    param_key: str
    param_name: str
    param_value: str
    is_encrypted: bool = False
    has_value: bool = False
    description: str | None = None
    status: str
    category_id: int | None = None
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
    is_encrypted: bool = False
    description: str | None = Field(default=None, max_length=20000)
    status: str = Field(default="enabled", pattern="^(enabled|disabled)$")
    category_id: int | None = None


class SystemParamUpdateRequest(BaseModel):
    param_name: str | None = Field(default=None, min_length=2, max_length=128)
    param_value: str | None = Field(default=None, max_length=20000)
    is_encrypted: bool | None = None
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, pattern="^(enabled|disabled)$")
    category_id: int | None = None


class SystemParamRuntimeItem(BaseModel):
    param_key: str
    param_value: str


class SystemParamRuntimeResponse(BaseModel):
    items: list[SystemParamRuntimeItem]
