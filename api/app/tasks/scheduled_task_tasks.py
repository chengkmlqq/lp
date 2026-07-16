from __future__ import annotations

from ..core.celery_app import celery_app
from ..services.scheduled_task_service import dispatch_due_scheduled_tasks, execute_scheduled_task


@celery_app.task(name="app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks")
def dispatch_due_scheduled_tasks_job() -> dict[str, int]:
    return dispatch_due_scheduled_tasks(actor_user_id="system")


@celery_app.task(name="app.tasks.scheduled_task_tasks.execute_scheduled_task_job")
def execute_scheduled_task_job(task_id: int, actor_user_id: str = "system") -> dict[str, object]:
    return execute_scheduled_task(task_id, actor_user_id=actor_user_id)
