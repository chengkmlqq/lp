"""机组型号 / 叶片型号映射 API（前缀 ``/api/v1/wind-models``）。

映射维护挂在「风电场数据准备」下（``wind_data_prep.manage``），
读取额外放开给单风机计算用户（``wind_turbine_calc.read``），
使计算表单能取到启用型号选项而无需数据准备权限。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import (
    CurrentUser,
    require_any_permission,
    require_enabled_menu_route,
    require_permission,
)
from ...schemas.wind_model_mapping import (
    WindBladeModelCreateRequest,
    WindBladeModelListResponse,
    WindBladeModelSummary,
    WindBladeModelUpdateRequest,
    WindTurbineModelCreateRequest,
    WindTurbineModelListResponse,
    WindTurbineModelSummary,
    WindTurbineModelUpdateRequest,
)
from ...services import wind_model_mapping_service as service

router = APIRouter(
    prefix="/wind-models",
    tags=["wind-models"],
    dependencies=[Depends(require_enabled_menu_route)],
)

_READ_PERMISSIONS = (
    "wind_data_prep.read",
    "wind_data_prep.manage",
    "wind_turbine_calc.read",
)
_MANAGE_PERMISSION = "wind_data_prep.manage"


# ---------------------------------------------------------------------------
# 机组型号
# ---------------------------------------------------------------------------
@router.get("/turbines", response_model=WindTurbineModelListResponse)
def list_wind_turbine_models(
    enabled: bool | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindTurbineModelListResponse:
    return service.list_wind_turbine_models(
        db, limit=limit, offset=offset, keyword=keyword, enabled=enabled
    )


@router.post("/turbines", response_model=WindTurbineModelSummary)
def create_wind_turbine_model(
    payload: WindTurbineModelCreateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindTurbineModelSummary:
    return service.create_wind_turbine_model(
        db, payload, actor_user_id=current_user.user.id
    )


@router.patch("/turbines/{model_id}", response_model=WindTurbineModelSummary)
def update_wind_turbine_model(
    model_id: str,
    payload: WindTurbineModelUpdateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindTurbineModelSummary:
    updated = service.update_wind_turbine_model(
        db, model_id, payload, actor_user_id=current_user.user.id
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="机组型号不存在")
    return updated


@router.delete("/turbines/{model_id}")
def delete_wind_turbine_model(
    model_id: str,
    _: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if not service.delete_wind_turbine_model(db, model_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="机组型号不存在")
    return {"success": True}


# ---------------------------------------------------------------------------
# 叶片型号
# ---------------------------------------------------------------------------
@router.get("/blades", response_model=WindBladeModelListResponse)
def list_wind_blade_models(
    enabled: bool | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(require_any_permission(*_READ_PERMISSIONS)),
    db: Session = Depends(get_db),
) -> WindBladeModelListResponse:
    return service.list_wind_blade_models(
        db, limit=limit, offset=offset, keyword=keyword, enabled=enabled
    )


@router.post("/blades", response_model=WindBladeModelSummary)
def create_wind_blade_model(
    payload: WindBladeModelCreateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindBladeModelSummary:
    return service.create_wind_blade_model(
        db, payload, actor_user_id=current_user.user.id
    )


@router.patch("/blades/{model_id}", response_model=WindBladeModelSummary)
def update_wind_blade_model(
    model_id: str,
    payload: WindBladeModelUpdateRequest,
    current_user: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> WindBladeModelSummary:
    updated = service.update_wind_blade_model(
        db, model_id, payload, actor_user_id=current_user.user.id
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="叶片型号不存在")
    return updated


@router.delete("/blades/{model_id}")
def delete_wind_blade_model(
    model_id: str,
    _: CurrentUser = Depends(require_permission(_MANAGE_PERMISSION)),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    if not service.delete_wind_blade_model(db, model_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="叶片型号不存在")
    return {"success": True}
