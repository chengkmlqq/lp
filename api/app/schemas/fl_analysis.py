from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


FlAnalysisJobType = Literal["normal", "tongtiao", "risk", "mitigation", "report", "scenario"]
FlAnalysisJobStatus = Literal["pending", "queued", "running", "blocked", "success", "failed"]
FlAnalysisRunStatus = Literal["pending", "running", "blocked", "success", "failed"]
FlAnalysisAdapter = Literal["placeholder", "wine", "atp", "legacy_atp", "custom"]
FlAnalysisCurrentWaveform = Literal["heidler", "double_slope", "double_exponential"]
FlAnalysisFlashoverMethod = Literal["guideline", "intersection", "leader_development"]
FlAnalysisAltitudeCorrection = Literal["none", "formula1", "formula2"]
FlAnalysisInducedVoltageFormula = Literal["formula1", "formula2"]


class FlAnalysisWaveformExecutionOptions(BaseModel):
    current_waveform: FlAnalysisCurrentWaveform = "heidler"
    flashover_method: FlAnalysisFlashoverMethod = "intersection"
    altitude_correction: FlAnalysisAltitudeCorrection = "none"
    induced_voltage_formula: FlAnalysisInducedVoltageFormula = "formula1"
    head_time_min_us: float = 2.6
    head_time_max_us: float = 2.6
    head_time_step_us: float = 0.1
    tail_time_min_us: float = 50.0
    tail_time_max_us: float = 50.0
    tail_time_step_us: float = 1.0


class FlAnalysisRunSummary(BaseModel):
    id: str
    job_id: str
    status: FlAnalysisRunStatus
    runner_kind: FlAnalysisAdapter | str
    engine_command: str | None = None
    working_dir: str | None = None
    error_message: str | None = None
    snapshot_tower_count: int = 0
    result_tower_count: int = 0
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class FlAnalysisJobSummary(BaseModel):
    id: str
    line_id: str
    line_code: str | None = None
    line_name: str | None = None
    job_name: str | None = None
    job_type: FlAnalysisJobType | str
    source_kind: str
    status: FlAnalysisJobStatus | str
    task_id: str | None = None
    latest_run_id: str | None = None
    total_tower_count: int = 0
    snapshotted_tower_count: int = 0
    result_tower_count: int = 0
    external_adapter: FlAnalysisAdapter | str
    adapter_config_json: dict[str, Any] = Field(default_factory=dict)
    execution_options_json: dict[str, Any] = Field(default_factory=dict)
    result_summary_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class FlAnalysisJobDetail(FlAnalysisJobSummary):
    runs: list[FlAnalysisRunSummary] = Field(default_factory=list)


class FlAnalysisJobListResponse(BaseModel):
    items: list[FlAnalysisJobSummary]
    total: int


class FlAnalysisJobCreateRequest(BaseModel):
    line_id: str = Field(min_length=1, max_length=64)
    job_name: str | None = Field(default=None, min_length=1, max_length=255)
    job_type: FlAnalysisJobType = "normal"
    external_adapter: FlAnalysisAdapter = "placeholder"
    adapter_config_json: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "normal/tongtiao 任务在 external_adapter=atp/wine 时可传 model_id、version_id/version_no、"
            "result_file、parameter_bindings 等 ATP 执行配置；"
            "external_adapter=legacy_atp 时可传 model_root、template_id/template_subdir、calculation_mode、"
            "use_egm、feature_bindings、result_file 等旧 ATP/EGM 资产配置。"
        ),
    )
    execution_options_json: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "normal/tongtiao 任务可传波形、闪络判据以及波头/波尾扫描参数；"
            "mitigation 任务可传 source_job_id、selected_tower_ids、non_construction；"
            "scenario 任务可传 source_job_id、base_job_id、selected_tower_ids；"
            "report 任务可传 source_job_id、selected_tower_ids。"
        ),
    )


class FlAnalysisJobCreateResponse(BaseModel):
    job: FlAnalysisJobDetail


class FlAnalysisJobStartResponse(BaseModel):
    job: FlAnalysisJobDetail
    queued: bool = True


class FlAnalysisTowerResultSummary(BaseModel):
    id: str
    job_id: str
    run_id: str
    snapshot_id: str
    tower_id: str
    seq_no: int
    tower_no: str
    tower_model: str | None = None
    tower_type: str | None = None
    status: str
    risk_level: str | None = None
    summary_text: str | None = None
    result_json: dict[str, Any] = Field(default_factory=dict)
    create_date: datetime
    update_date: datetime


class FlAnalysisTowerResultListResponse(BaseModel):
    items: list[FlAnalysisTowerResultSummary]
    total: int
