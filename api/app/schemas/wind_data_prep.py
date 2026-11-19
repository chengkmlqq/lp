from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TerrainMode = Literal["zero", "tif"]


class WindDataPrepImportResponse(BaseModel):
    batch_id: str
    task_id: str | None = None
    status: str = "processing"


class WindDataPrepPreviewResponse(BaseModel):
    """提交前预览：统计摘要、校验报告、P0.abc 头部与五文件行数（不落库）。"""

    turbine_count: int = 0
    lightning_total: int = 0
    lightning_valid: int = 0
    lightning_in_scope: int = 0
    nonzero_cell_count: int = 0
    nl_max: float | None = None
    nl_min: float | None = None
    nl_avg: float | None = None
    time_span: str = ""
    type_distribution: dict[str, int] = Field(default_factory=dict)
    report: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    p0abc_header: dict[str, Any] = Field(default_factory=dict)
    file_lines: dict[str, int] = Field(default_factory=dict)
    file_sizes: dict[str, int] = Field(default_factory=dict)


class WindDataPrepBatchSummary(BaseModel):
    id: str
    name: str = ""
    wind_farm_name: str | None = None
    remark: str | None = None

    start_lon: float = 0.0
    start_lat: float = 0.0
    grid_nx: int = 0
    grid_ny: int = 0
    grid_step_deg: float = 0.01
    risk_base_s: float = 0.0
    data_years: int = 6
    terrain_mode: str = "zero"

    turbine_count: int = 0
    lightning_total: int = 0
    lightning_valid: int = 0
    lightning_in_scope: int = 0

    status: str = "pending"
    stage: str = "parsing"
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None

    files_ready: int = 0
    has_report: bool = False
    create_date: datetime | None = None
    update_date: datetime | None = None
    create_user: str | None = None


class WindDataPrepBatchListResponse(BaseModel):
    total: int = 0
    items: list[WindDataPrepBatchSummary] = Field(default_factory=list)


class WindDataPrepBatchDetail(WindDataPrepBatchSummary):
    turbine_file_name: str = ""
    lightning_file_name: str = ""
    terrain_file_name: str | None = None

    nonzero_cell_count: int = 0
    zero_nl_turbine_count: int = 0
    nl_max: float | None = None
    nl_min: float | None = None
    nl_avg: float | None = None
    report_json: dict[str, Any] | None = None
    stats_json: dict[str, Any] | None = None
    p0abc_header: dict[str, Any] = Field(default_factory=dict)


class WindDataPrepTurbineRow(BaseModel):
    seq: int
    turbine_no: str | None = None
    lon: float
    lat: float
    cell_i: int
    cell_j: int
    grid_id: int
    flash_count: int
    flash_count_east: int
    nl: float
    density_per_km2_year: float | None = None
    height: float | None = None
    blade: float | None = None
    motion: int | None = None
    circuit: int | None = None


class WindDataPrepTurbineListResponse(BaseModel):
    total: int = 0
    items: list[WindDataPrepTurbineRow] = Field(default_factory=list)
