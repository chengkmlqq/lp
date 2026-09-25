from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AtpAssetStatus = Literal["draft", "enabled", "disabled", "archived"]
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
    voltage_level_label: str | None = None
    tower_type: str | None = None
    tower_type_label: str | None = None
    scene_type: str | None = None
    scene_type_label: str | None = None
    arrester_config: str | None = None
    arrester_config_label: str | None = None
    storage_mount_code: str | None = None
    storage_root_path: str | None = None
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


class AtpAssetFileEntry(BaseModel):
    relative_path: str
    name: str
    is_dir: bool
    size: int = 0
    mime_type: str | None = None
    file_role: str | None = None
    modified_at: str | None = None


class AtpAssetFileListResponse(BaseModel):
    asset_id: str
    storage_mount_code: str
    storage_root_path: str
    items: list[AtpAssetFileEntry]
    total: int


class AtpAssetFileContentResponse(BaseModel):
    asset_id: str
    relative_path: str
    name: str
    size: int
    mime_type: str | None = None
    content_type: str  # "text" | "binary" | "not-found"
    content: str = ""  # text 时为请求行范围内的内容(UTF-8);binary 时为空
    preview_lines: list[str] = []  # text 前 N 行,供前端快速渲染
    # 懒加载分页：offset/limit 请求的行切片 + 总行数，前端滚动追加读取全文
    offset: int = 0
    limit: int = 0
    total_lines: int = 0
    has_more: bool = False


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


AtpAssetTestStage = Literal["materialize", "geometry", "simulate", "all"]
AtpAssetTestParamsSource = Literal["template", "tower"]


class AtpAssetTestRunRequest(BaseModel):
    """ATP 资产「单模型测试」请求。

    分段：``materialize``（物化 + 引擎文件）→ ``geometry``（DAT→LIB）→
    ``simulate``（单次 ATP）。请求子集时依赖段会自动补齐
    （simulate ⇒ geometry ⇒ materialize），产物记录里会区分「请求的段」。

    对拍口径（必须显式给，禁止各自默认）：
    ``current_ka`` 固定雷电流、``base_tower``/``profile`` 参数来源、
    ``params_raw`` 与 C# harness 原样对照的输入串。
    """

    stages: list[AtpAssetTestStage] = Field(
        default_factory=lambda: ["materialize", "geometry", "simulate"]
    )
    tower_kind: str | None = None
    tower_no: str | None = None
    voltage_kv: int | None = None
    scene: str | None = None
    base_tower: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    execution_options: dict[str, Any] = Field(default_factory=dict)
    params_raw: str | None = None
    current_ka: float | None = Field(default=31.0, gt=0)
    timeout_seconds: int | None = Field(default=600, ge=1)
    dry_run: bool = False
    # 参数来源：template = 无杆塔（资产维度 + 参数模板默认值，默认）；tower = 用传入的杆塔数据
    params_source: AtpAssetTestParamsSource = "template"
    # 模板默认值不完整时是否仍继续（默认 False → 显式报错，禁止静默算无意义结果）
    allow_incomplete_defaults: bool = False