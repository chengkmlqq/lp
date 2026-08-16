from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...core.file_upload import (
    resolve_temp_upload,
    save_temp_upload,
    validate_upload,
    validate_upload_bytes,
)
from ...schemas.fault_analysis import (
    FaultAnalysisCreateRequest,
    FaultAnalysisCreateResponse,
    FaultAnalysisDetail,
    FaultAnalysisListResponse,
    FaultAnalysisTempUploadResponse,
    FaultAnalysisUpdateRequest,
)
from ...services.fault_analysis_service import (
    assemble_ledger_csv,
    create_analysis,
    delete_analysis,
    dispatch_fault_diagnosis,
    ensure_line_has_towers,
    get_analysis_by_id,
    list_analyses,
    serialize_detail,
    set_analysis_upload_files,
    store_analysis_upload_file,
    update_analysis,
)
from ...services.minio_storage import MinioStorageError, MinioObjectNotFoundError, get_object
from ...services.fault_input_discovery import (
    CATEGORY_FIELDS,
    CATEGORY_LABELS,
    CATEGORY_UNKNOWN,
    SINGLE_FILE_CATEGORIES,
    classify_upload_file,
)

router = APIRouter(
    prefix="/fault-analysis",
    tags=["fault-analysis"],
    dependencies=[Depends(require_enabled_menu_route)],
)

# 各类判别输入文件允许的扩展名（LP-378：移除自动归类后，按独立上传组件逐一校验）。
# 与前端各上传卡片的 accept 保持一致，后端 validate_upload 为最终底线。
UPLOAD_ALLOWED_EXTS: dict[str, set[str]] = {
    "wave_data_file": {"txt", "json", "csv", "pdf", "xlsx"},
    "lightning_data_file": {"xls", "xlsx", "csv"},
    "ledger_data_file": {"csv"},
    "traveling_wave_file": {"csv", "dat", "txt", "json"},
    "optical_data_file": {
        "jpg", "jpeg", "png", "gif", "bmp", "webp",
        "mp4", "avi", "mov", "mkv", "wmv", "flv",
    },
}


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


@router.post("/upload-temp", response_model=FaultAnalysisTempUploadResponse)
def upload_fault_analysis_temp_file(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
) -> FaultAnalysisTempUploadResponse:
    """选择文件后立即上传到临时目录，返回 temp_file_id 供确认提交时引用（LP-369）。

    与地闪密度导入交互一致：前端先调用本端点展示上传进度条，
    确认提交时携带 temp_file_id 列表，由 create-fault-analysis-with-files 消费。
    临时文件在消费后自动删除，或由定时清理任务兜底清除（24h）。
    """
    temp_file_id, file_name = save_temp_upload(file, current_user.user.id)
    return FaultAnalysisTempUploadResponse(temp_file_id=temp_file_id, file_name=file_name)


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
    wave_data_temp_file_id: str | None = Form(default=None),
    lightning_data_temp_file_id: str | None = Form(default=None),
    ledger_data_temp_file_id: str | None = Form(default=None),
    traveling_wave_temp_file_id: str | None = Form(default=None),
    optical_data_temp_file_id: str | None = Form(default=None),
    auto_classify_temp_file_ids: list[str] | None = Form(default=None),
    current_user: CurrentUser = Depends(require_any_permission("line.manage", "tower.manage")),
    db: Session = Depends(get_db),
) -> FaultAnalysisCreateResponse:
    """创建故障分析记录并附带判别输入文件（录波/雷电/台账/行波/光学）。

    支持两段式上传（LP-369）：先调用 upload-temp 获取 temp_file_id，
    确认提交时传对应 ``*_temp_file_id``，后端从临时目录取文件并消费删除；
    同时保留直接上传原始文件的兼容入参。各类文件提交时统一做扩展名/大小校验。

    台账（LP-378）：用户未上传台账文件时，按所选线路自动从系统数据组装判别台账
    （格式转换为判别所需 CSV 结构，见 ``assemble_ledger_csv``）；线路无杆塔数据时
    提前给出明确提示。
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

    # 台账自动组装预检（LP-378）：未上传台账时需能从系统数据组装，
    # 线路无杆塔数据则提前提示，避免落库后无法生成判别台账。
    user_ledger_uploaded = bool(
        ledger_data_temp_file_id
        or (ledger_data_file is not None and ledger_data_file.filename)
        or auto_classify
        or auto_classify_temp_file_ids
    )
    if not user_ledger_uploaded and line_id:
        ensure_line_has_towers(db, line_id)

    # 先落库拿到记录 ID，再按 ID 持久化上传文件，最后关联并派发判别任务。
    created = create_analysis(
        db,
        payload,
        actor=current_user.user,
        upload_files={},
        auto_diagnose=False,
    )
    analysis_id = created.analysis.id
    user_id = current_user.user.id

    try:
        if auto_classify or auto_classify_temp_file_ids:
            upload_files = await _store_auto_classified_files(
                analysis_id,
                uploads=auto_classify_files or [],
                temp_file_ids=auto_classify_temp_file_ids or [],
                user_id=user_id,
            )
            if "ledger_data_file" not in upload_files and line_id:
                relative, _ = assemble_ledger_csv(db, analysis_id, line_id)
                upload_files["ledger_data_file"] = relative
        else:
            upload_files: dict[str, object] = {}
            await _store_explicit_uploads(
                upload_files,
                analysis_id,
                user_id,
                (
                    ("wave_data_file", wave_data_file, wave_data_temp_file_id),
                    ("lightning_data_file", lightning_data_file, lightning_data_temp_file_id),
                    ("ledger_data_file", ledger_data_file, ledger_data_temp_file_id),
                    ("traveling_wave_file", traveling_wave_file, traveling_wave_temp_file_id),
                    ("optical_data_file", optical_data_file, optical_data_temp_file_id),
                ),
            )
            if "ledger_data_file" not in upload_files and line_id:
                relative, _ = assemble_ledger_csv(db, analysis_id, line_id)
                upload_files["ledger_data_file"] = relative
    except Exception:
        # 文件校验/落盘失败时清理已创建记录，避免残留孤儿分析（LP-378）。
        delete_analysis(db, analysis_id)
        raise

    if upload_files:
        set_analysis_upload_files(db, analysis_id, upload_files)
    dispatch_fault_diagnosis(db, analysis_id)
    saved = get_analysis_by_id(db, analysis_id)
    return FaultAnalysisCreateResponse(analysis=serialize_detail(saved))


async def _store_explicit_uploads(
    upload_files: dict[str, object],
    analysis_id: str,
    user_id: str,
    items: tuple[tuple[str, UploadFile | None, str | None], ...],
) -> None:
    for field, upload, temp_file_id in items:
        allowed_exts = UPLOAD_ALLOWED_EXTS[field]
        if temp_file_id:
            content, file_name = resolve_temp_upload(temp_file_id, user_id)
            validate_upload_bytes(file_name, content, allowed_exts=allowed_exts)
            upload_files[field] = store_analysis_upload_file(analysis_id, field, file_name, content)
        elif upload is not None and upload.filename:
            validate_upload(upload, allowed_exts=allowed_exts)
            content = await upload.read()
            upload_files[field] = store_analysis_upload_file(analysis_id, field, upload.filename, content)


async def _store_auto_classified_files(
    analysis_id: str,
    uploads: list[UploadFile],
    temp_file_ids: list[str],
    user_id: str,
) -> dict[str, object]:
    upload_files: dict[str, object] = {}
    single_fields: set[str] = set()
    items: list[tuple[str, bytes]] = []
    for temp_file_id in temp_file_ids:
        if temp_file_id:
            content, file_name = resolve_temp_upload(temp_file_id, user_id)
            items.append((file_name, content))
    for upload in uploads:
        if upload.filename:
            items.append((upload.filename, await upload.read()))

    for file_name, content in items:
        category = classify_upload_file(file_name)
        if category == CATEGORY_UNKNOWN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法自动识别文件类别：{file_name}，请使用 1/2/3 分隔前缀或 TXT/JSON 行波文件",
            )
        field = CATEGORY_FIELDS[category]
        validate_upload_bytes(file_name, content, allowed_exts=UPLOAD_ALLOWED_EXTS[field])
        if field in single_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{CATEGORY_LABELS[category]}同一类别仅允许一个文件，请保留一个：{file_name}",
            )
        relative = store_analysis_upload_file(analysis_id, field, file_name, content)
        if category in SINGLE_FILE_CATEGORIES:
            single_fields.add(field)
            upload_files[field] = relative
        else:
            upload_files.setdefault(field, [])
            assert isinstance(upload_files[field], list)
            upload_files[field].append(relative)
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


@router.get("/{analysis_id}/report", response_model=None)
def download_fault_analysis_report(
    analysis_id: str,
    _: CurrentUser = Depends(require_any_permission("line.read", "line.manage")),
    db: Session = Depends(get_db),
) -> object:
    """下载判别成功后生成的 Word 正式报告（LP-343）。"""
    item = get_analysis_by_id(db, analysis_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故障分析记录不存在")
    if not item.result_json or not item.result_json.get("diagnosis"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该记录尚未完成判别，无法生成报告")
    artifact_key = ((item.result_json or {}).get("artifacts") or {}).get("report_docx")
    if isinstance(artifact_key, str) and artifact_key:
        try:
            content = get_object(artifact_key)
        except MinioObjectNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件尚未生成，请稍后重试")
        except MinioStorageError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        filename = f"fault_analysis_{analysis_id}_report.docx"
        return StreamingResponse(
            iter([content]),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    report_path = Path(get_settings().file_vfs_root) / "fault_analysis" / analysis_id / "report.docx"
    if not report_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告文件尚未生成，请稍后重试")
    filename = f"fault_analysis_{analysis_id}_report.docx"
    return FileResponse(
        report_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
