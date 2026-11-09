"""防雷测试集（fl test set）管理 API。

集合按类别（fl_calc 防雷计算 / retrofit 防雷改造）组织用例，批量发起真实的
fl_analysis_job 并打 ``test_run_case_id`` 标记：
- 防雷计算页 / 防雷改造页默认排除测试任务（见 fl_analysis.list_jobs）；
- 测试集页面通过 ``/fl-analysis/jobs?test_run_id=`` 查看某次执行的全部任务。
权限：查看 line.read/atp.read 族；发起与重跑 fl.start/atp.manage 族；
集合与用例管理 fl.create/fl.delete/atp.manage 族。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.fl_test_set import (
    FlTestCaseCreateRequest,
    FlTestCaseListResponse,
    FlTestCaseUpdateRequest,
    FlTestRunCreateRequest,
    FlTestRunListResponse,
    FlTestRunSummary,
    FlTestSetCreateRequest,
    FlTestSetListResponse,
    FlTestSetSummary,
    FlTestSetUpdateRequest,
    FlTestVerdictRequest,
)
from ...services.fl_test_set_service import (
    _get_case,
    cancel_run,
    create_case,
    create_set,
    delete_case,
    delete_set,
    get_run,
    list_cases,
    list_runs,
    list_sets,
    rerun_run_case,
    set_verdict,
    start_run,
    update_case,
    update_set,
)

router = APIRouter(
    prefix="/fl-test-sets", tags=["fl-test-sets"], dependencies=[Depends(require_enabled_menu_route)]
)

_READ_PERMS = ("line.read", "line.manage", "atp.read", "atp.run", "atp.manage")
_MANAGE_PERMS = ("fl.create", "line.manage", "atp.manage")
_RUN_PERMS = ("fl.start", "fl.create", "line.manage", "atp.manage")
_DELETE_PERMS = ("fl.delete", "line.manage", "atp.manage")


# ─────────────────────────── 测试集 CRUD ───────────────────────────


@router.get("", response_model=FlTestSetListResponse)
def list_fl_test_sets_endpoint(
    category: str | None = Query(default=None, description="fl_calc / retrofit"),
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestSetListResponse:
    """测试集列表（含用例数与最近一次执行摘要）。"""
    data = list_sets(db, category=category, keyword=keyword, limit=limit, offset=offset)
    return FlTestSetListResponse(**data)


@router.post("", response_model=FlTestSetSummary)
def create_fl_test_set_endpoint(
    payload: FlTestSetCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_MANAGE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestSetSummary:
    """创建测试集（类别创建后不可变更）。"""
    data = create_set(db, payload=payload, actor_user_id=current_user.user.id)
    return FlTestSetSummary(**data)


@router.patch("/{set_id}", response_model=FlTestSetSummary)
def update_fl_test_set_endpoint(
    set_id: str,
    payload: FlTestSetUpdateRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_MANAGE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestSetSummary:
    """更新测试集（名称/描述/状态/标签）。"""
    data = update_set(db, set_id=set_id, payload=payload, actor_user_id=current_user.user.id)
    return FlTestSetSummary(**data)


@router.delete("/{set_id}")
def delete_fl_test_set_endpoint(
    set_id: str,
    _: CurrentUser = Depends(require_any_permission(*_DELETE_PERMS)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除测试集（级联删除其用例与执行记录；已创建的防雷计算任务保留）。"""
    delete_set(db, set_id=set_id)
    return {"status": "ok"}


# ─────────────────────────── 用例 CRUD ───────────────────────────


@router.get("/{set_id}/cases", response_model=FlTestCaseListResponse)
def list_fl_test_set_cases_endpoint(
    set_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestCaseListResponse:
    """测试集用例列表（按 sort_order 升序）。"""
    data = list_cases(db, set_id=set_id)
    return FlTestCaseListResponse(**data)


@router.post("/{set_id}/cases", response_model=FlTestCaseListResponse)
def create_fl_test_set_case_endpoint(
    set_id: str,
    payload: FlTestCaseCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_MANAGE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestCaseListResponse:
    """添加用例（字段按集合类别校验）。返回全量用例便于前端直接刷新。"""
    create_case(db, set_id=set_id, payload=payload, actor_user_id=current_user.user.id)
    data = list_cases(db, set_id=set_id)
    return FlTestCaseListResponse(**data)


@router.patch("/cases/{case_id}", response_model=FlTestCaseListResponse)
def update_fl_test_set_case_endpoint(
    case_id: str,
    payload: FlTestCaseUpdateRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_MANAGE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestCaseListResponse:
    """更新用例。返回所属集合的全量用例。"""
    data_case = update_case(db, case_id=case_id, payload=payload, actor_user_id=current_user.user.id)
    data = list_cases(db, set_id=str(data_case["set_id"]))
    return FlTestCaseListResponse(**data)


@router.delete("/cases/{case_id}", response_model=FlTestCaseListResponse)
def delete_fl_test_set_case_endpoint(
    case_id: str,
    _: CurrentUser = Depends(require_any_permission(*_DELETE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestCaseListResponse:
    """删除用例。返回所属集合的全量用例。"""
    set_id = _get_case(db, case_id).set_id
    delete_case(db, case_id=case_id)
    data = list_cases(db, set_id=set_id)
    return FlTestCaseListResponse(**data)


# ─────────────────────────── 批量执行（run） ───────────────────────────


@router.post("/{set_id}/runs", response_model=FlTestRunSummary)
def start_fl_test_set_run_endpoint(
    set_id: str,
    payload: FlTestRunCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_RUN_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunSummary:
    """批量发起：逐用例创建并启动防雷计算/改造任务（打测试标记）。"""
    data = start_run(db, set_id=set_id, payload_case_ids=payload.case_ids, actor_user_id=current_user.user.id)
    return FlTestRunSummary(**data)


@router.get("/{set_id}/runs", response_model=FlTestRunListResponse)
def list_fl_test_set_runs_endpoint(
    set_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunListResponse:
    """测试集执行历史（按发起时间倒序；读取时同步任务状态与自动评估）。"""
    data = list_runs(db, set_id=set_id, limit=limit, offset=offset)
    return FlTestRunListResponse(**data)


@router.get("/runs/{run_id}", response_model=FlTestRunSummary)
def get_fl_test_set_run_endpoint(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunSummary:
    """执行批次详情：用例级任务状态 + 评估结论。"""
    data = get_run(db, run_id=run_id)
    return FlTestRunSummary(**data)


@router.post("/runs/{run_id}/cancel", response_model=FlTestRunSummary)
def cancel_fl_test_set_run_endpoint(
    run_id: str,
    current_user: CurrentUser = Depends(require_any_permission(*_RUN_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunSummary:
    """取消整批执行：未完成任务逐个 cancel（复用现有取消链路）。"""
    data = cancel_run(db, run_id=run_id, actor_user_id=current_user.user.id)
    return FlTestRunSummary(**data)


@router.post("/run-cases/{run_case_id}/rerun", response_model=FlTestRunSummary)
def rerun_fl_test_run_case_endpoint(
    run_case_id: str,
    current_user: CurrentUser = Depends(require_any_permission(*_RUN_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunSummary:
    """重跑单个用例：重新创建并启动任务，旧任务保留可查。"""
    data = rerun_run_case(db, run_case_id=run_case_id, actor_user_id=current_user.user.id)
    return FlTestRunSummary(**data)


@router.post("/run-cases/{run_case_id}/verdict", response_model=FlTestRunSummary)
def set_fl_test_run_case_verdict_endpoint(
    run_case_id: str,
    payload: FlTestVerdictRequest,
    current_user: CurrentUser = Depends(require_any_permission(*_MANAGE_PERMS)),
    db: Session = Depends(get_db),
) -> FlTestRunSummary:
    """人工判定：manual_pass / manual_fail（覆盖自动结论）。"""
    data = set_verdict(db, run_case_id=run_case_id, payload=payload, actor_user_id=current_user.user.id)
    return FlTestRunSummary(**data)
