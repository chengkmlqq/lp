from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, case, delete as sa_delete, func, insert, or_, select, String
from sqlalchemy.orm import Session

from ..core.database import SessionLocal

from ..models.base import utcnow
from ..models.lightning_distribution import LightningDistribution
from ..models.lightning_event import LightningCurrentEvent
from ..models.lightning_sample import LightningCurrentSample
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.tower_profile import TowerProfile
from ..schemas.lightning import (
    LightningCurrentEventListResponse,
    LightningCurrentEventSummary,
    LightningCurrentEventUpdateRequest,
    LightningCurrentPreparationRequest,
    LightningCurrentPreparationResponse,
    LightningDistributionImportResponse,
    LightningDistributionRecord,
    LightningDistributionListResponse,
    LightningDistributionStatusResponse,
    LightningDistributionImageResponse,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningCurrentExceedancePoint,
    LightningCurrentExceedanceResponse,
    LightningCurrentImportResponse,
    LightningCurrentSampleItem,
    LightningCurrentSampleListResponse,
    LightningPolarity,
    LightningFillDensityRequest,
    LightningFillDensityResponse,
)
from ..schemas.lightning_import import (
    LightningImportBatchSummary,
    LightningImportBatchListResponse,
)
from .line_preparation_service import record_line_preparation_source, summarize_line_preparation
from .line_service import serialize_line
from .push_service import publish_topic

LIGHTNING_TOPIC = "admin.lightning-currents"
POWER_LINES_TOPIC = "admin.power-lines"
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "latin-1")
MAX_SAMPLES = 2_000_000
INSERT_CHUNK_SIZE = 5_000
MAX_DISTRIBUTION_ROWS = 2_000_000
DELETE_CHUNK_SIZE = 50_000
STANDARD_WAVE_SHAPES: tuple[tuple[str, float, float], ...] = (
    ("10/350", 10.0, 350.0),
    ("8/20", 8.0, 20.0),
    ("1.2/50", 1.2, 50.0),
)
TOKEN_SPLIT_PATTERN = re.compile(r"[,\t; ]+")
DEGREE_TO_KM = 111.32
TERRAIN_ALGORITHM_VERSION = "horn_3x3.v1"

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

def serialize_lightning_event(event: LightningCurrentEvent) -> LightningCurrentEventSummary:
    return LightningCurrentEventSummary(
        id=event.id,
        event_id=event.event_id,
        source_file_name=event.source_file_name,
        event_time=event.event_time,
        sample_count=event.sample_count,
        sample_interval_us=event.sample_interval_us,
        sampling_frequency_hz=event.sampling_frequency_hz,
        peak_current_ka=event.peak_current_ka,
        peak_abs_current_ka=event.peak_abs_current_ka,
        wavefront_time_t1_us=event.wavefront_time_t1_us,
        half_value_time_t2_us=event.half_value_time_t2_us,
        steepness_ka_per_us=event.steepness_ka_per_us,
        action_integral_j_ohm=event.action_integral_j_ohm,
        wave_shape=event.wave_shape,
        polarity=event.polarity,  # type: ignore[arg-type]
        stroke_count=event.stroke_count,
        stroke_peaks_json=event.stroke_peaks_json or [],
        region_id=event.region_id,
        location_tag=event.location_tag,
        city=event.city,
        longitude=event.longitude,
        latitude=event.latitude,
        altitude_m=event.altitude_m,
        sensor_model=event.sensor_model,
        install_position=event.install_position,
        weather_level=event.weather_level,
        pressure_hpa=event.pressure_hpa,
        humidity_percent=event.humidity_percent,
        is_synthetic=event.is_synthetic,
        feature_json=event.feature_json or {},
        notes=event.notes,
        create_date=event.create_date,
        create_user=event.create_user,
        update_date=event.update_date,
        update_user=event.update_user,
    )

def serialize_lightning_sample(sample: LightningCurrentSample) -> LightningCurrentSampleItem:
    return LightningCurrentSampleItem(
        id=sample.id,
        event_ref_id=sample.event_ref_id,
        seq_no=sample.seq_no,
        time_us=sample.time_us,
        current_ka=sample.current_ka,
    )

def get_lightning_event_by_id(db: Session, event_id: str) -> LightningCurrentEvent | None:
    return db.execute(select(LightningCurrentEvent).where(LightningCurrentEvent.id == event_id)).scalar_one_or_none()

def get_lightning_event_by_event_id(db: Session, event_id: str) -> LightningCurrentEvent | None:
    normalized = _normalize_str(event_id)
    if normalized is None:
        return None
    return db.execute(
        select(LightningCurrentEvent).where(func.lower(LightningCurrentEvent.event_id) == normalized.lower())
    ).scalar_one_or_none()

def list_lightning_events(
    db: Session,
    *,
    keyword: str | None,
    region_id: str | None,
    polarity: str | None,
    wave_shape: str | None,
    is_synthetic: bool | None,
    limit: int,
    offset: int,
) -> LightningCurrentEventListResponse:
    stmt = select(LightningCurrentEvent).where(LightningCurrentEvent.sample_count >= 2)
    total_stmt = select(func.count()).select_from(LightningCurrentEvent).where(LightningCurrentEvent.sample_count >= 2)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = or_(
            LightningCurrentEvent.event_id.ilike(like),
            LightningCurrentEvent.location_tag.ilike(like),
            LightningCurrentEvent.city.ilike(like),
            LightningCurrentEvent.source_file_name.ilike(like),
        )
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    normalized_region = _normalize_str(region_id)
    if normalized_region:
        stmt = stmt.where(LightningCurrentEvent.region_id == normalized_region)
        total_stmt = total_stmt.where(LightningCurrentEvent.region_id == normalized_region)

    normalized_polarity = _normalize_str(polarity)
    if normalized_polarity:
        stmt = stmt.where(LightningCurrentEvent.polarity == normalized_polarity.lower())
        total_stmt = total_stmt.where(LightningCurrentEvent.polarity == normalized_polarity.lower())

    normalized_wave_shape = _normalize_str(wave_shape)
    if normalized_wave_shape:
        stmt = stmt.where(func.lower(LightningCurrentEvent.wave_shape) == normalized_wave_shape.lower())
        total_stmt = total_stmt.where(func.lower(LightningCurrentEvent.wave_shape) == normalized_wave_shape.lower())

    if is_synthetic is not None:
        stmt = stmt.where(LightningCurrentEvent.is_synthetic == is_synthetic)
        total_stmt = total_stmt.where(LightningCurrentEvent.is_synthetic == is_synthetic)

    total = int(db.scalar(total_stmt) or 0)
    rows = db.execute(
        stmt.order_by(
            LightningCurrentEvent.event_time.desc(),
            LightningCurrentEvent.update_date.desc(),
            LightningCurrentEvent.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    return LightningCurrentEventListResponse(
        items=[serialize_lightning_event(item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )

def update_lightning_event(
    db: Session,
    event_id: str,
    payload: LightningCurrentEventUpdateRequest,
    *,
    actor_user_id: str,
) -> LightningCurrentEventSummary | None:
    event = get_lightning_event_by_id(db, event_id)
    if not event:
        return None

    data = payload.model_dump(exclude_unset=True)

    if "event_time" in data:
        event.event_time = data["event_time"]
    if "region_id" in data:
        event.region_id = _normalize_str(data["region_id"])
    if "location_tag" in data:
        event.location_tag = _normalize_str(data["location_tag"])
    if "city" in data:
        event.city = _normalize_str(data["city"])
    if "longitude" in data:
        event.longitude = data["longitude"]
    if "latitude" in data:
        event.latitude = data["latitude"]
    if "altitude_m" in data:
        event.altitude_m = data["altitude_m"]
    if "sensor_model" in data:
        event.sensor_model = _normalize_str(data["sensor_model"])
    if "install_position" in data:
        event.install_position = _normalize_str(data["install_position"])
    if "weather_level" in data:
        event.weather_level = _normalize_str(data["weather_level"])
    if "pressure_hpa" in data:
        event.pressure_hpa = data["pressure_hpa"]
    if "humidity_percent" in data:
        event.humidity_percent = data["humidity_percent"]
    if "is_synthetic" in data and data["is_synthetic"] is not None:
        event.is_synthetic = bool(data["is_synthetic"])
    if "wave_shape" in data:
        event.wave_shape = _normalize_str(data["wave_shape"])
    if "notes" in data:
        event.notes = _normalize_str(data["notes"])
    if "feature_json" in data and data["feature_json"] is not None:
        event.feature_json = dict(data["feature_json"])

    event.update_user = actor_user_id
    event.update_date = utcnow()
    db.commit()

    saved = get_lightning_event_by_id(db, event_id)
    if not saved:
        return None

    _publish_lightning_change("lightning.updated", {"action": "updated", "event_id": saved.id})
    return serialize_lightning_event(saved)

def delete_lightning_event(db: Session, event_id: str) -> bool:
    event = get_lightning_event_by_id(db, event_id)
    if not event:
        return False

    db.delete(event)
    db.commit()
    _publish_lightning_change("lightning.deleted", {"action": "deleted", "event_id": event_id})
    return True

def list_lightning_samples(
    db: Session,
    *,
    event_id: str,
    limit: int,
    offset: int,
) -> LightningCurrentSampleListResponse:
    total = int(
        db.scalar(
            select(func.count()).select_from(LightningCurrentSample).where(LightningCurrentSample.event_ref_id == event_id)
        )
        or 0
    )
    rows = db.execute(
        select(LightningCurrentSample)
        .where(LightningCurrentSample.event_ref_id == event_id)
        .order_by(LightningCurrentSample.seq_no.asc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    return LightningCurrentSampleListResponse(
        items=[serialize_lightning_sample(item) for item in rows],
        total=total,
        limit=limit,
        offset=offset,
    )

def import_lightning_event_from_file(
    db: Session,
    *,
    file: UploadFile,
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
) -> LightningCurrentImportResponse:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    text = _decode_text_bytes(content)
    parsed = _parse_current_series(text)
    if len(parsed.currents_ka) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有效采样点数量不足（至少需要 2 个点）")
    if len(parsed.currents_ka) > MAX_SAMPLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"采样点过多（>{MAX_SAMPLES}），请拆分后再导入",
        )

    time_axis_us, inferred_interval_us, inferred_fs_hz, time_warnings = _build_time_axis(
        parsed.time_us,
        sample_interval_us=sample_interval_us,
        sample_count=len(parsed.currents_ka),
    )
    warnings = [*parsed.warnings, *time_warnings]
    features = _extract_wave_features(parsed.currents_ka, time_axis_us, inferred_interval_us)

    normalized_event_id = _normalize_str(event_id) or _generate_event_id()
    if get_lightning_event_by_event_id(db, normalized_event_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"事件编号已存在：{normalized_event_id}")

    now = utcnow()
    event = LightningCurrentEvent(
        event_id=normalized_event_id,
        source_file_name=_normalize_str(file.filename),
        event_time=event_time,
        sample_count=len(parsed.currents_ka),
        sample_interval_us=inferred_interval_us,
        sampling_frequency_hz=inferred_fs_hz,
        peak_current_ka=features.peak_current_ka,
        peak_abs_current_ka=features.peak_abs_current_ka,
        wavefront_time_t1_us=features.wavefront_time_t1_us,
        half_value_time_t2_us=features.half_value_time_t2_us,
        steepness_ka_per_us=features.steepness_ka_per_us,
        action_integral_j_ohm=features.action_integral_j_ohm,
        wave_shape=features.wave_shape,
        polarity=features.polarity,
        stroke_count=features.stroke_count,
        stroke_peaks_json=features.stroke_peaks_json,
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
        feature_json={
            "source": "import-file",
            "has_explicit_time_axis": parsed.time_us is not None,
        },
        create_user=actor_user_id,
        update_user=actor_user_id,
        create_date=now,
        update_date=now,
    )
    db.add(event)
    db.flush()

    sample_insert_stmt = insert(LightningCurrentSample)
    total_samples = len(parsed.currents_ka)
    for start in range(0, total_samples, INSERT_CHUNK_SIZE):
        end = min(start + INSERT_CHUNK_SIZE, total_samples)
        chunk = [
            {
                "event_ref_id": event.id,
                "seq_no": idx + 1,
                "time_us": time_axis_us[idx],
                "current_ka": parsed.currents_ka[idx],
            }
            for idx in range(start, end)
        ]
        db.execute(sample_insert_stmt, chunk)

    db.commit()
    saved = get_lightning_event_by_id(db, event.id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="雷电流事件保存失败")

    _publish_lightning_change("lightning.imported", {"action": "imported", "event_id": saved.id})
    return LightningCurrentImportResponse(
        event=serialize_lightning_event(saved),
        warning_count=len(warnings),
        warnings=warnings,
    )

def import_lightning_current_async(
    db: Session,
    *,
    file: UploadFile,
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
) -> LightningCurrentImportResponse:
    """
    保存上传文件到临时目录并异步提交 Celery 任务处理。
    参照 import_lightning_distribution_from_file 的异步模式实现。
    """
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    # Create an import batch record immediately with status="pending"
    from ..models.lightning_import_batch import LightningImportBatch
    from uuid import uuid4 as _uuid4
    _now = utcnow()
    _batch = LightningImportBatch(
        id=_uuid4().hex,
        source_file_name=_normalize_str(str(file.filename or "upload")),
        import_type="waveform",
        status="pending",
        region_id=_normalize_str(region_id),
        location_tag=_normalize_str(location_tag),
        city=_normalize_str(city),
        is_synthetic=bool(is_synthetic),
        notes=_normalize_str(notes),
        create_user=actor_user_id,
        create_date=_now,
        update_date=_now,
    )
    db.add(_batch)
    db.commit()

    # Save file to shared temp volume for async Celery processing
    import os as _os
    _temp_dir = "/app/data/temp/lightning-current"
    _os.makedirs(_temp_dir, exist_ok=True)
    _temp_path = f"{_temp_dir}/{uuid4().hex}_{_normalize_str(str(file.filename or 'upload'))}"
    with open(_temp_path, "wb") as _f:
        _f.write(content)

    # Queue Celery task for async processing
    from ..core.celery_app import celery_app as _celery_app
    _task = _celery_app.send_task(
        "app.tasks.lightning_tasks.import_lightning_current_job",
        kwargs=dict(
            batch_id=_batch.id,
            file_path=_temp_path,
            source_file_name=_normalize_str(file.filename),
            actor_user_id=actor_user_id,
            event_id=event_id,
            event_time=event_time.isoformat() if event_time else None,
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
            is_synthetic=is_synthetic,
            notes=_normalize_str(notes),
        ),
        queue="celery",
    )
    # Link task_id to batch
    _batch.task_id = str(_task.id)
    _batch.status = "processing"
    db.commit()

    return LightningCurrentImportResponse(
        imported_count=0,
        skipped_count=0,
        warning_count=0,
        warnings=[],
        task_id=str(_task.id),
        batch_id=_batch.id,
    )

def execute_current_import_from_path(
    *,
    file_path: str,
    source_file_name: str | None,
    actor_user_id: str,
    event_id: str | None,
    event_time_str: str | None,
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
) -> LightningCurrentImportResponse:
    """从文件路径读取雷电流波形数据并执行导入。由 Celery task 或直接调用。"""
    db: Session = SessionLocal()
    try:
        with open(file_path, "rb") as _f:
            content = _f.read()
        text = _decode_text_bytes(content)
        parsed = _parse_current_series(text)
        if len(parsed.currents_ka) < 2:
            return LightningCurrentImportResponse(
                imported_count=0, skipped_count=0, warning_count=1,
                warnings=["有效采样点数量不足（至少需要 2 个点）"],
            )
        if len(parsed.currents_ka) > MAX_SAMPLES:
            return LightningCurrentImportResponse(
                imported_count=0, skipped_count=0, warning_count=1,
                warnings=[f"采样点过多（>{MAX_SAMPLES}），请拆分后再导入"],
            )

        event_time = None
        if event_time_str:
            try:
                event_time = datetime.fromisoformat(event_time_str)
            except ValueError:
                pass

        time_axis_us, inferred_interval_us, inferred_fs_hz, time_warnings = _build_time_axis(
            parsed.time_us,
            sample_interval_us=sample_interval_us,
            sample_count=len(parsed.currents_ka),
        )
        warnings = [*parsed.warnings, *time_warnings]
        features = _extract_wave_features(parsed.currents_ka, time_axis_us, inferred_interval_us)

        normalized_event_id = _normalize_str(event_id) or _generate_event_id()
        if get_lightning_event_by_event_id(db, normalized_event_id):
            return LightningCurrentImportResponse(
                imported_count=0, skipped_count=0, warning_count=1,
                warnings=[f"事件编号已存在：{normalized_event_id}"],
            )

        now = utcnow()
        event = LightningCurrentEvent(
            event_id=normalized_event_id,
            source_file_name=source_file_name,
            event_time=event_time,
            sample_count=len(parsed.currents_ka),
            sample_interval_us=inferred_interval_us,
            sampling_frequency_hz=inferred_fs_hz,
            peak_current_ka=features.peak_current_ka,
            peak_abs_current_ka=features.peak_abs_current_ka,
            wavefront_time_t1_us=features.wavefront_time_t1_us,
            half_value_time_t2_us=features.half_value_time_t2_us,
            steepness_ka_per_us=features.steepness_ka_per_us,
            action_integral_j_ohm=features.action_integral_j_ohm,
            wave_shape=features.wave_shape,
            polarity=features.polarity,
            stroke_count=features.stroke_count,
            stroke_peaks_json=features.stroke_peaks_json,
            region_id=region_id,
            location_tag=location_tag,
            city=city,
            longitude=longitude,
            latitude=latitude,
            altitude_m=altitude_m,
            sensor_model=sensor_model,
            install_position=install_position,
            weather_level=weather_level,
            pressure_hpa=pressure_hpa,
            humidity_percent=humidity_percent,
            is_synthetic=bool(is_synthetic),
            notes=notes,
            feature_json={
                "source": "import-file",
                "has_explicit_time_axis": parsed.time_us is not None,
            },
            create_user=actor_user_id,
            update_user=actor_user_id,
            create_date=now,
            update_date=now,
        )
        db.add(event)
        db.flush()

        sample_insert_stmt = insert(LightningCurrentSample)
        total_samples = len(parsed.currents_ka)
        for start in range(0, total_samples, INSERT_CHUNK_SIZE):
            end = min(start + INSERT_CHUNK_SIZE, total_samples)
            chunk = [
                {
                    "event_ref_id": event.id,
                    "seq_no": idx + 1,
                    "time_us": time_axis_us[idx],
                    "current_ka": parsed.currents_ka[idx],
                }
                for idx in range(start, end)
            ]
            db.execute(sample_insert_stmt, chunk)

        db.commit()

        _publish_lightning_change(
            "lightning.created",
            f"导入雷电流数据：{normalized_event_id}（源文件：{source_file_name}）",
        )

        warning_count = len(warnings)
        imported_count = 1
        return LightningCurrentImportResponse(
            imported_count=imported_count,
            skipped_count=0,
            warning_count=warning_count,
            warnings=warnings[:50] if warnings else [],
        )

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        # Clean up temp file
        import os as _os2
        try:
            _os2.remove(file_path)
        except OSError:
            pass

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
    filters: list[Any] = [LightningCurrentEvent.peak_abs_current_ka.is_not(None), LightningCurrentEvent.sample_count >= 2]

    normalized_region = _normalize_str(region_id)
    if normalized_region:
        filters.append(LightningCurrentEvent.region_id == normalized_region)
    normalized_polarity = _normalize_str(polarity)
    if normalized_polarity:
        filters.append(LightningCurrentEvent.polarity == normalized_polarity.lower())
    normalized_wave_shape = _normalize_str(wave_shape)
    if normalized_wave_shape:
        filters.append(func.lower(LightningCurrentEvent.wave_shape) == normalized_wave_shape.lower())
    if is_synthetic is not None:
        filters.append(LightningCurrentEvent.is_synthetic == is_synthetic)

    values = db.execute(select(LightningCurrentEvent.peak_abs_current_ka).where(*filters)).scalars().all()
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
) -> LightningCurrentPreparationResponse:
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

    filters: list[Any] = [LightningCurrentEvent.peak_abs_current_ka.is_not(None), LightningCurrentEvent.sample_count >= 2]
    normalized_region = _normalize_str(payload.region_id)
    if normalized_region:
        filters.append(LightningCurrentEvent.region_id == normalized_region)
    if payload.is_synthetic is not None:
        filters.append(LightningCurrentEvent.is_synthetic == payload.is_synthetic)

    peaks = [
        float(item)
        for item in db.execute(select(LightningCurrentEvent.peak_abs_current_ka).where(*filters)).scalars().all()
        if item is not None
    ]
    if not peaks:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到可用于线路雷电流拟合的幅值样本")

    current_a, current_b, peak_max, peak_min, warnings = _fit_line_current_parameters(peaks)
    now = utcnow()
    tower_ids = [tower.id for tower in towers]
    existing_profiles = db.execute(select(TowerProfile).where(TowerProfile.tower_id.in_(tower_ids))).scalars().all()
    profile_map = {item.tower_id: item for item in existing_profiles}
    created_profile_count = 0

    for tower in towers:
        profile = profile_map.get(tower.id)
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

def _publish_lightning_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            LIGHTNING_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/lightning-currents"],
            dedupe_key=f"{event_name}:{payload.get('event_id', 'unknown')}",
        )
    )

def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)

def _query_batch_groups(
    db: Session,
    model: type,
    *,
    keyword: str | None,
    region_id: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[LightningImportBatchSummary]]:
    """Query import batch groups from a single model table."""
    import hashlib

    filters = []

    if keyword:
        keyword_pattern = f"%{keyword}%"
        filters.append(
            or_(
                model.source_file_name.ilike(keyword_pattern),
                model.location_tag.ilike(keyword_pattern),
                model.city.ilike(keyword_pattern),
            )
        )

    if region_id:
        filters.append(model.region_id == region_id)

    batch_key = func.concat(
        func.coalesce(model.source_file_name, ""),
        "|",
        func.date_trunc("second", model.create_date).cast(String),
        "|",
        func.coalesce(model.region_id, ""),
        "|",
        func.coalesce(model.location_tag, ""),
        "|",
        func.coalesce(model.city, ""),
    )

    total = db.execute(
        select(func.count(func.distinct(batch_key)))
        .select_from(model)
        .where(*filters)
    ).scalar() or 0

    rows = db.execute(
        select(
            batch_key.label("batch_key"),
            model.source_file_name,
            func.min(model.create_date).label("import_time"),
            func.count().label("event_count"),
            model.region_id,
            model.location_tag,
            model.city,
            func.extract("year", func.min(model.event_time)).label("event_year"),
            func.bool_or(model.is_synthetic).label("is_synthetic"),
            func.max(model.notes).label("notes"),
            func.max(model.peak_abs_current_ka).label("max_abs_current_ka"),
            func.avg(model.peak_abs_current_ka).label("avg_abs_current_ka"),
            func.sum(case((model.polarity == "positive", 1), else_=0)).label("positive_count"),
            func.sum(case((model.polarity == "negative", 1), else_=0)).label("negative_count"),
            func.max(model.create_user).label("create_user"),
        )
        .where(*filters)
        .group_by(
            batch_key,
            model.source_file_name,
            model.region_id,
            model.location_tag,
            model.city,
        )
        .order_by(func.min(model.create_date).desc())
    ).all()

    items = []
    for row in rows:
        batch_id = hashlib.md5(row.batch_key.encode()).hexdigest()[:16]
        items.append(
            LightningImportBatchSummary(
                batch_id=batch_id,
                source_file_name=row.source_file_name,
                import_time=row.import_time,
                event_count=row.event_count,
                region_id=row.region_id,
                location_tag=row.location_tag,
                city=row.city,
                event_year=int(row.event_year) if row.event_year else None,
                is_synthetic=row.is_synthetic or False,
                notes=row.notes,
                max_abs_current_ka=float(row.max_abs_current_ka) if row.max_abs_current_ka else None,
                avg_abs_current_ka=float(row.avg_abs_current_ka) if row.avg_abs_current_ka else None,
                positive_count=int(row.positive_count or 0),
                negative_count=int(row.negative_count or 0),
                create_user=row.create_user,
            )
        )

    return total, items


# ---------------------------------------------------------------------------
# 地闪分布（LightningDistribution）服务函数
# ---------------------------------------------------------------------------
def _serialize_distribution(dist: LightningDistribution) -> LightningDistributionRecord:
    """把 LightningDistribution ORM 对象序列化为 schema。"""
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
        status=dist.status,
        stage=dist.stage,
        progress=dist.progress,
        task_id=dist.task_id,
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
        stats_json=dist.stats_json,
        has_image=bool(dist.image_object_key),
        create_user=dist.create_user,
        create_date=dist.create_date,
        update_date=dist.update_date,
        update_user=dist.update_user,
    )


def import_lightning_distribution_from_file(
    db: Session,
    *,
    file: UploadFile,
    actor_user_id: str,
    event_year: int | None,
    region_id: str | None,
    location_tag: str | None,
    city: str | None,
    notes: str | None,
    line_id: str | None = None,
) -> LightningDistributionImportResponse:
    """上传文件 → 立即 put_object 到 MinIO → 建 LightningDistribution(pending) → 派发 Celery。"""
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    from ..services.minio_storage import build_source_key, put_object
    from uuid import uuid4 as _uuid4

    source_file_name = _normalize_str(str(file.filename or "upload")) or "upload"
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
        create_user=actor_user_id,
        create_date=_now,
        update_date=_now,
    )
    db.add(dist)
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

    return LightningDistributionListResponse(
        items=[_serialize_distribution(d) for d in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


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
    return _serialize_distribution(dist)


def get_lightning_distribution_status(
    db: Session,
    distribution_id: str,
) -> LightningDistributionStatusResponse:
    """轮询任务进度（status/stage/progress）。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    return LightningDistributionStatusResponse(
        distribution_id=dist.id,
        status=dist.status,
        stage=dist.stage,
        progress=dist.progress,
        error_message=dist.error_message,
        record=_serialize_distribution(dist),
    )


def get_lightning_distribution_image_url(
    db: Session,
    distribution_id: str,
) -> LightningDistributionImageResponse:
    """返回密度图 MinIO 预签名 URL（供前端 <img> 直接展示）。"""
    dist = get_lightning_distribution_by_id(db, distribution_id)
    if not dist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    if not dist.image_object_key:
        return LightningDistributionImageResponse(distribution_id=dist.id, image_url=None)
    from ..services.minio_storage import presigned_url
    image_url = presigned_url(dist.image_object_key, expires=3600)
    return LightningDistributionImageResponse(distribution_id=dist.id, image_url=image_url)


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
    for key in (dist.source_object_key, dist.image_object_key, dist.thumbnail_key):
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
    )
    return {"success": True}


def trigger_line_density_fill(
    db: Session,
    payload: LightningFillDensityRequest,
    *,
    actor_user_id: str | None,
) -> LightningFillDensityResponse:
    """线路地闪密度回填：派发 fill_line_lightning_density_job。"""
    from ..tasks.lightning_tasks import fill_line_lightning_density_job
    task = fill_line_lightning_density_job.delay(
        line_id=payload.line_id,
        region_id=payload.region_id,
        years=payload.years,
        radius_km=payload.radius_km,
        actor_user_id=actor_user_id,
    )
    return LightningFillDensityResponse(task_id=task.id, status="submitted")


# ---------------------------------------------------------------------------
# 线路密度回填（同步版，/prepare-density 使用）
# ---------------------------------------------------------------------------
def prepare_line_lightning_density(
    db: Session,
    payload: LightningDensityPreparationRequest,
    *,
    actor_user_id: str,
) -> LightningDensityPreparationResponse:
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

    # 数据来源：线路关联的最新 LightningDistribution + MinIO 原始文件（不再读明细点表）
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
# 文件导入批次列表（仅波形，distribution 已迁移至 /distributions）
# ---------------------------------------------------------------------------
def list_lightning_import_batches(
    db: Session,
    *,
    keyword: str | None = None,
    region_id: str | None = None,
    import_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LightningImportBatchListResponse:
    """
    列出文件导入批次记录，按导入时间分组。
    地闪分布导入已迁移至 /distributions 系列（LightningDistribution 表），
    本接口仅服务雷电流波形导入（LightningCurrentEvent + LightningImportBatch）。
    """
    waveform_items = []

    if import_type is None or import_type == "waveform":
        _, waveform_items = _query_batch_groups(
            db, LightningCurrentEvent,
            keyword=keyword, region_id=region_id, limit=1000, offset=0,
        )

    # 从 LightningImportBatch 表查询正在处理或待处理的导入记录
    from ..models.lightning_import_batch import LightningImportBatch as ImportBatchModel
    batch_filters = [ImportBatchModel.status.in_(["pending", "processing", "failed"])]
    if import_type and import_type != "waveform":
        batch_filters.append(ImportBatchModel.import_type == import_type)
    if keyword:
        batch_filters.append(ImportBatchModel.source_file_name.ilike(f"%{keyword}%"))
    if region_id:
        batch_filters.append(ImportBatchModel.region_id == region_id)
    pending_batches = db.execute(
        select(ImportBatchModel).where(*batch_filters).order_by(ImportBatchModel.create_date.desc())
    ).scalars().all()

    batch_items = []
    for b in pending_batches:
        batch_items.append(
            LightningImportBatchSummary(
                batch_id=b.id,
                source_file_name=b.source_file_name,
                import_time=b.create_date,
                event_count=b.event_count,
                region_id=b.region_id,
                location_tag=b.location_tag,
                city=b.city,
                event_year=b.event_year,
                is_synthetic=b.is_synthetic,
                notes=b.notes,
                line_id=b.line_id,
                status=b.status,
                create_user=b.create_user,
            )
        )

    all_items = batch_items + waveform_items
    all_items.sort(key=lambda x: x.import_time or datetime.min, reverse=True)
    total = len(all_items)
    paginated = all_items[offset:offset + limit]

    return LightningImportBatchListResponse(
        items=paginated,
        total=total,
        limit=limit,
        offset=offset,
    )
