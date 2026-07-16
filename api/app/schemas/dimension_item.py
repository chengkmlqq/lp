from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DimensionItemSummary(BaseModel):
    id: str
    dimension_type: str
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


class DimensionItemTreeNode(BaseModel):
    id: str
    dimension_type: str
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
    children: list[DimensionItemTreeNode] = Field(default_factory=list)


class DimensionItemListResponse(BaseModel):
    items: list[DimensionItemSummary]
    total: int


class DimensionItemCreateRequest(BaseModel):
    dimension_type: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    parent_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=1_000_000)


class DimensionItemUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)
