from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.flower_monitor import (
    FlowerWorkerTaskOverviewResponse,
    FlowerWorkersOverviewResponse,
)
from ...services.flower_monitor_service import (
    build_worker_task_overview,
    build_workers_overview,
)

router = APIRouter(prefix="/admin/flower", tags=["admin-flower"], dependencies=[Depends(require_enabled_menu_route)])


@router.get("/workers", response_model=FlowerWorkersOverviewResponse)
def get_flower_workers_overview(
    force_refresh: bool = Query(default=False, alias="forceRefresh"),
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> FlowerWorkersOverviewResponse:
    return build_workers_overview(force_refresh=force_refresh)


@router.get("/worker-tasks", response_model=FlowerWorkerTaskOverviewResponse)
def get_flower_worker_tasks(
    worker: str = Query(min_length=1, max_length=255),
    force_refresh: bool = Query(default=False, alias="forceRefresh"),
    recent_limit: int = Query(default=100, alias="recentLimit", ge=1, le=200),
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> FlowerWorkerTaskOverviewResponse:
    return build_worker_task_overview(
        worker=worker,
        force_refresh=force_refresh,
        recent_limit=recent_limit,
    )
