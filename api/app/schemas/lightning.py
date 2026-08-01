from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .line import LineSummary

LightningPolarity = Literal["positive", "negative", "mixed", "unknown"]


class LightningCurrentEventSummary(BaseModel):
    id: str
    event_id: str
    source_file_name: str | None = None
    event_time: datetime | None = None
    sample_count: int = 0
    sample_interval_us: float | None = None
    sampling_frequency_hz: float | None = None
    peak_current_ka: float | None = None
    peak_abs_current_ka: float | None = None
    wavefront_time_t1_us: float | None = None
    half_value_time_t2_us: float | None = None
    steepness_ka_per_us: float | None = None
    action_integral_j_ohm: float | None = None
    wave_shape: str | None = None
    polarity: LightningPolarity
    stroke_count: int = 1
    stroke_peaks_json: list[dict[str, Any]] = Field(default_factory=list)
    region_id: str | None = None
    location_tag: str | None = None
    city: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    altitude_m: float | None = None
    sensor_model: str | None = None
    install_position: str | None = None
    weather_level: str | None = None
    pressure_hpa: float | None = None
    humidity_percent: float | None = None
    is_synthetic: bool = False
    feature_json: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class LightningCurrentEventListResponse(BaseModel):
    items: list[LightningCurrentEventSummary]
    total: int
    limit: int
    offset: int


class LightningCurrentEventUpdateRequest(BaseModel):
    event_time: datetime | None = None
    region_id: str | None = Field(default=None, max_length=64)
    location_tag: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=128)
    longitude: float | None = None
    latitude: float | None = None
    altitude_m: float | None = None
    sensor_model: str | None = Field(default=None, max_length=128)
    install_position: str | None = Field(default=None, max_length=128)
    weather_level: str | None = Field(default=None, max_length=64)
    pressure_hpa: float | None = None
    humidity_percent: float | None = Field(default=None, ge=0, le=100)
    is_synthetic: bool | None = None
    wave_shape: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    feature_json: dict[str, Any] | None = None


class LightningCurrentImportResponse(BaseModel):
    imported_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    task_id: str | None = None
    batch_id: str | None = None


class LightningCurrentSampleItem(BaseModel):
    id: int
    event_ref_id: str
    seq_no: int
    time_us: float
    current_ka: float


class LightningCurrentSampleListResponse(BaseModel):
    items: list[LightningCurrentSampleItem]
    total: int
    limit: int
    offset: int


class LightningCurrentExceedancePoint(BaseModel):
    threshold_ka: float
    exceedance_probability: float
    exceedance_count: int


class LightningCurrentExceedanceResponse(BaseModel):
    total_events: int
    thresholds: list[LightningCurrentExceedancePoint]


class LightningDistributionImportResponse(BaseModel):
    """上传文件后立即返回，Celery 异步处理。"""
    distribution_id: str
    task_id: str | None = None
    status: str = "pending"


class LightningDistributionRecord(BaseModel):
    """一次地闪分布导入的「批次 + 统计 + 图片引用」记录。"""
    id: str
    region_id: str | None = None
    location_tag: str | None = None
    city: str | None = None
    event_year: int | None = None
    line_id: str | None = None
    source_file_name: str
    source_object_key: str | None = None
    import_type: str = "distribution"

    status: str = "pending"   # pending|processing|completed|failed
    stage: str = "parsing"    # parsing|validating|statistics|rendering
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None

    total_lines: int = 0
    valid_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    warnings: list[str] | None = None

    area_km2: float | None = None
    data_years: float | None = None
    grid_size_km: float | None = None
    overall_ng: float | None = None
    max_abs_current: float | None = None
    avg_abs_current: float | None = None
    positive_count: int = 0
    negative_count: int = 0
    unknown_count: int = 0
    stats_json: dict[str, Any] | None = None

    has_image: bool = False

    create_user: str | None = None
    create_date: datetime
    update_date: datetime
    update_user: str | None = None


class LightningDistributionListResponse(BaseModel):
    items: list[LightningDistributionRecord]
    total: int
    limit: int
    offset: int


class LightningDistributionStatusResponse(BaseModel):
    distribution_id: str
    status: str
    stage: str
    progress: int
    error_message: str | None = None
    record: LightningDistributionRecord | None = None


class LightningDistributionImageResponse(BaseModel):
    distribution_id: str
    image_url: str | None = None


class LightningCurrentPreparationRequest(BaseModel):
    line_id: str = Field(min_length=1, max_length=64)
    region_id: str | None = Field(default=None, max_length=64)
    is_synthetic: bool | None = None


class LightningCurrentPreparationResponse(BaseModel):
    line: LineSummary
    current_a: float
    current_b: float
    peak_max: float
    peak_min: float
    sampled_event_count: int
    updated_tower_count: int
    created_profile_count: int = 0
    warning_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class LightningDensityPreparationRequest(BaseModel):
    line_id: str = Field(min_length=1, max_length=64)
    region_id: str | None = Field(default=None, max_length=64)
    is_synthetic: bool | None = None
    radius_km: float | None = Field(default=None, gt=0.05, le=50.0)
    years: float | None = Field(default=None, gt=0)


class LightningDensityPreparationResponse(BaseModel):
    line: LineSummary
    updated_tower_count: int
    missing_geo_count: int = 0
    radius_km: float
    data_years: float
    avg_density: float | None = None
    min_density: float | None = None
    max_density: float | None = None
    warning_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class LightningFillDensityRequest(BaseModel):
    """线路地闪密度回填请求。"""
    line_id: str = Field(min_length=1, max_length=64)
    region_id: str | None = Field(default=None, max_length=64)
    years: float | None = Field(default=None, gt=0)
    radius_km: float | None = Field(default=None, gt=0.05, le=50.0)


class LightningFillDensityResponse(BaseModel):
    task_id: str
    status: str = "submitted"
