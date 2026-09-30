from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.overview import SystemOverviewResponse
from ...schemas.overview_config import OverviewConfigRequest, OverviewConfigResponse
from ...services.overview_config_service import get_overview_config, save_overview_config
from ...services.overview_service import build_system_overview

router = APIRouter(
    prefix="/admin/overview",
    tags=["admin-overview"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("", response_model=SystemOverviewResponse)
def get_system_overview(
    _: CurrentUser = Depends(require_any_permission("menu.read")),
    db: Session = Depends(get_db),
) -> SystemOverviewResponse:
    return build_system_overview(db)


@router.get("/config", response_model=OverviewConfigResponse)
def get_overview_config_endpoint(
    user: CurrentUser = Depends(require_any_permission("menu.read")),
    db: Session = Depends(get_db),
) -> OverviewConfigResponse:
    """读取当前用户的系统总览卡片配置（无配置时返回默认布局）。"""
    return get_overview_config(db, user_id=user.user_id)


@router.put("/config", response_model=OverviewConfigResponse)
def put_overview_config_endpoint(
    payload: OverviewConfigRequest,
    user: CurrentUser = Depends(require_any_permission("menu.read")),
    db: Session = Depends(get_db),
) -> OverviewConfigResponse:
    """保存当前用户的系统总览卡片配置（全量覆盖，返回清洗后的结果）。"""
    return save_overview_config(db, user_id=user.user_id, payload=payload)