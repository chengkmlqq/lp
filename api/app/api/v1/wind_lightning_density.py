"""风电场地闪密度统计 API。

前缀 ``/api/v1/wind-lightning-density``，与 ``/api/v1/lightning-currents`` 的
GB/T 40621 地闪密度统计完全隔离（独立表、独立算法、独立菜单与权限点）。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.wind_lightning_density import (
    WindLightningDensityBatchDetail,
    WindLightningDensityBatchListResponse,
    WindLightningDensityCellListResponse,
    WindLightningDensityImportResponse,
    WindLightningDensityPreviewResponse,
    WindLightningDensityTurbineListResponse,
)
from ...services import wind_lightning_density_service as service
from ...services.wind_lightning_density import (
    DEFAULT_GRID_STEP_DEG,
    DEFAULT_MARGIN_DEG,
    WindLightningDensityError,
)

router = APIRouter(
    prefix="/wind-lightning-density",
    tags=["wind-lightning-density"],
    dependencies=[Depends(require_enabled_menu_route)],
)

_READ_PERMISSIONS = ("wind_lightning_density.read", "wind_lightning_density.manage")
_MANAGE_PERMISSION = "wind_lightning_density.manage"


def _bad_request(exc: WindLightningDensityError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _attachment_headers(filename: str) -> dict[str, str]:
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
        )
    }


# ---------------------------------------------------------------------------
# 新建 / 预览
# ---------------------------------------------------------------------------
@router.post("/preview", response_model=WindLightningDensityPreviewResponse)
def preview_wind_lightning_density(
    turbine_file: UploadFile = File(...),
    lightning_file: UploadFile = File(...),
    grid_step_deg: float = Form(DEFAULT_GRID_STEP_DEG),
    margin_deg: float = Form(DEFAULT_MARGIN_DEG),
    years_source: str = Form("auto"),
    _: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
) -> WindLightningDensityPreviewResponse:
    """提交前预览：解析两份文件，返回 bbox、预估网格数与可解析行数（不落库）。"""
    try:
        return service.preview_batch(
            turbine_file=turbine_file,
            lightning_file=lightning_file,
            grid_step_deg=grid_step_deg,
            margin_deg=margin_deg,
            years_source=years_source,
        )
    except WindLightningDensityError as exc:
        raise _bad_request(exc) from exc


@router.post("", response_model=WindLightningDensityImportResponse)
def create_wind_lightning_density_batch(
    turbine_file: UploadFile = File(...),
    lightning_file: UploadFile = File(...),
    batch_name: str = Form(""),
    wind_farm_name: str = Form(""),
    notes: str = Form(""),
    grid_step_deg: float = Form(DEFAULT_GRID_STEP_DEG),
    margin_deg: float = Form(DEFAULT_MARGIN_DEG),
    years_source: str = Form("auto"),
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindLightningDensityImportResponse:
    """上传风机文件 + 雷电 CSV + 参数，创建批次并派发异步任务。"""
    try:
        return service.create_batch(
            db,
            turbine_file=turbine_file,
            lightning_file=lightning_file,
            batch_name=batch_name,
            wind_farm_name=wind_farm_name,
            notes=notes,
            grid_step_deg=grid_step_deg,
            margin_deg=margin_deg,
            years_source=years_source,
            actor_user_id=current_user.user.id,
        )
    except WindLightningDensityError as exc:
        raise _bad_request(exc) from exc


# ---------------------------------------------------------------------------
# 列表 / 详情
# ---------------------------------------------------------------------------
@router.get("", response_model=WindLightningDensityBatchListResponse)
def list_wind_lightning_density_batches(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindLightningDensityBatchListResponse:
    return service.list_batches(
        db,
        keyword=keyword,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}", response_model=WindLightningDensityBatchDetail)
def get_wind_lightning_density_batch(
    batch_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindLightningDensityBatchDetail:
    return service.get_batch_detail(db, batch_id)


@router.get("/{batch_id}/cells", response_model=WindLightningDensityCellListResponse)
def list_wind_lightning_density_cells(
    batch_id: str,
    sort_by: str = Query(default="density_per_km2_year"),
    sort_order: str = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindLightningDensityCellListResponse:
    return service.list_cells(
        db,
        batch_id,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}/turbines", response_model=WindLightningDensityTurbineListResponse)
def list_wind_lightning_density_turbines(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindLightningDensityTurbineListResponse:
    return service.list_turbines(db, batch_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 图片 / 导出
# ---------------------------------------------------------------------------
@router.get("/{batch_id}/image")
def get_wind_lightning_density_image(
    batch_id: str,
    unit: str = Query(default="km2", description="km2=次/(km²·年)，cell=次/(格·年)"),
    interpolation: str = Query(default="bilinear", description="bilinear 或 nearest"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    content, media_type = service.get_batch_image(
        db, batch_id, unit=unit, interpolation=interpolation
    )
    return StreamingResponse(iter([content]), media_type=media_type or "image/png")


@router.get("/{batch_id}/export")
def export_wind_lightning_density_excel(
    batch_id: str,
    export_type: str = Query(default="all", alias="type"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, filename = service.export_excel(db, batch_id, export_type=export_type)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=_attachment_headers(filename),
    )


@router.get("/{batch_id}/export-core")
def export_wind_lightning_density_core_files(
    batch_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, filename = service.export_core_files(db, batch_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers=_attachment_headers(filename),
    )


# ---------------------------------------------------------------------------
# 重算 / 删除
# ---------------------------------------------------------------------------
@router.post("/{batch_id}/recompute", response_model=WindLightningDensityImportResponse)
def recompute_wind_lightning_density_batch(
    batch_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindLightningDensityImportResponse:
    """用原文件重算该批次（清空旧网格/风机明细后重建）。"""
    try:
        return service.recompute_batch(db, batch_id, actor_user_id=current_user.user.id)
    except WindLightningDensityError as exc:
        raise _bad_request(exc) from exc


@router.delete("/{batch_id}")
def delete_wind_lightning_density_batch(
    batch_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service.delete_batch(db, batch_id, actor_user_id=current_user.user.id)
    return {"status": "deleted", "batch_id": batch_id}
