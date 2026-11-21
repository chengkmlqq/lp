from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

YearsSource = Literal["auto", "fixed"]


class WindLightningDensityImportResponse(BaseModel):
    batch_id: str
    task_id: str | None = None
    status: str = "processing"
    # 后端生成的真实批次名（前端详情 Tab 标题用此值，不用本地草稿名）
    batch_name: str = ""


class WindLightningDensityPreviewResponse(BaseModel):
    """新建抽屉的提交前预览：bbox、预估网格数、可解析行数。"""

    turbine_count: int = 0
    turbine_skipped: int = 0
    total_records: int = 0
    valid_records: int = 0
    skipped_records: int = 0
    in_range_records: int = 0
    bbox_min_lon: float | None = None
    bbox_max_lon: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lat: float | None = None
    grid_x_count: int = 0
    grid_y_count: int = 0
    area_km2: float | None = None
    data_years: float | None = None
    years_source: str = "auto"
    detected_years: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WindLightningDensityBatchSummary(BaseModel):
    id: str
    batch_name: str = ""
    wind_farm_name: str | None = None
    notes: str | None = None

    status: str = "pending"
    stage: str = "parsing"
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None

    turbine_count: int = 0
    total_records: int = 0
    valid_records: int = 0
    skipped_records: int = 0

    data_years: float | None = None
    years_source: str = "auto"
    overall_density: float | None = None
    peak_density: float | None = None
    area_km2: float | None = None
    grid_x_count: int = 0
    grid_y_count: int = 0

    has_image: bool = False
    create_date: datetime | None = None
    update_date: datetime | None = None
    create_user: str | None = None


class WindLightningDensityBatchListResponse(BaseModel):
    total: int = 0
    items: list[WindLightningDensityBatchSummary] = Field(default_factory=list)


class WindLightningDensityCoreGrid(BaseModel):
    start_lon: float
    start_lat: float
    x_count: int
    y_count: int
    step_deg: float


class WindLightningDensityBatchDetail(WindLightningDensityBatchSummary):
    turbine_source_file_name: str = ""
    lightning_source_file_name: str = ""

    grid_step_deg: float = 0.01
    margin_deg: float = 0.01

    bbox_min_lon: float | None = None
    bbox_max_lon: float | None = None
    bbox_min_lat: float | None = None
    bbox_max_lat: float | None = None

    peak_lon: float | None = None
    peak_lat: float | None = None
    stats_json: dict[str, Any] | None = None
    core_grid: WindLightningDensityCoreGrid | None = None
    cell_rows_stored: int = 0


class WindLightningDensityCellRow(BaseModel):
    cell_i: int
    cell_j: int
    center_lon: float
    center_lat: float
    min_lon: float
    max_lon: float
    min_lat: float
    max_lat: float
    strike_count: int
    density_per_cell_year: float
    density_per_km2_year: float
    turbine_count: int


class WindLightningDensityCellListResponse(BaseModel):
    total: int = 0
    items: list[WindLightningDensityCellRow] = Field(default_factory=list)


class WindLightningDensityTurbineRow(BaseModel):
    seq: int
    turbine_no: str | None = None
    lon: float
    lat: float
    cell_i: int
    cell_j: int
    cell_density: float


class WindLightningDensityTurbineListResponse(BaseModel):
    total: int = 0
    items: list[WindLightningDensityTurbineRow] = Field(default_factory=list)
