"""风电场数据准备 API（前缀 ``/api/v1/wind-data-prep``）。

与 LP-32 ``/api/v1/wind-lightning-density`` 完全隔离：独立表、独立权限点、
独立页面，只共用纯函数内核 ``wind_grid.py``。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.wind_data_prep import (
    WindDataPrepBatchDetail,
    WindDataPrepBatchListResponse,
    WindDataPrepImportResponse,
    WindDataPrepPreviewResponse,
    WindDataPrepTurbineListResponse,
)
from ...services import wind_data_prep as prep
from ...services import wind_data_prep_service as service
from ...services.wind_grid import DEFAULT_DDEG, WindGridError

router = APIRouter(
    prefix="/wind-data-prep",
    tags=["wind-data-prep"],
    dependencies=[Depends(require_enabled_menu_route)],
)

_READ_PERMISSIONS = ("wind_data_prep.read", "wind_data_prep.manage")
_MANAGE_PERMISSION = "wind_data_prep.manage"


def _bad_request(exc: WindGridError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _attachment_headers(filename: str) -> dict[str, str]:
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'
        )
    }


def _params(
    *,
    start_lon: float,
    start_lat: float,
    grid_nx: int,
    grid_ny: int,
    risk_base_s: float,
    grid_step_deg: float,
    terrain_mode: str,
    wind_farm_name: str,
    remark: str,
) -> prep.PrepParams:
    return service.build_params(
        start_lon=start_lon,
        start_lat=start_lat,
        grid_nx=grid_nx,
        grid_ny=grid_ny,
        risk_base_s=risk_base_s,
        grid_step_deg=grid_step_deg,
        terrain_mode=terrain_mode,
        wind_farm_name=wind_farm_name,
        remark=remark,
    )


# ---------------------------------------------------------------------------
# 预览 / 新建
# ---------------------------------------------------------------------------
@router.post("/preview", response_model=WindDataPrepPreviewResponse)
def preview_wind_data_prep(
    turbine_file: UploadFile = File(...),
    lightning_file: UploadFile = File(...),
    terrain_file: UploadFile | None = File(default=None),
    start_lon: float = Form(...),
    start_lat: float = Form(...),
    grid_nx: int = Form(...),
    grid_ny: int = Form(...),
    risk_base_s: float = Form(...),
    grid_step_deg: float = Form(DEFAULT_DDEG),
    terrain_mode: str = Form("zero"),
    wind_farm_name: str = Form(""),
    remark: str = Form(""),
    _: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
) -> WindDataPrepPreviewResponse:
    """提交前预览：完整校验但不落库，返回报告与五文件结构。"""
    try:
        return service.preview_batch(
            turbine_file=turbine_file,
            lightning_file=lightning_file,
            terrain_file=terrain_file,
            params=_params(
                start_lon=start_lon,
                start_lat=start_lat,
                grid_nx=grid_nx,
                grid_ny=grid_ny,
                risk_base_s=risk_base_s,
                grid_step_deg=grid_step_deg,
                terrain_mode=terrain_mode,
                wind_farm_name=wind_farm_name,
                remark=remark,
            ),
        )
    except WindGridError as exc:
        raise _bad_request(exc) from exc


@router.post("", response_model=WindDataPrepImportResponse)
def create_wind_data_prep_batch(
    turbine_file: UploadFile = File(...),
    lightning_file: UploadFile = File(...),
    terrain_file: UploadFile | None = File(default=None),
    name: str = Form(""),
    start_lon: float = Form(...),
    start_lat: float = Form(...),
    grid_nx: int = Form(...),
    grid_ny: int = Form(...),
    risk_base_s: float = Form(...),
    grid_step_deg: float = Form(DEFAULT_DDEG),
    terrain_mode: str = Form("zero"),
    wind_farm_name: str = Form(""),
    remark: str = Form(""),
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindDataPrepImportResponse:
    try:
        return service.create_batch(
            db,
            turbine_file=turbine_file,
            lightning_file=lightning_file,
            terrain_file=terrain_file,
            params=_params(
                start_lon=start_lon,
                start_lat=start_lat,
                grid_nx=grid_nx,
                grid_ny=grid_ny,
                risk_base_s=risk_base_s,
                grid_step_deg=grid_step_deg,
                terrain_mode=terrain_mode,
                wind_farm_name=wind_farm_name,
                remark=remark,
            ),
            name=name,
            actor_user_id=current_user.user.id,
        )
    except WindGridError as exc:
        raise _bad_request(exc) from exc


# ---------------------------------------------------------------------------
# 列表 / 详情
# ---------------------------------------------------------------------------
@router.get("", response_model=WindDataPrepBatchListResponse)
def list_wind_data_prep_batches(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindDataPrepBatchListResponse:
    return service.list_batches(
        db,
        keyword=keyword,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{batch_id}", response_model=WindDataPrepBatchDetail)
def get_wind_data_prep_batch(
    batch_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindDataPrepBatchDetail:
    return service.get_batch_detail(db, batch_id)


@router.get("/{batch_id}/turbines", response_model=WindDataPrepTurbineListResponse)
def list_wind_data_prep_turbines(
    batch_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindDataPrepTurbineListResponse:
    return service.list_turbines(db, batch_id, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# 文件 / 打包 / 报告
# ---------------------------------------------------------------------------
@router.get("/{batch_id}/files/{name}")
def get_wind_data_prep_file(
    batch_id: str,
    name: str,
    preview: bool = Query(default=False, description="预览：文本在线显示，P0.abc 显示头部 6 个数值"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, media_type, filename = service.get_file(db, batch_id, name, preview=preview)
    headers = {} if preview else _attachment_headers(filename)
    return Response(content=content, media_type=media_type, headers=headers)


@router.get("/{batch_id}/package")
def get_wind_data_prep_package(
    batch_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, filename = service.get_package(db, batch_id)
    return Response(content=content, media_type="application/zip", headers=_attachment_headers(filename))


@router.get("/{batch_id}/report")
def get_wind_data_prep_report(
    batch_id: str,
    format: str = Query(default="json", description="json 或 excel"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, media_type, filename = service.get_report(db, batch_id, format=format)
    headers = {} if format == "json" else _attachment_headers(filename)
    return Response(content=content, media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# 重算 / 删除
# ---------------------------------------------------------------------------
@router.post("/{batch_id}/recompute", response_model=WindDataPrepImportResponse)
def recompute_wind_data_prep_batch(
    batch_id: str,
    start_lon: float | None = Form(default=None),
    start_lat: float | None = Form(default=None),
    grid_nx: int | None = Form(default=None),
    grid_ny: int | None = Form(default=None),
    risk_base_s: float | None = Form(default=None),
    grid_step_deg: float | None = Form(default=None),
    terrain_mode: str | None = Form(default=None),
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindDataPrepImportResponse:
    """用原文件 + 可选新参数重跑（不传参数则沿用原参数）。"""
    overrides = {
        "start_lon": start_lon,
        "start_lat": start_lat,
        "grid_nx": grid_nx,
        "grid_ny": grid_ny,
        "risk_base_s": risk_base_s,
        "grid_step_deg": grid_step_deg,
        "terrain_mode": terrain_mode,
    }
    try:
        return service.recompute_batch(
            db,
            batch_id,
            actor_user_id=current_user.user.id,
            param_overrides=overrides,
        )
    except WindGridError as exc:
        raise _bad_request(exc) from exc


@router.delete("/{batch_id}")
def delete_wind_data_prep_batch(
    batch_id: str,
    # 删除口径与前端对齐：有页面访问权限（read/manage）即可删除，避免"按钮可见但接口 403"
    current_user: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service.delete_batch(db, batch_id, actor_user_id=current_user.user.id)
    return {"status": "deleted", "batch_id": batch_id}
