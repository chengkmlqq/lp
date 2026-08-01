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
    LightningCurrentSampleListResponse,
    LightningDistributionImportResponse,
    LightningDistributionRecord,
    LightningDistributionListResponse,
    LightningDistributionStatusResponse,
    LightningDistributionImageResponse,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningFillDensityRequest,
    LightningFillDensityResponse,
)
from ...schemas.lightning_import import LightningImportBatchListResponse
from ...services.lightning_service import (
    delete_lightning_event,
    delete_lightning_distribution,
    get_lightning_distribution_detail,
    get_lightning_distribution_image_url,
    get_lightning_distribution_status,
    get_lightning_event_by_id,
    get_peak_exceedance_curve,
    import_lightning_current_async,
    import_lightning_distribution_from_file,
    import_lightning_event_from_file,
    list_lightning_distributions,
    list_lightning_events,
    list_lightning_samples,
    prepare_line_lightning_current,
    prepare_line_lightning_density,
    retry_lightning_distribution,
    serialize_lightning_event,
    trigger_line_density_fill,
    update_lightning_event,
    list_lightning_import_batches,
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
        notes=notes,
        line_id=line_id,
    )


@router.get("/distributions", response_model=LightningDistributionListResponse)
def get_lightning_distributions(
    keyword: str | None = Query(default=None),
    region_id: str | None = Query(default=None),
    city: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionListResponse:
    return list_lightning_distributions(
        db,
        keyword=keyword,
        region_id=region_id,
        city=city,
        limit=limit,
        offset=offset,
    )


@router.get("/distributions/{distribution_id}/status", response_model=LightningDistributionStatusResponse)
def get_lightning_distribution_status_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionStatusResponse:
    return get_lightning_distribution_status(db, distribution_id)


@router.get("/distributions/{distribution_id}/image", response_model=LightningDistributionImageResponse)
def get_lightning_distribution_image_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionImageResponse:
    return get_lightning_distribution_image_url(db, distribution_id)


@router.post("/distributions/{distribution_id}/retry", response_model=LightningDistributionImportResponse)
def retry_lightning_distribution_endpoint(
    distribution_id: str,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionImportResponse:
    return retry_lightning_distribution(db, distribution_id, actor_user_id=current_user.user.id)


@router.delete("/distributions/{distribution_id}")
def delete_lightning_distribution_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_lightning_distribution(db, distribution_id)
    if not deleted.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="地闪分布记录不存在")
    return deleted


@router.get("/distributions/{distribution_id}", response_model=LightningDistributionRecord)
def get_lightning_distribution_detail_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningDistributionRecord:
    return get_lightning_distribution_detail(db, distribution_id)


@router.post("/fill-density", response_model=LightningFillDensityResponse)
def trigger_line_lightning_density_fill(
    payload: LightningFillDensityRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningFillDensityResponse:
    return trigger_line_density_fill(db, payload, actor_user_id=current_user.user.id)


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
    import_type: str | None = Query(default=None, description="过滤类型：waveform（雷电流波形）"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningImportBatchListResponse:
    return list_lightning_import_batches(
        db,
        keyword=keyword,
        region_id=region_id,
        import_type=import_type,
        limit=limit,
        offset=offset,
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
