from __future__ import annotations

from pydantic import BaseModel, Field


class ParamCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None
    sort_order: int = Field(default=0, ge=0)


class ParamCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    parent_id: int | None = None
    sort_order: int | None = Field(default=None, ge=0)


class ParamCategoryTreeItem(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    sort_order: int = 0
    children: list[ParamCategoryTreeItem] = []