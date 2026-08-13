from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import task_monitor_service


def _now() -> datetime:
    return datetime(2026, 8, 2, 0, 0, 0, tzinfo=timezone.utc)


class TestTaskMonitorOverviewErrorIsolation:
    """LP-313: overview must be pure-DB and never fail when Flower/Redis is unavailable."""

    def test_db_failure_yields_empty_db_tasks(self):
        """When TaskHistory table is missing/unreachable, DB source degrades to empty, not 500."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ):
            result = task_monitor_service.build_task_monitor_overview(
                task_limit=10,
                history_limit=5,
            )
        assert result.tasks == []
        assert result.workers == []
        assert result.queues == []
        assert result.workers_online == 0
        assert result.generated_at is not None

    def test_flower_independent_response_shape(self):
        """Overview no longer depends on Flower: workers are empty and broker info comes from settings."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ):
            with patch(
                "app.services.task_monitor_service._safe_queue_pending_counts",
                return_value={},
            ):
                result = task_monitor_service.build_task_monitor_overview(
                    task_limit=10,
                    history_limit=5,
                )
        assert result.workers_online == 0
        assert result.worker_concurrency_total == 0
        assert result.workers == []
        assert result.tasks == []
        assert result.broker_url == "redis://redis:6379/0"
        assert result.result_backend == "redis://redis:6379/1"

    def test_db_tasks_are_returned(self):
        """DB task history is the single source of truth for the task list."""
        from app.schemas.task_monitor import TaskMonitorTaskItem

        items = [
            TaskMonitorTaskItem(
                task_id="task-1",
                name="export",
                state="STARTED",
                queue_name="q1",
                worker="celery@worker-1",
                started_at=_now(),
            ),
            TaskMonitorTaskItem(
                task_id="task-2",
                name="import",
                state="SUCCESS",
                queue_name="q1",
                done_at=_now(),
            ),
        ]
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=items,
        ):
            with patch(
                "app.services.task_monitor_service._safe_queue_pending_counts",
                return_value={},
            ):
                result = task_monitor_service.build_task_monitor_overview(
                    task_limit=10,
                    history_limit=5,
                )

        assert [t.task_id for t in result.tasks] == ["task-1", "task-2"]
        assert result.tasks[0].worker == "celery@worker-1"
        assert {q.name for q in result.queues} == {"q1"}

    def test_queue_active_count_counts_only_started(self):
        """Queue active_count counts STARTED tasks from DB; others do not inflate it."""
        from app.schemas.task_monitor import TaskMonitorTaskItem

        items = [
            TaskMonitorTaskItem(
                task_id="task-1",
                name="a",
                state="STARTED",
                queue_name="q1",
                started_at=_now(),
            ),
            TaskMonitorTaskItem(
                task_id="task-2",
                name="b",
                state="SUCCESS",
                queue_name="q1",
                done_at=_now(),
            ),
            TaskMonitorTaskItem(
                task_id="task-3",
                name="c",
                state="STARTED",
                queue_name="q2",
                started_at=_now(),
            ),
        ]
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=items,
        ):
            with patch(
                "app.services.task_monitor_service._safe_queue_pending_counts",
                return_value={"q1": 4, "q2": 0},
            ):
                result = task_monitor_service.build_task_monitor_overview(
                    task_limit=10,
                    history_limit=5,
                )

        queues = {q.name: q for q in result.queues}
        assert queues["q1"].active_count == 1
        assert queues["q1"].pending_count == 4
        assert queues["q1"].consumer_count == 0
        assert queues["q2"].active_count == 1
        assert result.queue_pending_total == 4

    @patch("app.services.task_monitor_service._load_db_task_history", return_value=[])
    @patch("app.services.task_monitor_service._safe_queue_pending_counts", return_value={})
    def test_task_state_buckets_built_from_db_tasks(self, *_mocks):
        from app.schemas.task_monitor import TaskMonitorTaskItem

        items = [
            TaskMonitorTaskItem(task_id="t1", name="a", state="STARTED"),
            TaskMonitorTaskItem(task_id="t2", name="b", state="SUCCESS"),
            TaskMonitorTaskItem(task_id="t3", name="c", state="SUCCESS"),
        ]
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=items,
        ):
            result = task_monitor_service.build_task_monitor_overview(
                task_limit=10,
                history_limit=5,
            )
        buckets = {b.key: b.count for b in result.task_state_buckets}
        assert buckets["STARTED"] == 1
        assert buckets["SUCCESS"] == 2

    def test_redis_pending_failure_degrades_to_zero(self):
        """Redis LLEN failure must not crash the overview; pending counts stay 0."""
        with patch(
            "app.services.task_monitor_service._safe_queue_pending_counts",
            return_value={},
        ):
            from app.schemas.task_monitor import TaskMonitorTaskItem

            with patch(
                "app.services.task_monitor_service._load_db_task_history",
                return_value=[
                    TaskMonitorTaskItem(
                        task_id="task-1",
                        name="a",
                        state="STARTED",
                        queue_name="q1",
                        started_at=_now(),
                    )
                ],
            ):
                result = task_monitor_service.build_task_monitor_overview(
                    task_limit=10,
                    history_limit=5,
                )
        queues = {q.name: q for q in result.queues}
        assert queues["q1"].pending_count == 0

    def test_safe_queue_pending_counts_returns_empty_on_redis_error(self):
        """_safe_queue_pending_counts itself must swallow Redis errors and return {}."""
        fake_client = MagicMock()
        fake_pipe = MagicMock()
        fake_pipe.execute.side_effect = RuntimeError("redis down")
        fake_client.pipeline.return_value = fake_pipe
        with patch(
            "app.services.task_monitor_service.get_settings"
        ) as fake_settings:
            fake_settings.return_value = type(
                "S",
                (),
                {"resolved_celery_broker_url": "redis://localhost:1/0"},
            )()
            with patch("redis.from_url", return_value=fake_client):
                assert task_monitor_service._safe_queue_pending_counts(["q1"]) == {}

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("boom"), OSError("boom"), ValueError("boom")],
    )
    def test_load_db_task_history_returns_empty_on_error(self, exc):
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            side_effect=exc,
        ):
            assert task_monitor_service._load_db_task_history(limit=10) == []


class TestDeleteTaskHistory:
    def test_delete_returns_true_when_row_deleted(self):
        fake_db = MagicMock()
        fake_result = MagicMock()
        fake_result.rowcount = 1
        fake_db.execute.return_value = fake_result
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            return_value=fake_db,
        ):
            assert task_monitor_service.delete_task_history("task-1") is True

    def test_delete_returns_false_when_row_missing(self):
        fake_db = MagicMock()
        fake_result = MagicMock()
        fake_result.rowcount = 0
        fake_db.execute.return_value = fake_result
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            return_value=fake_db,
        ):
            assert task_monitor_service.delete_task_history("task-missing") is False

    def test_delete_returns_false_on_db_error(self):
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            side_effect=RuntimeError("db down"),
        ):
            assert task_monitor_service.delete_task_history("task-1") is False
