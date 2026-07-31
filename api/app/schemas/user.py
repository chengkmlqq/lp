import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class UserPublic(BaseModel):
    id: str
    email: str
    username: str
    status: str
    role_codes: list[str]
    permission_codes: list[str]
    created_at: datetime
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
    avatar_url: str | None = None


class UserListResponse(BaseModel):
    items: list[UserPublic]
    total: int


class UserIdCheckResponse(BaseModel):
    available: bool
    message: str


class UserUpdateRequest(BaseModel):
    new_user_id: str | None = Field(default=None, min_length=3, max_length=64)
    email: str | None = None
    username: str | None = Field(default=None, min_length=3, max_length=64)
    status: Literal["active", "disabled", "enabled"] | None = None

    @field_validator("new_user_id")
    @classmethod
    def validate_new_user_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("new_user_id cannot be empty")
        if not re.match(r"^[a-zA-Z0-9_]+$", normalized):
            raise ValueError("new_user_id must contain only letters, numbers, and underscores")
        return normalized


class UserRoleUpdateRequest(BaseModel):
    role_codes: list[str] = Field(min_length=1)


class UserPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserCreateRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=64)
    email: str | None = None
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("user_id cannot be empty")
        return normalized
