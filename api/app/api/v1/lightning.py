from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.lightning import (
    LightningAmplitudeImportResponse,
    LightningAmplitudeRecord,
    LightningAmplitudeListResponse,
    LightningAmplitudeStatusResponse,
    LightningCurrentPreparationRequest,
    LightningCurrentPreparationResponse,
    LightningCurrentExceedanceResponse,
    LightningDistributionImportResponse,
    LightningDistributionRecord,
    LightningDistributionListResponse,
    LightningDistributionStatusResponse,
    LightningDensityPreparationRequest,
    LightningDensityPreparationResponse,
    LightningFillDensityRequest,
    LightningFillDensityResponse,
    LightningLpDrawRequest,
    LightningLpDrawResponse,
)
from ...services.lightning_service import (
    delete_lightning_amplitude,
    delete_lightning_distribution,
    get_lightning_amplitude_detail,
    get_lightning_amplitude_status,
    get_lightning_distribution_detail,
    get_lightning_distribution_image_content,
    get_lightning_distribution_lp_image_content,
    get_lightning_distribution_status,
    get_peak_exceedance_curve,
    import_lightning_amplitude_from_file,
    import_lightning_distribution_from_file,
    list_lightning_amplitudes,
    list_lightning_distributions,
    prepare_line_lightning_current,
    prepare_line_lightning_density,
    retry_lightning_amplitude,
    retry_lightning_distribution,
    trigger_line_density_fill,
    trigger_lp_density_draw,
)

router = APIRouter(
    prefix="/lightning-currents",
    tags=["lightning-currents"],
    dependencies=[Depends(require_enabled_menu_route)],
)


# ---------------------------------------------------------------------------
# 雷电流幅值（LightningAmplitude）
# ---------------------------------------------------------------------------
@router.get("", response_model=LightningAmplitudeListResponse)
def get_lightning_amplitude_list(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    region_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningAmplitudeListResponse:
    """雷电流幅值记录列表（兼容旧 GET /，供线路页事件选择器使用）。"""
    return list_lightning_amplitudes(
        db,
        keyword=keyword,
        status_filter=status_filter,
        region_id=region_id,
        limit=limit,
        offset=offset,
    )


@router.get("/amplitudes", response_model=LightningAmplitudeListResponse)
def get_lightning_amplitudes(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    region_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningAmplitudeListResponse:
    """雷电流幅值记录列表（分页 + 关键词/状态过滤）。"""
    return list_lightning_amplitudes(
        db,
        keyword=keyword,
        status_filter=status_filter,
        region_id=region_id,
        limit=limit,
        offset=offset,
    )


@router.get("/amplitudes/{amplitude_id}", response_model=LightningAmplitudeRecord)
def get_lightning_amplitude_detail_endpoint(
    amplitude_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningAmplitudeRecord:
    return get_lightning_amplitude_detail(db, amplitude_id)


@router.get("/amplitudes/{amplitude_id}/status", response_model=LightningAmplitudeStatusResponse)
def get_lightning_amplitude_status_endpoint(
    amplitude_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningAmplitudeStatusResponse:
    return get_lightning_amplitude_status(db, amplitude_id)


@router.post("/amplitudes/{amplitude_id}/retry", response_model=LightningAmplitudeImportResponse)
def retry_lightning_amplitude_endpoint(
    amplitude_id: str,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningAmplitudeImportResponse:
    return retry_lightning_amplitude(db, amplitude_id, actor_user_id=current_user.user.id)


@router.delete("/amplitudes/{amplitude_id}")
def delete_lightning_amplitude_endpoint(
    amplitude_id: str,
    _: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_lightning_amplitude(db, amplitude_id)
    if not deleted.get("success"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="雷电流幅值记录不存在")
    return deleted


@router.post("/import-async", response_model=LightningAmplitudeImportResponse)
def import_lightning_amplitude_file_async(
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
) -> LightningAmplitudeImportResponse:
    """
    异步导入雷电流幅值波形数据（Celery Worker 后台处理）。
    上传文件立即 put_object 到 MinIO → 建 LightningAmplitude(pending) → 派发任务。
    """
    return import_lightning_amplitude_from_file(
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


# ---------------------------------------------------------------------------
# 地闪分布（LightningDistribution）
# ---------------------------------------------------------------------------
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


@router.get("/distributions/{distribution_id}/image")
def get_lightning_distribution_image_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, media_type = get_lightning_distribution_image_content(db, distribution_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="密度图不存在")
    return StreamingResponse(iter([content]), media_type=media_type or "image/png")


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


# ---------------------------------------------------------------------------
# LP 桌面端分区密度图（draw-lp）
# ---------------------------------------------------------------------------
@router.post("/distributions/{distribution_id}/draw-lp", response_model=LightningLpDrawResponse)
def trigger_lp_density_draw_endpoint(
    distribution_id: str,
    payload: LightningLpDrawRequest,
    current_user: CurrentUser = Depends(require_permission("lightning.manage")),
    db: Session = Depends(get_db),
) -> LightningLpDrawResponse:
    return trigger_lp_density_draw(db, distribution_id, payload, actor_user_id=current_user.user.id)


@router.get("/distributions/{distribution_id}/lp-image")
def get_lightning_distribution_lp_image_endpoint(
    distribution_id: str,
    _: CurrentUser = Depends(require_any_permission("lightning.read", "lightning.manage")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, media_type = get_lightning_distribution_lp_image_content(db, distribution_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LP 密度图不存在")
    return StreamingResponse(iter([content]), media_type=media_type or "image/png")


# ---------------------------------------------------------------------------
# 线路回填（prepare）
# ---------------------------------------------------------------------------
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
