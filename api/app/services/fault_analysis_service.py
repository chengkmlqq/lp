from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.fault_analysis import FaultAnalysis
from ..models.user import User
from ..schemas.fault_analysis import (
    FaultAnalysisCreateRequest,
    FaultAnalysisCreateResponse,
    FaultAnalysisDetail,
    FaultAnalysisListResponse,
    FaultAnalysisSummary,
    FaultAnalysisUpdateRequest,
)


def serialize_summary(item: FaultAnalysis) -> FaultAnalysisSummary:
    return FaultAnalysisSummary(
        id=item.id,
        title=item.title,
        description=item.description,
        line_id=item.line_id,
        line_name=item.line_name,
        status=item.status,
        risk_level=item.risk_level,
        fault_time=item.fault_time,
        fault_type=item.fault_type,
        fault_phase=item.fault_phase,
        confidence=item.confidence,
        station=item.station,
        lightning_current_ka=item.lightning_current_ka,
        wave_distance_km=item.wave_distance_km,
        traveling_wave_distance_km=item.traveling_wave_distance_km,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_detail(item: FaultAnalysis) -> FaultAnalysisDetail:
    return FaultAnalysisDetail(
        id=item.id,
        title=item.title,
        description=item.description,
        line_id=item.line_id,
        line_name=item.line_name,
        status=item.status,
        risk_level=item.risk_level,
        fault_time=item.fault_time,
        fault_type=item.fault_type,
        fault_phase=item.fault_phase,
        fault_duration_ms=item.fault_duration_ms,
        reclosure_status=item.reclosure_status,
        fault_voltage_v=item.fault_voltage_v,
        fault_current_a=item.fault_current_a,
        max_zero_current_a=item.max_zero_current_a,
        zero_compensation=item.zero_compensation,
        fault_resistance_ohm=item.fault_resistance_ohm,
        line_length_km=item.line_length_km,
        line_angle_deg=item.line_angle_deg,
        line_impedance_ohm=item.line_impedance_ohm,
        confidence=item.confidence,
        station=item.station,
        lightning_current_ka=item.lightning_current_ka,
        lightning_longitude=item.lightning_longitude,
        lightning_latitude=item.lightning_latitude,
        wave_distance_km=item.wave_distance_km,
        traveling_wave_distance_km=item.traveling_wave_distance_km,
        optical_position=item.optical_position,
        optical_device_location=item.optical_device_location,
        result_json=item.result_json or {},
        upload_files=item.upload_files or {},
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def list_analyses(
    db: Session,
    *,
    keyword: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FaultAnalysisListResponse:
    stmt = select(FaultAnalysis)
    total_stmt = select(func.count()).select_from(FaultAnalysis)

    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                FaultAnalysis.title.ilike(pattern),
                FaultAnalysis.line_name.ilike(pattern),
                FaultAnalysis.description.ilike(pattern),
                FaultAnalysis.station.ilike(pattern),
            )
        )
        total_stmt = total_stmt.where(
            or_(
                FaultAnalysis.title.ilike(pattern),
                FaultAnalysis.line_name.ilike(pattern),
                FaultAnalysis.description.ilike(pattern),
                FaultAnalysis.station.ilike(pattern),
            )
        )
    if status_filter:
        stmt = stmt.where(FaultAnalysis.status == status_filter)
        total_stmt = total_stmt.where(FaultAnalysis.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(FaultAnalysis.create_date.desc(), FaultAnalysis.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    return FaultAnalysisListResponse(
        items=[serialize_summary(item) for item in items],
        total=total,
    )


def get_analysis_by_id(db: Session, analysis_id: str) -> FaultAnalysis | None:
    return db.execute(
        select(FaultAnalysis).where(FaultAnalysis.id == analysis_id)
    ).scalar_one_or_none()


def create_analysis(
    db: Session,
    payload: FaultAnalysisCreateRequest,
    *,
    actor: User,
    upload_files: dict[str, str] | None = None,
    auto_diagnose: bool = True,
) -> FaultAnalysisCreateResponse:
    now = utcnow()
    item = FaultAnalysis(
        title=payload.title,
        description=payload.description,
        line_id=payload.line_id,
        line_name=payload.line_name,
        status="pending",
        risk_level=payload.risk_level,
        fault_time=payload.fault_time,
        fault_type=payload.fault_type,
        fault_phase=payload.fault_phase,
        fault_duration_ms=payload.fault_duration_ms,
        station=payload.station,
        reclosure_status=payload.reclosure_status,
        fault_voltage_v=payload.fault_voltage_v,
        fault_current_a=payload.fault_current_a,
        max_zero_current_a=payload.max_zero_current_a,
        zero_compensation=payload.zero_compensation,
        fault_resistance_ohm=payload.fault_resistance_ohm,
        line_length_km=payload.line_length_km,
        line_angle_deg=payload.line_angle_deg,
        line_impedance_ohm=payload.line_impedance_ohm,
        lightning_current_ka=payload.lightning_current_ka,
        lightning_longitude=payload.lightning_longitude,
        lightning_latitude=payload.lightning_latitude,
        wave_distance_km=payload.wave_distance_km,
        traveling_wave_distance_km=payload.traveling_wave_distance_km,
        optical_position=payload.optical_position,
        optical_device_location=payload.optical_device_location,
        confidence=payload.confidence,
        result_json={},
        upload_files=upload_files or {},
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(item)
    db.commit()

    saved = get_analysis_by_id(db, item.id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建故障分析记录失败",
        )
    if auto_diagnose:
        dispatch_fault_diagnosis(db, saved.id)
    return FaultAnalysisCreateResponse(analysis=serialize_detail(saved))


def store_analysis_upload_file(analysis_id: str, field: str, filename: str, content: bytes) -> str:
    """把上传的判别输入文件保存到共享卷，返回相对 vfs 根的路径供 worker 读取。"""
    settings = get_settings()
    vfs_root = Path(settings.file_vfs_root)
    analysis_dir = vfs_root / "fault_analysis" / analysis_id
    analysis_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or f"{field}.bin").name
    target = analysis_dir / f"{field}_{safe_name}"
    target.write_bytes(content)
    return target.relative_to(vfs_root).as_posix()


def set_analysis_upload_files(db: Session, analysis_id: str, upload_files: dict[str, str]) -> None:
    item = get_analysis_by_id(db, analysis_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故障分析记录不存在",
        )
    item.upload_files = upload_files
    item.update_date = utcnow()
    db.commit()


def dispatch_fault_diagnosis(db: Session, analysis_id: str) -> None:
    """派发判别任务到 Celery；队列不可用时将记录标记为失败并记录原因。"""
    from ..tasks.fault_diagnosis_tasks import run_fault_diagnosis_task

    item = get_analysis_by_id(db, analysis_id)
    if item is not None:
        item.status = "processing"
        item.update_date = utcnow()
        db.commit()
    try:
        run_fault_diagnosis_task.delay(analysis_id)
    except Exception as exc:  # pragma: no cover - depends on broker availability
        item = get_analysis_by_id(db, analysis_id)
        if item is not None:
            item.status = "failed"
            item.result_json = dict(item.result_json or {})
            item.result_json["error"] = {"message": f"判别任务派发失败: {exc}"}
            item.update_date = utcnow()
            db.commit()


def delete_analysis(db: Session, analysis_id: str) -> None:
    item = get_analysis_by_id(db, analysis_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故障分析记录不存在",
        )
    upload_dir = Path(get_settings().file_vfs_root) / "fault_analysis" / analysis_id
    db.delete(item)
    db.commit()
    # 尽力清理该记录关联的判别输入文件（失败不阻断删除）。
    import shutil

    try:
        if upload_dir.is_dir():
            shutil.rmtree(upload_dir, ignore_errors=True)
    except OSError:
        pass


def update_analysis(
    db: Session,
    analysis_id: str,
    payload: FaultAnalysisUpdateRequest,
    *,
    actor: User,
) -> FaultAnalysisCreateResponse:
    item = get_analysis_by_id(db, analysis_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故障分析记录不存在",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    now = utcnow()
    item.update_date = now
    item.update_user = actor.id
    db.commit()

    saved = get_analysis_by_id(db, analysis_id)
    if not saved:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新故障分析记录失败",
        )
    return FaultAnalysisCreateResponse(analysis=serialize_detail(saved))
