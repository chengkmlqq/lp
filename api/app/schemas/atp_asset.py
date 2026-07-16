from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AtpAssetStatus = Literal["draft", "enabled", "disabled", "archived"]
AtpAssetReleaseStatus = Literal["draft", "released", "archived"]
AtpAssetRunnerKind = Literal["atp", "egm", "hybrid"]
AtpAssetRunStatus = Literal["pending", "running", "success", "failed"]
AtpAssetEngineMode = Literal["wine", "native"]


class AtpAssetSummary(BaseModel):
    id: str
    code: str
    name: str
    description: str
    status: AtpAssetStatus
    voltage_level: str | None = None
    tower_type: str | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    storage_mount_code: str | None = None
    storage_root_path: str | None = None
    latest_release_no: int = 0
    active_release_no: int | None = None
    active_release_id: str | None = None
    active_release_tag: str | None = None
    storage_mount_code: str | None = None
    storage_root_path: str | None = None
    release_count: int = 0
    run_count: int = 0
    last_run_status: AtpAssetRunStatus | None = None
    last_run_date: datetime | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class AtpAssetListResponse(BaseModel):
    items: list[AtpAssetSummary]
    total: int


class AtpAssetDetail(AtpAssetSummary):
    pass


class AtpAssetCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=8000)
    status: AtpAssetStatus = "enabled"
    voltage_level: str | None = Field(default=None, max_length=16)
    tower_type: str | None = Field(default=None, max_length=64)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    storage_mount_code: str | None = Field(default=None, max_length=64)
    storage_root_path: str | None = Field(default=None, max_length=2048)


class AtpAssetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    status: AtpAssetStatus | None = None
    voltage_level: str | None = Field(default=None, max_length=16)
    tower_type: str | None = Field(default=None, max_length=64)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    storage_mount_code: str | None = Field(default=None, max_length=64)
    storage_root_path: str | None = Field(default=None, max_length=2048)


class AtpAssetReleaseSummary(BaseModel):
    id: str
    asset_id: str
    asset_code: str
    asset_name: str
    release_no: int
    release_tag: str | None = None
    status: AtpAssetReleaseStatus
    voltage_level: str
    tower_type: str
    scene_type: str
    scenario_code: str | None = None
    runner_kind: AtpAssetRunnerKind
    storage_mount_code: str
    storage_root_path: str
    entry_file: str | None = None
    result_file: str | None = None
    egm_subdir: str | None = None
    egm_result_file: str | None = None
    preprocess_script: str | None = None
    postprocess_script: str | None = None
    content_hash: str
    is_active: bool
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class AtpAssetReleaseDetail(AtpAssetReleaseSummary):
    manifest_json: dict[str, Any] = Field(default_factory=dict)
    validation_json: dict[str, Any] = Field(default_factory=dict)


class AtpAssetReleaseListResponse(BaseModel):
    items: list[AtpAssetReleaseSummary]
    total: int


class AtpAssetReleaseCreateRequest(BaseModel):
    release_tag: str | None = Field(default=None, max_length=64)
    status: AtpAssetReleaseStatus = "released"
    voltage_level: str = Field(min_length=1, max_length=16)
    tower_type: str = Field(min_length=1, max_length=64)
    scene_type: str = Field(min_length=1, max_length=32)
    scenario_code: str | None = Field(default=None, max_length=64)
    runner_kind: AtpAssetRunnerKind = "atp"
    storage_mount_code: str = Field(default="main", min_length=1, max_length=64)
    storage_root_path: str = Field(min_length=1, max_length=2048)
    entry_file: str | None = Field(default=None, max_length=255)
    result_file: str | None = Field(default=None, max_length=255)
    egm_subdir: str | None = Field(default=None, max_length=255)
    egm_result_file: str | None = Field(default=None, max_length=255)
    preprocess_script: str | None = Field(default=None, max_length=255)
    postprocess_script: str | None = Field(default=None, max_length=255)


class AtpAssetReleaseUpdateRequest(BaseModel):
    release_tag: str | None = Field(default=None, max_length=64)
    status: AtpAssetReleaseStatus | None = None
    voltage_level: str | None = Field(default=None, min_length=1, max_length=16)
    tower_type: str | None = Field(default=None, min_length=1, max_length=64)
    scene_type: str | None = Field(default=None, min_length=1, max_length=32)
    scenario_code: str | None = Field(default=None, max_length=64)
    runner_kind: AtpAssetRunnerKind | None = None
    storage_mount_code: str | None = Field(default=None, min_length=1, max_length=64)
    storage_root_path: str | None = Field(default=None, min_length=1, max_length=2048)
    entry_file: str | None = Field(default=None, max_length=255)
    result_file: str | None = Field(default=None, max_length=255)
    egm_subdir: str | None = Field(default=None, max_length=255)
    egm_result_file: str | None = Field(default=None, max_length=255)
    preprocess_script: str | None = Field(default=None, max_length=255)
    postprocess_script: str | None = Field(default=None, max_length=255)


class AtpAssetFileEntry(BaseModel):
    relative_path: str
    name: str
    is_dir: bool
    size: int = 0
    mime_type: str | None = None
    file_role: str | None = None


class AtpAssetFileListResponse(BaseModel):
    asset_id: str
    release_id: str | None = None
    storage_mount_code: str
    storage_root_path: str
    items: list[AtpAssetFileEntry]
    total: int


class AtpAssetFileUploadResponse(BaseModel):
    asset_id: str
    storage_mount_code: str
    storage_root_path: str
    uploaded_count: int
    success: bool = True


class AtpAssetRunSummary(BaseModel):
    id: str
    asset_id: str
    asset_code: str
    asset_name: str
    release_id: str
    release_no: int
    release_tag: str | None = None
    status: AtpAssetRunStatus
    engine_mode: AtpAssetEngineMode
    runner_kind: AtpAssetRunnerKind
    task_id: str | None = None
    storage_mount_code: str | None = None
    storage_root_path: str | None = None
    materialized_root_path: str | None = None
    engine_command: str | None = None
    working_dir: str | None = None
    timeout_seconds: int
    exit_code: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    stdout_size: int = 0
    stderr_size: int = 0
    create_date: datetime
    create_user: str | None = None


class AtpAssetRunDetail(AtpAssetRunSummary):
    stdout_text: str | None = None
    stderr_text: str | None = None
    output_manifest_json: dict[str, Any] = Field(default_factory=dict)
    result_summary_json: dict[str, Any] = Field(default_factory=dict)


class AtpAssetRunListResponse(BaseModel):
    items: list[AtpAssetRunSummary]
    total: int


class AtpAssetRunRequest(BaseModel):
    timeout_seconds: int | None = Field(default=None, ge=1)
    extra_args: list[str] = Field(default_factory=list, max_length=32)
    environment: dict[str, str] = Field(default_factory=dict, max_length=16)
    dry_run: bool = False


class AtpAssetReleaseUploadResponse(BaseModel):
    task_id: str
    status: str


class AtpEngineStatusResponse(BaseModel):
    mode: AtpAssetEngineMode
    available: bool
    executable_path: str
    resolved_executable: str | None = None
    storage_root: str
    workdir: str
    default_timeout_seconds: int
    max_timeout_seconds: int
    checks: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error: str | None = None
