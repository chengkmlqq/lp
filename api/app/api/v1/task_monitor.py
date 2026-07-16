from fastapi import APIRouter, Depends, Query

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.task_monitor import TaskMonitorOverviewResponse
from ...services.task_monitor_service import build_task_monitor_overview

router = APIRouter(
    prefix="/admin/task-monitor",
    tags=["admin-task-monitor"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/overview", response_model=TaskMonitorOverviewResponse)
def get_task_monitor_overview(
    task_limit: int = Query(default=100, ge=1, le=500),
    history_limit: int = Query(default=100, ge=0, le=500),
    _: CurrentUser = Depends(
        require_any_permission(
            "celery.read",
            "celery.manage",
        )
    ),
) -> TaskMonitorOverviewResponse:
    return build_task_monitor_overview(
        task_limit=task_limit,
        history_limit=history_limit,
    )
