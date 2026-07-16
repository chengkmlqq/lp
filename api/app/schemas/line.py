from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

class LineSummary(BaseModel):
    id: str
    code: str
    name: str
    voltage_kv: int | None = None
    phase_sequence_json: dict[str, Any] = Field(default_factory=dict)
    arrester_install_json: dict[str, Any] = Field(default_factory=dict)
    lightning_param_json: dict[str, Any] = Field(default_factory=dict)
    preparation_json: dict[str, Any] = Field(default_factory=dict)
    tower_count: int = 0
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class LineListResponse(BaseModel):
    items: list[LineSummary]
    total: int


class LineCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    voltage_kv: int | None = Field(default=None, ge=1, le=2000)
    phase_sequence_json: dict[str, Any] = Field(default_factory=dict)
    arrester_install_json: dict[str, Any] = Field(default_factory=dict)
    lightning_param_json: dict[str, Any] = Field(default_factory=dict)


class LineUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    voltage_kv: int | None = Field(default=None, ge=1, le=2000)
    phase_sequence_json: dict[str, Any] | None = None
    arrester_install_json: dict[str, Any] | None = None
    lightning_param_json: dict[str, Any] | None = None


class LineTowerSummary(BaseModel):
    id: str
    line_id: str
    seq_no: int
    tower_no: str
    tower_model: str | None = None
    tower_type: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    altitude_m: float | None = None
    terrain: str | None = None
    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    span_small_m: float | None = None
    span_large_m: float | None = None
    slope_1: float | None = None
    slope_2: float | None = None
    risk_level: str | None = None
    circuit_geometry_json: dict[str, Any] = Field(default_factory=dict)
    lightning_result_json: dict[str, Any] = Field(default_factory=dict)
    raw_extra_json: dict[str, Any] = Field(default_factory=dict)
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class LineTowerListResponse(BaseModel):
    items: list[LineTowerSummary]
    total: int


class LineTowerCreateRequest(BaseModel):
    seq_no: int = Field(ge=1, le=1_000_000)
    tower_no: str = Field(min_length=1, max_length=64)
    tower_model: str | None = Field(default=None, max_length=128)
    tower_type: str | None = Field(default=None, max_length=32)
    longitude: float | None = None
    latitude: float | None = None
    altitude_m: float | None = None
    terrain: str | None = Field(default=None, max_length=64)
    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    span_small_m: float | None = None
    span_large_m: float | None = None
    slope_1: float | None = None
    slope_2: float | None = None
    risk_level: str | None = Field(default=None, max_length=32)
    circuit_geometry_json: dict[str, Any] = Field(default_factory=dict)
    lightning_result_json: dict[str, Any] = Field(default_factory=dict)
    raw_extra_json: dict[str, Any] = Field(default_factory=dict)


class LineTowerUpdateRequest(BaseModel):
    seq_no: int | None = Field(default=None, ge=1, le=1_000_000)
    tower_no: str | None = Field(default=None, min_length=1, max_length=64)
    tower_model: str | None = Field(default=None, max_length=128)
    tower_type: str | None = Field(default=None, max_length=32)
    longitude: float | None = None
    latitude: float | None = None
    altitude_m: float | None = None
    terrain: str | None = Field(default=None, max_length=64)
    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    span_small_m: float | None = None
    span_large_m: float | None = None
    slope_1: float | None = None
    slope_2: float | None = None
    risk_level: str | None = Field(default=None, max_length=32)
    circuit_geometry_json: dict[str, Any] | None = None
    lightning_result_json: dict[str, Any] | None = None
    raw_extra_json: dict[str, Any] | None = None


class LineTowerImportResponse(BaseModel):
    line: LineSummary
    imported_count: int
    updated_count: int
    skipped_count: int
    warning_count: int
    warnings: list[str] = Field(default_factory=list)
