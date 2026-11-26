from __future__ import annotations

import math
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

_CODE_MAX = 128
_NAME_MAX = 255
_DESCRIPTION_MAX = 2000
_SORT_ORDER_MAX = 1_000_000


def _require_positive_finite(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("must be a finite number greater than 0")
    return value


class WindTurbineModelSummary(BaseModel):
    id: str
    code: str
    name: str
    hub_height_m: float
    description: str | None = None
    is_enabled: bool = True
    sort_order: int = 0
    create_user: str | None = None
    create_date: datetime
    update_user: str | None = None
    update_date: datetime


class WindTurbineModelCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=_CODE_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    hub_height_m: float
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=_SORT_ORDER_MAX)

    @field_validator("code")
    @classmethod
    def _strip_code(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("code must not be blank")
        return cleaned

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("hub_height_m")
    @classmethod
    def _check_hub_height(cls, value: float) -> float:
        return _require_positive_finite(value)


class WindTurbineModelUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=_CODE_MAX)
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    hub_height_m: float | None = None
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=_SORT_ORDER_MAX)

    @field_validator("code")
    @classmethod
    def _strip_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("code must not be blank")
        return cleaned

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("hub_height_m")
    @classmethod
    def _check_hub_height(cls, value: float | None) -> float | None:
        return None if value is None else _require_positive_finite(value)


class WindTurbineModelListResponse(BaseModel):
    items: list[WindTurbineModelSummary] = Field(default_factory=list)
    total: int = 0


class WindBladeModelSummary(BaseModel):
    id: str
    code: str
    name: str
    blade_length_m: float
    description: str | None = None
    is_enabled: bool = True
    sort_order: int = 0
    create_user: str | None = None
    create_date: datetime
    update_user: str | None = None
    update_date: datetime


class WindBladeModelCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=_CODE_MAX)
    name: str = Field(min_length=1, max_length=_NAME_MAX)
    blade_length_m: float
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=_SORT_ORDER_MAX)

    @field_validator("code")
    @classmethod
    def _strip_code(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("code must not be blank")
        return cleaned

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("blade_length_m")
    @classmethod
    def _check_blade_length(cls, value: float) -> float:
        return _require_positive_finite(value)


class WindBladeModelUpdateRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=_CODE_MAX)
    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    blade_length_m: float | None = None
    description: str | None = Field(default=None, max_length=_DESCRIPTION_MAX)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=_SORT_ORDER_MAX)

    @field_validator("code")
    @classmethod
    def _strip_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("code must not be blank")
        return cleaned

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @field_validator("blade_length_m")
    @classmethod
    def _check_blade_length(cls, value: float | None) -> float | None:
        return None if value is None else _require_positive_finite(value)


class WindBladeModelListResponse(BaseModel):
    items: list[WindBladeModelSummary] = Field(default_factory=list)
    total: int = 0
