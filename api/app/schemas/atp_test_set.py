"""ATP 测试集（test set）schemas。

测试集管理：把 ATP 模型的仿真测试用例组织成集合（普通计算/同跳计算），
支持一键批量执行（复用单模型测试管线）与跨执行回归对比。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AtpTestSetStatus = Literal["enabled", "disabled"]
AtpTestJobKind = Literal["normal", "tongtiao"]
AtpTestSetRunStatus = Literal["pending", "running", "success", "failed"]


# ─────────────────────────── 测试集 ───────────────────────────


class AtpTestSetSummary(BaseModel):
    id: str
    name: str
    description: str
    status: AtpTestSetStatus
    tags_json: list[str] = Field(default_factory=list)
    case_count: int = 0
    enabled_case_count: int = 0
    last_run: dict[str, Any] | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class AtpTestSetListResponse(BaseModel):
    items: list[AtpTestSetSummary]
    total: int


class AtpTestSetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=8000)
    status: AtpTestSetStatus = "enabled"
    tags_json: list[str] = Field(default_factory=list)


class AtpTestSetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    status: AtpTestSetStatus | None = None
    tags_json: list[str] | None = None


# ─────────────────────────── 测试用例 ───────────────────────────


class AtpTestSetCaseSummary(BaseModel):
    id: str
    set_id: str
    asset_id: str
    asset_code: str = ""
    asset_name: str = ""
    voltage_level: str | None = None
    tower_type: str | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    job_kind: AtpTestJobKind = "normal"
    name: str = ""
    description: str = ""
    params_json: dict[str, Any] = Field(default_factory=dict)
    expected_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int = 0
    create_date: datetime
    update_date: datetime


class AtpTestSetCaseListResponse(BaseModel):
    items: list[AtpTestSetCaseSummary]
    total: int


class AtpTestSetCaseCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1, max_length=32)
    job_kind: AtpTestJobKind = "normal"
    name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=8000)
    params_json: dict[str, Any] = Field(default_factory=dict)
    expected_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int | None = None


class AtpTestSetCaseUpdateRequest(BaseModel):
    asset_id: str | None = Field(default=None, min_length=1, max_length=32)
    job_kind: AtpTestJobKind | None = None
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    params_json: dict[str, Any] | None = None
    expected_json: dict[str, Any] | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class AtpTestSetCaseReorderRequest(BaseModel):
    # 新顺序的用例 id 列表（其余用例按原 sort_order 跟在其后）
    case_ids: list[str] = Field(default_factory=list, max_length=2000)


# ─────────────────────────── 测试集执行 ───────────────────────────


class AtpTestSetRunItem(BaseModel):
    """一次测试集执行里单个用例的运行摘要（从 atp_asset_run 聚合）。"""

    run_id: str
    case_id: str
    case_name: str = ""
    asset_id: str
    asset_code: str
    asset_name: str
    voltage_level: str | None = None
    tower_type: str | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    job_kind: AtpTestJobKind = "normal"
    status: str
    duration_ms: int | None = None
    error_message: str | None = None
    flashover_count: int | None = None
    flashover_phases: list[str] = Field(default_factory=list)
    current_ka: float | None = None
    result_summary_json: dict[str, Any] = Field(default_factory=dict)
    # 回归对比（与上一执行同用例）：None = 无上一执行
    previous: dict[str, Any] | None = None


class AtpTestSetRunReport(BaseModel):
    overall_pass_rate: float = 0
    counts: dict[str, int] = Field(default_factory=dict)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    failure_reasons_top: list[dict[str, Any]] = Field(default_factory=list)
    # 回归统计：{"counts": {first_run/unchanged/changed/regressed/improved/flashover_changed}}
    regression: dict[str, Any] = Field(default_factory=dict)


class AtpTestSetRunSummary(BaseModel):
    run_id: str
    set_id: str
    set_name: str = ""
    status: AtpTestSetRunStatus
    batch_marker: str | None = None
    total_cases: int = 0
    counts: dict[str, int] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    create_user: str | None = None
    create_date: datetime
    update_date: datetime | None = None
    report: AtpTestSetRunReport | None = None
    items: list[AtpTestSetRunItem] = Field(default_factory=list)
    # 是否有更早一次执行（用于「对比上次执行」提示）
    has_previous_run: bool = False


class AtpTestSetRunListResponse(BaseModel):
    total: int = 0
    items: list[AtpTestSetRunSummary] = Field(default_factory=list)


class AtpTestSetExecuteRequest(BaseModel):
    """执行测试集：可选只跑指定用例（空 = 全部启用的用例）。"""

    case_ids: list[str] = Field(default_factory=list, max_length=2000)
    timeout_seconds: int | None = Field(default=None, ge=1)
    dry_run: bool = False


class AtpTestSetExecuteResponse(BaseModel):
    run_id: str
    set_id: str
    batch_marker: str
    status: str = "running"
    total_cases: int = 0
    launched: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)