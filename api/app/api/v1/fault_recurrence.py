from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...core.file_upload import resolve_temp_upload, save_temp_upload, validate_upload
from ...schemas.fault_recurrence import (
    FaultRecurrenceAnalyzeResponse,
    FaultRecurrenceStrokeMode,
    FaultRecurrenceTempUploadResponse,
)
from ...services.fault_recurrence_service import build_fault_recurrence_report


router = APIRouter(
    prefix="/fault-recurrence",
    tags=["fault-recurrence"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.post("/upload-temp", response_model=FaultRecurrenceTempUploadResponse)
def upload_fault_recurrence_temp_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_any_permission("line.read", "line.manage", "tower.read", "tower.manage")),
) -> FaultRecurrenceTempUploadResponse:
    """选择文件后立即上传到 MinIO 临时目录，返回 temp_file_id 供确认分析时引用。

    临时文件将在分析消费后自动删除，或由定时清理任务清理超过 24h 的孤儿文件。
    """
    temp_file_id, file_name = save_temp_upload(file, current_user.user.id)
    return FaultRecurrenceTempUploadResponse(temp_file_id=temp_file_id, file_name=file_name)


@router.post("/analyze", response_model=FaultRecurrenceAnalyzeResponse)
def analyze_fault_recurrence(
    file: UploadFile | None = File(default=None),
    temp_file_id: str | None = Form(default=None),
    curve_no: int = Form(..., ge=1, le=3),
    stroke_mode: FaultRecurrenceStrokeMode = Form(...),
    withstand_level_ka: float = Form(..., gt=0),
    current_user: CurrentUser = Depends(require_any_permission("line.read", "line.manage", "tower.read", "tower.manage")),
) -> FaultRecurrenceAnalyzeResponse:
    if temp_file_id:
        file_bytes, source_file_name = resolve_temp_upload(temp_file_id, current_user.user.id)
    elif file is not None:
        validate_upload(file, allowed_exts={"csv", "txt"})
        file_bytes = file.file.read()
        source_file_name = (file.filename or "fault-recurrence.txt").strip() or "fault-recurrence.txt"
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件，请提供 file 或 temp_file_id")

    try:
        payload = build_fault_recurrence_report(
            file_bytes,
            file_name=source_file_name,
            curve_no=curve_no,
            stroke_mode=stroke_mode,
            withstand_level_ka=withstand_level_ka,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return FaultRecurrenceAnalyzeResponse.model_validate(payload)
