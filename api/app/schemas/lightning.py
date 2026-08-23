from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .line import LineSummary

LightningPolarity = Literal["positive", "negative", "mixed", "unknown"]


class LightningCurrentExceedancePoint(BaseModel):
    threshold_ka: float
    exceedance_probability: float
    exceedance_count: int


class LightningCurrentExceedanceResponse(BaseModel):
    total_events: int
    thresholds: list[LightningCurrentExceedancePoint]


# ---------------------------------------------------------------------------
# 雷电流幅值（LightningAmplitude）
# ---------------------------------------------------------------------------
class LightningTempUploadResponse(BaseModel):
    """选择文件后立即上传到 MinIO 临时目录，返回 temp_file_id 供确认导入时引用。"""
    temp_file_id: str
    file_name: str = "upload"


class LightningAmplitudeImportResponse(BaseModel):
    """上传文件后立即返回，Celery 异步处理。"""
    amplitude_id: str
    task_id: str | None = None
    status: str = "pending"


class LightningAmplitudeRecord(BaseModel):
    """一次雷电流幅值导入的「状态机 + 元数据 + 波形特征统计 + MinIO 引用」记录。"""
    id: str
    event_id: str | None = None
    source_file_name: str = "upload"
    event_time: datetime | None = None
    source_object_key: str = ""

    status: str = "pending"   # pending|processing|completed|failed
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None

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
    polarity: LightningPolarity = "unknown"
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
    backfill_line_count: int = 0

    create_user: str | None = None
    create_date: datetime
    update_date: datetime
    update_user: str | None = None


class LightningAmplitudeUpdateRequest(BaseModel):
    """雷电流幅值记录元信息更新请求（仅允许修改可编辑元信息字段）。"""
    event_id: str | None = None
    event_time: datetime | None = None
    sample_interval_us: float | None = None
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
    is_synthetic: bool | None = None
    notes: str | None = None


class LightningAmplitudeListResponse(BaseModel):
    items: list[LightningAmplitudeRecord]
    total: int
    limit: int
    offset: int


class LightningAmplitudeBackfillLine(BaseModel):
    """一条雷电流幅值记录被某线路回填使用的摘要（回填线路小窗行）。"""

    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    voltage_kv: int | None = None
    prepared_at: datetime | None = None
    current_a: float | None = None
    current_b: float | None = None
    peak_max: float | None = None
    peak_min: float | None = None
    sampled_event_count: int = 0


class LightningAmplitudeBackfillLineListResponse(BaseModel):
    items: list[LightningAmplitudeBackfillLine]
    total: int


class LightningAmplitudeStatusResponse(BaseModel):
    amplitude_id: str
    status: str
    progress: int
    error_message: str | None = None
    record: LightningAmplitudeRecord | None = None


# ---------------------------------------------------------------------------
# 地闪分布（LightningDistribution）
# ---------------------------------------------------------------------------
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

    linked_line_count: int | None = None

    status: str = "pending"   # pending|processing|completed|failed
    stage: str = "parsing"    # parsing|validating|statistics|rendering
    progress: int = 0
    task_id: str | None = None
    lp_draw_task_id: str | None = None
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
    has_lp_image: bool = False

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


# ---------------------------------------------------------------------------
# 线路密度计算（prepare）
# ---------------------------------------------------------------------------
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


class LightningCurrentPreparationAsyncResponse(BaseModel):
    task_id: str
    backfill_task_id: str
    line_id: str
    status: str = "pending"  # pending | processing | completed | failed


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


# ---------------------------------------------------------------------------
# LP 桌面端分区密度图（draw-lp）
# ---------------------------------------------------------------------------
class LightningLpDrawRequest(BaseModel):
    """LP 分区密度图绘制请求。"""
    line_id: str = Field(min_length=1, max_length=64)
    radius_km: float | None = Field(default=None, gt=0.05, le=50.0)


class LightningLpDrawResponse(BaseModel):
    task_id: str
    status: str = "submitted"


# ---------------------------------------------------------------------------
# 关联线路反查（回填关系）
# ---------------------------------------------------------------------------
class LightningLinkedLineSummary(BaseModel):
    """一条地闪分布记录回填过的线路摘要。"""
    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    voltage_kv: float | None = None
    tower_count: int = 0          # 该线路有多少杆塔引用了此分布数据
    prepared_at: str | None = None   # 最近一次回填时间


class LightningLinkedLinesResponse(BaseModel):
    items: list[LightningLinkedLineSummary]
    total: int


class LightningCurrentBackfillTaskSummary(BaseModel):
    id: str
    line_id: str
    line_name: str | None
    prepared_at: datetime
    prepared_by: str | None
    current_a: float | None
    current_b: float | None
    peak_max: float | None
    peak_min: float | None
    sampled_event_count: int
    updated_tower_count: int
    created_profile_count: int
    warnings: list[str]
    region_id: str | None
    is_synthetic: bool
    status: str = "pending"
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None


class LightningCurrentBackfillTaskListResponse(BaseModel):
    items: list[LightningCurrentBackfillTaskSummary]
    total: int


class LightningCurrentBackfillTowerDetail(BaseModel):
    tower_id: str
    tower_no: str | None
    action: str
    previous_current_a: float | None
    previous_current_b: float | None
    current_a: float | None
    current_b: float | None
    delta_a: float | None
    delta_b: float | None


class LightningCurrentBackfillTaskDetail(BaseModel):
    task: LightningCurrentBackfillTaskSummary
    towers: list[LightningCurrentBackfillTowerDetail]
