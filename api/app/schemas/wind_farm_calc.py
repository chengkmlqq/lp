from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WindFarmCalcPrepBatchOption(BaseModel):
    """新建计算时可选的已完成数据准备批次摘要。"""

    id: str
    name: str = ""
    wind_farm_name: str | None = None
    turbine_count: int = 0
    grid_nx: int = 0
    grid_ny: int = 0
    risk_base_s: float = 0.0
    files_ready: int = 0
    create_date: datetime | None = None


class WindFarmCalcPrepBatchOptions(BaseModel):
    items: list[WindFarmCalcPrepBatchOption] = Field(default_factory=list)


class WindFarmCalcCreateRequest(BaseModel):
    prep_batch_id: str
    name: str = ""


class WindFarmCalcCreateResponse(BaseModel):
    job_id: str
    task_id: str | None = None
    status: str = "processing"


class WindFarmCalcJobSummary(BaseModel):
    id: str
    name: str = ""
    prep_batch_id: str = ""
    status: str = "pending"
    stage: str = "fetching"
    progress: int = 0
    task_id: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    turbine_count: int = 0
    risk_I_count: int = 0
    risk_II_count: int = 0
    risk_III_count: int = 0
    risk_IV_count: int = 0
    shutdown_count: int = 0
    circuit_shutdown_count: int = 0
    farm_shutdown_count: int = 0
    risk_mismatch_count: int = 0
    create_user: str | None = None
    create_date: datetime | None = None


class WindFarmCalcJobListResponse(BaseModel):
    total: int = 0
    items: list[WindFarmCalcJobSummary] = Field(default_factory=list)


class WindFarmCalcJobDetail(WindFarmCalcJobSummary):
    engine_path: str | None = None
    engine_md5: str | None = None
    stdout_object_key: str | None = None
    output_object_key: str | None = None
    preflight_json: dict[str, Any] | None = None
    update_date: datetime | None = None


class WindFarmCalcResultRow(BaseModel):
    seq: int
    turbine_no: str | None = None
    lon: float = 0.0
    lat: float = 0.0
    value_v: float = 0.0
    risk_level: int = 1
    suggestion_code: int = 1
    suggestion_text: str = "无"
    circuit_no: int | None = None
    raw_line: str | None = None


class WindFarmCalcResultListResponse(BaseModel):
    total: int = 0
    items: list[WindFarmCalcResultRow] = Field(default_factory=list)


class WindFarmCalcEngineInfo(BaseModel):
    """引擎信息拆成两件事：API 侧检查共享卷里的 exe，执行 worker 侧探测 Wine。

    API 容器不装 Wine，因此这里不再有「本机 wine 是否可用」的语义：
    ``engine_exists`` 只表示 exe 在共享卷里存在；``worker_*`` 才代表真实执行环境。
    """

    configured: str = ""
    resolved: str | None = None
    engine_exists: bool = False
    size: int | None = None
    modified_at: datetime | None = None
    md5: str | None = None
    wine_binary: str = "wine"
    worker_online: bool = False
    worker_name: str | None = None
    worker_wine_available: bool = False
    worker_wine_version: str | None = None
    worker_wine_error: str | None = None
    worker_wine_binary: str | None = None
    worker_checked_at: datetime | None = None
    # 探测结果正在刷新（worker 忙或刚提交探测），前端据此显示「探测中」而非「不可用」
    worker_probe_pending: bool = False
    message: str | None = None


class WindFarmCalcCancelResponse(BaseModel):
    job_id: str
    status: str


class WindFarmCalcLogResponse(BaseModel):
    job_id: str
    task_id: str | None = None
    sse_url: str | None = None
    raw_url: str | None = None
