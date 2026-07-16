from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, require_any_permission, require_enabled_menu_route, require_permission
from ...schemas.scheduled_task import (
    ScheduledTaskCreateRequest,
    ScheduledTaskListResponse,
    ScheduledTaskRunResponse,
    ScheduledTaskSummary,
    ScheduledTaskUpdateRequest,
)
from ...services.scheduled_task_service import (
    create_scheduled_task,
    get_scheduled_task_by_id,
    list_scheduled_tasks,
    run_scheduled_task_now,
    serialize_scheduled_task,
    update_scheduled_task,
)

router = APIRouter(
    prefix="/admin/scheduled-tasks",
    tags=["admin-scheduled-tasks"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("", response_model=ScheduledTaskListResponse)
def get_scheduled_tasks(
    keyword: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
    db: Session = Depends(get_db),
) -> ScheduledTaskListResponse:
    return list_scheduled_tasks(db, keyword=keyword, status_filter=status_filter)


@router.post("", response_model=ScheduledTaskSummary)
def create_scheduled_task_endpoint(
    payload: ScheduledTaskCreateRequest,
    current_user: CurrentUser = Depends(require_permission("celery.manage")),
    db: Session = Depends(get_db),
) -> ScheduledTaskSummary:
    try:
        created = create_scheduled_task(db, payload, actor_user_id=current_user.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not created:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Scheduled task key already exists")
    return created


@router.get("/{task_id}", response_model=ScheduledTaskSummary)
def get_scheduled_task_detail(
    task_id: int,
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
    db: Session = Depends(get_db),
) -> ScheduledTaskSummary:
    item = get_scheduled_task_by_id(db, task_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found")
    return serialize_scheduled_task(item)


@router.patch("/{task_id}", response_model=ScheduledTaskSummary)
def update_scheduled_task_endpoint(
    task_id: int,
    payload: ScheduledTaskUpdateRequest,
    current_user: CurrentUser = Depends(require_permission("celery.manage")),
    db: Session = Depends(get_db),
) -> ScheduledTaskSummary:
    try:
        updated = update_scheduled_task(db, task_id, payload, actor_user_id=current_user.user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found")
    return updated


@router.post("/{task_id}/run", response_model=ScheduledTaskRunResponse)
def run_scheduled_task_endpoint(
    task_id: int,
    current_user: CurrentUser = Depends(require_permission("celery.manage")),
    db: Session = Depends(get_db),
) -> ScheduledTaskRunResponse:
    result = run_scheduled_task_now(db, task_id, actor_user_id=current_user.user.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled task not found")
    return result
