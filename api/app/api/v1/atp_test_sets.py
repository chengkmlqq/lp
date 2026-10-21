"""ATP 测试集（test set）管理 API。

测试集把 ATP 模型（atp_asset）的仿真测试组织成集合：
- 用例：绑定一个资产 + 计算类型（普通计算 normal / 同跳计算 tongtiao）
  + 测试参数快照 + 预期结果（回归断言可选）
- 执行：逐用例走单模型测试管线（materialize → geometry → simulate），
  一键批量回归，支持与上次执行对比（通过率/闪络相数变化）
- 权限：查看 atp.read / 执行 atp.run / 管理 atp.manage（与 ATP 模块一致）
"""

from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import (
    CurrentUser,
    require_any_permission,
    require_enabled_menu_route,
    require_permission,
)
from ...schemas.atp_test_set import (
    AtpTestSetCaseCreateRequest,
    AtpTestSetCaseListResponse,
    AtpTestSetCaseReorderRequest,
    AtpTestSetCaseSummary,
    AtpTestSetCaseUpdateRequest,
    AtpTestSetCreateRequest,
    AtpTestSetExecuteRequest,
    AtpTestSetExecuteResponse,
    AtpTestSetListResponse,
    AtpTestSetRunListResponse,
    AtpTestSetRunSummary,
    AtpTestSetSummary,
    AtpTestSetUpdateRequest,
)
from ...services.atp_test_set_service import (
    build_set_run_report_zip,
    create_case,
    create_set,
    delete_case,
    delete_set,
    execute_set,
    get_set_run,
    list_cases,
    list_set_runs,
    list_sets,
    reorder_cases,
    update_case,
    update_set,
)

router = APIRouter(
    prefix="/atp", tags=["atp-test-sets"], dependencies=[Depends(require_enabled_menu_route)]
)


# ─────────────────────────── 测试集 CRUD ───────────────────────────


@router.get("/test-sets", response_model=AtpTestSetListResponse)
def list_atp_test_sets_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None, description="按名称/描述模糊搜索"),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetListResponse:
    """测试集列表（含用例数与最近一次执行摘要）。"""
    data = list_sets(db, limit=limit, offset=offset, keyword=keyword)
    return AtpTestSetListResponse(**data)


@router.post("/test-sets", response_model=AtpTestSetSummary)
def create_atp_test_set_endpoint(
    payload: AtpTestSetCreateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetSummary:
    """创建测试集。"""
    data = create_set(db, payload=payload, actor_user_id=current_user.user.id)
    return AtpTestSetSummary(**data)


@router.patch("/test-sets/{set_id}", response_model=AtpTestSetSummary)
def update_atp_test_set_endpoint(
    set_id: str,
    payload: AtpTestSetUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetSummary:
    """更新测试集（名称/描述/状态/标签）。"""
    data = update_set(db, set_id=set_id, payload=payload, actor_user_id=current_user.user.id)
    return AtpTestSetSummary(**data)


@router.delete("/test-sets/{set_id}")
def delete_atp_test_set_endpoint(
    set_id: str,
    _: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除测试集（级联删除其用例与执行记录）。"""
    delete_set(db, set_id=set_id)
    return {"status": "ok"}


# ─────────────────────────── 测试用例 CRUD ───────────────────────────


@router.get("/test-sets/{set_id}/cases", response_model=AtpTestSetCaseListResponse)
def list_atp_test_set_cases_endpoint(
    set_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetCaseListResponse:
    """测试集用例列表（按 sort_order 升序）。"""
    data = list_cases(db, set_id=set_id)
    return AtpTestSetCaseListResponse(**data)


@router.post("/test-sets/{set_id}/cases", response_model=AtpTestSetCaseSummary)
def create_atp_test_set_case_endpoint(
    set_id: str,
    payload: AtpTestSetCaseCreateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetCaseSummary:
    """添加用例（绑定资产 + 计算类型 + 参数快照 + 预期结果）。"""
    data = create_case(db, set_id=set_id, payload=payload, actor_user_id=current_user.user.id)
    return AtpTestSetCaseSummary(**data)


@router.patch("/test-sets/cases/{case_id}", response_model=AtpTestSetCaseSummary)
def update_atp_test_set_case_endpoint(
    case_id: str,
    payload: AtpTestSetCaseUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetCaseSummary:
    """更新用例。"""
    data = update_case(db, case_id=case_id, payload=payload, actor_user_id=current_user.user.id)
    return AtpTestSetCaseSummary(**data)


@router.delete("/test-sets/cases/{case_id}")
def delete_atp_test_set_case_endpoint(
    case_id: str,
    _: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除用例。"""
    delete_case(db, case_id=case_id)
    return {"status": "ok"}


@router.post("/test-sets/{set_id}/cases/reorder", response_model=AtpTestSetCaseListResponse)
def reorder_atp_test_set_cases_endpoint(
    set_id: str,
    payload: AtpTestSetCaseReorderRequest,
    _: CurrentUser = Depends(require_permission("atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetCaseListResponse:
    """调整用例顺序：case_ids 为新的完整顺序（未列出的排在其后）。"""
    data = reorder_cases(db, set_id=set_id, payload=payload)
    return AtpTestSetCaseListResponse(**data)


# ─────────────────────────── 测试集执行 ───────────────────────────


@router.post("/test-sets/{set_id}/runs", response_model=AtpTestSetExecuteResponse)
def execute_atp_test_set_endpoint(
    set_id: str,
    payload: AtpTestSetExecuteRequest,
    current_user: CurrentUser = Depends(require_any_permission("atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetExecuteResponse:
    """执行测试集：逐用例发起单模型测试（异步执行），返回 run_id 供轮询。"""
    data = execute_set(
        db,
        set_id=set_id,
        payload=payload,
        actor_user_id=current_user.user.id,
    )
    return AtpTestSetExecuteResponse(**data)


@router.get("/test-sets/{set_id}/runs", response_model=AtpTestSetRunListResponse)
def list_atp_test_set_runs_endpoint(
    set_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetRunListResponse:
    """测试集执行历史（按发起时间倒序）。"""
    data = list_set_runs(db, set_id=set_id, limit=limit, offset=offset)
    return AtpTestSetRunListResponse(**data)


@router.get("/test-sets/runs/{run_id}", response_model=AtpTestSetRunSummary)
def get_atp_test_set_run_endpoint(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
) -> AtpTestSetRunSummary:
    """执行批次详情：用例级结果 + 分组报告 + 与上次执行的回归对比。"""
    data = get_set_run(db, run_id=run_id)
    return AtpTestSetRunSummary(**data)


@router.get("/test-sets/runs/{run_id}/report")
def download_atp_test_set_run_report(
    run_id: str,
    _: CurrentUser = Depends(require_any_permission("atp.read", "atp.run", "atp.manage")),
    db: Session = Depends(get_db),
):
    """下载测试集执行报告包（report.xlsx + detail.csv + report.json 的 zip）。"""
    data, filename = build_set_run_report_zip(db, run_id=run_id)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )