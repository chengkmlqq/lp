from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TowerCircuitSummary(BaseModel):
    id: str | None = None
    tower_id: str | None = None
    circuit_no: int
    phase_sequence: str | None = None
    spacing_upper_m: float | None = None
    spacing_middle_m: float | None = None
    spacing_lower_m: float | None = None
    height_upper_m: float | None = None
    height_middle_m: float | None = None
    height_lower_m: float | None = None


class TowerLightningResultSummary(BaseModel):
    id: str | None = None
    tower_id: str | None = None
    counterstroke_indicator: int | None = None
    counterstroke_withstand_ka: float | None = None
    counterstroke_trip_rate: float | None = None
    shielding_withstand_ka: float | None = None
    shielding_trip_rate: float | None = None
    angle_deg: float | None = None
    current_a_ka: float | None = None
    current_b_ka: float | None = None
    risk_level: str | None = None


class TowerAnalysisSummary(BaseModel):
    id: str | None = None
    tower_id: str | None = None
    cause_analysis: str | None = None
    mitigation_recommendation: str | None = None


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
    estimated_length_km: float | None = None
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


class TowerProfileLightningCurrentSummary(BaseModel):
    """TowerProfile 中「雷电流幅值回填」数据（extra_profile_json.lightning_current_preparation）。"""

    line_id: str | None = None
    line_code: str | None = None
    current_a: float | None = None
    current_b: float | None = None
    peak_max: float | None = None
    peak_min: float | None = None
    sampled_event_count: int = 0
    region_id: str | None = None
    is_synthetic: bool = False
    prepared_at: str | None = None


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
    circuits: list[TowerCircuitSummary] = Field(default_factory=list)
    lightning_result: TowerLightningResultSummary | None = None
    analysis: TowerAnalysisSummary | None = None
    raw_extra_json: dict[str, Any] = Field(default_factory=dict)
    current_type: str | None = None
    current_a: float | None = None
    current_b: float | None = None
    lightning_current_preparation: TowerProfileLightningCurrentSummary | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class TowerBasicDetail(BaseModel):
    """杆塔详情抽屉「基本信息」Tab 的塔本体字段（含线路电压等级与专业参数）。"""

    id: str
    line_id: str
    seq_no: int
    tower_no: str
    tower_model: str | None = None
    tower_type: str | None = None
    voltage_kv: int | None = None
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
    current_type: str | None = None
    current_a: float | None = None
    current_b: float | None = None
    structure_kind: str | None = None
    stroke_mode: str | None = None
    insulator_length_m: float | None = None
    call_height_m: float | None = None
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    shield_wire_height_m: float | None = None
    lightning_wire_left_mid_distance_m: float | None = None
    lightning_wire_right_mid_distance_m: float | None = None


class TowerDetailResponse(BaseModel):
    """防雷详情页杆塔聚合详情（`GET /api/v1/lines/towers/{tower_id}/detail`）。"""

    tower: TowerBasicDetail
    circuits: list[TowerCircuitSummary] = Field(default_factory=list)
    arrester: dict[str, bool] = Field(default_factory=dict)
    lightning_result: TowerLightningResultSummary | None = None
    analysis: TowerAnalysisSummary | None = None


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
    circuits: list[TowerCircuitSummary] = Field(default_factory=list)
    lightning_result: TowerLightningResultSummary | None = None
    analysis: TowerAnalysisSummary | None = None
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
    circuits: list[TowerCircuitSummary] | None = None
    lightning_result: TowerLightningResultSummary | None = None
    analysis: TowerAnalysisSummary | None = None
    raw_extra_json: dict[str, Any] | None = None


class LineTowerImportResponse(BaseModel):
    line: LineSummary
    imported_count: int
    updated_count: int
    skipped_count: int
    warning_count: int
    warnings: list[str] = Field(default_factory=list)
