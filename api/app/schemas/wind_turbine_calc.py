from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WindTurbineCalcCreateRequest(BaseModel):
    name: str = ""
    hub_height: float = 105.5
    receptor_radii: list[float] = Field(default_factory=lambda: [53.6, 63.6, 73.6, 78.6, 82.6])
    blade_length: float | None = None  # 缺省取 max(receptor_radii)
    start_current: float = 1.0
    angle_list: list[float] = Field(
        default_factory=lambda: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
    )

    @field_validator("receptor_radii")
    @classmethod
    def _check_radii(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("接闪器径向位置 r_list 不能为空")
        if any(r <= 0 for r in v):
            raise ValueError("接闪器径向位置必须为正数")
        if any(b <= a for a, b in zip(v, v[1:])):
            raise ValueError("接闪器径向位置必须严格递增")
        return v

    @field_validator("angle_list")
    @classmethod
    def _check_angles(cls, v: list[float]) -> list[float]:
        if not v:
            raise ValueError("旋转角列表不能为空")
        if len(v) > 36:
            raise ValueError("旋转角数量不能超过 36")
        return v

    @field_validator("hub_height")
    @classmethod
    def _check_h(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("轮毂高度 h 必须大于 0")
        return v

    @field_validator("start_current")
    @classmethod
    def _check_ic(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("起始雷电流 Ic 必须大于 0")
        return v


class WindTurbineCalcCreateResponse(BaseModel):
    job_id: str
    task_id: str | None = None
    status: str = "processing"


class WindTurbineCalcJobSummary(BaseModel):
    id: str
    name: str = ""
    hub_height: float = 0.0
    receptor_radii: list[float] = Field(default_factory=list)
    blade_length: float = 0.0
    start_current: float = 0.0
    angle_list: list[float] = Field(default_factory=list)
    angle_count: int = 0
    engine_module: str = "wind_turbine_calc"
    engine_version_hash: str | None = None
    engine_version_tag: str | None = None
    runtime_version: str | None = None
    status: str = "pending"
    stage: str = "preparing"
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    mean_failure_rate: float | None = None
    min_failure_rate: float | None = None
    max_failure_rate: float | None = None
    create_user: str | None = None
    create_date: datetime | None = None


class WindTurbineCalcJobListResponse(BaseModel):
    total: int = 0
    items: list[WindTurbineCalcJobSummary] = Field(default_factory=list)


class WindTurbineCalcJobDetail(WindTurbineCalcJobSummary):
    min_failure_rate_theta: float | None = None
    max_failure_rate_theta: float | None = None
    chart_object_key: str | None = None
    csv_object_key: str | None = None
    update_date: datetime | None = None


class WindTurbineCalcResultRow(BaseModel):
    theta_deg: float
    failure_rate: float
    failure_rate_pct: float


class WindTurbineCalcResultListResponse(BaseModel):
    total: int = 0
    items: list[WindTurbineCalcResultRow] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class WindTurbineCalcEngineInfo(BaseModel):
    module_slug: str = "wind_turbine_calc"
    configured_dir: str = ""
    compiled_dir_exists: bool = False
    exe_name: str = ""
    exe_exists: bool = False
    launch_script: str = ""
    launch_script_exists: bool = False
    runtime_version: str | None = None
    active_version_hash: str | None = None
    active_version_tag: str | None = None
    message: str | None = None


class WindTurbineCalcCancelResponse(BaseModel):
    job_id: str
    status: str
