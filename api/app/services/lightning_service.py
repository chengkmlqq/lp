from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import cast, func, or_, select, String
from sqlalchemy.orm import Session

from ..core.database import SessionLocal

from ..models.base import utcnow
from ..models.lightning_amplitude import LightningAmplitude
from ..models.line_amplitude_backfill import LineAmplitudeBackfill
from ..models.lightning_current_backfill import LightningCurrentBackfillTask, LightningCurrentBackfillTower
from ..models.lightning_density_backfill import LightningDensityBackfillTask
from ..models.lightning_distribution import LightningDistribution
from ..models.line import Line
from ..models.line_amplitude_backfill import LineAmplitudeBackfill
from ..models.line_tower import LineTower
from ..models.tower_profile import TowerProfile
from ..schemas.lightning import (
    LightningAmplitudeBackfillLine,
    LightningAmplitudeBackfillLineListResponse,
    LightningAmplitudeImportResponse,
    LightningAmplitudeRecord,
    LightningAmplitudeListResponse,
    LightningAmplitudeStatusResponse,
    LightningAmplitudeUpdateRequest,
    LightningCurrentPreparationRequest,
    LightningCurrentPreparationResponse,
    LightningCurrentPreparationAsyncResponse,
    LightningCurrentBackfillTaskSummary,
    LightningCurrentBackfillTaskListResponse,
    LightningCurrentBackfillTaskDetail,
    LightningCurrentBackfillTowerDetail,
    LightningDistributionImportResponse,
    LightningDistributionRecord,
    LightningDistributionListResponse,
    LightningDistributionStatusResponse,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningDensityPreparationAsyncResponse,
    LightningCurrentExceedancePoint,
    LightningCurrentExceedanceResponse,
    LightningPolarity,
    LightningLpDrawRequest,
    LightningLpDrawResponse,
    LightningLinkedLineSummary,
    LightningLinkedLinesResponse,
    LightningDensityBackfillTowerDetail,
    LightningDensityBackfillTowersResponse,
    LightningDensityBackfillTaskSummary,
    LightningDensityBackfillHistoryResponse,
)
from .audit_service import compose_audit_detail, write_audit_log
from .line_preparation_service import record_line_preparation_source, summarize_line_preparation
from .line_service import serialize_line
from .push_service import publish_topic

LIGHTNING_DISTRIBUTION_TOPIC = "admin.lightning-distribution"
LIGHTNING_AMPLITUDE_TOPIC = "admin.lightning-amplitude"
LIGHTNING_CURRENT_BACKFILL_TOPIC = "admin.lightning-current-backfill"
POWER_LINES_TOPIC = "admin.power-lines"
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
MAX_SAMPLES = 2_000_000
STANDARD_WAVE_SHAPES: tuple[tuple[str, float, float], ...] = (
    ("10/350", 10.0, 350.0),
    ("8/20", 8.0, 20.0),
    ("1.2/50", 1.2, 50.0),
)
TOKEN_SPLIT_PATTERN = re.compile(r"[,\t; ]+")
DEGREE_TO_KM = 111.32

def recommend_radius_km(voltage_kv: int | None) -> float:
    """
    根据线路电压等级推荐地闪密度计算的缓冲区半径。

    参考规则（来自参考工程FormDiShanMiDu.cs）：
    - 35/66/110kV → 2.0 km
    - 220/330kV → 3.0 km
    - 500/750/800/1000kV → 5.0 km
    - ±500/±800直流 → 5.0 km
    - 默认（未知或无电压等级） → 2.0 km

    Args:
        voltage_kv: 线路电压等级（kV）

    Returns:
        推荐的缓冲区半径（km）
    """
    if voltage_kv is None:
        return 2.0

    if voltage_kv in (35, 66, 110):
        return 2.0
    elif voltage_kv in (220, 330):
        return 3.0
    elif voltage_kv in (500, 750, 800, 1000):
        return 5.0
    else:
        return 2.0

@dataclass
class ParsedSeries:
    currents_ka: list[float]
    time_us: list[float] | None
    warnings: list[str]

@dataclass
class WaveFeatures:
    peak_current_ka: float | None
    peak_abs_current_ka: float | None
    wavefront_time_t1_us: float | None
    half_value_time_t2_us: float | None
    steepness_ka_per_us: float | None
    action_integral_j_ohm: float | None
    wave_shape: str | None
    polarity: LightningPolarity
    stroke_count: int
    stroke_peaks_json: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# 雷电流幅值（LightningAmplitude）服务函数
# ---------------------------------------------------------------------------
def _serialize_amplitude(amp: LightningAmplitude, *, backfill_line_count: int = 0) -> LightningAmplitudeRecord:
    """把 LightningAmplitude ORM 对象序列化为 schema。"""
    return LightningAmplitudeRecord(
        id=amp.id,
        event_id=amp.event_id,
        source_file_name=amp.source_file_name,
        event_time=amp.event_time,
        source_object_key=amp.source_object_key,
        status=amp.status,
        progress=amp.progress,
        task_id=amp.task_id,
        error_message=amp.error_message,
        sample_count=amp.sample_count,
        sample_interval_us=amp.sample_interval_us,
        sampling_frequency_hz=amp.sampling_frequency_hz,
        peak_current_ka=amp.peak_current_ka,
        peak_abs_current_ka=amp.peak_abs_current_ka,
        wavefront_time_t1_us=amp.wavefront_time_t1_us,
        half_value_time_t2_us=amp.half_value_time_t2_us,
        steepness_ka_per_us=amp.steepness_ka_per_us,
        action_integral_j_ohm=amp.action_integral_j_ohm,
        wave_shape=amp.wave_shape,
        polarity=amp.polarity,  # type: ignore[arg-type]
        stroke_count=amp.stroke_count,
        stroke_peaks_json=amp.stroke_peaks_json or [],
        region_id=amp.region_id,
        location_tag=amp.location_tag,
        city=amp.city,
        longitude=amp.longitude,
        latitude=amp.latitude,
        altitude_m=amp.altitude_m,
        sensor_model=amp.sensor_model,
        install_position=amp.install_position,
        weather_level=amp.weather_level,
        pressure_hpa=amp.pressure_hpa,
        humidity_percent=amp.humidity_percent,
        is_synthetic=amp.is_synthetic,
        feature_json=amp.feature_json or {},
        notes=amp.notes,
        backfill_line_count=backfill_line_count,
        create_user=amp.create_user,
        create_date=amp.create_date,
        update_date=amp.update_date,
        update_user=amp.update_user,
    )


def get_lightning_amplitude_by_id(db: Session, amplitude_id: str) -> LightningAmplitude | None:
    return db.execute(
        select(LightningAmplitude).where(LightningAmplitude.id == amplitude_id)
    ).scalar_one_or_none()


def _resolve_import_content(
    *,
    file: UploadFile | None,
    temp_file_id: str | None,
    actor_user_id: str,
) -> tuple[bytes, str]:
    """从上传文件或临时文件标识解析导入内容与原始文件名。

    优先使用 temp_file_id（两段式上传流程），
    兼容传统 file 上传参数（向后兼容 multipart 调用方）。

    Returns:
        (content: bytes, source_file_name: str)
    """
    from ..core.file_upload import resolve_temp_upload

    if temp_file_id:
        content, source_file_name = resolve_temp_upload(temp_file_id, actor_user_id)
        return content, source_file_name

    if file is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件，请提供 file 或 temp_file_id")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")
    source_file_name = _normalize_str(str(file.filename or "upload")) or "upload"
    return content, source_file_name


def _validate_amplitude_content(content: bytes, source_file_name: str) -> None:
    """导入前格式预校验：雷电流幅值源文件应为纯数值文本（每行一个或多个数字）。

    全坏或有效比例过低（<10%）直接 400 拒绝，避免无效文件入库后后台任务空跑。
    幅值文件期望格式：每行 1 个电流值（如 -15.3），或「时间 电流」两列（如 0.0001 -15.3）。
    """
    text = _decode_text_bytes(content)
    total_lines = len([ln for ln in text.splitlines() if ln.strip()])
    if total_lines == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件「{source_file_name}」为空，无有效数据行",
        )

    parsed = _parse_current_series(text)
    valid = len(parsed.currents_ka)
    if valid == 0 or (valid / total_lines) < 0.1:
        sample_line = next(
            (ln.strip() for ln in text.splitlines() if ln.strip()),
            "",
        )[:120]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"文件「{source_file_name}」格式不符合要求："
                f"共 {total_lines} 行数据，仅解析出 {valid} 个有效采样点"
                f"（期望每行 1 个电流值，如「-15.3」；或「时间 电流」两列，如「0.0001 -15.3」）。"
                f"示例行：{sample_line!r}。请检查文件后重新上传。"
            ),
        )


def import_lightning_amplitude_from_file(
    db: Session,
    *,
    file: UploadFile | None = None,
    temp_file_id: str | None = None,
    actor_user_id: str,
    event_id: str | None,
    event_time: datetime | None,
    sample_interval_us: float | None,
    region_id: str | None,
    location_tag: str | None,
    city: str | None,
    longitude: float | None,
    latitude: float | None,
    altitude_m: float | None,
    sensor_model: str | None,
    install_position: str | None,
    weather_level: str | None,
    pressure_hpa: float | None,
    humidity_percent: float | None,
    is_synthetic: bool,
    notes: str | None,
) -> LightningAmplitudeImportResponse:
    """上传文件或引用临时文件 → 立即 put_object 到 MinIO → 建 LightningAmplitude(pending) → 派发 Celery。

    与 import_lightning_distribution_from_file 同一异步模式：
    源文件只存 MinIO，不再写容器临时盘；采样明细不落库。
    """
    content, source_file_name = _resolve_import_content(file=file, temp_file_id=temp_file_id, actor_user_id=actor_user_id)
    # 格式预校验：坏文件（全坏 / 有效比例 <10%）直接 400 拒绝，不进 MinIO 不派发任务
    _validate_amplitude_content(content, source_file_name)

    from ..services.minio_storage import build_amplitude_source_key, put_object
    from uuid import uuid4 as _uuid4

    source_key = build_amplitude_source_key(source_file_name)
    put_object(source_key, content, content_type="text/plain")

    normalized_event_id = _normalize_str(event_id)
    # 事件编号唯一：用户显式填写时校验不重复，为空则由任务内自动生成
    if normalized_event_id:
        existing = db.execute(
            select(LightningAmplitude).where(
                func.lower(LightningAmplitude.event_id) == normalized_event_id.lower()
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"事件编号已存在：{normalized_event_id}")

    _now = utcnow()
    amp = LightningAmplitude(
        id=_uuid4().hex,
        event_id=normalized_event_id,
        source_file_name=source_file_name,
        source_object_key=source_key,
        status="pending",
        progress=0,
        event_time=event_time,
        sample_interval_us=sample_interval_us,
        region_id=_normalize_str(region_id),
        location_tag=_normalize_str(location_tag),
        city=_normalize_str(city),
        longitude=longitude,
        latitude=latitude,
        altitude_m=altitude_m,
        sensor_model=_normalize_str(sensor_model),
        install_position=_normalize_str(install_position),
        weather_level=_normalize_str(weather_level),
        pressure_hpa=pressure_hpa,
        humidity_percent=humidity_percent,
        is_synthetic=bool(is_synthetic),
        notes=_normalize_str(notes),
        create_user=actor_user_id,
        create_date=_now,
        update_date=_now,
        update_user=actor_user_id,
    )
    db.add(amp)
    db.commit()

    write_audit_log(
        db,
        action="lightning.amplitude.import",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"amplitude_id={amp.id}",
            f"source_file={source_file_name}",
            f"event_id={normalized_event_id or '(自动生成)'}",
        ),
    )
    db.commit()

    from ..core.celery_app import celery_app as _celery_app
    _task = _celery_app.send_task(
        "app.tasks.lightning_tasks.import_lightning_amplitude_job",
        kwargs=dict(
            amplitude_id=amp.id,
            actor_user_id=actor_user_id,
        ),
        queue="celery",
    )
    amp.task_id = str(_task.id)
    amp.status = "processing"
    db.commit()

    return LightningAmplitudeImportResponse(
        amplitude_id=amp.id,
        task_id=str(_task.id),
        status="processing",
    )


def list_lightning_amplitudes(
    db: Session,
    *,
    keyword: str | None = None,
    status_filter: str | None = None,
    region_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LightningAmplitudeListResponse:
    """列出雷电流幅值记录（元数据 + 状态 + 波形特征统计）。"""
    filters: list[Any] = []
    if keyword:
        keyword_pattern = f"%{keyword}%"
        filters.append(
            or_(
                LightningAmplitude.source_file_name.ilike(keyword_pattern),
                LightningAmplitude.event_id.ilike(keyword_pattern),
                LightningAmplitude.location_tag.ilike(keyword_pattern),
                LightningAmplitude.city.ilike(keyword_pattern),
            )
        )
    if status_filter:
        normalized_status = _normalize_str(status_filter)
        if normalized_status:
            filters.append(LightningAmplitude.status == normalized_status)
    if region_id:
        filters.append(LightningAmplitude.region_id == region_id)

    total = db.execute(
        select(func.count()).select_from(LightningAmplitude).where(*filters)
    ).scalar() or 0
    rows = db.execute(
        select(LightningAmplitude)
        .where(*filters)
        .order_by(LightningAmplitude.create_date.desc(), LightningAmplitude.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    # 回填关联线路数：按 amplitude_id 分组统计关联表行数（避免 N+1）
    amplitude_ids = [item.id for item in rows]
    backfill_counts: dict[str, int] = {}
    if amplitude_ids:
        count_rows = db.execute(
            select(LineAmplitudeBackfill.amplitude_id, func.count())
            .where(LineAmplitudeBackfill.amplitude_id.in_(amplitude_ids))
            .group_by(LineAmplitudeBackfill.amplitude_id)
        ).all()
        backfill_counts = {str(amp_id): int(count or 0) for amp_id, count in count_rows}

    return LightningAmplitudeListResponse(
        items=[
            _serialize_amplitude(a, backfill_line_count=int(backfill_counts.get(a.id, 0)))
            for a in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_lightning_amplitude_detail(
    db: Session,
    amplitude_id: str,
) -> LightningAmplitudeRecord:
    """单条详情（含全部特征字段 + 状态）。"""
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")
    return _serialize_amplitude(amp)


def get_lightning_amplitude_status(
    db: Session,
    amplitude_id: str,
) -> LightningAmplitudeStatusResponse:
    """轮询任务进度（status/progress）。"""
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")
    return LightningAmplitudeStatusResponse(
        amplitude_id=amp.id,
        status=amp.status,
        progress=amp.progress,
        error_message=amp.error_message,
        record=_serialize_amplitude(amp),
    )


def get_backfill_lines_for_amplitude(
    db: Session,
    amplitude_id: str,
    *,
    keyword: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> LightningAmplitudeBackfillLineListResponse:
    """查询一条雷电流幅值记录被哪些线路回填使用过（回填线路小窗）。

    反查路径：`line_amplitude_backfill` WHERE amplitude_id = ? JOIN power_line，
    按 prepared_at 倒序（最近一次回填在前）；支持线路编号/名称关键词与分页。
    """
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")

    rows = db.execute(
        select(LineAmplitudeBackfill)
        .where(LineAmplitudeBackfill.amplitude_id == amplitude_id)
        .order_by(LineAmplitudeBackfill.prepared_at.desc(), LineAmplitudeBackfill.create_date.desc())
    ).scalars().all()

    kw = (keyword or "").strip().lower()
    items: list[LightningAmplitudeBackfillLine] = []
    for row in rows:
        line = row.line
        if kw:
            haystack = f"{(line.code or '')} {(line.name or '')}".lower()
            if kw not in haystack:
                continue
        items.append(
            LightningAmplitudeBackfillLine(
                line_id=row.line_id,
                line_code=line.code if line else None,
                line_name=line.name if line else None,
                voltage_kv=line.voltage_kv if line else None,
                prepared_at=row.prepared_at,
                current_a=row.current_a,
                current_b=row.current_b,
                peak_max=row.peak_max,
                peak_min=row.peak_min,
                sampled_event_count=row.sampled_event_count,
            )
        )
    total = len(items)
    if limit is not None:
        items = items[offset: offset + limit]
    elif offset:
        items = items[offset:]
    return LightningAmplitudeBackfillLineListResponse(items=items, total=total)


def get_backfill_task_detail_for_amplitude_line(
    db: Session,
    amplitude_id: str,
    line_id: str,
) -> LightningCurrentBackfillTaskDetail:
    """某幅值在某线路上的回填明细（含每塔回填前/后幅值与变化量）。

    幅值回填会按线路写入 `lightning_current_backfill_task`，并在
    `source_amplitude_ids`（JSON 字符串数组）中记录来源幅值 id；
    这里取最近一条匹配记录，复用任务详情序列化，保证与"回填任务详情"口径一致。
    """
    rows = db.execute(
        select(LightningCurrentBackfillTask)
        .where(LightningCurrentBackfillTask.line_id == line_id)
        .order_by(
            LightningCurrentBackfillTask.prepared_at.desc(),
            LightningCurrentBackfillTask.create_date.desc(),
        )
        .limit(100)
    ).scalars().all()
    task = next(
        (row for row in rows if amplitude_id in (row.source_amplitude_ids or [])),
        None,
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该线路在此幅值下没有可展示的回填明细",
        )
    return get_lightning_current_backfill_task_detail(db, task.id)


def retry_lightning_amplitude(
    db: Session,
    amplitude_id: str,
    actor_user_id: str,
) -> LightningAmplitudeImportResponse:
    """失败重试：重置状态并重新派发导入任务。"""
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")
    if not amp.source_object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="记录缺少 MinIO 源文件引用，无法重试",
        )
    amp.status = "pending"
    amp.progress = 0
    amp.error_message = None
    amp.update_user = actor_user_id
    db.commit()

    from ..core.celery_app import celery_app as _celery_app
    _task = _celery_app.send_task(
        "app.tasks.lightning_tasks.import_lightning_amplitude_job",
        kwargs=dict(amplitude_id=amp.id, actor_user_id=actor_user_id),
        queue="celery",
    )
    amp.task_id = str(_task.id)
    amp.status = "processing"
    db.commit()

    return LightningAmplitudeImportResponse(
        amplitude_id=amp.id,
        task_id=str(_task.id),
        status="processing",
    )


def delete_lightning_amplitude(db: Session, amplitude_id: str) -> dict[str, bool]:
    """删除雷电流幅值记录，并同步删除 MinIO 上的源文件。"""
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        return {"success": False}
    from ..services import minio_storage
    if amp.source_object_key:
        try:
            minio_storage.delete_object(amp.source_object_key)
        except Exception:
            pass
    db.delete(amp)
    db.commit()
    _publish_lightning_change(
        "lightning.deleted",
        {"event_id": amp.id, "message": f"删除雷电流幅值记录：{amp.source_file_name}"},
        topic=LIGHTNING_AMPLITUDE_TOPIC,
        requires_refetch=["/api/v1/lightning-currents/amplitudes"],
    )
    return {"success": True}


def update_lightning_amplitude(
    db: Session,
    amplitude_id: str,
    payload: LightningAmplitudeUpdateRequest,
    actor_user_id: str,
) -> LightningAmplitudeRecord:
    """更新雷电流幅值记录的元数据信息（仅允许修改可编辑元信息字段）。"""
    amp = get_lightning_amplitude_by_id(db, amplitude_id)
    if not amp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")

    # 逐字段更新（仅更新非 None 的字段）
    update_fields = {
        "event_id": payload.event_id,
        "event_time": payload.event_time,
        "sample_interval_us": payload.sample_interval_us,
        "location_tag": payload.location_tag,
        "city": payload.city,
        "longitude": payload.longitude,
        "latitude": payload.latitude,
        "altitude_m": payload.altitude_m,
        "sensor_model": payload.sensor_model,
        "install_position": payload.install_position,
        "weather_level": payload.weather_level,
        "pressure_hpa": payload.pressure_hpa,
        "humidity_percent": payload.humidity_percent,
        "is_synthetic": payload.is_synthetic,
        "notes": payload.notes,
    }
    for field_name, value in update_fields.items():
        if value is not None:
            setattr(amp, field_name, value)

    amp.update_user = actor_user_id
    db.commit()
    db.refresh(amp)

    _publish_lightning_change(
        "lightning.updated",
        {"event_id": amp.id, "message": f"更新雷电流幅值记录：{amp.source_file_name}"},
        topic=LIGHTNING_AMPLITUDE_TOPIC,
        requires_refetch=["/api/v1/lightning-currents/amplitudes"],
    )
    return _serialize_amplitude(amp)


def get_peak_exceedance_curve(
    db: Session,
    *,
    region_id: str | None,
    polarity: str | None,
    wave_shape: str | None,
    is_synthetic: bool | None,
    thresholds_ka: list[float] | None,
    default_points: int = 12,
) -> LightningCurrentExceedanceResponse:
    """峰值超越概率 P 曲线：聚合 LightningAmplitude.peak_abs_current_ka（仅 completed 记录）。"""
    filters: list[Any] = [
        LightningAmplitude.peak_abs_current_ka.is_not(None),
        LightningAmplitude.status == "completed",
    ]

    normalized_region = _normalize_str(region_id)
    if normalized_region:
        filters.append(LightningAmplitude.region_id == normalized_region)
    normalized_polarity = _normalize_str(polarity)
    if normalized_polarity:
        filters.append(LightningAmplitude.polarity == normalized_polarity.lower())
    normalized_wave_shape = _normalize_str(wave_shape)
    if normalized_wave_shape:
        filters.append(func.lower(LightningAmplitude.wave_shape) == normalized_wave_shape.lower())
    if is_synthetic is not None:
        filters.append(LightningAmplitude.is_synthetic == is_synthetic)

    values = db.execute(select(LightningAmplitude.peak_abs_current_ka).where(*filters)).scalars().all()
    peaks = [float(item) for item in values if item is not None]
    total = len(peaks)
    if total == 0:
        return LightningCurrentExceedanceResponse(total_events=0, thresholds=[])

    manual_thresholds = sorted({float(value) for value in (thresholds_ka or []) if value > 0})
    if manual_thresholds:
        thresholds = manual_thresholds
    else:
        max_peak = max(peaks)
        step = max(1.0, round(max_peak / max(default_points, 1), 3))
        thresholds = [round(step * idx, 3) for idx in range(1, default_points + 1)]

    points: list[LightningCurrentExceedancePoint] = []
    for threshold in thresholds:
        exceedance_count = sum(1 for value in peaks if value >= threshold)
        probability = exceedance_count / total
        points.append(
            LightningCurrentExceedancePoint(
                threshold_ka=threshold,
                exceedance_probability=probability,
                exceedance_count=exceedance_count,
            )
        )

    return LightningCurrentExceedanceResponse(total_events=total, thresholds=points)


def prepare_line_lightning_current(
    db: Session,
    payload: LightningCurrentPreparationRequest,
    *,
    actor_user_id: str,
) -> LightningCurrentPreparationAsyncResponse:
    """提交线路雷电流幅值回填任务（异步）。

    API 层只做前置校验 + 创建 pending 回填任务记录 + 派发 Celery 任务，
    立即返回 task_id。实际计算由 Celery worker 执行
    （prepare_line_lightning_current_job，见 api/app/tasks/lightning_tasks.py）。
    """
    # 前置校验：线路存在
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    # 前置校验：有可用幅值数据（避免空任务排队后才失败）
    if not _has_usable_lightning_amplitudes(db, payload):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未找到可用于线路雷电流拟合的幅值记录（请先导入并等待处理完成）",
        )

    now = utcnow()
    normalized_region = _normalize_str(payload.region_id)
    task = LightningCurrentBackfillTask(
        line_id=line.id,
        prepared_at=now,
        prepared_by_user_id=actor_user_id,
        region_id=normalized_region,
        is_synthetic=bool(payload.is_synthetic),
        status="pending",
        progress=0,
    )
    db.add(task)
    db.commit()

    from ..core.celery_app import celery_app

    celery_task = celery_app.send_task(
        "app.tasks.lightning_tasks.prepare_line_lightning_current_job",
        kwargs={
            "line_id": line.id,
            "region_id": normalized_region,
            "is_synthetic": payload.is_synthetic,
            "backfill_task_id": task.id,
            "actor_user_id": actor_user_id,
        },
        queue="celery",
    )
    task.task_id = str(celery_task.id)
    task.status = "processing"
    db.commit()

    return LightningCurrentPreparationAsyncResponse(
        task_id=str(celery_task.id),
        backfill_task_id=task.id,
        line_id=line.id,
        status="processing",
    )


def _has_usable_lightning_amplitudes(
    db: Session,
    payload: LightningCurrentPreparationRequest,
) -> bool:
    """校验是否存在可用于线路雷电流拟合的 completed 幅值记录。"""
    filters: list[Any] = [
        LightningAmplitude.status == "completed",
        LightningAmplitude.source_object_key != "",
    ]
    normalized_region = _normalize_str(payload.region_id)
    if normalized_region:
        filters.append(LightningAmplitude.region_id == normalized_region)
    if payload.is_synthetic is not None:
        filters.append(LightningAmplitude.is_synthetic == payload.is_synthetic)
    count = db.execute(select(func.count()).select_from(LightningAmplitude).where(*filters)).scalar() or 0
    return count > 0


def _execute_line_lightning_current_backfill(
    db: Session,
    payload: LightningCurrentPreparationRequest,
    *,
    actor_user_id: str,
    backfill_task_id: str | None = None,
) -> LightningCurrentPreparationResponse:
    """在 Celery worker 中执行线路雷电流幅值回填的实际计算。

    数据源：线路关联的 LightningAmplitude（completed）→ 按 source_object_key 从 MinIO
    下载源文件 → 实时解析落雷电流集合 → 拟合。禁止直接读库表统计字段做该分析。
    """
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    towers = db.execute(
        select(LineTower)
        .where(LineTower.line_id == line.id)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
    ).scalars().all()
    if not towers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可回填的杆塔数据")

    normalized_region = _normalize_str(payload.region_id)
    filters: list[Any] = [
        LightningAmplitude.status == "completed",
        LightningAmplitude.source_object_key != "",
    ]
    if normalized_region:
        filters.append(LightningAmplitude.region_id == normalized_region)
    if payload.is_synthetic is not None:
        filters.append(LightningAmplitude.is_synthetic == payload.is_synthetic)

    amplitudes = db.execute(
        select(LightningAmplitude)
        .where(*filters)
        .order_by(LightningAmplitude.create_date.desc())
    ).scalars().all()

    if not amplitudes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未找到可用于线路雷电流拟合的幅值记录（请先导入并等待处理完成）",
        )

    from ..services import minio_storage
    peaks: list[float] = []
    used_amplitude_ids: list[str] = []
    for amp in amplitudes:
        try:
            content = minio_storage.get_object(amp.source_object_key)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"读取幅值源文件失败（{amp.source_file_name}）：{exc}",
            ) from exc
        try:
            text = _decode_text_bytes(content)
            parsed = _parse_current_series(text)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"解析幅值源文件失败（{amp.source_file_name}）：{exc}",
            ) from exc
        if not parsed.currents_ka:
            continue
        peak_abs = max(abs(float(value)) for value in parsed.currents_ka)
        if peak_abs > 0:
            peaks.append(peak_abs)
            used_amplitude_ids.append(amp.id)

    if not peaks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到可用于线路雷电流拟合的幅值样本")

    current_a, current_b, peak_max, peak_min, warnings = _fit_line_current_parameters(peaks)
    now = utcnow()
    tower_ids = [tower.id for tower in towers]
    existing_profiles = db.execute(select(TowerProfile).where(TowerProfile.tower_id.in_(tower_ids))).scalars().all()
    profile_map = {item.tower_id: item for item in existing_profiles}
    created_profile_count = 0

    # 1. 复用/创建回填任务记录（历史快照）
    task = None
    if backfill_task_id:
        task = db.execute(
            select(LightningCurrentBackfillTask).where(LightningCurrentBackfillTask.id == backfill_task_id)
        ).scalar_one_or_none()
    if task is None:
        task = LightningCurrentBackfillTask(
            line_id=line.id,
            prepared_at=now,
            prepared_by_user_id=actor_user_id,
            region_id=normalized_region,
            is_synthetic=bool(payload.is_synthetic),
        )
    task.source_amplitude_ids = [amp_id for amp_id in used_amplitude_ids]
    task.status = "processing"
    task.progress = 30
    db.add(task)
    db.flush()  # 获取 task.id

    for tower in towers:
        profile = profile_map.get(tower.id)
        prev_a = profile.current_a if profile else None
        prev_b = profile.current_b if profile else None
        created_now = profile is None

        if profile is None:
            profile = TowerProfile(
                tower_id=tower.id,
                extra_profile_json={},
                create_date=now,
                create_user=actor_user_id,
                update_date=now,
                update_user=actor_user_id,
            )
            db.add(profile)
            profile_map[tower.id] = profile
            created_profile_count += 1

        extra_profile = dict(profile.extra_profile_json or {})
        extra_profile["lightning_current_preparation"] = {
            "line_id": line.id,
            "line_code": line.code,
            "current_a": current_a,
            "current_b": current_b,
            "peak_max": peak_max,
            "peak_min": peak_min,
            "sampled_event_count": len(peaks),
            "region_id": normalized_region,
            "is_synthetic": payload.is_synthetic,
            "prepared_at": now.isoformat(),
        }
        profile.current_a = current_a
        profile.current_b = current_b
        profile.current_type = "line_prepared"
        profile.extra_profile_json = extra_profile
        profile.update_date = now
        profile.update_user = actor_user_id

        # 2. 记录每条杆塔回填明细（快照）
        db.add(
            LightningCurrentBackfillTower(
                task_id=task.id,
                tower_id=tower.id,
                current_a=current_a,
                current_b=current_b,
                previous_current_a=prev_a,
                previous_current_b=prev_b,
                action="created" if created_now else "updated",
            )
        )

    # 3. 更新任务汇总
    task.current_a = current_a
    task.current_b = current_b
    task.peak_max = peak_max
    task.peak_min = peak_min
    task.sampled_event_count = len(peaks)
    task.updated_tower_count = len(towers)
    task.created_profile_count = created_profile_count
    task.warnings = warnings

    line_params = dict(line.lightning_param_json or {})
    line_params["雷电流幅值a"] = current_a
    line_params["雷电流幅值b"] = current_b
    line.lightning_param_json = line_params
    line.update_date = now
    line.update_user = actor_user_id
    record_line_preparation_source(
        line,
        component="lightning_current",
        payload={
            "prepared_at": now.isoformat(),
            "prepared_by_user_id": actor_user_id,
            "sampled_event_count": len(peaks),
            "region_id": normalized_region,
            "is_synthetic": payload.is_synthetic,
            "current_a": current_a,
            "current_b": current_b,
            "peak_max": peak_max,
            "peak_min": peak_min,
        },
    )

    # 记录本次回填实际用到的 amplitude ↔ line 关联（幂等 upsert：已存在则覆盖为本次为准）
    if used_amplitude_ids:
        existing_backfills = db.execute(
            select(LineAmplitudeBackfill).where(
                LineAmplitudeBackfill.line_id == line.id,
                LineAmplitudeBackfill.amplitude_id.in_(used_amplitude_ids),
            )
        ).scalars().all()
        backfill_by_amplitude = {item.amplitude_id: item for item in existing_backfills}
        for amplitude_id in used_amplitude_ids:
            backfill = backfill_by_amplitude.get(amplitude_id)
            if backfill is None:
                backfill = LineAmplitudeBackfill(
                    line_id=line.id,
                    amplitude_id=amplitude_id,
                    create_user=actor_user_id,
                    create_date=now,
                    update_user=actor_user_id,
                )
                db.add(backfill)
                backfill_by_amplitude[amplitude_id] = backfill
            backfill.prepared_at = now
            backfill.prepared_by_user_id = actor_user_id
            backfill.sampled_event_count = len(peaks)
            backfill.current_a = current_a
            backfill.current_b = current_b
            backfill.peak_max = peak_max
            backfill.peak_min = peak_min
            backfill.region_id = normalized_region
            backfill.is_synthetic = bool(payload.is_synthetic)
            backfill.update_date = now
            backfill.update_user = actor_user_id
    db.commit()

    # 标记任务完成
    task.status = "completed"
    task.progress = 100
    db.commit()

    preparation_json = summarize_line_preparation(db, line, tower_count=len(towers))
    _publish_line_change(
        "power-lines.lightning-current.prepared",
        {"action": "lightning_current_prepared", "line_id": line.id},
    )
    return LightningCurrentPreparationResponse(
        line=serialize_line(line, tower_count=len(towers), preparation_json=preparation_json),
        current_a=current_a,
        current_b=current_b,
        peak_max=peak_max,
        peak_min=peak_min,
        sampled_event_count=len(peaks),
        updated_tower_count=len(towers),
        created_profile_count=created_profile_count,
        warning_count=len(warnings),
        warnings=warnings,
    )

def _safe_km_per_lon(latitude: float) -> float:
    factor = abs(math.cos(math.radians(latitude)))
    return max(DEGREE_TO_KM * factor, 1e-6)

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * (math.sin(delta_lon / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(1.0 - a, 0.0)))
    return radius_km * c

def _parse_current_series(text: str) -> ParsedSeries:
    rows: list[tuple[float | None, float]] = []
    warnings: list[str] = []
    explicit_time_rows = 0

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue

        tokens = [token for token in TOKEN_SPLIT_PATTERN.split(stripped) if token]
        if not tokens:
            continue

        parsed_pair = _parse_two_numbers(tokens)
        if parsed_pair is not None:
            rows.append(parsed_pair)
            explicit_time_rows += 1
            continue

        current_value = _parse_last_number(tokens)
        if current_value is None:
            if len(warnings) < 20:
                warnings.append(f"第 {line_no} 行未识别为数值，已跳过")
            continue
        rows.append((None, current_value))

    if not rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件中未解析到有效数值序列")

    currents = [item[1] for item in rows]
    time_axis: list[float] | None = None
    if explicit_time_rows == len(rows):
        time_axis = [float(item[0]) for item in rows if item[0] is not None]
    elif explicit_time_rows > 0:
        warnings.append("检测到部分行存在时间列但并不完整，已统一按采样间隔重建时间轴")

    return ParsedSeries(currents_ka=currents, time_us=time_axis, warnings=warnings)

def _parse_two_numbers(tokens: list[str]) -> tuple[float, float] | None:
    if len(tokens) < 2:
        return None
    first = _parse_float(tokens[0])
    second = _parse_float(tokens[1])
    if first is None or second is None:
        return None
    return (first, second)

def _parse_last_number(tokens: list[str]) -> float | None:
    for token in reversed(tokens):
        parsed = _parse_float(token)
        if parsed is not None:
            return parsed
    return None

def _build_time_axis(
    raw_time_us: list[float] | None,
    *,
    sample_interval_us: float | None,
    sample_count: int,
) -> tuple[list[float], float, float | None, list[str]]:
    warnings: list[str] = []
    if raw_time_us and len(raw_time_us) == sample_count:
        base_time = raw_time_us[0]
        normalized = [float(item - base_time) for item in raw_time_us]
        positive_deltas: list[float] = []
        monotonic = True
        for idx in range(1, len(normalized)):
            delta = normalized[idx] - normalized[idx - 1]
            if delta <= 0:
                monotonic = False
                break
            positive_deltas.append(delta)

        if monotonic and positive_deltas:
            inferred_interval = _median(positive_deltas)
            inferred_frequency = 1_000_000.0 / inferred_interval if inferred_interval > 0 else None
            return normalized, inferred_interval, inferred_frequency, warnings

        warnings.append("时间列非严格递增，已改用固定采样间隔重建时间轴")

    interval = sample_interval_us if sample_interval_us is not None else 1.0
    if interval <= 0:
        warnings.append("采样间隔必须大于 0，已回退到 1.0us")
        interval = 1.0
    if sample_interval_us is None:
        warnings.append("未提供采样间隔，默认按 1.0us 计算")

    axis = [float(idx) * interval for idx in range(sample_count)]
    fs = 1_000_000.0 / interval if interval > 0 else None
    return axis, interval, fs, warnings

def _extract_wave_features(currents_ka: list[float], time_axis_us: list[float], sample_interval_us: float) -> WaveFeatures:
    sample_count = len(currents_ka)
    if sample_count == 0:
        return WaveFeatures(
            peak_current_ka=None,
            peak_abs_current_ka=None,
            wavefront_time_t1_us=None,
            half_value_time_t2_us=None,
            steepness_ka_per_us=None,
            action_integral_j_ohm=None,
            wave_shape=None,
            polarity="unknown",
            stroke_count=0,
            stroke_peaks_json=[],
        )

    max_val = max(currents_ka)
    min_val = min(currents_ka)

    polarity: LightningPolarity
    if math.isclose(max_val, 0.0, abs_tol=1e-12) and math.isclose(min_val, 0.0, abs_tol=1e-12):
        polarity = "unknown"
    elif abs(max_val) > abs(min_val):
        polarity = "positive"
    elif abs(min_val) > abs(max_val):
        polarity = "negative"
    else:
        polarity = "mixed"

    peak_idx = max(range(sample_count), key=lambda idx: abs(currents_ka[idx]))
    peak_current = float(currents_ka[peak_idx])
    peak_abs = abs(peak_current)

    dominant_sign = 1.0 if peak_current >= 0 else -1.0
    aligned = [dominant_sign * value for value in currents_ka]
    aligned_peak = aligned[peak_idx]

    steepness = _compute_max_steepness(aligned, time_axis_us, peak_idx)
    t10 = _find_up_crossing_time(time_axis_us, aligned, 0.1 * aligned_peak, peak_idx)
    t90 = _find_up_crossing_time(time_axis_us, aligned, 0.9 * aligned_peak, peak_idx)
    wavefront_time_t1: float | None = None
    t0_virtual: float | None = None
    if t10 is not None and t90 is not None and t90 > t10:
        wavefront_time_t1 = 1.25 * (t90 - t10)
        t0_virtual = t10 - 0.125 * (t90 - t10)

    t50 = _find_down_crossing_time(time_axis_us, aligned, 0.5 * aligned_peak, peak_idx)
    half_value_time_t2: float | None = None
    if t50 is not None:
        if t0_virtual is not None:
            half_value_time_t2 = max(t50 - t0_virtual, 0.0)
        else:
            half_value_time_t2 = max(t50 - time_axis_us[0], 0.0)

    action_integral = _compute_action_integral(currents_ka, time_axis_us, fallback_interval=sample_interval_us)
    wave_shape = _classify_wave_shape(wavefront_time_t1, half_value_time_t2)
    stroke_peaks = _detect_multiple_strokes(
        currents_ka=currents_ka,
        time_axis_us=time_axis_us,
        dominant_sign=dominant_sign,
        peak_abs=peak_abs,
        sample_interval_us=sample_interval_us,
    )

    return WaveFeatures(
        peak_current_ka=peak_current,
        peak_abs_current_ka=peak_abs,
        wavefront_time_t1_us=wavefront_time_t1,
        half_value_time_t2_us=half_value_time_t2,
        steepness_ka_per_us=steepness,
        action_integral_j_ohm=action_integral,
        wave_shape=wave_shape,
        polarity=polarity,
        stroke_count=len(stroke_peaks),
        stroke_peaks_json=stroke_peaks,
    )

def _compute_max_steepness(aligned: list[float], time_axis_us: list[float], peak_idx: int) -> float | None:
    max_slope: float | None = None
    for idx in range(1, peak_idx + 1):
        dt = time_axis_us[idx] - time_axis_us[idx - 1]
        if dt <= 0:
            continue
        slope = (aligned[idx] - aligned[idx - 1]) / dt
        if max_slope is None or slope > max_slope:
            max_slope = slope
    return max_slope

def _find_up_crossing_time(
    time_axis_us: list[float],
    signal: list[float],
    threshold: float,
    end_idx: int,
) -> float | None:
    if end_idx <= 0:
        return None
    for idx in range(1, end_idx + 1):
        left = signal[idx - 1]
        right = signal[idx]
        if left == threshold:
            return time_axis_us[idx - 1]
        if left < threshold <= right:
            return _interpolate_time(
                time_axis_us[idx - 1],
                time_axis_us[idx],
                left,
                right,
                threshold,
            )
    return None

def _find_down_crossing_time(
    time_axis_us: list[float],
    signal: list[float],
    threshold: float,
    start_idx: int,
) -> float | None:
    if start_idx >= len(signal) - 1:
        return None
    for idx in range(start_idx + 1, len(signal)):
        left = signal[idx - 1]
        right = signal[idx]
        if left == threshold:
            return time_axis_us[idx - 1]
        if left >= threshold > right:
            return _interpolate_time(
                time_axis_us[idx - 1],
                time_axis_us[idx],
                left,
                right,
                threshold,
            )
    return None

def _interpolate_time(x1: float, x2: float, y1: float, y2: float, target: float) -> float:
    if math.isclose(y1, y2):
        return x2
    ratio = (target - y1) / (y2 - y1)
    return x1 + ratio * (x2 - x1)

def _compute_action_integral(currents_ka: list[float], time_axis_us: list[float], *, fallback_interval: float) -> float:
    if len(currents_ka) < 2:
        return 0.0

    total = 0.0
    for idx in range(1, len(currents_ka)):
        dt = time_axis_us[idx] - time_axis_us[idx - 1]
        if dt <= 0:
            dt = fallback_interval
        average_i2 = ((currents_ka[idx - 1] ** 2) + (currents_ka[idx] ** 2)) / 2.0
        total += average_i2 * dt
    return total

def _classify_wave_shape(t1_us: float | None, t2_us: float | None) -> str | None:
    if t1_us is None or t2_us is None or t1_us <= 0 or t2_us <= 0:
        return None

    best_name: str | None = None
    best_score = float("inf")
    for name, std_t1, std_t2 in STANDARD_WAVE_SHAPES:
        score = ((t1_us - std_t1) / std_t1) ** 2 + ((t2_us - std_t2) / std_t2) ** 2
        if score < best_score:
            best_name = name
            best_score = score
    return best_name

def _detect_multiple_strokes(
    *,
    currents_ka: list[float],
    time_axis_us: list[float],
    dominant_sign: float,
    peak_abs: float,
    sample_interval_us: float,
) -> list[dict[str, Any]]:
    if not currents_ka:
        return []

    aligned = [dominant_sign * item for item in currents_ka]
    threshold = max(peak_abs * 0.3, 5.0)
    min_gap_us = 80.0
    min_gap_samples = max(1, int(round(min_gap_us / max(sample_interval_us, 1e-9))))

    peak_indices: list[int] = []
    for idx in range(1, len(aligned) - 1):
        current = aligned[idx]
        if current < threshold:
            continue
        if current >= aligned[idx - 1] and current > aligned[idx + 1]:
            if peak_indices and idx - peak_indices[-1] < min_gap_samples:
                if current > aligned[peak_indices[-1]]:
                    peak_indices[-1] = idx
                continue
            peak_indices.append(idx)

    if not peak_indices:
        dominant_idx = max(range(len(currents_ka)), key=lambda idx: abs(currents_ka[idx]))
        peak_indices = [dominant_idx]

    limited = peak_indices[:20]
    return [
        {
            "seq_no": order + 1,
            "sample_index": idx + 1,
            "time_us": time_axis_us[idx],
            "current_ka": currents_ka[idx],
        }
        for order, idx in enumerate(limited)
    ]

def _decode_text_bytes(content: bytes) -> str:
    for encoding in TEXT_ENCODINGS:
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件编码不受支持")

def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None

def _fit_line_current_parameters(values: list[float]) -> tuple[float, float, float, float, list[str]]:
    cleaned = sorted(abs(float(item)) for item in values)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="雷电流幅值样本为空")

    warnings: list[str] = []
    unique_values = {round(item, 6) for item in cleaned}
    if len(unique_values) == 1:
        return round(cleaned[0], 3), 2.6, round(cleaned[0], 3), round(cleaned[0], 3), ["样本幅值单一，已使用默认 b=2.6"]

    peak_max = max(cleaned)
    peak_min = min(cleaned)
    thresholds = [peak_max]
    probabilities = [1.0 / len(cleaned)]
    current = peak_max
    while current > peak_min:
        current = round(current - 0.1, 10)
        thresholds.append(current)
        exceedance_count = sum(1 for item in cleaned if item >= current)
        probabilities.append(exceedance_count / len(cleaned))

    lower_index: int | None = None
    upper_index: int | None = None
    best_lower = -1.0
    best_upper = 1.0
    for index, probability in enumerate(probabilities):
        delta = probability - 0.5
        if delta < 0:
            if delta > best_lower:
                best_lower = delta
                lower_index = index
        else:
            if delta < best_upper:
                best_upper = delta
                upper_index = index

    if lower_index is None or upper_index is None or lower_index == upper_index:
        current_a = _median(cleaned)
        warnings.append("样本分布不足以插值求解 a，已回退到中位数")
    else:
        upper_probability = probabilities[upper_index]
        lower_probability = probabilities[lower_index]
        upper_threshold = thresholds[upper_index]
        lower_threshold = thresholds[lower_index]
        denominator = lower_probability - upper_probability
        if abs(denominator) < 1e-9:
            current_a = _median(cleaned)
            warnings.append("样本概率分布异常，已回退到中位数")
        else:
            current_a = (0.5 - upper_probability) * (lower_threshold - upper_threshold) / denominator + upper_threshold

    exponent_values: list[float] = []
    if current_a <= 0:
        current_a = _median(cleaned)
        warnings.append("样本拟合得到的 a 非法，已回退到中位数")
    for threshold, probability in zip(thresholds[:-1], probabilities[:-1], strict=False):
        if probability <= 0 or probability >= 1:
            continue
        if threshold <= current_a:
            continue
        denominator = math.log(threshold / current_a)
        if abs(denominator) < 1e-9:
            continue
        numerator = math.log(1.0 / probability - 1.0)
        exponent = numerator / denominator
        if math.isfinite(exponent):
            exponent_values.append(exponent)

    if exponent_values:
        current_b = sum(exponent_values) / len(exponent_values)
    else:
        current_b = 2.6
        warnings.append("样本分布不足以稳定拟合 b，已使用默认 b=2.6")

    return round(current_a, 3), round(current_b, 3), round(peak_max, 3), round(peak_min, 3), warnings

def _normalize_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    n = len(sorted_values)
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_values[mid])
    return float((sorted_values[mid - 1] + sorted_values[mid]) / 2.0)

def _generate_event_id() -> str:
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"LC-{now}-{uuid4().hex[:6]}"

def _publish_line_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            POWER_LINES_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lines"],
            dedupe_key=f"{event_name}:{payload.get('line_id', 'unknown')}",
        )
    )


def _publish_backfill_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.lightning-current-backfill 主题推送回填任务事件（经 Redis 桥）。

    供 Celery worker 使用；Web 进程场景下 publish_topic 同样可行，
    统一走 _fire_and_forget 异步投递，失败不影响任务主体逻辑。
    """
    _fire_and_forget(
        publish_topic(
            LIGHTNING_CURRENT_BACKFILL_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents/backfill-tasks"],
            dedupe_key=f"{event_name}:{payload.get('backfill_task_id', payload.get('line_id', 'unknown'))}",
        )
    )


def _publish_lightning_change(event_name: str, payload: dict[str, Any], topic: str = LIGHTNING_DISTRIBUTION_TOPIC, requires_refetch: list[str] | None = None) -> None:
    if requires_refetch is None:
        if topic == LIGHTNING_AMPLITUDE_TOPIC:
            requires_refetch = ["/api/v1/lightning-currents/amplitudes"]
        else:
            requires_refetch = ["/api/v1/lightning-currents/distributions"]
    _fire_and_forget(
        publish_topic(
            topic,
            name=event_name,
            payload=payload,
            requires_refetch=requires_refetch,
            dedupe_key=f"{event_name}:{payload.get('event_id', 'unknown')}",
        )
    )

def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行中的事件循环（例如 Celery worker 同步线程），直接同步执行协程。
        try:
            asyncio.run(coro)  # type: ignore[arg-type]
        except Exception:
            pass
        return
    loop.create_task(coro)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 地闪分布（LightningDistribution）服务函数
# ---------------------------------------------------------------------------
def _serialize_distribution(
    dist: LightningDistribution,
    *,
    linked_line_count: int | None = None,
) -> LightningDistributionRecord:
    """把 LightningDistribution ORM 对象序列化为 schema。"""
    # 兜底剥离 grid_cells（历史数据或再次引入时防御），防止列表接口响应体过大。
    _stats_json = dist.stats_json
    if isinstance(_stats_json, dict) and "grid_cells" in _stats_json:
        _stats_json = {k: v for k, v in _stats_json.items() if k != "grid_cells"}
    return LightningDistributionRecord(
        id=dist.id,
        region_id=dist.region_id,
        location_tag=dist.location_tag,
        city=dist.city,
        event_year=dist.event_year,
        line_id=dist.line_id,
        source_file_name=dist.source_file_name,
        source_object_key=dist.source_object_key,
        import_type=dist.import_type,
        linked_line_count=linked_line_count,
        status=dist.status,
        stage=dist.stage,
        progress=dist.progress,
        task_id=dist.task_id,
        lp_draw_task_id=dist.lp_draw_task_id,
        error_message=dist.error_message,
        total_lines=dist.total_lines,
        valid_count=dist.valid_count,
        skipped_count=dist.skipped_count,
        warning_count=dist.warning_count,
        warnings=dist.warnings,
        area_km2=dist.area_km2,
        data_years=dist.data_years,
        grid_size_km=dist.grid_size_km,
        overall_ng=dist.overall_ng,
        max_abs_current=dist.max_abs_current,
        avg_abs_current=dist.avg_abs_current,
        positive_count=dist.positive_count,
        negative_count=dist.negative_count,
        unknown_count=dist.unknown_count,
        stats_json=_stats_json,
        has_image=bool(dist.image_object_key),
        has_lp_image=bool(dist.lp_image_object_key is not None),
        has_circle_image=bool(dist.circle_image_object_key is not None),
        create_user=dist.create_user,
        create_date=dist.create_date,
        update_date=dist.update_date,
        update_user=dist.update_user,
    )


# ---------------------------------------------------------------------------
# 回填关系反查（关联线路）
# ---------------------------------------------------------------------------
def _as_optional_int(value: Any) -> int | None:
    """安全转 int；None/非数值返回 None。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iter_linked_towers(
    db: Session,
    distribution_id: str,
) -> list[tuple[str, dict[str, Any]]]:
    """查询所有 `raw_extra_json.lightning_density.source_distribution_id == distribution_id` 的杆塔。

    返回 `(line_id, raw_extra_json)` 轻量元组，避免触发 `selectin` 关系加载
    （profile/circuits 等字段本函数用不到）。

    `raw_extra_json` 是 SQLAlchemy JSON 列。PostgreSQL 与 SQLite 的 JSON 路径查询语法
    不同（SQLite 不支持 `.astext` / jsonb 路径），这里采用「SQL 粗筛 + 内存精滤」的
    跨方言稳妥做法：
    - 先按 JSON 文本 LIKE 粗筛（仅包含 `source_distribution_id` 与目标 id），两种方言都可用；
    - 再在 Python 中精确读取 `lightning_density.source_distribution_id` 做等值判断，
      避免 LIKE 命中同名的其他字段。
    """
    if not distribution_id:
        return []
    raw_json_text = cast(LineTower.raw_extra_json, String)
    candidates = db.execute(
        select(LineTower.id, LineTower.line_id, LineTower.raw_extra_json)
        .where(
            raw_json_text.ilike(f"%{distribution_id}%"),
        )
    ).all()

    matched: list[tuple[str, dict[str, Any]]] = []
    for row in candidates:
        tower_line_id, raw_extra = row[1], row[2]
        if not tower_line_id:
            continue
        extra = raw_extra or {}
        density = extra.get("lightning_density")
        if not isinstance(density, dict):
            continue
        if density.get("source_distribution_id") == distribution_id:
            matched.append((tower_line_id, extra))
    return matched


def _collect_linked_lines(
    towers: list[tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """按 line_id 聚合杆塔列表，返回 {line_id: {tower_count, prepared_at}}。"""
    aggregated: dict[str, dict[str, Any]] = {}
    for line_id, extra in towers:
        if not line_id:
            continue
        bucket = aggregated.get(line_id)
        if bucket is None:
            bucket = {
                "line_id": line_id,
                "tower_count": 0,
                "prepared_at": None,
            }
            aggregated[line_id] = bucket
        bucket["tower_count"] += 1
        next_prepared: str | None = None
        density = extra.get("lightning_density")
        if isinstance(density, dict):
            next_prepared = density.get("prepared_at")
        if next_prepared:
            previous = bucket["prepared_at"]
            if previous is None or next_prepared > previous:
                bucket["prepared_at"] = next_prepared
    return aggregated


def _linked_lines_with_line_meta(
    db: Session,
    aggregated: dict[str, dict[str, Any]],
) -> list[LightningLinkedLineSummary]:
    """把按 line_id 聚合的摘要 join Line 元数据，产出响应模型列表。"""
    if not aggregated:
        return []
    line_ids = list(aggregated.keys())
    line_rows = db.execute(
        select(Line.id, Line.code, Line.name, Line.voltage_kv).where(Line.id.in_(line_ids))
    ).all()
    line_map = {row[0]: row for row in line_rows}

    items: list[LightningLinkedLineSummary] = []
    for line_id, bucket in aggregated.items():
        line = line_map.get(line_id)
        items.append(
            LightningLinkedLineSummary(
                line_id=line_id,
                line_code=line[1] if line else None,
                line_name=line[2] if line else None,
                voltage_kv=float(line[3]) if line and line[3] is not None else None,
                tower_count=bucket["tower_count"],
                prepared_at=bucket.get("prepared_at"),
            )
        )
    items.sort(key=lambda item: ((item.line_code or "").upper(), item.line_id))
    return items


def get_linked_lines_for_distribution(
    db: Session,
    distribution_id: str,
) -> LightningLinkedLinesResponse:
    """反查该分布回填过的线路列表，按 line_id 去重聚合。

    返回字段：line_id / line_code / line_name / voltage_kv / tower_count / prepared_at。
    没有任何杆塔引用时返回空列表（total=0）。
    """
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")

    towers = _iter_linked_towers(db, distribution_id)
    aggregated = _collect_linked_lines(towers)
    items = _linked_lines_with_line_meta(db, aggregated)
    return LightningLinkedLinesResponse(items=items, total=len(items))


def get_distribution_linked_line_count(db: Session, distribution_id: str) -> int:
    """统计单个分布被多少条线路的杆塔引用（列表页展示数量）。"""
    towers = _iter_linked_towers(db, distribution_id)
    return len(_collect_linked_lines(towers))


def _validate_distribution_content(content: bytes, source_file_name: str) -> None:
    """导入前格式预校验：地闪密度源文件应为「纬度 经度 电流」空格分隔的文本。

    全坏或有效比例过低（<10%）直接 400 拒绝，避免无效文件入库后后台任务
    空跑（曾出现 128 万行全坏文件导入后统计阶段 0 条落雷的案例）。
    """
    from ..services.lightning_statistics import parse_distribution_content

    text = _decode_text_bytes(content)
    total_lines = len([ln for ln in text.splitlines() if ln.strip()])
    if total_lines == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件「{source_file_name}」为空，无有效数据行",
        )

    warnings: list[str] = []
    strikes = parse_distribution_content(text, warnings=warnings)
    valid = len(strikes)
    if valid == 0 or (valid / total_lines) < 0.1:
        sample_line = next(
            (ln.strip() for ln in text.splitlines() if ln.strip()),
            "",
        )[:120]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"文件「{source_file_name}」格式不符合要求："
                f"共 {total_lines} 行数据，仅解析出 {valid} 条有效落雷"
                f"（期望每行格式：纬度 经度 电流，空格分隔，如「22.54 114.05 -15.3」）。"
                f"示例行：{sample_line!r}。请检查文件后重新上传。"
            ),
        )


def import_lightning_distribution_from_file(
    db: Session,
    *,
    file: UploadFile | None = None,
    temp_file_id: str | None = None,
    actor_user_id: str,
    event_year: int | None,
    data_years: float | None = None,
    region_id: str | None,
    location_tag: str | None,
    city: str | None,
    notes: str | None,
    line_id: str | None = None,
) -> LightningDistributionImportResponse:
    """上传文件或引用临时文件 → 立即 put_object 到 MinIO → 建 LightningDistribution(pending) → 派发 Celery。"""
    content, source_file_name = _resolve_import_content(file=file, temp_file_id=temp_file_id, actor_user_id=actor_user_id)
    # 格式预校验：坏文件（全坏 / 有效比例 <10%）直接 400 拒绝，不进 MinIO 不派发任务
    _validate_distribution_content(content, source_file_name)

    from ..services.minio_storage import build_source_key, put_object
    from uuid import uuid4 as _uuid4

    source_key = build_source_key(source_file_name)
    put_object(source_key, content, content_type="text/plain")

    _now = utcnow()
    dist = LightningDistribution(
        id=_uuid4().hex,
        source_file_name=source_file_name,
        source_object_key=source_key,
        import_type="distribution",
        status="pending",
        stage="parsing",
        progress=0,
        region_id=_normalize_str(region_id),
        location_tag=_normalize_str(location_tag),
        city=_normalize_str(city),
        event_year=event_year,
        line_id=line_id,
        grid_size_km=1.0,
        data_years=data_years,
        create_user=actor_user_id,
        create_date=_now,
        update_date=_now,
    )
    db.add(dist)
    db.commit()

    write_audit_log(
        db,
        action="lightning.distribution.import",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"distribution_id={dist.id}",
            f"source_file={source_file_name}",
            f"event_year={event_year or '-'}",
            f"data_years={data_years or '-'}",
            f"line_id={line_id or '-'}",
        ),
    )
    db.commit()

    from ..core.celery_app import celery_app as _celery_app
    _task = _celery_app.send_task(
        "app.tasks.lightning_tasks.import_lightning_distribution_job",
        kwargs=dict(
            distribution_id=dist.id,
            actor_user_id=actor_user_id,
        ),
        queue="celery",
    )
    dist.task_id = str(_task.id)
    dist.status = "processing"
    db.commit()

    return LightningDistributionImportResponse(
        distribution_id=dist.id,
        task_id=str(_task.id),
        status="processing",
    )


def list_lightning_distributions(
    db: Session,
    *,
    keyword: str | None = None,
    region_id: str | None = None,
    city: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LightningDistributionListResponse:
    """列出地闪分布记录（元数据 + 状态 + 统计）。"""
    filters: list[Any] = []
    if keyword:
        keyword_pattern = f"%{keyword}%"
        filters.append(
            or_(
                LightningDistribution.source_file_name.ilike(keyword_pattern),
                LightningDistribution.location_tag.ilike(keyword_pattern),
                LightningDistribution.city.ilike(keyword_pattern),
            )
        )
    if region_id:
        filters.append(LightningDistribution.region_id == region_id)
    if city:
        normalized_city = _normalize_str(city)
        if normalized_city:
            filters.append(func.lower(LightningDistribution.city) == normalized_city.lower())

    total = db.execute(
        select(func.count()).select_from(LightningDistribution).where(*filters)
    ).scalar() or 0
    rows = db.execute(
        select(LightningDistribution)
        .where(*filters)
        .order_by(LightningDistribution.create_date.desc(), LightningDistribution.id.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

    # 批量统计每页分布被多少条线路的杆塔引用（linked_line_count）
    row_ids = [dist.id for dist in rows]
    linked_counts = _batch_distribution_linked_line_counts(db, row_ids)

    return LightningDistributionListResponse(
        items=[
            _serialize_distribution(dist, linked_line_count=linked_counts.get(dist.id, 0))
            for dist in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _batch_distribution_linked_line_counts(
    db: Session,
    distribution_ids: list[str],
) -> dict[str, int]:
    """对一批分布 id 统计各自被多少条线路的杆塔引用（linked_line_count）。

    复用 SQL 粗筛 + 内存精滤：先按 JSON 文本 LIKE 缩小候选杆塔集合，
    再精确匹配 `lightning_density.source_distribution_id`。
    """
    if not distribution_ids:
        return {}
    distinct_ids = list(dict.fromkeys(distribution_ids))
    result: dict[str, int] = {distribution_id: 0 for distribution_id in distinct_ids}
    try:
        raw_json_text = cast(LineTower.raw_extra_json, String)
        candidates = db.execute(
            select(LineTower.id, LineTower.line_id, LineTower.raw_extra_json).where(
                raw_json_text.ilike("%source_distribution_id%"),
            )
        ).all()
    except Exception:
        return result

    per_id_lines: dict[str, set[str]] = {distribution_id: set() for distribution_id in distinct_ids}
    wanted = set(distinct_ids)
    for row in candidates:
        tower_line_id, raw_extra = row[1], row[2]
        if not tower_line_id:
            continue
        extra = raw_extra or {}
        density = extra.get("lightning_density")
        if not isinstance(density, dict):
            continue
        source_id = density.get("source_distribution_id")
        if source_id in wanted:
            per_id_lines[source_id].add(tower_line_id)
    for distribution_id, line_ids in per_id_lines.items():
        result[distribution_id] = len(line_ids)
    return result


def get_lightning_distribution_by_id(db: Session, distribution_id: str) -> LightningDistribution | None:
    return db.execute(
        select(LightningDistribution).where(LightningDistribution.id == distribution_id)
    ).scalar_one_or_none()


def get_lightning_distribution_detail(
    db: Session,
    distribution_id: str,
) -> LightningDistributionRecord:
    """单条详情（含统计，不含事件明细）。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    linked_count = get_distribution_linked_line_count(db, distribution_id)
    return _serialize_distribution(dist, linked_line_count=linked_count)


def get_lightning_distribution_status(
    db: Session,
    distribution_id: str,
) -> LightningDistributionStatusResponse:
    """轮询任务进度（status/stage/progress）。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    linked_count = get_distribution_linked_line_count(db, distribution_id)
    return LightningDistributionStatusResponse(
        distribution_id=dist.id,
        status=dist.status,
        stage=dist.stage,
        progress=dist.progress,
        error_message=dist.error_message,
        record=_serialize_distribution(dist, linked_line_count=linked_count),
    )


def get_lightning_distribution_image_content(
    db: Session,
    distribution_id: str,
) -> tuple[bytes | None, str | None]:
    """从 MinIO 读取密度图图片二进制，返回 (content, media_type)。

    不直接暴露 MinIO 内网预签名地址，改由 LP 服务代理返回图片字节，
    供浏览器经 LP 服务加载。无图时 content 为 None。
    """
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    if not dist.image_object_key:
        return None, None
    from ..services import minio_storage
    content = minio_storage.get_object(dist.image_object_key)
    return content, "image/png"


def get_lightning_distribution_lp_image_content(
    db: Session,
    distribution_id: str,
) -> tuple[bytes | None, str | None]:
    """读取 LP 分区图；不存在返回 (None, None)。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist or not dist.lp_image_object_key:
        return None, None
    from ..services import minio_storage
    content = minio_storage.get_object(dist.lp_image_object_key)
    return content, "image/png"


def get_lightning_distribution_circle_image_content(
    db: Session,
    distribution_id: str,
) -> tuple[bytes | None, str | None]:
    """读取「沿线圆」密度图；不存在返回 (None, None)。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist or not dist.circle_image_object_key:
        return None, None
    from ..services import minio_storage
    content = minio_storage.get_object(dist.circle_image_object_key)
    return content, "image/png"


def get_lightning_density_backfill_circle_image_content(
    db: Session,
    backfill_task_id: str,
) -> tuple[bytes | None, str | None]:
    """读取某次地闪密度回填任务自带的「沿线圆」密度图；不存在返回 (None, None)。

    每次回填各自生成一张图（对象键落在回填任务记录上），因此按任务读取
    能拿到该次回填对应的图，而不是被后续回填覆盖的最新一张。
    """
    task = db.execute(
        select(LightningDensityBackfillTask).where(LightningDensityBackfillTask.id == backfill_task_id)
    ).scalar_one_or_none()
    if not task or not task.circle_image_object_key:
        return None, None
    from ..services import minio_storage
    content = minio_storage.get_object(task.circle_image_object_key)
    return content, "image/png"


def get_lightning_density_backfill_towers(
    db: Session,
    distribution_id: str,
    line_id: str,
    *,
    keyword: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> LightningDensityBackfillTowersResponse:
    """反查某地闪分布回填到某线路的杆塔 Ng 值明细。

    关联方式：`power_line_tower.raw_extra_json.lightning_density.source_distribution_id == distribution_id`
    （与 get_linked_lines_for_distribution 同一链路），Ng 值取杆塔表 `lightning_density` 列，
    prepared_at/strike_count 取 raw_extra_json.lightning_density 内字段。
    """
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    line = db.execute(select(Line.id).where(Line.id == line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    raw_json_text = cast(LineTower.raw_extra_json, String)
    stmt = (
        select(LineTower)
        .where(
            LineTower.line_id == line_id,
            raw_json_text.ilike(f"%{distribution_id}%"),
        )
        .order_by(LineTower.tower_no.asc())
    )
    normalized = (keyword or "").strip()
    if normalized:
        like = f"%{normalized}%"
        stmt = stmt.where(LineTower.tower_no.ilike(like))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0)
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars().all()

    items: list[LightningDensityBackfillTowerDetail] = []
    for tower in rows:
        extra = tower.raw_extra_json or {}
        density = extra.get("lightning_density") or {}
        if not isinstance(density, dict):
            continue
        if density.get("source_distribution_id") != distribution_id:
            continue
        items.append(
            LightningDensityBackfillTowerDetail(
                tower_id=tower.id,
                tower_no=tower.tower_no,
                longitude=tower.longitude,
                latitude=tower.latitude,
                lightning_density=tower.lightning_density,
                strike_count=_as_optional_int(density.get("strike_count")),
                prepared_at=density.get("prepared_at"),
            )
        )
    return LightningDensityBackfillTowersResponse(items=items, total=len(items))


def list_lightning_density_backfill_history(
    db: Session,
    distribution_id: str,
    *,
    keyword: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> LightningDensityBackfillHistoryResponse:
    """查询某地闪分布的全部回填历史记录（最新在上）。

    从新建的 `lightning_density_backfill_task` 表读取（每次回填生成一条），
    供回填记录 tab 展示所有历史回填，而非仅当前最新覆盖值。
    """
    from ..models.lightning_density_backfill import LightningDensityBackfillTask as _LDBT
    from ..models.line import Line as _Line

    stmt = select(_LDBT).where(_LDBT.distribution_id == distribution_id)
    normalized = (keyword or "").strip()
    if normalized:
        like = f"%{normalized}%"
        line_sub = select(_Line.id).where(_Line.name.ilike(like))
        stmt = stmt.where(_LDBT.line_id.in_(line_sub))
    total = int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0)
    rows = (
        db.execute(stmt.order_by(_LDBT.prepared_at.desc(), _LDBT.create_date.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )

    line_ids = {r.line_id for r in rows}
    lines = {}
    if line_ids:
        for line_row in db.execute(select(_Line).where(_Line.id.in_(line_ids))).scalars().all():
            lines[line_row.id] = line_row

    items: list[LightningDensityBackfillTaskSummary] = []
    for task in rows:
        line_row = lines.get(task.line_id)
        items.append(
            LightningDensityBackfillTaskSummary(
                id=task.id,
                line_id=task.line_id,
                line_name=line_row.name if line_row else None,
                line_code=line_row.code if line_row else None,
                distribution_id=task.distribution_id,
                prepared_at=task.prepared_at.isoformat() if task.prepared_at else None,
                prepared_by_user_id=task.prepared_by_user_id,
                radius_km=task.radius_km,
                data_years=task.data_years,
                updated_tower_count=task.updated_tower_count,
                missing_geo_count=task.missing_geo_count,
                avg_density=task.avg_density,
                min_density=task.min_density,
                max_density=task.max_density,
                strike_count=task.strike_count,
                warnings=list(task.warnings or []),
                status=task.status or "completed",
                progress=task.progress or 0,
                task_id=task.task_id,
                error_message=task.error_message,
                has_circle_image=bool(task.circle_image_object_key),
            )
        )
    return LightningDensityBackfillHistoryResponse(distribution_id=distribution_id, items=items, total=total)


def retry_lightning_distribution(
    db: Session,
    distribution_id: str,
    actor_user_id: str,
) -> LightningDistributionImportResponse:
    """失败重试：重置状态并重新派发导入任务。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    dist.status = "pending"
    dist.stage = "parsing"
    dist.progress = 0
    dist.error_message = None
    dist.update_user = actor_user_id
    db.commit()

    from ..core.celery_app import celery_app as _celery_app
    _task = _celery_app.send_task(
        "app.tasks.lightning_tasks.import_lightning_distribution_job",
        kwargs=dict(distribution_id=dist.id, actor_user_id=actor_user_id),
        queue="celery",
    )
    dist.task_id = str(_task.id)
    dist.status = "processing"
    db.commit()

    return LightningDistributionImportResponse(
        distribution_id=dist.id,
        task_id=str(_task.id),
        status="processing",
    )


def delete_lightning_distribution(db: Session, distribution_id: str) -> dict[str, bool]:
    """删除地闪分布记录，并同步删除 MinIO 上的原始文件与密度图对象。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        return {"success": False}
    from ..services import minio_storage
    for key in (dist.source_object_key, dist.image_object_key, dist.thumbnail_key, dist.lp_image_object_key, dist.circle_image_object_key):
        if key:
            try:
                minio_storage.delete_object(key)
            except Exception:
                pass
    db.delete(dist)
    db.commit()
    _publish_lightning_change(
        "lightning.deleted",
        {"event_id": distribution_id, "message": f"删除地闪分布记录：{dist.source_file_name}"},
        topic=LIGHTNING_DISTRIBUTION_TOPIC,
        requires_refetch=["/api/v1/lightning-currents/distributions"],
    )
    return {"success": True}


def trigger_lp_density_draw(
    db: Session,
    distribution_id: str,
    payload: LightningLpDrawRequest,
    actor_user_id: str | None,
) -> LightningLpDrawResponse:
    """派发 LP 分区绘图任务。校验分布存在且 completed。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    if dist.status != "completed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅已完成分布的线路可绘图")
    from ..tasks.lightning_tasks import render_lp_density_job
    task = render_lp_density_job.delay(
        distribution_id=dist.id, line_id=payload.line_id,
        radius_km=payload.radius_km, actor_user_id=actor_user_id,
    )
    return LightningLpDrawResponse(task_id=task.id, status="submitted")


# ---------------------------------------------------------------------------
# 线路密度回填（异步版，/prepare-density 使用）
# ---------------------------------------------------------------------------
def prepare_line_lightning_density(
    db: Session,
    payload: LightningDensityPreparationRequest,
    *,
    actor_user_id: str,
) -> LightningDensityPreparationAsyncResponse:
    """提交线路地闪密度回填任务（异步，LP：地闪密度回填异步化）。

    API 层只做前置校验 + 创建 pending 回填任务记录 + 派发 Celery 任务，
    立即返回 task_id。实际计算（解析落雷→逐塔统计→渲染沿线圆图→写历史）
    由 Celery worker 执行（prepare_line_lightning_density_job）。
    """
    # 前置校验：线路存在
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    # 前置校验：线路有可回填杆塔
    tower_count = db.execute(
        select(func.count()).select_from(LineTower).where(LineTower.line_id == line.id)
    ).scalar() or 0
    if tower_count == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可回填的杆塔数据")

    # 前置校验：有可用地闪分布数据（指定 distribution_id 优先，否则线路关联的最新 completed 分布）
    dist = None
    if payload.distribution_id:
        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == payload.distribution_id)
        ).scalar_one_or_none()
        if dist is not None and dist.status != "completed":
            dist = None
    if dist is None:
        dist = db.execute(
            select(LightningDistribution)
            .where(
                LightningDistribution.line_id == line.id,
                LightningDistribution.status == "completed",
            )
            .order_by(LightningDistribution.create_date.desc())
        ).scalars().first()
    if not dist or not dist.source_object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未找到可用于地闪密度计算的地闪分布数据（请先导入并关联线路）",
        )

    now = utcnow()
    normalized_region = _normalize_str(payload.region_id)
    task = LightningDensityBackfillTask(
        line_id=line.id,
        distribution_id=dist.id,
        prepared_at=now,
        prepared_by_user_id=actor_user_id,
        radius_km=payload.radius_km,
        status="pending",
        progress=0,
    )
    db.add(task)
    db.commit()

    from ..core.celery_app import celery_app

    celery_task = celery_app.send_task(
        "app.tasks.lightning_tasks.prepare_line_lightning_density_job",
        kwargs={
            "line_id": line.id,
            "distribution_id": dist.id,
            "radius_km": payload.radius_km,
            "region_id": normalized_region,
            "years": payload.years,
            "backfill_task_id": task.id,
            "actor_user_id": actor_user_id,
        },
        queue="celery",
    )
    task.task_id = str(celery_task.id)
    task.status = "processing"
    task.progress = 5
    db.commit()

    return LightningDensityPreparationAsyncResponse(
        task_id=str(celery_task.id),
        backfill_task_id=task.id,
        line_id=line.id,
        status="processing",
    )


def _execute_line_lightning_density_backfill(
    db: Session,
    payload: LightningDensityPreparationRequest,
    *,
    backfill_task_id: str | None,
    actor_user_id: str,
) -> LightningDensityPreparationResponse:
    """执行地闪密度回填计算（供 Celery worker 调用）。

    解析分布源文件落雷 → 按杆塔半径统计 Ng → 更新塔表 → 渲染「沿线圆」密度图
    并存 MinIO（对象键写入回填任务记录，每次回填各自一张，互不覆盖）→ 写历史。
    """
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    # 当radius_km未指定时，根据电压等级自动推荐半径
    if payload.radius_km is None:
        actual_radius_km = recommend_radius_km(line.voltage_kv)
    else:
        actual_radius_km = payload.radius_km

    towers = db.execute(
        select(LineTower)
        .where(LineTower.line_id == line.id)
        .order_by(LineTower.seq_no.asc(), LineTower.id.asc())
    ).scalars().all()
    if not towers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可回填的杆塔数据")

    geo_towers = [tower for tower in towers if tower.longitude is not None and tower.latitude is not None]
    if not geo_towers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路缺少杆塔经纬度，无法计算地闪密度")

    # 数据来源：指定 distribution_id 优先，否则线路关联的最新 LightningDistribution
    dist = None
    if payload.distribution_id:
        dist = db.execute(
            select(LightningDistribution).where(LightningDistribution.id == payload.distribution_id)
        ).scalar_one_or_none()
        if dist is not None and dist.status != "completed":
            dist = None
    if dist is None:
        dist = db.execute(
            select(LightningDistribution)
            .where(
                LightningDistribution.line_id == line.id,
                LightningDistribution.status == "completed",
            )
            .order_by(LightningDistribution.create_date.desc())
        ).scalars().first()
    if not dist or not dist.source_object_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="未找到可用于地闪密度计算的地闪分布数据（请先导入并关联线路）",
        )

    from ..services import lightning_statistics
    from ..services import minio_storage
    content = minio_storage.get_object(dist.source_object_key)
    text = lightning_statistics.decode_text_bytes(content)
    all_strikes = lightning_statistics.parse_distribution_content(text)

    lat_delta = actual_radius_km / DEGREE_TO_KM
    lon_deltas = [
        actual_radius_km / _safe_km_per_lon(float(tower.latitude))
        for tower in geo_towers
        if tower.latitude is not None
    ]
    lon_delta = max(lon_deltas) if lon_deltas else lat_delta
    min_lat = min(float(tower.latitude) for tower in geo_towers) - lat_delta
    max_lat = max(float(tower.latitude) for tower in geo_towers) + lat_delta
    min_lon = min(float(tower.longitude) for tower in geo_towers) - lon_delta
    max_lon = max(float(tower.longitude) for tower in geo_towers) + lon_delta

    candidate_rows = [
        {
            "latitude": float(s["lat"]),
            "longitude": float(s["lon"]),
        }
        for s in all_strikes
        if (
            s["lat"] is not None
            and s["lon"] is not None
            and min_lat <= float(s["lat"]) <= max_lat
            and min_lon <= float(s["lon"]) <= max_lon
        )
    ]
    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到可用于地闪密度计算的雷击分布数据")

    now = utcnow()
    area_km2 = math.pi * (actual_radius_km ** 2)
    updated_tower_count = 0
    missing_geo_count = 0
    density_values: list[float] = []
    source_years = payload.years if payload.years is not None else float(dist.data_years or 1.0)
    warnings: list[str] = []

    for tower in towers:
        if tower.longitude is None or tower.latitude is None:
            missing_geo_count += 1
            continue

        strike_count = 0
        for row in candidate_rows:
            if row["longitude"] is None or row["latitude"] is None:
                continue
            distance_km = _haversine_km(
                float(tower.latitude),
                float(tower.longitude),
                float(row["latitude"]),
                float(row["longitude"]),
            )
            if distance_km > actual_radius_km:
                continue
            strike_count += 1

        tower_years = max(source_years, 1e-6)
        density = strike_count / (area_km2 * tower_years) if strike_count > 0 else 0.0
        tower.lightning_density = round(density, 6)
        tower.update_date = now
        tower.update_user = actor_user_id
        raw_extra = dict(tower.raw_extra_json or {})
        raw_extra["lightning_density"] = {
            "line_id": line.id,
            "line_code": line.code,
            "radius_km": actual_radius_km,
            "data_years": round(tower_years, 6),
            "strike_count": strike_count,
            "region_id": _normalize_str(payload.region_id),
            "prepared_at": now.isoformat(),
            "source_distribution_id": dist.id,
        }
        tower.raw_extra_json = raw_extra
        density_values.append(float(tower.lightning_density))
        updated_tower_count += 1

    if missing_geo_count > 0:
        warnings.append(f"{missing_geo_count} 座杆塔缺少经纬度，未能回填地闪密度")

    line.update_date = now
    line.update_user = actor_user_id
    record_line_preparation_source(
        line,
        component="lightning_density",
        payload={
            "prepared_at": now.isoformat(),
            "prepared_by_user_id": actor_user_id,
            "region_id": _normalize_str(payload.region_id),
            "radius_km": actual_radius_km,
            "data_years": round(source_years, 6),
            "updated_tower_count": updated_tower_count,
            "missing_geo_count": missing_geo_count,
            "avg_density": round(sum(density_values) / len(density_values), 6) if density_values else None,
            "min_density": round(min(density_values), 6) if density_values else None,
            "max_density": round(max(density_values), 6) if density_values else None,
        },
    )

    # ---- 生成「沿线圆」密度图（对齐 C# banjin 分组圆画法）并存 MinIO ----
    # 失败不阻塞回填主流程：matplotlib 不可用 / 渲染异常时仅跳过图生成
    circle_image_object_key: str | None = None
    try:
        from ..services import lightning_statistics as _ls

        # 按电压等级分组（与桌面版 banjin group_size 一致）
        v = int(line.voltage_kv) if line.voltage_kv else 0
        if v <= 110:
            group_size = 2
        elif v <= 330:
            group_size = 3
        else:
            group_size = 5

        groups = []
        for gi in range(0, len(geo_towers), group_size):
            chunk = geo_towers[gi:gi + group_size]
            groups.append({
                "group_id": gi // group_size,
                "center_lat": sum(float(t.latitude) for t in chunk) / len(chunk),
                "center_lon": sum(float(t.longitude) for t in chunk) / len(chunk),
            })

        strikes_for_render = [
            {"lat": float(row["latitude"]), "lon": float(row["longitude"])}
            for row in candidate_rows
            if row["latitude"] is not None and row["longitude"] is not None
        ]
        png = _ls.render_along_route_circle_image(
            strikes_for_render,
            groups,
            [],
            data_years=source_years,
            radius_km=actual_radius_km,
            title=f"{line.name} - 地闪密度沿线圆",
        )
        if png:
            from ..services import minio_storage
            from uuid import uuid4 as _uuid4
            circle_key = f"lightning/dist/circle/{dist.id}/{_uuid4().hex}.png"
            minio_storage.put_object(circle_key, png, content_type="image/png")
            circle_image_object_key = circle_key
    except Exception:
        circle_image_object_key = None

    # ---- 写入回填历史记录（每次回填一条，供回填记录 tab 展示全部历史，最新在上）----
    backfill_task: LightningDensityBackfillTask | None = None
    if backfill_task_id:
        backfill_task = db.execute(
            select(LightningDensityBackfillTask).where(LightningDensityBackfillTask.id == backfill_task_id)
        ).scalar_one_or_none()
    if backfill_task is None:
        backfill_task = LightningDensityBackfillTask(
            line_id=line.id,
            distribution_id=dist.id if dist else None,
            prepared_at=now,
            prepared_by_user_id=actor_user_id,
            status="completed",
            progress=100,
        )
        db.add(backfill_task)
    backfill_task.radius_km = actual_radius_km
    backfill_task.data_years = round(source_years, 6)
    backfill_task.updated_tower_count = updated_tower_count
    backfill_task.missing_geo_count = missing_geo_count
    backfill_task.avg_density = round(sum(density_values) / len(density_values), 6) if density_values else None
    backfill_task.min_density = round(min(density_values), 6) if density_values else None
    backfill_task.max_density = round(max(density_values), 6) if density_values else None
    backfill_task.strike_count = len(candidate_rows)
    backfill_task.warnings = warnings
    backfill_task.status = "completed"
    backfill_task.progress = 100
    backfill_task.error_message = None
    if circle_image_object_key:
        backfill_task.circle_image_object_key = circle_image_object_key

    db.commit()

    preparation_json = summarize_line_preparation(db, line, tower_count=len(towers))
    _publish_line_change(
        "power-lines.lightning-density.prepared",
        {"action": "lightning_density_prepared", "line_id": line.id},
    )
    return LightningDensityPreparationResponse(
        line=serialize_line(line, tower_count=len(towers), preparation_json=preparation_json),
        updated_tower_count=updated_tower_count,
        missing_geo_count=missing_geo_count,
        radius_km=actual_radius_km,
        data_years=round(source_years, 6),
        avg_density=round(sum(density_values) / len(density_values), 6) if density_values else None,
        min_density=round(min(density_values), 6) if density_values else None,
        max_density=round(max(density_values), 6) if density_values else None,
        warning_count=len(warnings),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 雷电流幅值回填历史（LightningCurrentBackfillTask / Tower）
# ---------------------------------------------------------------------------
def _serialize_backfill_task(task: LightningCurrentBackfillTask) -> LightningCurrentBackfillTaskSummary:
    """把回填任务 ORM 对象序列化为摘要 schema。"""
    return LightningCurrentBackfillTaskSummary(
        id=task.id,
        line_id=task.line_id,
        line_name=task.line.name if task.line else None,
        prepared_at=task.prepared_at,
        prepared_by=task.prepared_by_user_id,
        current_a=task.current_a,
        current_b=task.current_b,
        peak_max=task.peak_max,
        peak_min=task.peak_min,
        sampled_event_count=task.sampled_event_count,
        updated_tower_count=task.updated_tower_count,
        created_profile_count=task.created_profile_count,
        warnings=list(task.warnings or []),
        region_id=task.region_id,
        is_synthetic=task.is_synthetic,
        status=task.status,
        progress=task.progress,
        task_id=task.task_id,
        error_message=task.error_message,
    )


def list_lightning_current_backfill_tasks(
    db: Session,
    *,
    line_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> LightningCurrentBackfillTaskListResponse:
    """回填任务列表（分页 + line_id / 时间范围筛选，按 prepared_at 倒序）。"""
    filters: list[Any] = []
    if line_id:
        filters.append(LightningCurrentBackfillTask.line_id == line_id)
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的 start_date：{start_date}，请使用 YYYY-MM-DD",
            ) from None
        filters.append(LightningCurrentBackfillTask.prepared_at >= start_dt)
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的 end_date：{end_date}，请使用 YYYY-MM-DD",
            ) from None
        filters.append(LightningCurrentBackfillTask.prepared_at <= end_dt)

    total = db.execute(
        select(func.count()).select_from(LightningCurrentBackfillTask).where(*filters)
    ).scalar() or 0
    rows = db.execute(
        select(LightningCurrentBackfillTask)
        .where(*filters)
        .order_by(LightningCurrentBackfillTask.prepared_at.desc(), LightningCurrentBackfillTask.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    return LightningCurrentBackfillTaskListResponse(
        items=[_serialize_backfill_task(item) for item in rows],
        total=total,
    )


def get_lightning_current_backfill_task_detail(
    db: Session,
    task_id: str,
    *,
    page: int = 1,
    page_size: int = 200,
) -> LightningCurrentBackfillTaskDetail:
    """回填任务详情：任务信息 + 逐杆塔明细（分页）。"""
    task = db.execute(
        select(LightningCurrentBackfillTask).where(LightningCurrentBackfillTask.id == task_id)
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="回填任务不存在")

    tower_rows = db.execute(
        select(LightningCurrentBackfillTower)
        .where(LightningCurrentBackfillTower.task_id == task_id)
        .order_by(LightningCurrentBackfillTower.create_date.asc(), LightningCurrentBackfillTower.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).scalars().all()

    # 批量取塔号（避免 N+1）
    tower_ids = [row.tower_id for row in tower_rows]
    tower_no_map: dict[str, str | None] = {}
    if tower_ids:
        tower_rows_by_id = db.execute(
            select(LineTower.id, LineTower.tower_no).where(LineTower.id.in_(tower_ids))
        ).all()
        tower_no_map = {str(item.id): item.tower_no for item in tower_rows_by_id}

    towers: list[LightningCurrentBackfillTowerDetail] = []
    for row in tower_rows:
        towers.append(
            LightningCurrentBackfillTowerDetail(
                tower_id=row.tower_id,
                tower_no=tower_no_map.get(row.tower_id),
                action=row.action,
                previous_current_a=row.previous_current_a,
                previous_current_b=row.previous_current_b,
                current_a=row.current_a,
                current_b=row.current_b,
                delta_a=(row.current_a - row.previous_current_a)
                if row.current_a is not None and row.previous_current_a is not None
                else None,
                delta_b=(row.current_b - row.previous_current_b)
                if row.current_b is not None and row.previous_current_b is not None
                else None,
            )
        )

    return LightningCurrentBackfillTaskDetail(
        task=_serialize_backfill_task(task),
        towers=towers,
    )


def get_lightning_current_backfill_task_towers(
    db: Session,
    task_id: str,
    *,
    page: int = 1,
    page_size: int = 200,
) -> LightningCurrentBackfillTaskDetail:
    """回填任务下所有杆塔回填详情（分页），返回结构与任务详情一致。"""
    return get_lightning_current_backfill_task_detail(db, task_id, page=page, page_size=page_size)
