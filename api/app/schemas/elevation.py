from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ElevationStatus = Literal["active", "disabled"]
ElevationTerrainStatus = Literal["pending", "processing", "ready", "failed", "not_supported"]
ElevationApplyMode = Literal["fill_null_only", "overwrite_all"]
ElevationApplyJobStatus = Literal["pending", "running", "success", "failed"]


class ElevationFileRecordSummary(BaseModel):
    id: str
    file_name: str
    file_path: str
    file_format: str
    file_size: int
    source: str | None = None
    mount_code: str
    resolution_m: float | None = None
    status: ElevationStatus
    data_source_type: str = "generic"
    linked_line_count: int = 0
    bbox_min_lon: float | None = None
    bbox_max_lon: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lat: float | None = None
    sample_count: int = 0
    analysis_task_id: str | None = None
    analysis_status: str = "not_started"
    analysis_error_message: str | None = None
    analysis_started_at: datetime | None = None
    analysis_finished_at: datetime | None = None
    terrain_status: ElevationTerrainStatus = "not_supported"
    terrain_task_id: str | None = None
    terrain_error_message: str | None = None
    terrain_root_path: str | None = None
    terrain_url_template: str | None = None
    terrain_min_zoom: int | None = None
    terrain_max_zoom: int | None = None
    terrain_bounds: dict[str, Any] | None = None
    terrain_metadata: dict[str, Any] | None = None
    notes: str | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class ElevationFileRecordListResponse(BaseModel):
    items: list[ElevationFileRecordSummary]
    total: int


class ElevationFileRecordCreateRequest(BaseModel):
    source: str | None = Field(default=None, max_length=512)
    mount_code: str | None = Field(default=None, min_length=2, max_length=64)
    resolution_m: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("source", "mount_code", "notes", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class ElevationFileRecordUpdateRequest(BaseModel):
    source: str | None = Field(default=None, max_length=512)
    resolution_m: float | None = Field(default=None, gt=0)
    status: ElevationStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)
    terrain_url_template: str | None = Field(default=None, max_length=1024)

    @field_validator("source", "notes", "terrain_url_template", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class ElevationFileRecordAnalyzeResponse(BaseModel):
    record: ElevationFileRecordSummary
    task_id: str | None = None
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ElevationFileRecordTerrainBuildResponse(BaseModel):
    record: ElevationFileRecordSummary
    task_id: str | None = None
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ElevationFileRecordUploadResponse(BaseModel):
    record: ElevationFileRecordSummary
    detail: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ElevationTempUploadResponse(BaseModel):
    """选择文件后立即上传到临时目录，返回 temp_file_id 供确认提交时引用。"""

    temp_file_id: str
    file_name: str


class ElevationPreviewPoint(BaseModel):
    longitude: float
    latitude: float
    altitude_m: float


class ElevationPreviewCell(BaseModel):
    min_longitude: float
    max_longitude: float
    min_latitude: float
    max_latitude: float
    altitude_m: float


class ElevationPreviewDiagnostics(BaseModel):
    source_crs: str | None = None
    source_bounds_min_x: float | None = None
    source_bounds_max_x: float | None = None
    source_bounds_min_y: float | None = None
    source_bounds_max_y: float | None = None
    wgs84_bounds_min_lon: float | None = None
    wgs84_bounds_max_lon: float | None = None
    wgs84_bounds_min_lat: float | None = None
    wgs84_bounds_max_lat: float | None = None
    raster_width: int | None = None
    raster_height: int | None = None
    target_samples: int | None = None
    sampling_step: int | None = None
    scanned_candidates: int | None = None
    valid_preview_count: int | None = None
    skip_read_error: int = 0
    skip_masked: int = 0
    skip_nodata: int = 0
    skip_nonfinite: int = 0
    skip_sample_transform_error: int = 0
    sample_tx_first_error: str | None = None
    skip_sample_out_of_range: int = 0
    skip_cell_transform_error: int = 0
    skip_cell_out_of_range: int = 0


class ElevationFileRecordPreviewResponse(BaseModel):
    record: ElevationFileRecordSummary
    preview_mode: Literal["point_cloud", "terrain_grid"]
    total_points: int
    sampled_points: int
    points: list[ElevationPreviewPoint] = Field(default_factory=list)
    cells: list[ElevationPreviewCell] = Field(default_factory=list)
    diagnostics: ElevationPreviewDiagnostics | None = None
    warnings: list[str] = Field(default_factory=list)


class ElevationFileRecordTaskStatusResponse(BaseModel):
    record_id: str
    file_name: str
    task_id: str | None = None
    status: Literal["queued", "running", "success", "failed", "unknown", "not_found"] = "not_found"
    detail: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    update_date: datetime | None = None


class ElevationFileRecordTerrainTaskStatusResponse(BaseModel):
    record_id: str
    file_name: str
    task_id: str | None = None
    status: Literal["queued", "running", "success", "failed", "unknown", "not_found"] = "not_found"
    detail: str | None = None
    terrain_url_template: str | None = None
    terrain_min_zoom: int | None = None
    terrain_max_zoom: int | None = None
    update_date: datetime | None = None


class ElevationTerrainLayerResponse(BaseModel):
    tilejson: str = "2.1.0"
    format: str = "heightmap-1.0"
    version: str = "1.0.0"
    scheme: Literal["tms"] = "tms"
    projection: Literal["EPSG:4326"] = "EPSG:4326"
    tiles: list[str]
    minzoom: int
    maxzoom: int
    extensions: list[str] = Field(default_factory=list)
    attribution: str | None = None
    bounds: list[float] | None = None
    available: list[list[dict[str, int]]] | None = None


class ElevationApplyJobSummary(BaseModel):
    id: str
    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    file_record_id: str | None = None
    file_record_name: str | None = None
    mode: ElevationApplyMode
    status: ElevationApplyJobStatus
    task_id: str | None = None
    total_tower_count: int = 0
    updated_tower_count: int = 0
    skipped_tower_count: int = 0
    missing_geo_count: int = 0
    unmatched_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    create_date: datetime
    create_user: str | None = None
    create_user_name: str | None = None
    update_date: datetime
    update_user: str | None = None


class ElevationApplyJobListResponse(BaseModel):
    items: list[ElevationApplyJobSummary]
    total: int


class ElevationApplyJobTowerDetail(BaseModel):
    """一次高程回填任务中单个杆塔的回填数据明细快照。"""

    id: str
    job_id: str
    tower_id: str
    tower_no: str | None = None
    seq_no: int | None = None
    longitude: float | None = None
    latitude: float | None = None
    # updated=已更新 / skipped=已跳过 / missing_geo=缺坐标 / unmatched=未命中
    action: str = "updated"
    altitude_before_m: float | None = None
    altitude_after_m: float | None = None
    slope_1_before: float | None = None
    slope_1_after: float | None = None
    slope_2_before: float | None = None
    slope_2_after: float | None = None
    create_date: datetime


class ElevationApplyJobTowerListResponse(BaseModel):
    items: list[ElevationApplyJobTowerDetail]
    total: int


class ElevationLinkedLineSummary(BaseModel):
    """高程文件回填过的关联线路摘要（按线路聚合取最近一次回填任务）。"""

    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    voltage_kv: float | None = None
    apply_status: str          # 最近一次回填任务状态
    tower_count: int = 0       # 该线路回填任务涉及的杆塔数（total_tower_count）
    updated_tower_count: int = 0  # 实际更新杆塔数
    applied_at: datetime | None = None  # 最近回填时间（finished_at）


class ElevationLinkedLineListResponse(BaseModel):
    items: list[ElevationLinkedLineSummary]
    total: int


class ElevationApplyJobCreateRequest(BaseModel):
    line_id: str = Field(min_length=1, max_length=64)
    file_record_id: str | None = Field(default=None, min_length=1, max_length=64)
    mode: ElevationApplyMode = "fill_null_only"


class ElevationApplyJobCreateResponse(BaseModel):
    job: ElevationApplyJobSummary
    queued: bool = True


class ElevationDatasetSummary(BaseModel):
    id: str
    code: str
    name: str
    source: str | None = None
    file_format: str
    mount_code: str
    dataset_dir: str = ""
    file_path: str
    resolution_m: float | None = None
    status: ElevationStatus
    usage_status: str = "idle"
    sample_count: int = 0
    bbox_min_lon: float | None = None
    bbox_max_lon: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lat: float | None = None
    analysis_task_id: str | None = None
    analysis_status: str = "not_started"
    analysis_error_message: str | None = None
    analysis_started_at: datetime | None = None
    analysis_finished_at: datetime | None = None
    terrain_status: ElevationTerrainStatus = "not_supported"
    terrain_task_id: str | None = None
    terrain_error_message: str | None = None
    terrain_root_path: str | None = None
    terrain_url_template: str | None = None
    terrain_min_zoom: int | None = None
    terrain_max_zoom: int | None = None
    terrain_bounds: dict[str, Any] | None = None
    terrain_metadata: dict[str, Any] | None = None
    notes: str | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class ElevationDatasetListResponse(BaseModel):
    items: list[ElevationDatasetSummary]
    total: int


class ElevationBackfillCoverageLine(BaseModel):
    """一条候选线路对当前高程文件的可回填覆盖统计（逐塔预检）。"""

    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    voltage_kv: int | None = None
    total_tower_count: int = 0
    matchable_tower_count: int = 0


class ElevationBackfillCoverageResponse(BaseModel):
    file_record_id: str
    items: list[ElevationBackfillCoverageLine]
    total: int
