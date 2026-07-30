from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.lightning import (
    LightningCurrentEventListResponse,
    LightningCurrentEventSummary,
    LightningCurrentEventUpdateRequest,
    LightningCurrentPreparationRequest,
    LightningCurrentPreparationResponse,
    LightningCurrentExceedanceResponse,
    LightningCurrentImportResponse,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningCurrentSampleListResponse,
    LightningDistributionImportResponse,
    LightningDistributionReportResponse,
    LightningDistributionStatsResponse,
    LightningComputeDensityRequest,
    LightningComputeDensityResponse,
    LightningSyntheticCompareResponse,
    LightningTowerTerrainComputeRequest,
    LightningTowerTerrainComputeResponse,
    LightningTowerBufferStatsResponse,
)
from ...schemas.lightning_import import (
    LightningImportBatchListResponse,
    LightningImportBatchEventsResponse,
)
from ...services.lightning_service import (
    build_lightning_distribution_report,
    compare_measured_and_synthetic_distribution,
    compute_tower_terrain_metrics,
    delete_lightning_event,
    delete_lightning_import_batch,
    get_lightning_distribution_stats,
    get_lightning_event_by_id,
    get_peak_exceedance_curve,
    get_tower_buffer_stats,
    import_lightning_current_async,
    import_lightning_distribution_from_file,
    import_lightning_event_from_file,
    list_lightning_events,
    list_lightning_samples,
    prepare_line_lightning_current,
    prepare_line_lightning_density,
    serialize_lightning_event,
    update_lightning_event,
    list_lightning_import_batches,
    get_lightning_import_batch_events,
    trigger_ground_flash_density_computation,
)

router = APIRouter(
    prefix="/lightning-currents",
    tags=["lightning-currents"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("", response_model=LightningCurrentEventListResponse)
def get_lightning_event_list(
    keyword: str | None = Query(default=None),
    region_id: str | None = Query(default=None),
    polarity: str | None = Query(default=None),
    wave_shape: str | None = Query(default=None),
    is_synthetic: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentEventListResponse:
    return list_lightning_events(
        db,
        keyword=keyword,
        region_id=region_id,
        polarity=polarity,
        wave_shape=wave_shape,
        is_synthetic=is_synthetic,
        limit=limit,
        offset=offset,
    )


@router.get("/stats/exceedance", response_model=LightningCurrentExceedanceResponse)
def get_lightning_peak_exceedance(
    region_id: str | None = Query(default=None),
    polarity: str | None = Query(default=None),
    wave_shape: str | None = Query(default=None),
    is_synthetic: bool | None = Query(default=None),
    thresholds: str | None = Query(default=None, description="逗号分隔阈值，如 10,20,50"),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentExceedanceResponse:
    thresholds_ka: list[float] = []
    if thresholds:
        for token in thresholds.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                parsed = float(token)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"无效阈值：{token}") from None
            if parsed > 0:
                thresholds_ka.append(parsed)

    return get_peak_exceedance_curve(
        db,
        region_id=region_id,
        polarity=polarity,
        wave_shape=wave_shape,
        is_synthetic=is_synthetic,
        thresholds_ka=thresholds_ka,
    )


@router.post("/import", response_model=LightningCurrentImportResponse)
def import_lightning_current_file(
    file: UploadFile = File(...),
    event_id: str | None = Form(default=None),
    event_time: datetime | None = Form(default=None),
    sample_interval_us: float | None = Form(default=1.0),
    region_id: str | None = Form(default=None),
    location_tag: str | None = Form(default=None),
    city: str | None = Form(default=None),
    longitude: float | None = Form(default=None),
    latitude: float | None = Form(default=None),
    altitude_m: float | None = Form(default=None),
    sensor_model: str | None = Form(default=None),
    install_position: str | None = Form(default=None),
    weather_level: str | None = Form(default=None),
    pressure_hpa: float | None = Form(default=None),
    humidity_percent: float | None = Form(default=None),
    is_synthetic: bool = Form(default=False),
    notes: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentImportResponse:
    return import_lightning_event_from_file(
        db,
        file=file,
        actor_user_id=current_user.user.id,
        event_id=event_id,
        event_time=event_time,
        sample_interval_us=sample_interval_us,
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
        is_synthetic=is_synthetic,
        notes=notes,
    )


@router.post("/import-async", response_model=LightningCurrentImportResponse)
def import_lightning_current_file_async(
    file: UploadFile = File(...),
    event_id: str | None = Form(default=None),
    event_time: datetime | None = Form(default=None),
    sample_interval_us: float | None = Form(default=1.0),
    region_id: str | None = Form(default=None),
    location_tag: str | None = Form(default=None),
    city: str | None = Form(default=None),
    longitude: float | None = Form(default=None),
    latitude: float | None = Form(default=None),
    altitude_m: float | None = Form(default=None),
    sensor_model: str | None = Form(default=None),
    install_position: str | None = Form(default=None),
    weather_level: str | None = Form(default=None),
    pressure_hpa: float | None = Form(default=None),
    humidity_percent: float | None = Form(default=None),
    is_synthetic: bool = Form(default=False),
    notes: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentImportResponse:
    """
    异步导入雷电流波形数据（通过 Celery Worker 后台处理）。
    上传文件后立即返回 task_id，不阻塞请求。
    """
    return import_lightning_current_async(
        db,
        file=file,
        actor_user_id=current_user.user.id,
        event_id=event_id,
        event_time=event_time,
        sample_interval_us=sample_interval_us,
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
        is_synthetic=is_synthetic,
        notes=notes,
    )


@router.post("/import-distribution", response_model=LightningDistributionImportResponse)
def import_lightning_distribution_file(
    file: UploadFile = File(...),
    event_year: int | None = Form(default=None, ge=1900, le=2100),
    region_id: str | None = Form(default=None),
    location_tag: str | None = Form(default=None),
    city: str | None = Form(default=None),
    is_synthetic: bool = Form(default=False),
    notes: str | None = Form(default=None),
    line_id: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionImportResponse:
    return import_lightning_distribution_from_file(
        db,
        file=file,
        actor_user_id=current_user.user.id,
        event_year=event_year,
        region_id=region_id,
        location_tag=location_tag,
        city=city,
        is_synthetic=is_synthetic,
        notes=notes,
        line_id=line_id,
    )


@router.post("/compute-density", response_model=LightningComputeDensityResponse)
def trigger_ground_flash_density(
    payload: LightningComputeDensityRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningComputeDensityResponse:
    return trigger_ground_flash_density_computation(
        db,
        line_id=payload.line_id,
        region_id=payload.region_id,
        is_synthetic=payload.is_synthetic,
        actor_user_id=current_user.user.id,
    )


@router.post("/prepare-current", response_model=LightningCurrentPreparationResponse)
def prepare_lightning_current_for_line(
    payload: LightningCurrentPreparationRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentPreparationResponse:
    return prepare_line_lightning_current(db, payload, actor_user_id=current_user.user.id)


@router.post("/prepare-density", response_model=LightningDensityPreparationResponse)
def prepare_lightning_density_for_line(
    payload: LightningDensityPreparationRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDensityPreparationResponse:
    return prepare_line_lightning_density(db, payload, actor_user_id=current_user.user.id)


@router.get("/import-batches", response_model=LightningImportBatchListResponse)
def get_lightning_import_batches(
    keyword: str | None = Query(default=None),
    region_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningImportBatchListResponse:
    return list_lightning_import_batches(
        db,
        keyword=keyword,
        region_id=region_id,
        limit=limit,
        offset=offset,
    )


@router.get("/import-batches/events", response_model=LightningImportBatchEventsResponse)
def get_import_batch_events(
    source_file_name: str | None = Query(default=None),
    import_time: datetime = Query(...),
    region_id: str | None = Query(default=None),
    location_tag: str | None = Query(default=None),
    city: str | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningImportBatchEventsResponse:
    return get_lightning_import_batch_events(
        db,
        source_file_name=source_file_name,
        import_time=import_time,
        region_id=region_id,
        location_tag=location_tag,
        city=city,
    )


@router.delete("/import-batches")
def delete_lightning_import_batch_endpoint(
    source_file_name: str | None = Query(default=None),
    import_time: datetime = Query(...),
    region_id: str | None = Query(default=None),
    location_tag: str | None = Query(default=None),
    city: str | None = Query(default=None),
    _: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool | int]:
    return delete_lightning_import_batch(
        db,
        source_file_name=source_file_name,
        import_time=import_time,
        region_id=region_id,
        location_tag=location_tag,
        city=city,
    )


@router.get("/{event_id}", response_model=LightningCurrentEventSummary)
def get_lightning_event_detail(
    event_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentEventSummary:
    event = get_lightning_event_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流事件不存在")
    return serialize_lightning_event(event)


@router.patch("/{event_id}", response_model=LightningCurrentEventSummary)
def update_lightning_event_endpoint(
    event_id: str,
    payload: LightningCurrentEventUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentEventSummary:
    updated = update_lightning_event(db, event_id, payload, actor_user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流事件不存在")
    return updated


@router.delete("/{event_id}")
def delete_lightning_event_endpoint(
    event_id: str,
    _: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_lightning_event(db, event_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流事件不存在")
    return {"success": True}


@router.get("/{event_id}/samples", response_model=LightningCurrentSampleListResponse)
def get_lightning_samples(
    event_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningCurrentSampleListResponse:
    event = get_lightning_event_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流事件不存在")
    return list_lightning_samples(db, event_id=event_id, limit=limit, offset=offset)


@router.get("/stats/distribution", response_model=LightningDistributionStatsResponse)
def get_lightning_distribution_statistics(
    min_lat: float | None = Query(default=None),
    max_lat: float | None = Query(default=None),
    min_lon: float | None = Query(default=None),
    max_lon: float | None = Query(default=None),
    region_id: str | None = Query(default=None),
    city: str | None = Query(default=None),
    location_tag: str | None = Query(default=None),
    polarity: str | None = Query(default=None),
    is_synthetic: bool | None = Query(default=None),
    grid_size_km: float = Query(default=1.0, gt=0.05, le=100),
    years: float | None = Query(default=None, gt=0),
    grid_limit: int = Query(default=600, ge=1, le=5000),
    scatter_limit: int = Query(default=1200, ge=1, le=5000),
    thresholds: str | None = Query(default=None, description="逗号分隔阈值，如 10,20,50"),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionStatsResponse:
    thresholds_ka: list[float] = []
    if thresholds:
        for token in thresholds.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                value = float(token)
            except ValueError:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"无效阈值：{token}") from None
            if value > 0:
                thresholds_ka.append(value)

    return get_lightning_distribution_stats(
        db,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        polarity=polarity,
        is_synthetic=is_synthetic,
        grid_size_km=grid_size_km,
        years=years,
        grid_limit=grid_limit,
        scatter_limit=scatter_limit,
        thresholds_ka=thresholds_ka,
    )


@router.get("/stats/tower-buffer", response_model=LightningTowerBufferStatsResponse)
def get_lightning_tower_buffer_statistics(
    tower_id: str | None = Query(default=None),
    longitude: float | None = Query(default=None),
    latitude: float | None = Query(default=None),
    radius_km: float = Query(default=3.0, gt=0.1, le=20),
    design_current_ka: float = Query(default=100.0, gt=1, le=1000),
    years: float | None = Query(default=None, gt=0),
    region_id: str | None = Query(default=None),
    is_synthetic: bool | None = Query(default=None),
    include_events_limit: int = Query(default=100, ge=1, le=1000),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage", "tower.read", "tower.manage")),
    db: Session = Depends(get_db),
) -> LightningTowerBufferStatsResponse:
    return get_tower_buffer_stats(
        db,
        tower_id=tower_id,
        longitude=longitude,
        latitude=latitude,
        radius_km=radius_km,
        design_current_ka=design_current_ka,
        years=years,
        region_id=region_id,
        is_synthetic=is_synthetic,
        include_events_limit=include_events_limit,
    )


@router.post("/stats/tower-terrain", response_model=LightningTowerTerrainComputeResponse)
def compute_lightning_tower_terrain(
    payload: LightningTowerTerrainComputeRequest,
    current_user: CurrentUser = Depends(
        require_any_permission("lightning.read", "lightning.manage", "tower.read", "tower.manage")
    ),
    db: Session = Depends(get_db),
) -> LightningTowerTerrainComputeResponse:
    can_persist = (
        "admin" in current_user.role_codes
        or "lightning.manage" in current_user.permission_codes
        or "tower.manage" in current_user.permission_codes
    )
    return compute_tower_terrain_metrics(
        db,
        payload=payload,
        actor_user_id=current_user.user.id,
        can_persist=can_persist,
    )


@router.get("/stats/compare-synthetic", response_model=LightningSyntheticCompareResponse)
def get_lightning_synthetic_compare(
    min_lat: float | None = Query(default=None),
    max_lat: float | None = Query(default=None),
    min_lon: float | None = Query(default=None),
    max_lon: float | None = Query(default=None),
    region_id: str | None = Query(default=None),
    city: str | None = Query(default=None),
    location_tag: str | None = Query(default=None),
    grid_size_km: float = Query(default=1.0, gt=0.05, le=100),
    years: float | None = Query(default=None, gt=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningSyntheticCompareResponse:
    return compare_measured_and_synthetic_distribution(
        db,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        grid_size_km=grid_size_km,
        years=years,
    )


@router.get("/reports/distribution", response_model=LightningDistributionReportResponse)
def get_lightning_distribution_report(
    period: str = Query(default="week", pattern="^(week|month)$"),
    anchor_time: datetime | None = Query(default=None),
    min_lat: float | None = Query(default=None),
    max_lat: float | None = Query(default=None),
    min_lon: float | None = Query(default=None),
    max_lon: float | None = Query(default=None),
    region_id: str | None = Query(default=None),
    city: str | None = Query(default=None),
    location_tag: str | None = Query(default=None),
    is_synthetic: bool | None = Query(default=None),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionReportResponse:
    return build_lightning_distribution_report(
        db,
        period=period,
        anchor_time=anchor_time,
        min_lat=min_lat,
        max_lat=max_lat,
        min_lon=min_lon,
        max_lon=max_lon,
        region_id=region_id,
        city=city,
        location_tag=location_tag,
        is_synthetic=is_synthetic,
    )
