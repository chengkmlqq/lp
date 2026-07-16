from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PermissionPublic(BaseModel):
    id: int
    code: str
    name: str


class RolePublic(BaseModel):
    id: str
    code: str
    name: str
    permission_codes: list[str]
    menu_ids: list[str] = Field(default_factory=list)


class RoleListResponse(BaseModel):
    items: list[RolePublic]
    total: int


class RoleCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=128)
    permission_codes: list[str] = Field(default_factory=list)
    menu_ids: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    permission_codes: list[str] | None = None
    menu_ids: list[str] | None = None


class MenuPublic(BaseModel):
    id: str
    code: str
    name: str
    path: str | None = None
    icon: str | None = None
    parent_id: str | None = None
    type: str
    sort_order: int
    status: str
    visible: bool
    cacheable: bool
    component: str | None = None
    permission_code: str | None = None


class MenuTreeItem(MenuPublic):
    children: list["MenuTreeItem"] = Field(default_factory=list)


class MenuListResponse(BaseModel):
    items: list[MenuPublic]
    total: int


class MenuCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=128)
    name: str = Field(min_length=2, max_length=128)
    path: str | None = Field(default=None, max_length=255)
    icon: str | None = Field(default=None, max_length=64)
    parent_id: str | None = None
    type: str = Field(default="menu")
    sort_order: int = 0
    status: str = Field(default="enabled")
    visible: bool = True
    cacheable: bool = False
    component: str | None = Field(default=None, max_length=255)
    permission_code: str | None = Field(default=None, max_length=64)


class MenuUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=128)
    path: str | None = Field(default=None, max_length=255)
    icon: str | None = Field(default=None, max_length=64)
    parent_id: str | None = None
    type: str | None = Field(default=None)
    sort_order: int | None = None
    status: str | None = Field(default=None)
    visible: bool | None = None
    cacheable: bool | None = None
    component: str | None = Field(default=None, max_length=255)
    permission_code: str | None = Field(default=None, max_length=64)


class RoleMenuUpdateRequest(BaseModel):
    menu_ids: list[str] = Field(default_factory=list)


class AuditLogPublic(BaseModel):
    id: int
    user_id: str | None = None
    username: str | None = None
    action: str
    detail: str | None = None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogPublic]
    total: int
    limit: int
    offset: int


class SeedCategorySummary(BaseModel):
    created: int = 0
    updated: int = 0
    linked: int = 0
    unchanged: int = 0
    overwritten: int = 0


class SeedDefaultsResponse(BaseModel):
    success: bool
    force: bool
    mode: Literal["missing_only", "force_overwrite"]
    overwrote_existing: bool
    summary: dict[str, SeedCategorySummary] = Field(default_factory=dict)


class RolesWithMenusResponse(BaseModel):
    roles: list[RolePublic]
    roles_total: int
    menus: list[MenuPublic]
    menus_total: int


MenuTreeItem.model_rebuild()
