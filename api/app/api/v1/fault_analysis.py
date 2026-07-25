from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.fault_analysis import (
    FaultAnalysisCreateRequest,
    FaultAnalysisCreateResponse,
    FaultAnalysisDetail,
    FaultAnalysisListResponse,
    FaultAnalysisUpdateRequest,
)
from ...services.fault_analysis_service import (
    create_analysis,
    delete_analysis,
    get_analysis_by_id,
    list_analyses,
    serialize_detail,
    update_analysis,
)

router = APIRouter(
    prefix="/fault-analysis",
    tags=["fault-analysis"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("", response_model=FaultAnalysisListResponse)
def get_fault_analyses(
    keyword: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisListResponse:
    return list_analyses(db, keyword=keyword, status_filter=status, limit=limit, offset=offset)


@router.get("/{analysis_id}", response_model=FaultAnalysisDetail)
def get_fault_analysis_detail(
    analysis_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisDetail:
    item = get_analysis_by_id(db, analysis_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故障分析记录不存在")
    return serialize_detail(item)


@router.post("", response_model=FaultAnalysisCreateResponse)
def create_fault_analysis(
    payload: FaultAnalysisCreateRequest,
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisCreateResponse:
    return create_analysis(db, payload, actor=current_user.user)


@router.put("/{analysis_id}", response_model=FaultAnalysisDetail)
def update_fault_analysis(
    analysis_id: str,
    payload: FaultAnalysisUpdateRequest,
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisDetail:
    result = update_analysis(db, analysis_id, payload, actor=current_user.user)
    return result.analysis


@router.delete("/{analysis_id}")
def delete_fault_analysis(
    analysis_id: str,
    _: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    delete_analysis(db, analysis_id)
    return {"message": "故障分析记录已删除"}