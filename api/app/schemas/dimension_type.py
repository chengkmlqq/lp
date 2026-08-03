from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DimensionTypeSummary(BaseModel):
    id: str
    code: str
    name: str
    parent_id: str | None = None
    description: str | None = None
    is_enabled: bool = True
    sort_order: int = 0
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class DimensionTypeTreeItem(BaseModel):
    id: str
    code: str
    name: str
    parent_id: str | None = None
    description: str | None = None
    is_enabled: bool = True
    sort_order: int = 0
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None
    children: list[DimensionTypeTreeItem] = Field(default_factory=list)


class DimensionTypeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=1_000_000)


class DimensionTypeUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)