from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DocumentChapterPublic(BaseModel):
    id: int
    name: str
    description: str | None = None
    parent_id: int | None = None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class DocumentChapterTreeItem(DocumentChapterPublic):
    children: list["DocumentChapterTreeItem"] = Field(default_factory=list)
    documents: list["DocumentPublic"] = Field(default_factory=list)


class DocumentChapterListResponse(BaseModel):
    items: list[DocumentChapterPublic]
    total: int


class DocumentChapterCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    parent_id: int | None = None
    sort_order: int = 0


class DocumentChapterUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    parent_id: int | None = None
    sort_order: int | None = None


class DocumentPublic(BaseModel):
    id: int
    title: str
    content: str
    chapter_id: int | None = None
    sort_order: int
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentPublic]
    total: int


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    content: str
    chapter_id: int | None = None
    sort_order: int = 0
    status: Literal["draft", "published"] = "draft"


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = None
    chapter_id: int | None = None
    sort_order: int | None = None
    status: Literal["draft", "published"] | None = None
