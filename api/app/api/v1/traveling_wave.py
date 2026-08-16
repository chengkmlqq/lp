from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...core.file_upload import read_temp_upload, save_temp_upload
from ...schemas.traveling_wave import (
    TravelingWaveAnalyzeRequest,
    TravelingWaveAnalyzeResponse,
    TravelingWaveStatusResponse,
    TravelingWaveTempUploadResponse,
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


@router.get("/environment", response_model=TravelingWaveStatusResponse)
async def get_traveling_wave_environment(
    _: CurrentUser = Depends(require_any_permission("traveling_wave.read", "traveling_wave.manage")),
) -> TravelingWaveStatusResponse:
    """检测行波分析服务环境可用性（``/status`` 的别名，供前端环境探针调用）。"""
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
        created_by=current_user.user.username if current_user else None,
    )
    return result


@router.post("/upload-temp", response_model=TravelingWaveTempUploadResponse)
async def upload_traveling_wave_temp_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("traveling_wave.manage")),
) -> TravelingWaveTempUploadResponse:
    """选择文件后立即上传到临时目录，返回 temp_file_id 供提交分析时引用。

    与地闪密度导入统一的两段式交互：选择文件先上传，确认提交时携带
    temp_file_id，服务端从临时目录取文件后处理；临时文件消费后删除，
    或由定时清理任务兜底清理超过保留时长的孤儿文件。
    """
    temp_file_id, file_name = save_temp_upload(file, current_user.user.id)
    return TravelingWaveTempUploadResponse(temp_file_id=temp_file_id, file_name=file_name)


@router.post("/analyze/upload", response_model=TravelingWaveAnalyzeResponse)
async def upload_and_analyze(
    file_a: UploadFile | None = File(default=None),
    file_b: UploadFile | None = File(default=None),
    file_c: UploadFile | None = File(default=None),
    file_a_temp_id: str | None = Form(default=None),
    file_b_temp_id: str | None = Form(default=None),
    file_c_temp_id: str | None = Form(default=None),
    sample_rate_hz: int = Form(default=1_000_000),
    fault_distance_km: float | None = Form(default=None),
    tower_no: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_any_permission("traveling_wave.manage")),
    db: Session = Depends(get_db),
) -> TravelingWaveAnalyzeResponse:
    """提交行波分析任务（通过文件上传或临时文件引用）。"""
    content_a: str | None = None
    content_b: str | None = None
    content_c: str | None = None

    if file_a:
        content_a = (await file_a.read()).decode("utf-8")
    elif file_a_temp_id:
        content_a = read_temp_upload(file_a_temp_id, current_user.user.id).decode("utf-8")

    if file_b:
        content_b = (await file_b.read()).decode("utf-8")
    elif file_b_temp_id:
        content_b = read_temp_upload(file_b_temp_id, current_user.user.id).decode("utf-8")

    if file_c:
        content_c = (await file_c.read()).decode("utf-8")
    elif file_c_temp_id:
        content_c = read_temp_upload(file_c_temp_id, current_user.user.id).decode("utf-8")

    if not content_a and not content_b and not content_c:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要上传一个相数据文件",
        )

    _, result = create_analysis_job(
        db=db,
        content_a=content_a,
        content_b=content_b,
        content_c=content_c,
        sample_rate_hz=sample_rate_hz,
        fault_distance_km=fault_distance_km,
        tower_no=tower_no,
        created_by=current_user.user.username if current_user else None,
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
