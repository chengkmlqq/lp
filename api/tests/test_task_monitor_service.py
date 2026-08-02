from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.services import task_monitor_service


def _now() -> datetime:
    return datetime(2026, 8, 2, 0, 0, 0, tzinfo=timezone.utc)


class TestTaskMonitorOverviewErrorIsolation:
    """LP-185: /admin/task-monitor/overview must not 500 when Flower or DB is unavailable."""

    def test_db_failure_yields_empty_db_tasks(self):
        """When TaskHistory table is missing/unreachable, DB source degrades to empty, not 500."""
        with patch("app.services.task_monitor_service._safe_workers_overview", return_value=None):
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

    def test_flower_unavailable_still_returns_response(self):
        """When Flower is unreachable, the overview still returns a valid (degraded) response."""
        with patch(
            "app.services.task_monitor_service._safe_workers_overview",
            return_value=None,
        ):
            with patch(
                "app.services.task_monitor_service._load_db_task_history",
                return_value=[],
            ):
                result = task_monitor_service.build_task_monitor_overview(
                    task_limit=10,
                    history_limit=5,
                )
        assert result.workers_online == 0
        assert result.workers == []
        assert result.tasks == []

    def test_single_worker_flower_failure_skips_only_that_worker(self):
        """A per-worker Flower failure should not fail the whole overview."""
        from app.schemas.flower_monitor import (
            FlowerWorkerItem,
            FlowerWorkersOverviewResponse,
            FlowerWorkersSummary,
        )

        overview = FlowerWorkersOverviewResponse(
            generated_at=_now(),
            workers=[
                FlowerWorkerItem(worker="worker-a", status="ONLINE", queue_names=["q1"]),
                FlowerWorkerItem(worker="worker-b", status="ONLINE", queue_names=["q2"]),
            ],
            summary=FlowerWorkersSummary(total=2, online=2, offline=0),
        )

        def fake_build_worker_task_overview(worker, **kwargs):
            if worker == "worker-b":
                raise RuntimeError("flower down for worker-b")
            from app.schemas.flower_monitor import (
                FlowerTaskItem,
                FlowerWorkerTaskOverviewResponse,
                FlowerWorkerTaskSummary,
            )
            return FlowerWorkerTaskOverviewResponse(
                generated_at=_now(),
                worker=worker,
                active_tasks=[],
                reserved_tasks=[],
                scheduled_tasks=[],
                recent_tasks=[],
                summary=FlowerWorkerTaskSummary(),
            )

        with patch(
            "app.services.task_monitor_service._safe_workers_overview",
            return_value=overview,
        ):
            with patch(
                "app.services.task_monitor_service.build_worker_task_overview",
                side_effect=fake_build_worker_task_overview,
            ):
                with patch(
                    "app.services.task_monitor_service._load_db_task_history",
                    return_value=[],
                ):
                    result = task_monitor_service.build_task_monitor_overview(
                        task_limit=10,
                        history_limit=5,
                    )

        assert result.workers_online == 2
        assert len(result.workers) == 2
        # queue names from both workers survive even if one worker's task fetch fails
        assert {q.name for q in result.queues} == {"q1", "q2"}
        assert result.tasks == []

    def test_flower_tasks_are_converted_and_merged(self):
        """Flower active/recent tasks are converted into the task list."""
        from app.schemas.flower_monitor import (
            FlowerTaskItem,
            FlowerWorkerItem,
            FlowerWorkerTaskOverviewResponse,
            FlowerWorkerTaskSummary,
            FlowerWorkersOverviewResponse,
            FlowerWorkersSummary,
        )

        overview = FlowerWorkersOverviewResponse(
            generated_at=_now(),
            workers=[FlowerWorkerItem(worker="worker-a", status="ONLINE", queue_names=["q1"])],
            summary=FlowerWorkersSummary(total=1, online=1, offline=0),
        )
        active = FlowerTaskItem(
            task_id="task-1",
            name="foo",
            state="STARTED",
            source="ACTIVE",
            worker="worker-a",
            queue_name="q1",
            started_at=_now(),
        )

        def fake_build_worker_task_overview(worker, **kwargs):
            return FlowerWorkerTaskOverviewResponse(
                generated_at=_now(),
                worker=worker,
                active_tasks=[active],
                reserved_tasks=[],
                scheduled_tasks=[],
                recent_tasks=[],
                summary=FlowerWorkerTaskSummary(),
            )

        with patch(
            "app.services.task_monitor_service._safe_workers_overview",
            return_value=overview,
        ):
            with patch(
                "app.services.task_monitor_service.build_worker_task_overview",
                side_effect=fake_build_worker_task_overview,
            ):
                with patch(
                    "app.services.task_monitor_service._load_db_task_history",
                    return_value=[],
                ):
                    result = task_monitor_service.build_task_monitor_overview(
                        task_limit=10,
                        history_limit=5,
                    )

        assert len(result.tasks) == 1
        assert result.tasks[0].task_id == "task-1"
        assert result.tasks[0].state == "STARTED"
        assert result.workers_online == 1

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
