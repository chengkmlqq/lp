from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...models.fl_analysis import FlAnalysisJob
from ...schemas.fl_analysis import (
    FlAnalysisJobCancelResponse,
    FlAnalysisJobCreateRequest,
    FlAnalysisJobCreateResponse,
    FlAnalysisJobDetail,
    FlAnalysisJobListResponse,
    FlAnalysisJobStartResponse,
    FlAnalysisTowerResultListResponse,
)
from ...schemas.tower_profile import TowerProfileDetail, TowerProfileUpsertRequest
from ...services.fl_analysis_service import (
    cancel_job,
    create_job,
    delete_job,
    download_result_csv,
    download_report_document,
    get_job_by_id,
    job_live_counts,
    list_jobs,
    list_tower_results,
    serialize_job,
    start_job,
)
from ...services.tower_profile_service import get_tower_profile_detail, upsert_tower_profile
from ...services.tower_topology import TowerGeometryValidationError

router = APIRouter(prefix="/fl-analysis", tags=["fl-analysis"], dependencies=[Depends(require_enabled_menu_route)])


def _fl_job_visible_owner(current_user: CurrentUser) -> str | None:
    """用户级数据隔离：admin 返回 None(全量可见)；普通用户返回自己 user.id(只可见自己提交的任务)。"""
    if "admin" in current_user.role_codes:
        return None
    return current_user.user.id


def _assert_fl_job_visible(item: FlAnalysisJob, current_user: CurrentUser) -> None:
    """任务归属校验：admin 或任务创建人可看；其余 404(不泄露存在性)。"""
    if "admin" in current_user.role_codes:
        return
    if item.create_user and item.create_user == current_user.user.id:
        return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")


@router.get("/tower-profiles/{tower_id}", response_model=TowerProfileDetail)
def get_professional_tower_profile(
    tower_id: str,
    _: CurrentUser = Depends(require_any_permission("tower.read", "tower.manage", "line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> TowerProfileDetail:
    item = get_tower_profile_detail(db, tower_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔不存在")
    return item


@router.put("/tower-profiles/{tower_id}", response_model=TowerProfileDetail)
def put_professional_tower_profile(
    tower_id: str,
    payload: TowerProfileUpsertRequest,
    current_user: CurrentUser = Depends(require_any_permission("tower.manage", "line.manage")),
    db: Session = Depends(get_db),
) -> TowerProfileDetail:
    try:
        updated = upsert_tower_profile(db, tower_id, payload, actor=current_user.user)
    except TowerGeometryValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔不存在")
    return updated


@router.get("/jobs", response_model=FlAnalysisJobListResponse)
def get_fl_analysis_jobs(
    line_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    # 2026-09-30：多值过滤（逗号分隔），防雷改造页传 mitigation,scenario,report
    job_types: str | None = Query(default=None, alias="job_types"),
    keyword: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobListResponse:
    type_list = [item.strip() for item in (job_types or "").split(",") if item.strip()]
    # 2026-09-30：用户级隔离——admin 全量，普通用户只看自己提交的任务
    owner_id = _fl_job_visible_owner(current_user)
    return list_jobs(db, line_id=line_id, status_filter=status_filter, job_types=type_list or None, owner_id=owner_id, keyword=keyword, limit=limit, offset=offset)


@router.get("/jobs/{job_id}", response_model=FlAnalysisJobDetail)
def get_fl_analysis_job_detail(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobDetail:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    return serialize_job(item, include_runs=True, live_counts=job_live_counts(db, [job_id]))


@router.get("/jobs/{job_id}/results", response_model=FlAnalysisTowerResultListResponse)
def get_fl_analysis_job_results(
    job_id: str,
    run_id: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisTowerResultListResponse:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    return list_tower_results(db, job_id=job_id, run_id=run_id or item.latest_run_id)


@router.get("/jobs/{job_id}/results/download")
def download_fl_analysis_results(
    job_id: str,
    run_id: str | None = Query(default=None),
    current_user: CurrentUser = Depends(require_any_permission("fl.export", "line.manage", "line.read")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    filename, content = download_result_csv(db, job_id=job_id, run_id=run_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type="text/csv", headers=headers)


@router.get("/jobs/{job_id}/report/download")
def download_fl_analysis_report(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("fl.export", "line.manage", "line.read")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    filename, content = download_report_document(db, job_id=job_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type="application/msword", headers=headers)


@router.post("/jobs", response_model=FlAnalysisJobCreateResponse)
def create_fl_analysis_job(
    payload: FlAnalysisJobCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission("fl.create", "line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobCreateResponse:
    return create_job(db, payload, actor=current_user.user)


@router.post("/jobs/{job_id}/start", response_model=FlAnalysisJobStartResponse)
def start_fl_analysis_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("fl.start", "line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobStartResponse:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    return start_job(db, job_id, actor=current_user.user)


@router.post("/jobs/{job_id}/cancel", response_model=FlAnalysisJobCancelResponse)
def cancel_fl_analysis_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("fl.cancel", "line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobCancelResponse:
    """取消排队中 / 运行中的任务（revoke celery 任务 + 状态置 cancelled + 清理残留引擎进程）。"""
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    job, status_written = cancel_job(db, job_id=job_id, actor=current_user.user)
    return FlAnalysisJobCancelResponse(
        job=serialize_job(job, include_runs=True),
        cancelled=True,
        status_written=status_written,
    )


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fl_analysis_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("fl.delete", "line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> None:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    _assert_fl_job_visible(item, current_user)
    delete_job(db, job_id=job_id, actor=current_user.user)
