"""单风机计算 API（前缀 ``/api/v1/wind-turbine-calc``）。"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.wind_turbine_calc import (
    WindTurbineCalcCancelResponse,
    WindTurbineCalcCreateRequest,
    WindTurbineCalcCreateResponse,
    WindTurbineCalcEngineInfo,
    WindTurbineCalcJobDetail,
    WindTurbineCalcJobListResponse,
    WindTurbineCalcResultListResponse,
)
from ...services import wind_turbine_calc_service as service
from ...services.wind_turbine_calc import WindTurbineCalcError

router = APIRouter(
    prefix="/wind-turbine-calc",
    tags=["wind-turbine-calc"],
    dependencies=[Depends(require_enabled_menu_route)],
)

_READ_PERMISSIONS = ("wind_turbine_calc.read", "wind_turbine_calc.manage")
_MANAGE_PERMISSION = "wind_turbine_calc.manage"


def _attachment_headers(filename: str) -> dict[str, str]:
    encoded = quote(filename)
    ascii_name = filename.encode("ascii", "ignore").decode() or "download"
    return {"Content-Disposition": f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded}'}


# 静态路径必须在 /{job_id} 之前注册
@router.get("/engine", response_model=WindTurbineCalcEngineInfo)
def get_engine_info(
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
) -> WindTurbineCalcEngineInfo:
    return service.get_engine_info()


@router.post("", response_model=WindTurbineCalcCreateResponse)
def create_wind_turbine_calc_job(
    payload: WindTurbineCalcCreateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindTurbineCalcCreateResponse:
    return service.create_job(
        db,
        name=payload.name,
        hub_height=payload.hub_height,
        receptor_radii=payload.receptor_radii,
        blade_length=payload.blade_length,
        start_current=payload.start_current,
        angle_list=payload.angle_list,
        actor_user_id=current_user.user.id,
    )


@router.get("", response_model=WindTurbineCalcJobListResponse)
def list_wind_turbine_calc_jobs(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindTurbineCalcJobListResponse:
    return service.list_jobs(
        db,
        keyword=keyword,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get("/{job_id}", response_model=WindTurbineCalcJobDetail)
def get_wind_turbine_calc_job(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindTurbineCalcJobDetail:
    return service.get_job_detail(db, job_id)


@router.get("/{job_id}/results", response_model=WindTurbineCalcResultListResponse)
def list_wind_turbine_calc_results(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindTurbineCalcResultListResponse:
    return service.list_results(db, job_id, limit=limit, offset=offset)


@router.get("/{job_id}/chart")
def get_wind_turbine_calc_chart(
    job_id: str,
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    return Response(content=service.get_chart_bytes(db, job_id), media_type="image/png")


@router.get("/{job_id}/export")
def export_wind_turbine_calc_results(
    job_id: str,
    export_type: str = Query(default="csv", alias="type", pattern="^(csv|all)$"),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> Response:
    content, media_type, filename = service.export_results(db, job_id, export_type=export_type)
    return Response(content=content, media_type=media_type, headers=_attachment_headers(filename))


@router.post("/{job_id}/cancel", response_model=WindTurbineCalcCancelResponse)
def cancel_wind_turbine_calc_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindTurbineCalcCancelResponse:
    return service.cancel_job(db, job_id, actor_user_id=current_user.user.id)


@router.delete("/{job_id}")
def delete_wind_turbine_calc_job(
    job_id: str,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    service.delete_job(db, job_id, actor_user_id=current_user.user.id)
    return {"status": "deleted", "job_id": job_id}
