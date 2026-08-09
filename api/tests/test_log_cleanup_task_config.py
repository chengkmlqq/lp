"""LP-283：日志清理 celery 任务注册与 beat 调度配置。"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from app.core.celery_app import celery_app  # noqa: F401,E402


class LogCleanupTaskConfigTest(unittest.TestCase):
    """LP-283：cleanup_expired_task_logs 应注册为 celery 任务并进入 beat_schedule。"""

    def test_cleanup_task_module_is_included(self) -> None:
        include = set(celery_app.conf.include or [])
        self.assertIn("app.tasks.log_cleanup_tasks", include)

    def test_cleanup_task_is_in_beat_schedule(self) -> None:
        beat_schedule = celery_app.conf.beat_schedule or {}
        self.assertIn("cleanup-expired-task-logs", beat_schedule)
        entry = beat_schedule["cleanup-expired-task-logs"]
        self.assertEqual(
            entry.get("task"),
            "app.tasks.log_cleanup_tasks.cleanup_expired_task_logs",
        )

    def test_cleanup_beat_schedule_is_hourly(self) -> None:
        beat_schedule = celery_app.conf.beat_schedule or {}
        entry = beat_schedule["cleanup-expired-task-logs"]
        self.assertEqual(entry.get("schedule"), 3600.0)


if __name__ == "__main__":
    unittest.main()
