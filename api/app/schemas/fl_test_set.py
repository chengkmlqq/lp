"""防雷测试集（fl test set）schemas。

集合级分类（category）决定用例形态：
- fl_calc  防雷计算用例：calc_kind(normal/tongtiao) + 表单快照 params_json
           （tower = 编辑杆塔表单字段，execution_options_json = 防雷计算表单字段）
           + 评估标准(expected_json.metrics)；line_id/tower_id 不再由前端提交，
           由后端按快照托管计算载体
- retrofit 防雷改造用例：mode(jianxian/feijianxian) + 前置任务(source_job_id)
           + 参考评估方案(expected_json.plan)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FlTestSetCategory = Literal["fl_calc", "retrofit"]
FlTestCalcKind = Literal["normal", "tongtiao"]
FlTestRetrofitMode = Literal["jianxian", "feijianxian"]
FlTestSetStatus = Literal["enabled", "disabled"]
FlTestRunStatus = Literal["pending", "running", "success", "partial", "failed", "cancelled"]
FlTestRunCaseStatus = Literal["pending", "running", "success", "failed", "skipped", "cancelled"]
FlTestVerdict = Literal["auto_pass", "auto_fail", "pending_manual", "manual_pass", "manual_fail"]


# ─────────────────────────── 测试集 ───────────────────────────


class FlTestSetSummary(BaseModel):
    id: str
    category: FlTestSetCategory = "fl_calc"
    name: str
    description: str = ""
    status: FlTestSetStatus = "enabled"
    tags_json: list[str] = Field(default_factory=list)
    case_count: int = 0
    enabled_case_count: int = 0
    last_run: dict[str, Any] | None = None
    create_date: datetime
    create_user: str | None = None
    update_date: datetime
    update_user: str | None = None


class FlTestSetListResponse(BaseModel):
    items: list[FlTestSetSummary]
    total: int


class FlTestSetCreateRequest(BaseModel):
    category: FlTestSetCategory = "fl_calc"
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=8000)
    status: FlTestSetStatus = "enabled"
    tags_json: list[str] = Field(default_factory=list)


class FlTestSetUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    status: FlTestSetStatus | None = None
    tags_json: list[str] | None = None


# ─────────────────────────── 测试用例 ───────────────────────────


class FlTestCaseSummary(BaseModel):
    id: str
    set_id: str
    name: str = ""
    description: str = ""
    # fl_calc：计算方式 + 系统托管计算载体（FLTC- 线路 + 1 基杆塔）
    calc_kind: FlTestCalcKind | None = None
    line_id: str | None = None
    line_code: str | None = None
    line_name: str | None = None
    tower_id: str | None = None
    tower_no: str | None = None
    params_json: dict[str, Any] = Field(default_factory=dict)
    # retrofit：改造口径 + 前置任务
    mode: FlTestRetrofitMode | None = None
    non_construction: bool = False
    source_job_id: str | None = None
    source_job_name: str | None = None
    source_job_status: str | None = None
    selected_tower_ids: list[str] = Field(default_factory=list)
    # 共用
    expected_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    sort_order: int = 0
    create_date: datetime
    update_date: datetime


class FlTestCaseListResponse(BaseModel):
    items: list[FlTestCaseSummary]
    total: int


class FlTestCaseCreateRequest(BaseModel):
    name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=8000)
    # fl_calc
    calc_kind: FlTestCalcKind | None = None
    line_id: str | None = Field(default=None, max_length=32)
    tower_id: str | None = Field(default=None, max_length=32)
    params_json: dict[str, Any] = Field(default_factory=dict)
    # retrofit
    mode: FlTestRetrofitMode | None = None
    source_job_id: str | None = Field(default=None, max_length=32)
    selected_tower_ids: list[str] = Field(default_factory=list)
    # 共用
    expected_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class FlTestCaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=8000)
    calc_kind: FlTestCalcKind | None = None
    line_id: str | None = Field(default=None, max_length=32)
    tower_id: str | None = Field(default=None, max_length=32)
    params_json: dict[str, Any] | None = None
    mode: FlTestRetrofitMode | None = None
    source_job_id: str | None = Field(default=None, max_length=32)
    selected_tower_ids: list[str] | None = None
    expected_json: dict[str, Any] | None = None
    enabled: bool | None = None


# ─────────────────────────── 执行（run） ───────────────────────────


class FlTestRunCreateRequest(BaseModel):
    """批量发起：case_ids 缺省 = 全部 enabled 用例。"""

    case_ids: list[str] | None = None


class FlTestRunCaseSummary(BaseModel):
    id: str
    run_id: str
    case_id: str
    case_name: str = ""
    job_id: str | None = None
    job_name: str | None = None
    job_type: str | None = None
    job_status: str | None = None
    status: FlTestRunCaseStatus = "pending"
    verdict: FlTestVerdict | None = None
    eval_json: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    create_date: datetime
    update_date: datetime


class FlTestRunSummary(BaseModel):
    id: str
    set_id: str
    status: FlTestRunStatus = "running"
    total_cases: int = 0
    finished_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    pending_manual_cases: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    result_summary_json: dict[str, Any] = Field(default_factory=dict)
    create_date: datetime
    create_user: str | None = None
    cases: list[FlTestRunCaseSummary] = Field(default_factory=list)


class FlTestRunListResponse(BaseModel):
    items: list[FlTestRunSummary]
    total: int


class FlTestVerdictRequest(BaseModel):
    """人工改判：仅接受 manual_pass / manual_fail。"""

    verdict: Literal["manual_pass", "manual_fail"]
    comment: str | None = Field(default=None, max_length=2000)
