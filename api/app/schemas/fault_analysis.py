from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FaultAnalysisSummary(BaseModel):
    id: str
    title: str | None = None
    description: str | None = None
    line_id: str | None = None
    line_name: str | None = None
    status: str = "pending"
    risk_level: str | None = None
    fault_time: str | None = None
    fault_type: str | None = None
    fault_phase: str | None = None
    confidence: float | None = None
    station: str | None = None
    lightning_current_ka: float | None = None
    wave_distance_km: float | None = None
    traveling_wave_distance_km: float | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None
    model_config = {"from_attributes": True}


class FaultAnalysisDetail(FaultAnalysisSummary):
    fault_duration_ms: float | None = None
    reclosure_status: str | None = None
    fault_voltage_v: float | None = None
    fault_current_a: float | None = None
    max_zero_current_a: float | None = None
    zero_compensation: float | None = None
    fault_resistance_ohm: float | None = None
    line_length_km: float | None = None
    line_angle_deg: float | None = None
    line_impedance_ohm: float | None = None
    lightning_longitude: float | None = None
    lightning_latitude: float | None = None
    optical_position: str | None = None
    optical_device_location: str | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)
    model_config = {"from_attributes": True}


class FaultAnalysisListResponse(BaseModel):
    items: list[FaultAnalysisSummary]
    total: int


class FaultAnalysisCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    line_id: str | None = Field(default=None, max_length=32)
    line_name: str | None = Field(default=None, max_length=255)
    risk_level: str | None = Field(default=None, max_length=32)
    fault_time: str | None = Field(default=None, max_length=64)
    fault_type: str | None = Field(default=None, max_length=255)
    fault_phase: str | None = Field(default=None, max_length=32)
    fault_duration_ms: float | None = None
    station: str | None = Field(default=None, max_length=255)
    reclosure_status: str | None = Field(default=None, max_length=32)
    fault_voltage_v: float | None = None
    fault_current_a: float | None = None
    max_zero_current_a: float | None = None
    zero_compensation: float | None = None
    fault_resistance_ohm: float | None = None
    line_length_km: float | None = None
    line_angle_deg: float | None = None
    line_impedance_ohm: float | None = None
    lightning_current_ka: float | None = None
    lightning_longitude: float | None = None
    lightning_latitude: float | None = None
    wave_distance_km: float | None = None
    traveling_wave_distance_km: float | None = None
    optical_position: str | None = Field(default=None, max_length=64)
    optical_device_location: str | None = Field(default=None, max_length=255)
    confidence: float | None = Field(default=None, ge=0, le=100)


class FaultAnalysisCreateResponse(BaseModel):
    analysis: FaultAnalysisDetail


class FaultAnalysisUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    description: str | None = None
    line_id: str | None = Field(default=None, max_length=32)
    line_name: str | None = Field(default=None, max_length=255)
    risk_level: str | None = Field(default=None, max_length=32)
    fault_time: str | None = Field(default=None, max_length=64)
    fault_type: str | None = Field(default=None, max_length=255)
    fault_phase: str | None = Field(default=None, max_length=32)
    fault_duration_ms: float | None = None
    station: str | None = Field(default=None, max_length=255)
    reclosure_status: str | None = Field(default=None, max_length=32)
    fault_voltage_v: float | None = None
    fault_current_a: float | None = None
    max_zero_current_a: float | None = None
    zero_compensation: float | None = None
    fault_resistance_ohm: float | None = None
    line_length_km: float | None = None
    line_angle_deg: float | None = None
    line_impedance_ohm: float | None = None
    lightning_current_ka: float | None = None
    lightning_longitude: float | None = None
    lightning_latitude: float | None = None
    wave_distance_km: float | None = None
    traveling_wave_distance_km: float | None = None
    optical_position: str | None = Field(default=None, max_length=64)
    optical_device_location: str | None = Field(default=None, max_length=255)
    confidence: float | None = Field(default=None, ge=0, le=100)
