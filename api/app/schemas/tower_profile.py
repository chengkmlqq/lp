from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TowerProfileDetail(BaseModel):
    id: str | None = None
    tower_id: str
    line_id: str
    tower_no: str
    seq_no: int
    tower_model: str | None = None
    tower_type: str | None = None
    profile_exists: bool = False
    phase_sequence_1: str | None = None
    phase_sequence_2: str | None = None
    phase_sequence_3: str | None = None
    phase_sequence_4: str | None = None
    arrester_a: str | None = None
    arrester_b: str | None = None
    arrester_c: str | None = None
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    shield_wire_height_m: float | None = None
    insulator_length_m: float | None = None
    call_height_m: float | None = None
    angle_deg: float | None = None
    current_a: float | None = None
    current_b: float | None = None
    structure_kind: str | None = None
    stroke_mode: str | None = None
    current_type: str | None = None
    current_head_time_us: float | None = None
    current_tail_time_us: float | None = None
    geometry_layers_json: dict[str, Any] = Field(default_factory=dict)
    extra_profile_json: dict[str, Any] = Field(default_factory=dict)
    create_date: datetime | None = None
    create_user: str | None = None
    update_date: datetime | None = None
    update_user: str | None = None


class TowerProfileUpsertRequest(BaseModel):
    phase_sequence_1: str | None = Field(default=None, max_length=32)
    phase_sequence_2: str | None = Field(default=None, max_length=32)
    phase_sequence_3: str | None = Field(default=None, max_length=32)
    phase_sequence_4: str | None = Field(default=None, max_length=32)
    arrester_a: str | None = Field(default=None, max_length=64)
    arrester_b: str | None = Field(default=None, max_length=64)
    arrester_c: str | None = Field(default=None, max_length=64)
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    shield_wire_height_m: float | None = None
    insulator_length_m: float | None = None
    call_height_m: float | None = None
    angle_deg: float | None = None
    current_a: float | None = None
    current_b: float | None = None
    structure_kind: str | None = Field(default=None, max_length=64)
    stroke_mode: str | None = Field(default=None, max_length=32)
    current_type: str | None = Field(default=None, max_length=32)
    current_head_time_us: float | None = None
    current_tail_time_us: float | None = None
    geometry_layers_json: dict[str, Any] = Field(default_factory=dict)
    extra_profile_json: dict[str, Any] = Field(default_factory=dict)