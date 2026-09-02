from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..models.base import utcnow
from ..models.fault_analysis import FaultAnalysis
from ..models.line import Line
from ..models.user import User
from ..schemas.fault_analysis import (
    FaultAnalysisCreateRequest,
    FaultAnalysisCreateResponse,
    FaultAnalysisDetail,
    FaultAnalysisListResponse,
    FaultAnalysisSummary,
    FaultAnalysisUpdateRequest,
)
from .fault_diagnosis_core import LEDGER_OUTPUT_FIELDS
from .minio_storage import (
    build_fault_analysis_generated_key,
    build_fault_analysis_input_key,
    build_fault_analysis_prefix,
    delete_prefix,
    put_object,
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
        reclosure_status=item.reclosure_status,
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
    # LP-537 兼容：历史记录存储的 sections 为旧字段式结构，读取时若 result_json
    # 含完整 diagnosis，用当前 _build_sections 实时重建，保证与 docx 报告同源。
    # 惰性导入避免与 fault_diagnosis_service 顶层循环依赖。
    from .fault_diagnosis_service import rebuild_sections_from_diagnosis

    result_json = item.result_json or {}
    try:
        rebuilt = rebuild_sections_from_diagnosis(result_json)
    except Exception:
        rebuilt = None
    if rebuilt is not None:
        result_json = rebuilt
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
        result_json=result_json,
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
    upload_files: dict[str, Any] | None = None,
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


def store_analysis_upload_file(analysis_id: str, field: str, filename: str, content: bytes) -> dict[str, str]:
    """把上传的判别输入文件保存到 MinIO，返回对象元数据。"""
    safe_name = Path(filename or f"{field}.bin").name
    key = build_fault_analysis_input_key(analysis_id, field, filename)
    put_object(key, content, content_type="application/octet-stream")
    return {
        "key": key,
        "filename": safe_name,
        "content_type": "application/octet-stream",
        "source": "uploaded",
    }


def set_analysis_upload_files(db: Session, analysis_id: str, upload_files: dict[str, object]) -> None:
    item = get_analysis_by_id(db, analysis_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="故障分析记录不存在",
        )
    item.upload_files = upload_files
    item.update_date = utcnow()
    db.commit()


def store_analysis_generated_file(
    analysis_id: str,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
) -> dict[str, str]:
    safe_name = Path(filename or "generated.bin").name
    key = build_fault_analysis_generated_key(analysis_id, filename)
    actual_content_type = content_type or "application/octet-stream"
    put_object(key, content, content_type=actual_content_type)
    return {
        "key": key,
        "filename": safe_name,
        "content_type": actual_content_type,
        "source": "generated",
    }


def ensure_line_has_towers(db: Session, line_id: str) -> None:
    """校验线路存在且含杆塔数据（台账自动组装前置条件，LP-378）。

    线路缺失或无杆塔数据时给出明确提示，避免创建后无法组装判别台账。
    """
    line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="所选故障线路不存在",
        )
    if not line.towers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"线路「{line.name}」无杆塔数据，无法自动组装判别台账，请补充杆塔数据或上传台账文件",
        )


def assemble_ledger_rows(db: Session, line_id: str) -> list[dict[str, object]]:
    """按线路从系统数据组装判别台账行（与 LEDGER_OUTPUT_FIELDS 16 列对齐，LP-378）。

    数据源：power_line（线路名称/电压等级）、power_line_tower（塔号/地形/地闪密度/
    海拔/杆塔模型/塔形/接地电阻/雷击风险等级/经纬度）、tower_profile（绝缘子串长度，
    米转毫米）、tower_lightning_result（反击/绕击耐雷水平）。「直线或耐张杆塔」与
    「塔形」同源取 tower_type，缺省时留空。
    """
    line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
    if line is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="所选故障线路不存在",
        )
    rows: list[dict[str, object]] = []
    for tower in line.towers:
        profile = tower.profile
        lightning = tower.lightning_result
        insulator_mm = (
            round(profile.insulator_length_m * 1000.0, 4)
            if profile is not None and profile.insulator_length_m is not None
            else None
        )
        rows.append(
            {
                "线路名称": line.name,
                "电压等级": line.voltage_kv,
                "塔号": tower.tower_no,
                "地形": tower.terrain,
                "地闪密度": tower.lightning_density,
                "海拔m": tower.altitude_m,
                "杆塔模型": tower.tower_model,
                "塔形": tower.tower_type,
                "直线或耐张杆塔": profile.structure_kind if profile is not None else None,
                "绝缘子串长度mm": insulator_mm,
                "接地电阻": tower.ground_resistance_ohm,
                "反击耐雷水平kA": lightning.counterstroke_withstand_ka if lightning is not None else None,
                "绕击耐雷水平kA": lightning.shielding_withstand_ka if lightning is not None else None,
                "雷击风险等级": tower.risk_level,
                "经度": tower.longitude,
                "纬度": tower.latitude,
            }
        )
    return rows


def assemble_ledger_csv(db: Session, analysis_id: str, line_id: str) -> tuple[str, int]:
    """按线路自动组装判别台账 CSV 并写入分析目录，返回 ``(relative_path, row_count)``。

    生成的 CSV 表头严格对齐 ``LEDGER_OUTPUT_FIELDS`` 16 列中文列名（判别核心
    ``load_ledger_rows`` / ``lookup_ledger`` 读取约定）。线路无杆塔数据时抛 400。
    """
    rows = assemble_ledger_rows(db, line_id)
    if not rows:
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        line_name = line.name if line is not None else line_id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"线路「{line_name}」无杆塔数据，无法自动组装判别台账，请补充杆塔数据或上传台账文件",
        )

    import csv
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(LEDGER_OUTPUT_FIELDS))
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column) for column in LEDGER_OUTPUT_FIELDS})
    content = buffer.getvalue().encode("utf-8-sig")
    relative = store_analysis_generated_file(
        analysis_id,
        "auto_assembled_ledger.csv",
        content,
        content_type="text/csv",
    )
    return relative, len(rows)


def dispatch_fault_diagnosis(db: Session, analysis_id: str) -> None:
    """派发判别任务到 Celery；队列不可用时将记录标记为失败并记录原因。"""
    from ..tasks.fault_diagnosis_tasks import run_fault_diagnosis_task

    item = get_analysis_by_id(db, analysis_id)
    if item is not None:
        item.status = "processing"
        item.update_date = utcnow()
        db.commit()
    try:
        result = run_fault_diagnosis_task.delay(analysis_id)
        # 记录判别任务 task_id，供页面按分析追溯执行日志
        item = get_analysis_by_id(db, analysis_id)
        if item is not None:
            item.task_id = str(result.id)
            item.update_date = utcnow()
            db.commit()
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
    try:
        delete_prefix(build_fault_analysis_prefix(analysis_id))
    except Exception:
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
