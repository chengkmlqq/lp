from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route
from ...schemas.task_monitor import TaskMonitorOverviewResponse
from ...services.task_monitor_service import build_task_monitor_overview, delete_task_history

router = APIRouter(
    prefix="/admin/task-monitor",
    tags=["admin-task-monitor"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/overview", response_model=TaskMonitorOverviewResponse)
def get_task_monitor_overview(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    keyword: str | None = Query(default=None, max_length=200),
    _: CurrentUser = Depends(
        require_any_permission(
            "celery.read",
            "celery.manage",
        )
    ),
) -> TaskMonitorOverviewResponse:
    return build_task_monitor_overview(
        offset=offset,
        limit=limit,
        keyword=keyword,
    )


@router.delete(
    "/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_task_monitor_task(
    task_id: str,
    _: CurrentUser = Depends(
        require_any_permission(
            "celery.read",
            "celery.manage",
        )
    ),
) -> None:
    if not delete_task_history(task_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )
