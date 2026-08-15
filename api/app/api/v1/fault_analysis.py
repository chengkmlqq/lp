from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ...core.config import get_settings
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
    dispatch_fault_diagnosis,
    get_analysis_by_id,
    list_analyses,
    serialize_detail,
    set_analysis_upload_files,
    store_analysis_upload_file,
    update_analysis,
)
from ...services.fault_input_discovery import (
    CATEGORY_FIELDS,
    SINGLE_FILE_CATEGORIES,
    CATEGORY_LABELS,
    InputDiscoveryError,
    classify_upload_file,
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


@router.post("/upload", response_model=FaultAnalysisCreateResponse)
async def create_fault_analysis_with_files(
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    line_id: str | None = Form(default=None),
    line_name: str | None = Form(default=None),
    risk_level: str | None = Form(default=None),
    fault_time: str | None = Form(default=None),
    fault_type: str | None = Form(default=None),
    fault_phase: str | None = Form(default=None),
    fault_duration_ms: float | None = Form(default=None),
    station: str | None = Form(default=None),
    reclosure_status: str | None = Form(default=None),
    fault_voltage_v: float | None = Form(default=None),
    fault_current_a: float | None = Form(default=None),
    max_zero_current_a: float | None = Form(default=None),
    zero_compensation: float | None = Form(default=None),
    fault_resistance_ohm: float | None = Form(default=None),
    line_length_km: float | None = Form(default=None),
    line_angle_deg: float | None = Form(default=None),
    line_impedance_ohm: float | None = Form(default=None),
    lightning_current_ka: float | None = Form(default=None),
    lightning_longitude: float | None = Form(default=None),
    lightning_latitude: float | None = Form(default=None),
    wave_distance_km: float | None = Form(default=None),
    traveling_wave_distance_km: float | None = Form(default=None),
    optical_position: str | None = Form(default=None),
    optical_device_location: str | None = Form(default=None),
    confidence: float | None = Form(default=None),
    wave_data_file: UploadFile | None = File(default=None),
    lightning_data_file: UploadFile | None = File(default=None),
    ledger_data_file: UploadFile | None = File(default=None),
    traveling_wave_file: UploadFile | None = File(default=None),
    optical_data_file: UploadFile | None = File(default=None),
    auto_classify: bool | None = Form(default=None),
    auto_classify_files: list[UploadFile] | None = File(default=None),
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisCreateResponse:
    """创建故障分析记录并附带判别输入文件（录波/雷电/台账/行波/光学）。

    auto_classify 为 True 时忽略前端表单字段名，改按文件名前缀自动归类：
    1 开头=录波、2 开头=雷电定位、3 开头=线路台账、其余 TXT/JSON=行波。
    """
    payload = FaultAnalysisCreateRequest(
        title=title,
        description=description,
        line_id=line_id,
        line_name=line_name,
        risk_level=risk_level,
        fault_time=fault_time,
        fault_type=fault_type,
        fault_phase=fault_phase,
        fault_duration_ms=fault_duration_ms,
        station=station,
        reclosure_status=reclosure_status,
        fault_voltage_v=fault_voltage_v,
        fault_current_a=fault_current_a,
        max_zero_current_a=max_zero_current_a,
        zero_compensation=zero_compensation,
        fault_resistance_ohm=fault_resistance_ohm,
        line_length_km=line_length_km,
        line_angle_deg=line_angle_deg,
        line_impedance_ohm=line_impedance_ohm,
        lightning_current_ka=lightning_current_ka,
        lightning_longitude=lightning_longitude,
        lightning_latitude=lightning_latitude,
        wave_distance_km=wave_distance_km,
        traveling_wave_distance_km=traveling_wave_distance_km,
        optical_position=optical_position,
        optical_device_location=optical_device_location,
        confidence=confidence,
    )

    # 先落库拿到记录 ID，再按 ID 持久化上传文件，最后关联并派发判别任务。
    created = create_analysis(
        db,
        payload,
        actor=current_user.user,
        upload_files={},
        auto_diagnose=False,
    )
    analysis_id = created.analysis.id

    if auto_classify:
        upload_files = await _store_auto_classified_files(analysis_id, auto_classify_files or [])
    else:
        upload_files: dict[str, str] = {}
        for field, upload in (
            ("wave_data_file", wave_data_file),
            ("lightning_data_file", lightning_data_file),
            ("ledger_data_file", ledger_data_file),
            ("traveling_wave_file", traveling_wave_file),
            ("optical_data_file", optical_data_file),
        ):
            if upload is not None and upload.filename:
                content = await upload.read()
                upload_files[field] = store_analysis_upload_file(
                    analysis_id, field, upload.filename, content
                )

    if upload_files:
        set_analysis_upload_files(db, analysis_id, upload_files)
    dispatch_fault_diagnosis(db, analysis_id)
    saved = get_analysis_by_id(db, analysis_id)
    return FaultAnalysisCreateResponse(analysis=serialize_detail(saved))


async def _store_auto_classified_files(
    analysis_id: str,
    uploads: list[UploadFile],
) -> dict[str, str | list[str]]:
    """按文件名前缀自动归类并持久化上传文件，返回 upload_files 字典。

    录波/雷电/台账为单文件类别：同类别上传多个文件时报错（提示保留一个）。
    行波允许多个，保存为相对路径列表。
    """
    upload_files: dict[str, str | list[str]] = {}
    seen_single: set[str] = set()
    for upload in uploads:
        if not upload.filename:
            continue
        try:
            category = classify_upload_file(upload.filename)
            field = CATEGORY_FIELDS[category]
        except (KeyError, InputDiscoveryError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"无法自动识别文件类别：{upload.filename}。"
                    "请按 1（录波）/2（雷电定位）/3（线路台账）前缀命名，"
                    "或使用 TXT/JSON 行波文件。"
                ),
            )
        content = await upload.read()
        relative = store_analysis_upload_file(analysis_id, field, upload.filename, content)
        if category in SINGLE_FILE_CATEGORIES:
            if field in seen_single:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"{CATEGORY_LABELS[category]}同一类别仅允许一个文件，"
                        f"请保留一个（{upload.filename}）。"
                    ),
                )
            seen_single.add(field)
            upload_files[field] = relative
        else:
            existing = upload_files.get(field)
            if isinstance(existing, list):
                existing.append(relative)
            elif existing:
                upload_files[field] = [existing, relative]
            else:
                upload_files[field] = [relative]
    return upload_files


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


@router.get("/{analysis_id}/report")
def download_fault_analysis_report(
    analysis_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> FileResponse:
    """下载判别成功后生成的 Word 正式报告（LP-343）。"""
    item = get_analysis_by_id(db, analysis_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故障分析记录不存在")
    if not item.result_json or not item.result_json.get("diagnosis"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该记录尚未完成判别，无法生成报告")
    report_path = (
        Path(get_settings().file_vfs_root) / "fault_analysis" / analysis_id / "report.docx"
    )
    if not report_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件尚未生成，请稍后重试")
    filename = f"fault_analysis_{analysis_id}_report.docx"
    return FileResponse(
        report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )