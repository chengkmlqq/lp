from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.overview import SystemOverviewResponse
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