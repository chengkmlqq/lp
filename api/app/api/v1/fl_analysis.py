from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.fl_analysis import (
    FlAnalysisJobCreateRequest,
    FlAnalysisJobCreateResponse,
    FlAnalysisJobDetail,
    FlAnalysisJobListResponse,
    FlAnalysisJobStartResponse,
    FlAnalysisTowerResultListResponse,
)
from ...schemas.tower_profile import TowerProfileDetail, TowerProfileUpsertRequest
from ...services.fl_analysis_service import (
    create_job,
    download_result_csv,
    download_report_document,
    get_job_by_id,
    list_jobs,
    list_tower_results,
    serialize_job,
    start_job,
)
from ...services.tower_profile_service import get_tower_profile_detail, upsert_tower_profile
from ...services.tower_topology import TowerGeometryValidationError

router = APIRouter(prefix="/fl-analysis", tags=["fl-analysis"], dependencies=[Depends(require_enabled_menu_route)])


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
    limit: int = Query(default=50, ge=1, le=200),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobListResponse:
    return list_jobs(db, line_id=line_id, status_filter=status_filter, limit=limit)


@router.get("/jobs/{job_id}", response_model=FlAnalysisJobDetail)
def get_fl_analysis_job_detail(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobDetail:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    return serialize_job(item, include_runs=True)


@router.get("/jobs/{job_id}/results", response_model=FlAnalysisTowerResultListResponse)
def get_fl_analysis_job_results(
    job_id: str,
    run_id: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisTowerResultListResponse:
    item = get_job_by_id(db, job_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    return list_tower_results(db, job_id=job_id, run_id=run_id or item.latest_run_id)


@router.get("/jobs/{job_id}/results/download")
def download_fl_analysis_results(
    job_id: str,
    run_id: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filename, content = download_result_csv(db, job_id=job_id, run_id=run_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type="text/csv", headers=headers)


@router.get("/jobs/{job_id}/report/download")
def download_fl_analysis_report(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    filename, content = download_report_document(db, job_id=job_id)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([content]), media_type="application/msword", headers=headers)


@router.post("/jobs", response_model=FlAnalysisJobCreateResponse)
def create_fl_analysis_job(
    payload: FlAnalysisJobCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobCreateResponse:
    return create_job(db, payload, actor=current_user.user)


@router.post("/jobs/{job_id}/start", response_model=FlAnalysisJobStartResponse)
def start_fl_analysis_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FlAnalysisJobStartResponse:
    return start_job(db, job_id, actor=current_user.user)
