from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import and_, case, func, insert, or_, select, String
from sqlalchemy.orm import Session

from ..models.base import utcnow
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
    LightningDistributionEventBrief,
    LightningDistributionGridCell,
    LightningDistributionImportResponse,
    LightningDistributionScatterPoint,
    LightningDistributionStatsResponse,
    LightningDistributionSummary,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningDistributionReportResponse,
    LightningCurrentExceedancePoint,
    LightningCurrentExceedanceResponse,
    LightningCurrentImportResponse,
    LightningPolarityStats,
    LightningCurrentSampleItem,
    LightningCurrentSampleListResponse,
    LightningPolarity,
    LightningSourceStats,
    LightningSyntheticCompareResponse,
    LightningSyntheticDatasetStats,
    LightningTowerBufferEventItem,
    LightningTowerBufferStatsResponse,
    LightningTowerTerrainComputeRequest,
    LightningTowerTerrainComputeResponse,
    LightningTowerTerrainMetrics,
)
from ..schemas.lightning_import import (
    LightningImportBatchSummary,
    LightningImportBatchListResponse,
    LightningImportBatchEventItem,
    LightningImportBatchEventsResponse,
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
    stmt = select(LightningCurrentEvent)
    total_stmt = select(func.count()).select_from(LightningCurrentEvent)

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


def import_lightning_distribution_from_file(
    db: Session,
    *,
    file: UploadFile,
    actor_user_id: str,
    event_year: int | None,
    region_id: str | None,
    location_tag: str | None,
    city: str | None,
    is_synthetic: bool,
    notes: str | None,
) -> LightningDistributionImportResponse:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传文件为空")

    text = _decode_text_bytes(content)
    normalized_region = _normalize_str(region_id)
    normalized_location = _normalize_str(location_tag)
    normalized_city = _normalize_str(city)
    normalized_notes = _normalize_str(notes)
    source_file_name = _normalize_str(file.filename)
    parsed_event_time = datetime(event_year, 1, 1) if event_year is not None else None

    rows_to_insert: list[dict[str, Any]] = []
    inserted_count = 0
    skipped_count = 0
    warnings: list[str] = []
    now = utcnow()

    insert_stmt = insert(LightningCurrentEvent)
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if inserted_count + skipped_count >= MAX_DISTRIBUTION_ROWS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"记录数超过上限（>{MAX_DISTRIBUTION_ROWS}），请拆分文件后重试",
            )

        parsed = _parse_distribution_line(raw_line)
        if not parsed:
            stripped = raw_line.strip()
            if stripped and len(warnings) < 50:
                warnings.append(f"第 {line_no} 行无法解析为“纬度 经度 电流”，已跳过")
            skipped_count += 1
            continue

        latitude, longitude, current_ka = parsed
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            skipped_count += 1
            if len(warnings) < 50:
                warnings.append(f"第 {line_no} 行坐标越界（lat={latitude}, lon={longitude}），已跳过")
            continue

        if math.isclose(current_ka, 0.0, abs_tol=1e-12):
            polarity: LightningPolarity = "unknown"
        else:
            polarity = "positive" if current_ka > 0 else "negative"

        event_id = _generate_distribution_event_id()
        stroke_peaks = [
            {
                "seq_no": 1,
                "sample_index": 1,
                "time_us": 0.0,
                "current_ka": current_ka,
            }
        ]
        rows_to_insert.append(
            {
                "id": uuid4().hex,
                "event_id": event_id,
                "source_file_name": source_file_name,
                "event_time": parsed_event_time,
                "sample_count": 1,
                "sample_interval_us": None,
                "sampling_frequency_hz": None,
                "peak_current_ka": current_ka,
                "peak_abs_current_ka": abs(current_ka),
                "wavefront_time_t1_us": None,
                "half_value_time_t2_us": None,
                "steepness_ka_per_us": None,
                "action_integral_j_ohm": None,
                "wave_shape": None,
                "polarity": polarity,
                "stroke_count": 1,
                "stroke_peaks_json": stroke_peaks,
                "region_id": normalized_region,
                "location_tag": normalized_location,
                "city": normalized_city,
                "longitude": longitude,
                "latitude": latitude,
                "altitude_m": None,
                "sensor_model": None,
                "install_position": None,
                "weather_level": None,
                "pressure_hpa": None,
                "humidity_percent": None,
                "is_synthetic": bool(is_synthetic),
                "feature_json": {
                    "source": "distribution-import",
                    "line_no": line_no,
                },
                "notes": normalized_notes,
                "create_user": actor_user_id,
                "update_user": actor_user_id,
                "create_date": now,
                "update_date": now,
            }
        )
        if len(rows_to_insert) >= INSERT_CHUNK_SIZE:
            db.execute(insert_stmt, rows_to_insert)
            inserted_count += len(rows_to_insert)
            rows_to_insert.clear()

    if rows_to_insert:
        db.execute(insert_stmt, rows_to_insert)
        inserted_count += len(rows_to_insert)

    if inserted_count == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未解析到可导入的有效地闪密度记录")

    db.commit()
    _publish_lightning_change(
        "lightning.distribution.imported",
        {"action": "distribution_imported", "imported_count": inserted_count},
    )
    return LightningDistributionImportResponse(
        imported_count=inserted_count,
        skipped_count=skipped_count,
        warning_count=len(warnings),
        warnings=warnings,
    )


def get_lightning_distribution_stats(
    db: Session,
    *,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
    region_id: str | None,
    city: str | None,
    location_tag: str | None,
    polarity: str | None,
    is_synthetic: bool | None,
    grid_size_km: float,
    years: float | None,
    grid_limit: int,
    scatter_limit: int,
    thresholds_ka: list[float] | None,
) -> LightningDistributionStatsResponse:
    filters = _build_distribution_filters(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        polarity=polarity,
        is_synthetic=is_synthetic,
    )

    summary_row = db.execute(
        select(
            func.count().label("total_records"),
            func.min(LightningCurrentEvent.latitude).label("min_lat"),
            func.max(LightningCurrentEvent.latitude).label("max_lat"),
            func.min(LightningCurrentEvent.longitude).label("min_lon"),
            func.max(LightningCurrentEvent.longitude).label("max_lon"),
            func.max(LightningCurrentEvent.peak_abs_current_ka).label("max_abs"),
            func.avg(LightningCurrentEvent.peak_abs_current_ka).label("avg_abs"),
            func.sum(case((LightningCurrentEvent.polarity == "positive", 1), else_=0)).label("positive_count"),
            func.sum(case((LightningCurrentEvent.polarity == "negative", 1), else_=0)).label("negative_count"),
            func.sum(case((LightningCurrentEvent.polarity == "mixed", 1), else_=0)).label("mixed_count"),
            func.sum(case((LightningCurrentEvent.polarity == "unknown", 1), else_=0)).label("unknown_count"),
            func.sum(case((LightningCurrentEvent.is_synthetic.is_(True), 1), else_=0)).label("synthetic_count"),
        ).where(*filters)
    ).one()

    total_records = int(summary_row.total_records or 0)
    if total_records == 0:
        return LightningDistributionStatsResponse(
            summary=LightningDistributionSummary(
                total_records=0,
                area_km2=0.0,
                data_years=years or 1.0,
                grid_size_km=grid_size_km,
                overall_ng_per_km2_year=0.0,
                max_abs_current_ka=None,
                avg_abs_current_ka=None,
            ),
            polarity=LightningPolarityStats(),
            sources=LightningSourceStats(),
            grid_cells=[],
            scatter_points=[],
            p_curve=[],
        )

    min_lat_value = float(summary_row.min_lat)
    max_lat_value = float(summary_row.max_lat)
    min_lon_value = float(summary_row.min_lon)
    max_lon_value = float(summary_row.max_lon)
    center_lat = (min_lat_value + max_lat_value) / 2.0
    km_per_lon = _safe_km_per_lon(center_lat)

    width_km = max((max_lon_value - min_lon_value) * km_per_lon, grid_size_km)
    height_km = max((max_lat_value - min_lat_value) * DEGREE_TO_KM, grid_size_km)
    area_km2 = max(width_km * height_km, grid_size_km * grid_size_km)
    data_years = years if years is not None else _infer_data_years(db, filters)
    data_years = max(data_years, 1e-6)
    overall_ng = total_records / (area_km2 * data_years)

    positive_count = int(summary_row.positive_count or 0)
    negative_count = int(summary_row.negative_count or 0)
    mixed_count = int(summary_row.mixed_count or 0)
    unknown_count = int(summary_row.unknown_count or 0)
    synthetic_count = int(summary_row.synthetic_count or 0)

    cell_x_expr = func.floor(((LightningCurrentEvent.longitude - min_lon_value) * km_per_lon) / grid_size_km)
    cell_y_expr = func.floor(((LightningCurrentEvent.latitude - min_lat_value) * DEGREE_TO_KM) / grid_size_km)
    grid_rows = db.execute(
        select(
            cell_x_expr.label("cell_x"),
            cell_y_expr.label("cell_y"),
            func.count().label("strike_count"),
            func.max(LightningCurrentEvent.peak_abs_current_ka).label("i_max"),
            func.avg(LightningCurrentEvent.peak_abs_current_ka).label("i_avg"),
            func.sum(case((LightningCurrentEvent.polarity == "positive", 1), else_=0)).label("positive_count"),
        )
        .where(*filters)
        .group_by(cell_x_expr, cell_y_expr)
        .order_by(func.count().desc())
        .limit(grid_limit)
    ).all()

    grid_cells: list[LightningDistributionGridCell] = []
    for row in grid_rows:
        grid_x = int(float(row.cell_x))
        grid_y = int(float(row.cell_y))
        x0_km = grid_x * grid_size_km
        x1_km = (grid_x + 1) * grid_size_km
        y0_km = grid_y * grid_size_km
        y1_km = (grid_y + 1) * grid_size_km

        cell_min_lat = min_lat_value + y0_km / DEGREE_TO_KM
        cell_max_lat = min_lat_value + y1_km / DEGREE_TO_KM
        cell_center_lat = (cell_min_lat + cell_max_lat) / 2.0
        cell_km_per_lon = _safe_km_per_lon(cell_center_lat)
        cell_min_lon = min_lon_value + x0_km / cell_km_per_lon
        cell_max_lon = min_lon_value + x1_km / cell_km_per_lon
        cell_center_lon = (cell_min_lon + cell_max_lon) / 2.0

        strike_count = int(row.strike_count or 0)
        positive_in_cell = int(row.positive_count or 0)
        grid_cells.append(
            LightningDistributionGridCell(
                grid_x=grid_x,
                grid_y=grid_y,
                min_lat=cell_min_lat,
                max_lat=cell_max_lat,
                min_lon=cell_min_lon,
                max_lon=cell_max_lon,
                center_lat=cell_center_lat,
                center_lon=cell_center_lon,
                strike_count=strike_count,
                ng_per_km2_year=strike_count / (grid_size_km * grid_size_km * data_years),
                i_max_ka=float(row.i_max) if row.i_max is not None else None,
                i_avg_ka=float(row.i_avg) if row.i_avg is not None else None,
                positive_ratio=(positive_in_cell / strike_count) if strike_count > 0 else 0.0,
            )
        )

    scatter_rows = db.execute(
        select(
            LightningCurrentEvent.id,
            LightningCurrentEvent.event_id,
            LightningCurrentEvent.longitude,
            LightningCurrentEvent.latitude,
            LightningCurrentEvent.peak_current_ka,
            LightningCurrentEvent.peak_abs_current_ka,
            LightningCurrentEvent.polarity,
            LightningCurrentEvent.region_id,
            LightningCurrentEvent.city,
            LightningCurrentEvent.location_tag,
            LightningCurrentEvent.event_time,
        )
        .where(*filters)
        .order_by(
            LightningCurrentEvent.peak_abs_current_ka.desc(),
            LightningCurrentEvent.update_date.desc(),
            LightningCurrentEvent.id.desc(),
        )
        .limit(scatter_limit)
    ).all()
    scatter_points = [
        LightningDistributionScatterPoint(
            id=str(row.id),
            event_id=str(row.event_id),
            longitude=float(row.longitude),
            latitude=float(row.latitude),
            current_ka=float(row.peak_current_ka) if row.peak_current_ka is not None else None,
            abs_current_ka=float(row.peak_abs_current_ka) if row.peak_abs_current_ka is not None else None,
            polarity=str(row.polarity),  # type: ignore[arg-type]
            region_id=row.region_id,
            city=row.city,
            location_tag=row.location_tag,
            event_time=row.event_time,
        )
        for row in scatter_rows
    ]

    p_curve = _build_p_curve_with_filters(
        db,
        filters=filters,
        total_events=total_records,
        max_peak=float(summary_row.max_abs) if summary_row.max_abs is not None else 0.0,
        thresholds_ka=thresholds_ka,
    )

    return LightningDistributionStatsResponse(
        summary=LightningDistributionSummary(
            total_records=total_records,
            area_km2=area_km2,
            data_years=data_years,
            grid_size_km=grid_size_km,
            overall_ng_per_km2_year=overall_ng,
            max_abs_current_ka=float(summary_row.max_abs) if summary_row.max_abs is not None else None,
            avg_abs_current_ka=float(summary_row.avg_abs) if summary_row.avg_abs is not None else None,
        ),
        polarity=LightningPolarityStats(
            positive_count=positive_count,
            negative_count=negative_count,
            mixed_count=mixed_count,
            unknown_count=unknown_count,
            positive_ratio=(positive_count / total_records) if total_records > 0 else 0.0,
            negative_ratio=(negative_count / total_records) if total_records > 0 else 0.0,
        ),
        sources=LightningSourceStats(
            measured_count=total_records - synthetic_count,
            synthetic_count=synthetic_count,
        ),
        grid_cells=grid_cells,
        scatter_points=scatter_points,
        p_curve=p_curve,
    )


def get_tower_buffer_stats(
    db: Session,
    *,
    tower_id: str | None,
    longitude: float | None,
    latitude: float | None,
    radius_km: float,
    design_current_ka: float,
    years: float | None,
    region_id: str | None,
    is_synthetic: bool | None,
    include_events_limit: int,
) -> LightningTowerBufferStatsResponse:
    if radius_km <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="radius_km 必须大于 0")
    if design_current_ka <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="design_current_ka 必须大于 0")

    tower: LineTower | None = None
    center_lon: float
    center_lat: float
    if tower_id:
        tower = db.execute(select(LineTower).where(LineTower.id == tower_id)).scalar_one_or_none()
        if not tower:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔不存在")
        if tower.longitude is None or tower.latitude is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该杆塔缺少经纬度，无法执行缓冲区分析")
        center_lon = float(tower.longitude)
        center_lat = float(tower.latitude)
    else:
        if longitude is None or latitude is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请提供 tower_id 或经纬度坐标")
        center_lon = float(longitude)
        center_lat = float(latitude)

    lat_delta = radius_km / DEGREE_TO_KM
    lon_delta = radius_km / _safe_km_per_lon(center_lat)
    filters = _build_distribution_filters(
        min_lat=center_lat - lat_delta,
        max_lat=center_lat + lat_delta,
        min_lon=center_lon - lon_delta,
        max_lon=center_lon + lon_delta,
        region_id=region_id,
        city=None,
        location_tag=None,
        polarity=None,
        is_synthetic=is_synthetic,
    )

    candidate_rows = db.execute(
        select(
            LightningCurrentEvent.id,
            LightningCurrentEvent.event_id,
            LightningCurrentEvent.longitude,
            LightningCurrentEvent.latitude,
            LightningCurrentEvent.peak_current_ka,
            LightningCurrentEvent.peak_abs_current_ka,
            LightningCurrentEvent.polarity,
            LightningCurrentEvent.event_time,
            LightningCurrentEvent.location_tag,
            LightningCurrentEvent.city,
        ).where(*filters)
    ).all()

    events: list[LightningTowerBufferEventItem] = []
    positive_count = 0
    max_abs = 0.0
    sum_abs = 0.0
    exceed_count = 0
    event_timestamps: list[datetime] = []
    for row in candidate_rows:
        if row.longitude is None or row.latitude is None:
            continue
        distance = _haversine_km(center_lat, center_lon, float(row.latitude), float(row.longitude))
        if distance > radius_km:
            continue
        abs_current = float(row.peak_abs_current_ka) if row.peak_abs_current_ka is not None else 0.0
        if str(row.polarity) == "positive":
            positive_count += 1
        if abs_current > max_abs:
            max_abs = abs_current
        sum_abs += abs_current
        if abs_current >= design_current_ka:
            exceed_count += 1
        if row.event_time is not None:
            event_timestamps.append(row.event_time)

        events.append(
            LightningTowerBufferEventItem(
                id=str(row.id),
                event_id=str(row.event_id),
                longitude=float(row.longitude),
                latitude=float(row.latitude),
                current_ka=float(row.peak_current_ka) if row.peak_current_ka is not None else None,
                abs_current_ka=abs_current,
                polarity=str(row.polarity),  # type: ignore[arg-type]
                event_time=row.event_time,
                location_tag=row.location_tag,
                city=row.city,
                distance_km=distance,
            )
        )

    strike_count = len(events)
    avg_abs = (sum_abs / strike_count) if strike_count > 0 else None
    data_years = years if years is not None else _resolve_data_years_from_timestamps(event_timestamps)
    data_years = max(data_years, 1e-6)
    area_km2 = math.pi * (radius_km ** 2)
    ng = strike_count / (area_km2 * data_years) if strike_count > 0 else 0.0
    positive_ratio = (positive_count / strike_count) if strike_count > 0 else 0.0
    terrain_metrics = _build_tower_terrain_metrics_from_tower(tower)
    terrain_exposure = (
        terrain_metrics.terrain_exposure_index
        if terrain_metrics is not None and terrain_metrics.terrain_exposure_index is not None
        else 0.0
    )
    ng_for_risk = ng * (1.0 + 0.25 * max(0.0, min(1.0, terrain_exposure)))
    risk_level = _derive_tower_risk_level(
        strike_count=strike_count,
        exceed_design_count=exceed_count,
        max_abs_current_ka=max_abs if strike_count > 0 else None,
        design_current_ka=design_current_ka,
        ng_per_km2_year=ng_for_risk,
    )
    recommended_action = _tower_risk_recommendation(risk_level)
    if terrain_metrics is not None and terrain_exposure >= 0.7:
        recommended_action = f"{recommended_action} 地形暴露指数较高，建议同步复核边坡防护与接地体布置。"

    sorted_events = sorted(events, key=lambda item: ((item.abs_current_ka or 0.0), -item.distance_km), reverse=True)
    return LightningTowerBufferStatsResponse(
        tower_id=tower.id if tower else None,
        tower_no=tower.tower_no if tower else None,
        line_id=tower.line_id if tower else None,
        center_longitude=center_lon,
        center_latitude=center_lat,
        radius_km=radius_km,
        design_current_ka=design_current_ka,
        strike_count=strike_count,
        exceed_design_count=exceed_count,
        max_abs_current_ka=(max_abs if strike_count > 0 else None),
        avg_abs_current_ka=avg_abs,
        ng_per_km2_year=ng,
        positive_ratio=positive_ratio,
        risk_level=risk_level,
        recommended_action=recommended_action,
        events=sorted_events[:include_events_limit],
        terrain_metrics=terrain_metrics,
    )


def compute_tower_terrain_metrics(
    db: Session,
    *,
    payload: LightningTowerTerrainComputeRequest,
    actor_user_id: str,
    can_persist: bool,
) -> LightningTowerTerrainComputeResponse:
    warnings: list[str] = []
    tower: LineTower | None = None

    if payload.tower_id:
        tower = db.execute(select(LineTower).where(LineTower.id == payload.tower_id)).scalar_one_or_none()
        if not tower:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="杆塔不存在")

    center_lon = payload.longitude if payload.longitude is not None else (float(tower.longitude) if tower and tower.longitude is not None else None)
    center_lat = payload.latitude if payload.latitude is not None else (float(tower.latitude) if tower and tower.latitude is not None else None)
    if center_lon is None or center_lat is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少中心经纬度，请传入 tower_id 或经纬度")

    z = payload.dem_grid_m
    cell_size_m = float(payload.cell_size_m)
    dem_resolution_m = float(payload.dem_resolution_m) if payload.dem_resolution_m is not None else cell_size_m

    dz_dx, dz_dy = _compute_horn_gradient(z, cell_size_m=cell_size_m)
    slope_rad = math.atan(math.sqrt(dz_dx * dz_dx + dz_dy * dz_dy))
    slope_deg = math.degrees(slope_rad)
    aspect_deg = _compute_aspect_deg(dz_dx, dz_dy)
    relief_m_50 = max(max(row) for row in z) - min(min(row) for row in z)

    neighbor_slopes = _compute_neighbor_slopes(z, cell_size_m=cell_size_m)
    slope_mean_deg = (sum(neighbor_slopes) / len(neighbor_slopes)) if neighbor_slopes else None
    slope_p95_deg = _percentile(neighbor_slopes, 0.95) if neighbor_slopes else None
    slope_max_deg = max(neighbor_slopes) if neighbor_slopes else None

    line_azimuth_deg = _infer_tower_line_azimuth_deg(db, tower) if tower else None
    slope_along_line_deg: float | None = None
    slope_cross_line_deg: float | None = None
    if line_azimuth_deg is not None:
        slope_along_line_deg = math.degrees(math.atan(_directional_gradient(dz_dx, dz_dy, line_azimuth_deg)))
        slope_cross_line_deg = math.degrees(math.atan(_directional_gradient(dz_dx, dz_dy, (line_azimuth_deg + 90.0) % 360.0)))
    elif tower is not None and tower.line_id:
        warnings.append("未找到可用相邻杆塔坐标，无法推导线路方向纵坡/横坡")

    windward_factor: float | None = None
    if payload.wind_direction_deg is not None and aspect_deg is not None:
        diff = _angle_difference_deg(aspect_deg, float(payload.wind_direction_deg))
        windward_factor = max(0.0, math.cos(math.radians(diff)))

    terrain_exposure_index = min(
        1.0,
        max(0.0, slope_deg / 45.0) * ((0.6 + 0.4 * windward_factor) if windward_factor is not None else 1.0),
    )

    quality_score, quality_level = _evaluate_terrain_quality(
        dem_resolution_m=dem_resolution_m,
        search_radius_m=float(payload.search_radius_m),
        warnings=warnings,
    )

    metrics = LightningTowerTerrainMetrics(
        slope_deg=round(slope_deg, 6),
        aspect_deg=(round(aspect_deg, 6) if aspect_deg is not None else None),
        slope_mean_deg=(round(slope_mean_deg, 6) if slope_mean_deg is not None else None),
        slope_p95_deg=(round(slope_p95_deg, 6) if slope_p95_deg is not None else None),
        slope_max_deg=(round(slope_max_deg, 6) if slope_max_deg is not None else None),
        slope_along_line_deg=(round(slope_along_line_deg, 6) if slope_along_line_deg is not None else None),
        slope_cross_line_deg=(round(slope_cross_line_deg, 6) if slope_cross_line_deg is not None else None),
        relief_m_50=round(relief_m_50, 6),
        dem_source=(payload.dem_source or "manual-grid"),
        dem_resolution_m=round(dem_resolution_m, 6),
        quality_score=round(quality_score, 2),
        quality_level=quality_level,
        terrain_exposure_index=round(terrain_exposure_index, 6),
        windward_factor=(round(windward_factor, 6) if windward_factor is not None else None),
        algorithm_version=TERRAIN_ALGORITHM_VERSION,
        computed_at=utcnow(),
        land_cover_type=payload.land_cover_type,
    )

    persisted = False
    if payload.persist:
        if tower is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="persist=true 时必须传入 tower_id")
        if not can_persist:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少 tower.manage/lightning.manage 权限，无法持久化")

        raw_extra = dict(tower.raw_extra_json or {})
        terrain_payload = metrics.model_dump(mode="json", exclude_none=True)
        terrain_payload["search_radius_m"] = float(payload.search_radius_m)
        if line_azimuth_deg is not None:
            terrain_payload["line_azimuth_deg"] = round(line_azimuth_deg, 6)
        raw_extra["terrain_metrics"] = terrain_payload

        tower.raw_extra_json = raw_extra
        if slope_along_line_deg is not None:
            tower.slope_1 = abs(float(slope_along_line_deg))
        if slope_cross_line_deg is not None:
            tower.slope_2 = abs(float(slope_cross_line_deg))
        if payload.altitude_m is not None:
            tower.altitude_m = payload.altitude_m
        tower.update_user = actor_user_id
        tower.update_date = utcnow()
        db.commit()
        persisted = True

    return LightningTowerTerrainComputeResponse(
        tower_id=tower.id if tower else None,
        tower_no=tower.tower_no if tower else None,
        line_id=tower.line_id if tower else None,
        center_longitude=float(center_lon),
        center_latitude=float(center_lat),
        method="horn_3x3",
        persisted=persisted,
        terrain_metrics=metrics,
        warnings=warnings,
    )


def compare_measured_and_synthetic_distribution(
    db: Session,
    *,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
    region_id: str | None,
    city: str | None,
    location_tag: str | None,
    grid_size_km: float,
    years: float | None,
) -> LightningSyntheticCompareResponse:
    base_filters = _build_distribution_filters(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        polarity=None,
        is_synthetic=None,
    )

    extent_row = db.execute(
        select(
            func.min(LightningCurrentEvent.latitude).label("min_lat"),
            func.max(LightningCurrentEvent.latitude).label("max_lat"),
            func.min(LightningCurrentEvent.longitude).label("min_lon"),
            func.max(LightningCurrentEvent.longitude).label("max_lon"),
        ).where(*base_filters)
    ).one()

    if extent_row.min_lat is None or extent_row.max_lat is None or extent_row.min_lon is None or extent_row.max_lon is None:
        empty_stats = LightningSyntheticDatasetStats(count=0)
        return LightningSyntheticCompareResponse(
            grid_size_km=grid_size_km,
            data_years=years or 1.0,
            measured=empty_stats,
            synthetic=empty_stats,
            grid_cosine_similarity=None,
            note="当前筛选条件下没有可对比的数据",
        )

    min_lat_value = float(extent_row.min_lat)
    max_lat_value = float(extent_row.max_lat)
    min_lon_value = float(extent_row.min_lon)
    max_lon_value = float(extent_row.max_lon)
    center_lat = (min_lat_value + max_lat_value) / 2.0
    km_per_lon = _safe_km_per_lon(center_lat)
    width_km = max((max_lon_value - min_lon_value) * km_per_lon, grid_size_km)
    height_km = max((max_lat_value - min_lat_value) * DEGREE_TO_KM, grid_size_km)
    area_km2 = max(width_km * height_km, grid_size_km * grid_size_km)
    data_years = years if years is not None else _infer_data_years(db, base_filters)
    data_years = max(data_years, 1e-6)

    measured_filters = [*base_filters, LightningCurrentEvent.is_synthetic.is_(False)]
    synthetic_filters = [*base_filters, LightningCurrentEvent.is_synthetic.is_(True)]
    measured = _aggregate_dataset_stats(db, measured_filters, area_km2=area_km2, data_years=data_years)
    synthetic = _aggregate_dataset_stats(db, synthetic_filters, area_km2=area_km2, data_years=data_years)

    similarity = _compute_grid_cosine_similarity(
        db,
        measured_filters=measured_filters,
        synthetic_filters=synthetic_filters,
        min_lat=min_lat_value,
        min_lon=min_lon_value,
        km_per_lon=km_per_lon,
        grid_size_km=grid_size_km,
    )
    note = None
    if measured.count == 0 or synthetic.count == 0:
        note = "实测或合成数据为空，无法计算网格相似度"

    return LightningSyntheticCompareResponse(
        grid_size_km=grid_size_km,
        data_years=data_years,
        measured=measured,
        synthetic=synthetic,
        grid_cosine_similarity=similarity,
        note=note,
    )


def build_lightning_distribution_report(
    db: Session,
    *,
    period: str,
    anchor_time: datetime | None,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
    region_id: str | None,
    city: str | None,
    location_tag: str | None,
    is_synthetic: bool | None,
) -> LightningDistributionReportResponse:
    now = anchor_time or utcnow()
    if period == "month":
        days = 30
    else:
        period = "week"
        days = 7
    start_time = now - timedelta(days=days)

    filters = _build_distribution_filters(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        polarity=None,
        is_synthetic=is_synthetic,
    )
    event_ts_expr = func.coalesce(LightningCurrentEvent.event_time, LightningCurrentEvent.create_date)
    filters.append(and_(event_ts_expr >= start_time, event_ts_expr <= now))

    summary_row = db.execute(
        select(
            func.count().label("count"),
            func.max(LightningCurrentEvent.peak_abs_current_ka).label("max_abs"),
            func.avg(LightningCurrentEvent.peak_abs_current_ka).label("avg_abs"),
            func.sum(case((LightningCurrentEvent.polarity == "positive", 1), else_=0)).label("positive_count"),
            func.min(LightningCurrentEvent.latitude).label("min_lat"),
            func.max(LightningCurrentEvent.latitude).label("max_lat"),
            func.min(LightningCurrentEvent.longitude).label("min_lon"),
            func.max(LightningCurrentEvent.longitude).label("max_lon"),
        ).where(*filters)
    ).one()

    strike_count = int(summary_row.count or 0)
    area_km2 = 1.0
    if (
        summary_row.min_lat is not None
        and summary_row.max_lat is not None
        and summary_row.min_lon is not None
        and summary_row.max_lon is not None
    ):
        center_lat = (float(summary_row.min_lat) + float(summary_row.max_lat)) / 2.0
        km_per_lon = _safe_km_per_lon(center_lat)
        width_km = max((float(summary_row.max_lon) - float(summary_row.min_lon)) * km_per_lon, 1.0)
        height_km = max((float(summary_row.max_lat) - float(summary_row.min_lat)) * DEGREE_TO_KM, 1.0)
        area_km2 = width_km * height_km

    data_years = max(days / 365.25, 1e-6)
    ng = strike_count / (area_km2 * data_years) if strike_count > 0 else 0.0

    most_severe_row = db.execute(
        select(
            LightningCurrentEvent.id,
            LightningCurrentEvent.event_id,
            LightningCurrentEvent.longitude,
            LightningCurrentEvent.latitude,
            LightningCurrentEvent.peak_current_ka,
            LightningCurrentEvent.peak_abs_current_ka,
            LightningCurrentEvent.polarity,
            LightningCurrentEvent.event_time,
            LightningCurrentEvent.location_tag,
            LightningCurrentEvent.city,
        )
        .where(*filters)
        .order_by(
            LightningCurrentEvent.peak_abs_current_ka.desc(),
            event_ts_expr.desc(),
            LightningCurrentEvent.id.desc(),
        )
        .limit(1)
    ).one_or_none()

    severe_event: LightningDistributionEventBrief | None = None
    if most_severe_row is not None:
        severe_event = LightningDistributionEventBrief(
            id=str(most_severe_row.id),
            event_id=str(most_severe_row.event_id),
            longitude=float(most_severe_row.longitude) if most_severe_row.longitude is not None else None,
            latitude=float(most_severe_row.latitude) if most_severe_row.latitude is not None else None,
            current_ka=float(most_severe_row.peak_current_ka) if most_severe_row.peak_current_ka is not None else None,
            abs_current_ka=float(most_severe_row.peak_abs_current_ka) if most_severe_row.peak_abs_current_ka is not None else None,
            polarity=str(most_severe_row.polarity),  # type: ignore[arg-type]
            event_time=most_severe_row.event_time,
            location_tag=most_severe_row.location_tag,
            city=most_severe_row.city,
        )

    positive_count = int(summary_row.positive_count or 0)
    return LightningDistributionReportResponse(
        period=period,  # type: ignore[arg-type]
        start_time=start_time,
        end_time=now,
        strike_count=strike_count,
        max_abs_current_ka=float(summary_row.max_abs) if summary_row.max_abs is not None else None,
        avg_abs_current_ka=float(summary_row.avg_abs) if summary_row.avg_abs is not None else None,
        positive_ratio=(positive_count / strike_count) if strike_count > 0 else 0.0,
        ng_per_km2_year=ng,
        most_severe_event=severe_event,
    )


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
    filters: list[Any] = [LightningCurrentEvent.peak_abs_current_ka.is_not(None)]

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

    filters: list[Any] = [LightningCurrentEvent.peak_abs_current_ka.is_not(None)]
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
                geometry_layers_json={},
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

    filters = _build_distribution_filters(
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=payload.region_id,
        city=None,
        location_tag=None,
        polarity=None,
        is_synthetic=payload.is_synthetic,
    )
    candidate_rows = db.execute(
        select(
            LightningCurrentEvent.longitude,
            LightningCurrentEvent.latitude,
            LightningCurrentEvent.event_time,
        ).where(*filters)
    ).all()
    if not candidate_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到可用于地闪密度计算的雷击分布数据")

    now = utcnow()
    area_km2 = math.pi * (actual_radius_km ** 2)
    updated_tower_count = 0
    missing_geo_count = 0
    density_values: list[float] = []
    all_event_times = [row.event_time for row in candidate_rows if row.event_time is not None]
    source_years = payload.years if payload.years is not None else _resolve_data_years_from_timestamps(all_event_times)
    warnings: list[str] = []

    for tower in towers:
        if tower.longitude is None or tower.latitude is None:
            missing_geo_count += 1
            continue

        tower_times: list[datetime] = []
        strike_count = 0
        for row in candidate_rows:
            if row.longitude is None or row.latitude is None:
                continue
            distance_km = _haversine_km(
                float(tower.latitude),
                float(tower.longitude),
                float(row.latitude),
                float(row.longitude),
            )
            if distance_km > actual_radius_km:
                continue
            strike_count += 1
            if row.event_time is not None:
                tower_times.append(row.event_time)

        tower_years = payload.years if payload.years is not None else _resolve_data_years_from_timestamps(tower_times)
        tower_years = max(tower_years, 1e-6)
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
            "is_synthetic": payload.is_synthetic,
            "prepared_at": now.isoformat(),
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
            "is_synthetic": payload.is_synthetic,
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


def _build_distribution_filters(
    *,
    min_lat: float | None,
    max_lat: float | None,
    min_lon: float | None,
    max_lon: float | None,
    region_id: str | None,
    city: str | None,
    location_tag: str | None,
    polarity: str | None,
    is_synthetic: bool | None,
) -> list[Any]:
    filters: list[Any] = [
        LightningCurrentEvent.latitude.is_not(None),
        LightningCurrentEvent.longitude.is_not(None),
        LightningCurrentEvent.peak_abs_current_ka.is_not(None),
    ]
    if min_lat is not None:
        filters.append(LightningCurrentEvent.latitude >= min_lat)
    if max_lat is not None:
        filters.append(LightningCurrentEvent.latitude <= max_lat)
    if min_lon is not None:
        filters.append(LightningCurrentEvent.longitude >= min_lon)
    if max_lon is not None:
        filters.append(LightningCurrentEvent.longitude <= max_lon)

    normalized_region = _normalize_str(region_id)
    if normalized_region:
        filters.append(LightningCurrentEvent.region_id == normalized_region)

    normalized_city = _normalize_str(city)
    if normalized_city:
        filters.append(func.lower(LightningCurrentEvent.city) == normalized_city.lower())

    normalized_location = _normalize_str(location_tag)
    if normalized_location:
        filters.append(LightningCurrentEvent.location_tag.ilike(f"%{normalized_location}%"))

    normalized_polarity = _normalize_str(polarity)
    if normalized_polarity:
        filters.append(LightningCurrentEvent.polarity == normalized_polarity.lower())

    if is_synthetic is not None:
        filters.append(LightningCurrentEvent.is_synthetic == is_synthetic)

    return filters


def _build_p_curve_with_filters(
    db: Session,
    *,
    filters: list[Any],
    total_events: int,
    max_peak: float,
    thresholds_ka: list[float] | None,
) -> list[LightningCurrentExceedancePoint]:
    if total_events <= 0:
        return []
    manual_thresholds = sorted({float(value) for value in (thresholds_ka or []) if value > 0})
    if manual_thresholds:
        thresholds = manual_thresholds
    else:
        default_points = 12
        step = max(1.0, round(max_peak / max(default_points, 1), 3))
        thresholds = [round(step * idx, 3) for idx in range(1, default_points + 1)]

    points: list[LightningCurrentExceedancePoint] = []
    for threshold in thresholds:
        exceed_count = int(
            db.scalar(
                select(func.count()).select_from(LightningCurrentEvent).where(
                    *filters,
                    LightningCurrentEvent.peak_abs_current_ka >= threshold,
                )
            )
            or 0
        )
        points.append(
            LightningCurrentExceedancePoint(
                threshold_ka=threshold,
                exceedance_probability=(exceed_count / total_events) if total_events > 0 else 0.0,
                exceedance_count=exceed_count,
            )
        )
    return points


def _aggregate_dataset_stats(
    db: Session,
    filters: list[Any],
    *,
    area_km2: float,
    data_years: float,
) -> LightningSyntheticDatasetStats:
    row = db.execute(
        select(
            func.count().label("count"),
            func.max(LightningCurrentEvent.peak_abs_current_ka).label("max_abs"),
            func.avg(LightningCurrentEvent.peak_abs_current_ka).label("avg_abs"),
            func.sum(case((LightningCurrentEvent.polarity == "positive", 1), else_=0)).label("positive_count"),
        ).where(*filters)
    ).one()
    count = int(row.count or 0)
    positive_count = int(row.positive_count or 0)
    ng = count / (area_km2 * data_years) if count > 0 else 0.0
    return LightningSyntheticDatasetStats(
        count=count,
        max_abs_current_ka=float(row.max_abs) if row.max_abs is not None else None,
        avg_abs_current_ka=float(row.avg_abs) if row.avg_abs is not None else None,
        positive_ratio=(positive_count / count) if count > 0 else 0.0,
        ng_per_km2_year=ng,
    )


def _compute_grid_cosine_similarity(
    db: Session,
    *,
    measured_filters: list[Any],
    synthetic_filters: list[Any],
    min_lat: float,
    min_lon: float,
    km_per_lon: float,
    grid_size_km: float,
) -> float | None:
    cell_x_expr = func.floor(((LightningCurrentEvent.longitude - min_lon) * km_per_lon) / grid_size_km)
    cell_y_expr = func.floor(((LightningCurrentEvent.latitude - min_lat) * DEGREE_TO_KM) / grid_size_km)
    measured_rows = db.execute(
        select(cell_x_expr.label("x"), cell_y_expr.label("y"), func.count().label("c"))
        .where(*measured_filters)
        .group_by(cell_x_expr, cell_y_expr)
    ).all()
    synthetic_rows = db.execute(
        select(cell_x_expr.label("x"), cell_y_expr.label("y"), func.count().label("c"))
        .where(*synthetic_filters)
        .group_by(cell_x_expr, cell_y_expr)
    ).all()

    if not measured_rows or not synthetic_rows:
        return None

    measured_map = {(int(float(item.x)), int(float(item.y))): float(item.c) for item in measured_rows}
    synthetic_map = {(int(float(item.x)), int(float(item.y))): float(item.c) for item in synthetic_rows}

    all_keys = set(measured_map.keys()) | set(synthetic_map.keys())
    dot = sum(measured_map.get(key, 0.0) * synthetic_map.get(key, 0.0) for key in all_keys)
    norm_m = math.sqrt(sum(value * value for value in measured_map.values()))
    norm_s = math.sqrt(sum(value * value for value in synthetic_map.values()))
    if norm_m <= 0 or norm_s <= 0:
        return None
    return max(0.0, min(1.0, dot / (norm_m * norm_s)))


def _parse_distribution_line(raw_line: str) -> tuple[float, float, float] | None:
    stripped = raw_line.strip()
    if not stripped:
        return None
    tokens = [token for token in TOKEN_SPLIT_PATTERN.split(stripped) if token]
    if len(tokens) < 3:
        return None
    values: list[float] = []
    for token in tokens:
        parsed = _parse_float(token)
        if parsed is not None:
            values.append(parsed)
        if len(values) >= 3:
            break
    if len(values) < 3:
        return None
    return (values[0], values[1], values[2])


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


def _resolve_data_years_from_timestamps(values: list[datetime]) -> float:
    if len(values) < 2:
        return 1.0
    minimum = min(values)
    maximum = max(values)
    delta_days = (maximum - minimum).total_seconds() / 86400.0
    return max(delta_days / 365.25, 1.0)


def _infer_data_years(db: Session, filters: list[Any]) -> float:
    row = db.execute(
        select(
            func.min(LightningCurrentEvent.event_time).label("min_time"),
            func.max(LightningCurrentEvent.event_time).label("max_time"),
        ).where(*filters, LightningCurrentEvent.event_time.is_not(None))
    ).one()
    if row.min_time is None or row.max_time is None:
        return 1.0
    delta_days = (row.max_time - row.min_time).total_seconds() / 86400.0
    return max(delta_days / 365.25, 1.0)


def _build_tower_terrain_metrics_from_tower(tower: LineTower | None) -> LightningTowerTerrainMetrics | None:
    if tower is None:
        return None

    raw_extra = tower.raw_extra_json or {}
    terrain_payload = raw_extra.get("terrain_metrics") if isinstance(raw_extra, dict) else None
    if isinstance(terrain_payload, dict):
        try:
            return LightningTowerTerrainMetrics.model_validate(terrain_payload)
        except Exception:
            pass

    slope_along = float(tower.slope_1) if tower.slope_1 is not None else None
    slope_cross = float(tower.slope_2) if tower.slope_2 is not None else None
    if slope_along is None and slope_cross is None:
        return None

    slope_candidates = [abs(value) for value in (slope_along, slope_cross) if value is not None]
    slope_deg = max(slope_candidates) if slope_candidates else None
    terrain_exposure = min(1.0, (slope_deg / 45.0)) if slope_deg is not None else None
    return LightningTowerTerrainMetrics(
        slope_deg=slope_deg,
        slope_max_deg=slope_deg,
        slope_along_line_deg=slope_along,
        slope_cross_line_deg=slope_cross,
        terrain_exposure_index=terrain_exposure,
        algorithm_version="tower-legacy",
    )


def _compute_horn_gradient(grid_m: list[list[float]], *, cell_size_m: float) -> tuple[float, float]:
    if len(grid_m) != 3 or any(len(row) != 3 for row in grid_m):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="DEM 网格必须是 3x3")
    if cell_size_m <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cell_size_m 必须大于 0")

    z1, z2, z3 = float(grid_m[0][0]), float(grid_m[0][1]), float(grid_m[0][2])
    z4, z5, z6 = float(grid_m[1][0]), float(grid_m[1][1]), float(grid_m[1][2])
    z7, z8, z9 = float(grid_m[2][0]), float(grid_m[2][1]), float(grid_m[2][2])

    dz_dx = ((z3 + 2.0 * z6 + z9) - (z1 + 2.0 * z4 + z7)) / (8.0 * cell_size_m)
    dz_dy = ((z1 + 2.0 * z2 + z3) - (z7 + 2.0 * z8 + z9)) / (8.0 * cell_size_m)
    return dz_dx, dz_dy


def _compute_aspect_deg(dz_dx: float, dz_dy: float) -> float | None:
    if math.isclose(dz_dx, 0.0, abs_tol=1e-12) and math.isclose(dz_dy, 0.0, abs_tol=1e-12):
        return None
    downslope_east = -dz_dx
    downslope_north = -dz_dy
    return (math.degrees(math.atan2(downslope_east, downslope_north)) + 360.0) % 360.0


def _compute_neighbor_slopes(grid_m: list[list[float]], *, cell_size_m: float) -> list[float]:
    center = float(grid_m[1][1])
    slopes: list[float] = []
    for row in range(3):
        for col in range(3):
            if row == 1 and col == 1:
                continue
            delta_h = float(grid_m[row][col]) - center
            distance = cell_size_m * math.sqrt(float((row - 1) ** 2 + (col - 1) ** 2))
            if distance <= 0:
                continue
            slopes.append(math.degrees(math.atan(abs(delta_h) / distance)))
    return slopes


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if quantile <= 0:
        return min(values)
    if quantile >= 1:
        return max(values)

    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * quantile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    lower_value = float(sorted_values[lower])
    upper_value = float(sorted_values[upper])
    weight = position - lower
    return lower_value * (1.0 - weight) + upper_value * weight


def _infer_tower_line_azimuth_deg(db: Session, tower: LineTower | None) -> float | None:
    if (
        tower is None
        or tower.line_id is None
        or tower.seq_no is None
        or tower.longitude is None
        or tower.latitude is None
    ):
        return None

    rows = db.execute(
        select(LineTower.seq_no, LineTower.longitude, LineTower.latitude)
        .where(
            LineTower.line_id == tower.line_id,
            LineTower.longitude.is_not(None),
            LineTower.latitude.is_not(None),
        )
        .order_by(LineTower.seq_no.asc())
    ).all()
    if not rows:
        return None

    previous: tuple[float, float] | None = None
    next_point: tuple[float, float] | None = None
    for row in rows:
        seq_no = int(row.seq_no)
        point = (float(row.longitude), float(row.latitude))
        if seq_no < tower.seq_no:
            previous = point
            continue
        if seq_no > tower.seq_no:
            next_point = point
            break

    if previous is not None and next_point is not None:
        start_lon, start_lat = previous
        end_lon, end_lat = next_point
    elif next_point is not None:
        start_lon = float(tower.longitude)
        start_lat = float(tower.latitude)
        end_lon, end_lat = next_point
    elif previous is not None:
        start_lon, start_lat = previous
        end_lon = float(tower.longitude)
        end_lat = float(tower.latitude)
    else:
        return None

    if math.isclose(start_lon, end_lon, abs_tol=1e-12) and math.isclose(start_lat, end_lat, abs_tol=1e-12):
        return None

    start_lat_rad = math.radians(start_lat)
    end_lat_rad = math.radians(end_lat)
    delta_lon_rad = math.radians(end_lon - start_lon)
    x = math.sin(delta_lon_rad) * math.cos(end_lat_rad)
    y = (
        math.cos(start_lat_rad) * math.sin(end_lat_rad)
        - math.sin(start_lat_rad) * math.cos(end_lat_rad) * math.cos(delta_lon_rad)
    )
    if math.isclose(x, 0.0, abs_tol=1e-12) and math.isclose(y, 0.0, abs_tol=1e-12):
        return None
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _directional_gradient(dz_dx: float, dz_dy: float, azimuth_deg: float) -> float:
    azimuth_rad = math.radians(azimuth_deg % 360.0)
    direction_east = math.sin(azimuth_rad)
    direction_north = math.cos(azimuth_rad)
    return dz_dx * direction_east + dz_dy * direction_north


def _angle_difference_deg(angle_1_deg: float, angle_2_deg: float) -> float:
    return abs((angle_1_deg - angle_2_deg + 180.0) % 360.0 - 180.0)


def _evaluate_terrain_quality(
    *,
    dem_resolution_m: float,
    search_radius_m: float,
    warnings: list[str],
) -> tuple[float, str]:
    score = 100.0

    def add_warning(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    if dem_resolution_m <= 5.0:
        score -= 0.0
    elif dem_resolution_m <= 10.0:
        score -= 5.0
    elif dem_resolution_m <= 12.5:
        score -= 10.0
    elif dem_resolution_m <= 30.0:
        score -= 25.0
        add_warning("DEM 分辨率大于 12.5m，微地形倾角结果可能偏平滑。")
    elif dem_resolution_m <= 90.0:
        score -= 45.0
        add_warning("DEM 分辨率较低（30-90m），建议使用 10m 及以上数据复核。")
    else:
        score -= 60.0
        add_warning("DEM 分辨率超过 90m，当前结果仅可用于粗略评估。")

    if search_radius_m < 30.0:
        score -= 15.0
        add_warning("地形检索半径过小（<30m），建议提高到 50m 左右。")
    elif search_radius_m < 50.0:
        score -= 8.0
    elif search_radius_m > 300.0:
        score -= 10.0
        add_warning("地形检索半径较大（>300m），局部坡度可能被稀释。")
    elif search_radius_m > 150.0:
        score -= 5.0

    score = max(0.0, min(100.0, score))
    if score >= 80.0:
        quality_level = "HIGH"
    elif score >= 60.0:
        quality_level = "MEDIUM"
    else:
        quality_level = "LOW"
    return score, quality_level


def _derive_tower_risk_level(
    *,
    strike_count: int,
    exceed_design_count: int,
    max_abs_current_ka: float | None,
    design_current_ka: float,
    ng_per_km2_year: float,
) -> str:
    if strike_count <= 0 or max_abs_current_ka is None:
        return "LOW"
    if exceed_design_count >= 3 or max_abs_current_ka >= design_current_ka * 1.5 or ng_per_km2_year >= 8.0:
        return "HIGH"
    if exceed_design_count >= 1 or max_abs_current_ka >= design_current_ka or ng_per_km2_year >= 4.0:
        return "MEDIUM"
    return "LOW"


def _tower_risk_recommendation(risk_level: str) -> str:
    if risk_level == "HIGH":
        return "建议立即复核绝缘配置与避雷器参数，并安排现场巡检。"
    if risk_level == "MEDIUM":
        return "建议纳入近期巡检计划，核查接地与线路防雷参数。"
    return "当前风险可控，建议按常规周期继续监测。"


def _generate_distribution_event_id() -> str:
    return f"LD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"


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


def list_lightning_import_batches(
    db: Session,
    *,
    keyword: str | None = None,
    region_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> LightningImportBatchListResponse:
    """
    列出文件导入批次记录，按导入时间分组
    """
    # 构建过滤条件
    filters = []

    if keyword:
        keyword_pattern = f"%{keyword}%"
        filters.append(
            or_(
                LightningCurrentEvent.source_file_name.ilike(keyword_pattern),
                LightningCurrentEvent.location_tag.ilike(keyword_pattern),
                LightningCurrentEvent.city.ilike(keyword_pattern),
            )
        )

    if region_id:
        filters.append(LightningCurrentEvent.region_id == region_id)

    # 按 source_file_name + create_date (精确到秒) + region_id + location_tag + city 分组
    # 使用 create_date 的日期和小时作为分组依据
    batch_key = func.concat(
        func.coalesce(LightningCurrentEvent.source_file_name, ""),
        "|",
        func.date_trunc("second", LightningCurrentEvent.create_date).cast(String),
        "|",
        func.coalesce(LightningCurrentEvent.region_id, ""),
        "|",
        func.coalesce(LightningCurrentEvent.location_tag, ""),
        "|",
        func.coalesce(LightningCurrentEvent.city, ""),
    )

    # 获取总数
    total_query = (
        select(func.count(func.distinct(batch_key)))
        .select_from(LightningCurrentEvent)
        .where(*filters)
    )
    total = db.execute(total_query).scalar() or 0

    # 查询批次数据
    batch_query = (
        select(
            batch_key.label("batch_key"),
            LightningCurrentEvent.source_file_name,
            func.min(LightningCurrentEvent.create_date).label("import_time"),
            func.count().label("event_count"),
            LightningCurrentEvent.region_id,
            LightningCurrentEvent.location_tag,
            LightningCurrentEvent.city,
            func.extract("year", func.min(LightningCurrentEvent.event_time)).label("event_year"),
            func.bool_or(LightningCurrentEvent.is_synthetic).label("is_synthetic"),
            func.max(LightningCurrentEvent.notes).label("notes"),
            func.max(LightningCurrentEvent.peak_abs_current_ka).label("max_abs_current_ka"),
            func.avg(LightningCurrentEvent.peak_abs_current_ka).label("avg_abs_current_ka"),
            func.sum(case((LightningCurrentEvent.polarity == "positive", 1), else_=0)).label("positive_count"),
            func.sum(case((LightningCurrentEvent.polarity == "negative", 1), else_=0)).label("negative_count"),
            func.max(LightningCurrentEvent.create_user).label("create_user"),
        )
        .where(*filters)
        .group_by(
            batch_key,
            LightningCurrentEvent.source_file_name,
            LightningCurrentEvent.region_id,
            LightningCurrentEvent.location_tag,
            LightningCurrentEvent.city,
        )
        .order_by(func.min(LightningCurrentEvent.create_date).desc())
        .limit(limit)
        .offset(offset)
    )

    rows = db.execute(batch_query).all()

    items = []
    for row in rows:
        # 使用批次key的哈希作为batch_id
        import hashlib
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

    return LightningImportBatchListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


def get_lightning_import_batch_events(
    db: Session,
    *,
    source_file_name: str | None,
    import_time: datetime,
    region_id: str | None,
    location_tag: str | None,
    city: str | None,
) -> LightningImportBatchEventsResponse:
    """
    获取某个导入批次的所有事件
    """
    import hashlib

    # 构建批次key
    batch_key_str = "|".join([
        source_file_name or "",
        import_time.isoformat(),
        region_id or "",
        location_tag or "",
        city or "",
    ])
    batch_id = hashlib.md5(batch_key_str.encode()).hexdigest()[:16]

    # 查询该批次的所有事件
    # 允许 create_date 有 5 秒误差
    time_tolerance = timedelta(seconds=5)
    filters = [
        LightningCurrentEvent.create_date >= import_time - time_tolerance,
        LightningCurrentEvent.create_date <= import_time + time_tolerance,
    ]

    if source_file_name:
        filters.append(LightningCurrentEvent.source_file_name == source_file_name)
    else:
        filters.append(LightningCurrentEvent.source_file_name.is_(None))

    if region_id:
        filters.append(LightningCurrentEvent.region_id == region_id)
    else:
        filters.append(LightningCurrentEvent.region_id.is_(None))

    if location_tag:
        filters.append(LightningCurrentEvent.location_tag == location_tag)
    else:
        filters.append(LightningCurrentEvent.location_tag.is_(None))

    if city:
        filters.append(LightningCurrentEvent.city == city)
    else:
        filters.append(LightningCurrentEvent.city.is_(None))

    query = select(LightningCurrentEvent).where(*filters).order_by(LightningCurrentEvent.event_time)

    events_db = db.execute(query).scalars().all()

    events = [
        LightningImportBatchEventItem(
            id=event.id,
            event_id=event.event_id,
            longitude=event.longitude,
            latitude=event.latitude,
            current_ka=event.peak_current_ka,
            abs_current_ka=event.peak_abs_current_ka,
            polarity=event.polarity,
            event_time=event.event_time,
        )
        for event in events_db
    ]

    return LightningImportBatchEventsResponse(
        batch_id=batch_id,
        source_file_name=source_file_name,
        import_time=import_time,
        events=events,
        total=len(events),
    )
