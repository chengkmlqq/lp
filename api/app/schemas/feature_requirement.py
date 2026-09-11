"""功能需求单：请求/响应模型。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

PRIORITIES = ("\u9ad8", "\u4e2d", "\u4f4e")
STATUSES = ("\u5f85\u5904\u7406", "\u8fdb\u884c\u4e2d", "\u5df2\u5b8c\u6210", "\u5df2\u5173\u95ed")


class RequirementBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    module: str | None = Field(default=None, max_length=64)
    priority: str = Field(default="\u4e2d", max_length=16)
    status: str = Field(default="\u5f85\u5904\u7406", max_length=32)
    description: str | None = None


class RequirementCreate(RequirementBase):
    pass


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    module: str | None = Field(default=None, max_length=64)
    priority: str | None = Field(default=None, max_length=16)
    status: str | None = Field(default=None, max_length=32)
    description: str | None = None


class RequirementStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class RequirementOut(RequirementBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RequirementListOut(BaseModel):
    items: list[RequirementOut]
    total: int


class RequirementMetaOut(BaseModel):
    modules: list[str]
    priorities: list[str]
    statuses: list[str]
