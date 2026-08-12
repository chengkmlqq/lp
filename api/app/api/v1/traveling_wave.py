from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.traveling_wave import (
    TravelingWaveAnalyzeRequest,
    TravelingWaveAnalyzeResponse,
    TravelingWaveStatusResponse,
)
from ...services.traveling_wave_service import (
    check_environment,
    create_analysis_job,
    get_analysis_result,
)


router = APIRouter(
    prefix="/traveling-wave",
    tags=["traveling-wave"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/status", response_model=TravelingWaveStatusResponse)
async def get_traveling_wave_status(
    _: CurrentUser = Depends(require_any_permission("traveling_wave.read", "traveling_wave.manage")),
) -> TravelingWaveStatusResponse:
    """检测行波分析服务环境可用性（Python / numpy / scipy / matplotlib）。"""
    return check_environment()


@router.post("/analyze", response_model=TravelingWaveAnalyzeResponse)
async def submit_traveling_wave_analysis(
    payload: TravelingWaveAnalyzeRequest,
    current_user: CurrentUser = Depends(require_any_permission("traveling_wave.manage")),
    db: Session = Depends(get_db),
) -> TravelingWaveAnalyzeResponse:
    """提交行波分析任务（通过服务端文件路径）。"""
    file_a = payload.file_a
    file_b = payload.file_b
    file_c = payload.file_c

    if not file_a and not file_b and not file_c:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要提供一个相数据文件路径",
        )

    # Validate file existence for provided paths
    for label, path in [("A相", file_a), ("B相", file_b), ("C相", file_c)]:
        if path and not os.path.isfile(path):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label} 文件不存在: {path}",
            )

    _, result = create_analysis_job(
        db=db,
        file_a_path=file_a,
        file_b_path=file_b,
        file_c_path=file_c,
        sample_rate_hz=payload.sample_rate_hz,
        fault_distance_km=payload.fault_distance_km,
        tower_no=payload.tower_no,
        created_by=current_user.username if current_user else None,
    )
    return result


@router.post("/analyze/upload", response_model=TravelingWaveAnalyzeResponse)
async def upload_and_analyze(
    file_a: UploadFile | None = None,
    file_b: UploadFile | None = None,
    file_c: UploadFile | None = None,
    sample_rate_hz: int = 1_000_000,
    fault_distance_km: float | None = None,
    tower_no: str | None = None,
    current_user: CurrentUser = Depends(require_any_permission("traveling_wave.manage")),
    db: Session = Depends(get_db),
) -> TravelingWaveAnalyzeResponse:
    """提交行波分析任务（通过文件上传）。"""
    if not file_a and not file_b and not file_c:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要上传一个相数据文件",
        )

    content_a = (await file_a.read()).decode("utf-8") if file_a else None
    content_b = (await file_b.read()).decode("utf-8") if file_b else None
    content_c = (await file_c.read()).decode("utf-8") if file_c else None

    _, result = create_analysis_job(
        db=db,
        content_a=content_a,
        content_b=content_b,
        content_c=content_c,
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
        created_by=current_user.username if current_user else None,
    )
    return result


@router.get("/analyze/{job_id}", response_model=TravelingWaveAnalyzeResponse)
async def get_traveling_wave_analysis(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission("traveling_wave.read", "traveling_wave.manage")),
    db: Session = Depends(get_db),
) -> TravelingWaveAnalyzeResponse:
    """查询行波分析结果。"""
    result = get_analysis_result(db, job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="分析任务不存在",
        )
    return result
