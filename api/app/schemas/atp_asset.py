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


class AtpAssetTreeChild(BaseModel):
    """维度树懒加载节点：一层维度下的一个去重值（电压/塔型/场景/避雷器组合）。"""

    key: str  # 完整路径 key，如 "vl:110|tw:鼓型塔"（点击展开时回传）
    code: str  # 该层维度值（原始 code，如 "guxing"）
    label: str  # 展示名（维度项中文名，缺失回落 code）
    count: int  # 该路径下资产数
    has_children: bool  # 是否还有下一层（非最后一维且有更深维度资产）
    children: list["AtpAssetTreeChild"] = Field(default_factory=list)  # 搜索模式嵌套树（懒加载模式为空）


class AtpAssetTreeChildrenResponse(BaseModel):
    items: list[AtpAssetTreeChild]


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
    # 操作人可读名（username 映射），前端「操作人」列展示；无则回落 create_user
    create_user_name: str | None = None
    # 测试运行的结果摘要（requested_stages / stages 判据 / compare.params_source 等）：
    # 用于列表进度条回显与参数来源列；详情接口同样返回
    result_summary_json: dict[str, Any] = Field(default_factory=dict)


class AtpAssetRunDetail(AtpAssetRunSummary):
    stdout_text: str | None = None
    stderr_text: str | None = None
    output_manifest_json: dict[str, Any] = Field(default_factory=dict)


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
    # 从线路杆塔选择：由后端按塔组装 base_tower/profile（与「参数试算」同口径），
    # 优先级高于显式传入的 base_tower/profile
    line_tower_id: str | None = None
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


class AtpBatchTestRunRequest(BaseModel):
    """ATP 资产「批量测试」请求：同一组测试参数应用到多个资产。"""

    asset_ids: list[str] = Field(min_length=1, max_length=200)
    # 公共测试参数（与单测 AtpAssetTestRunRequest 同语义）
    stages: list[AtpAssetTestStage] = Field(
        default_factory=lambda: ["materialize", "geometry", "simulate"]
    )
    tower_kind: str | None = None
    tower_no: str | None = None
    voltage_kv: int | None = None
    scene: str | None = None
    line_tower_id: str | None = None
    base_tower: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    execution_options: dict[str, Any] = Field(default_factory=dict)
    params_raw: str | None = None
    current_ka: float | None = Field(default=31.0, gt=0)
    timeout_seconds: int | None = Field(default=600, ge=1)
    dry_run: bool = False
    params_source: AtpAssetTestParamsSource = "template"
    allow_incomplete_defaults: bool = False


class AtpBatchTestRunItem(BaseModel):
    """批量测试中单个资产的运行摘要（含资产维度信息，便于报告分组）。"""

    run_id: str
    asset_id: str
    asset_code: str
    asset_name: str
    voltage_level: str | None = None
    tower_type: str | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    status: AtpAssetRunStatus
    duration_ms: int | None = None
    error_message: str | None = None
    result_summary_json: dict[str, Any] = Field(default_factory=dict)


class AtpBatchTestRunSummary(BaseModel):
    """批量测试的总体进度与报告。"""

    batch_id: str
    total: int
    pending: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0
    # 总报告：按电压/塔型/场景分组的通过率与闪络相数等
    report: dict[str, Any] = Field(default_factory=dict)
    items: list[AtpBatchTestRunItem] = Field(default_factory=list)