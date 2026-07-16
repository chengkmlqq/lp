from __future__ import annotations

import os
import unittest
from importlib.util import find_spec

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from api.app import models  # noqa: F401
from api.app.core.celery_app import celery_app
from api.app.core.database import Base
from api.app.services.legacy_admin_rbac_service import PROTECTED_MENU_CODES


REMOVED_MODULES = (
    "api.app.api.v1.jwt_generator",
    "api.app.models.calendar_event",
    "api.app.models.requirement",
    "api.app.models.todo",
    "api.app.schemas.calendar_event",
    "api.app.schemas.jwt_generator",
    "api.app.schemas.requirement",
    "api.app.schemas.todo",
    "api.app.services.calendar_event_service",
    "api.app.services.jwt_generator_service",
    "api.app.services.requirement_service",
    "api.app.services.todo_service",
    "api.app.tasks.schedule_tasks",
)

REMOVED_TABLES = {
    "calendar_event",
    "project_requirement",
    "project_requirement_log",
    "requirement_comments",
    "todo",
}


class LegacyModuleCleanupContractTest(unittest.TestCase):
    def test_removed_modules_are_not_importable(self) -> None:
        for module_name in REMOVED_MODULES:
            self.assertIsNone(find_spec(module_name), module_name)

    def test_removed_tables_are_not_registered(self) -> None:
        self.assertTrue(REMOVED_TABLES.isdisjoint(Base.metadata.tables))

    def test_removed_schedule_task_is_not_registered(self) -> None:
        include = set(celery_app.conf.include or [])
        self.assertNotIn("app.tasks.schedule_tasks", include)

        beat_schedule = celery_app.conf.beat_schedule or {}
        self.assertNotIn("expire-overdue-schedule-items", beat_schedule)
        scheduled_tasks = {
            str(entry.get("task"))
            for entry in beat_schedule.values()
            if isinstance(entry, dict)
        }
        self.assertNotIn("app.tasks.schedule_tasks.expire_overdue_schedule_items", scheduled_tasks)

    def test_removed_modules_are_not_protected_admin_menus(self) -> None:
        self.assertNotIn("admin.todos", PROTECTED_MENU_CODES)
        self.assertNotIn("admin.jwt_generator", PROTECTED_MENU_CODES)

    def test_new_scheduled_task_dispatcher_is_registered(self) -> None:
        include = set(celery_app.conf.include or [])
        self.assertIn("app.tasks.scheduled_task_tasks", include)

        beat_schedule = celery_app.conf.beat_schedule or {}
        self.assertIn("dispatch-due-scheduled-tasks", beat_schedule)
        entry = beat_schedule["dispatch-due-scheduled-tasks"]
        self.assertEqual(entry.get("task"), "app.tasks.scheduled_task_tasks.dispatch_due_scheduled_tasks")


if __name__ == "__main__":
    unittest.main()
