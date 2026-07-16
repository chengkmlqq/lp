from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TowerModelSummary(BaseModel):
    id: str
    code: str
    name: str
    tower_type: str | None = None
    description: str | None = None
    image_mount_code: str | None = None
    image_path: str | None = None
    source_tag: str | None = None
    is_enabled: bool = True
    sort_order: int = 0
    default_altitude_m: float | None = None
    default_terrain: str | None = None
    default_ground_resistance_ohm: float | None = None
    default_lightning_density: float | None = None
    default_span_small_m: float | None = None
    default_span_large_m: float | None = None
    default_slope_1: float | None = None
    default_slope_2: float | None = None
    default_risk_level: str | None = None
    default_raw_json: dict[str, Any] = Field(default_factory=dict)
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class TowerModelListResponse(BaseModel):
    items: list[TowerModelSummary]
    total: int


class TowerModelCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    tower_type: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    image_mount_code: str | None = Field(default=None, min_length=2, max_length=64)
    image_path: str | None = Field(default=None, min_length=1, max_length=2048)
    source_tag: str | None = Field(default=None, max_length=64)
    is_enabled: bool = True
    sort_order: int = Field(default=0, ge=0, le=1_000_000)
    default_altitude_m: float | None = None
    default_terrain: str | None = Field(default=None, max_length=64)
    default_ground_resistance_ohm: float | None = None
    default_lightning_density: float | None = None
    default_span_small_m: float | None = None
    default_span_large_m: float | None = None
    default_slope_1: float | None = None
    default_slope_2: float | None = None
    default_risk_level: str | None = Field(default=None, max_length=32)
    default_raw_json: dict[str, Any] = Field(default_factory=dict)


class TowerModelUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    tower_type: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=2000)
    image_mount_code: str | None = Field(default=None, min_length=2, max_length=64)
    image_path: str | None = Field(default=None, min_length=1, max_length=2048)
    source_tag: str | None = Field(default=None, max_length=64)
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1_000_000)
    default_altitude_m: float | None = None
    default_terrain: str | None = Field(default=None, max_length=64)
    default_ground_resistance_ohm: float | None = None
    default_lightning_density: float | None = None
    default_span_small_m: float | None = None
    default_span_large_m: float | None = None
    default_slope_1: float | None = None
    default_slope_2: float | None = None
    default_risk_level: str | None = Field(default=None, max_length=32)
    default_raw_json: dict[str, Any] | None = None


class TowerModelImageUploadResponse(BaseModel):
    model: TowerModelSummary
    mount_code: str
    image_path: str


class TowerModelSeedResponse(BaseModel):
    total_models: int
    imported_models: int
    updated_models: int
    skipped_models: int
    copied_images: int
    warnings: list[str] = Field(default_factory=list)

