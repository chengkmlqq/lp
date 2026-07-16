from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.fault_recurrence import (
    FaultRecurrenceAnalyzeResponse,
    FaultRecurrenceStrokeMode,
)
from ...services.fault_recurrence_service import build_fault_recurrence_report


router = APIRouter(
    prefix="/fault-recurrence",
    tags=["fault-recurrence"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.post("/analyze", response_model=FaultRecurrenceAnalyzeResponse)
def analyze_fault_recurrence(
    file: UploadFile = File(...),
    curve_no: int = Form(..., ge=1, le=3),
    stroke_mode: FaultRecurrenceStrokeMode = Form(...),
    withstand_level_ka: float = Form(..., gt=0),
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage", "tower.read", "tower.manage")),
) -> FaultRecurrenceAnalyzeResponse:
    try:
        payload = build_fault_recurrence_report(
            file.file.read(),
            file_name=file.filename or "fault-recurrence.txt",
            curve_no=curve_no,
            stroke_mode=stroke_mode,
            withstand_level_ka=withstand_level_ka,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return FaultRecurrenceAnalyzeResponse.model_validate(payload)
