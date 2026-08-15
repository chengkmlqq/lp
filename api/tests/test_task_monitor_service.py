from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services import task_monitor_service


def _now() -> datetime:
    return datetime(2026, 8, 2, 0, 0, 0, tzinfo=timezone.utc)


def _build_overview(**kwargs):
    """Call build_task_monitor_overview with defaults friendly to mocked DB helpers."""
    defaults = {"offset": 0, "limit": 10}
    defaults.update(kwargs)
    return task_monitor_service.build_task_monitor_overview(**defaults)


class TestTaskMonitorOverviewErrorIsolation:
    """LP-313: overview must be pure-DB and never fail when Flower/Redis is unavailable."""

    def test_db_failure_yields_empty_db_tasks(self):
        """When TaskHistory table is missing/unreachable, DB source degrades to empty, not 500."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ):
            with patch(
                "app.services.task_monitor_service._count_db_task_history",
                return_value=0,
            ):
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        result = _build_overview()
        assert result.tasks == []
        assert result.workers == []
        assert result.queues == []
        assert result.workers_online == 0
        assert result.total == 0
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
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        with patch(
                            "app.services.task_monitor_service._count_db_task_history",
                            return_value=0,
                        ):
                            result = _build_overview()
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
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=({"q1"}, {"q1": 1}),
                    ):
                        with patch(
                            "app.services.task_monitor_service._count_db_task_history",
                            return_value=len(items),
                        ):
                            result = _build_overview()

        assert [t.task_id for t in result.tasks] == ["task-1", "task-2"]
        assert result.tasks[0].worker == "celery@worker-1"
        assert {q.name for q in result.queues} == {"q1"}
        assert result.total == 2

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
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=({"q1", "q2"}, {"q1": 1, "q2": 1}),
                    ):
                        with patch(
                            "app.services.task_monitor_service._count_db_task_history",
                            return_value=len(items),
                        ):
                            result = _build_overview()

        queues = {q.name: q for q in result.queues}
        assert queues["q1"].active_count == 1
        assert queues["q1"].pending_count == 4
        assert queues["q1"].consumer_count == 0
        assert queues["q2"].active_count == 1
        assert result.queue_pending_total == 4

    def test_task_state_buckets_built_from_db_tasks(self):
        """State buckets aggregate the full filtered set via SQL (mocked here)."""
        from app.schemas.task_monitor import TaskMonitorBucketItem

        buckets = [
            TaskMonitorBucketItem(key="STARTED", label="执行中", count=1),
            TaskMonitorBucketItem(key="SUCCESS", label="成功", count=2),
        ]
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ):
            with patch(
                "app.services.task_monitor_service._count_db_task_history",
                return_value=3,
            ):
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=buckets,
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        result = _build_overview()
        buckets_map = {b.key: b.count for b in result.task_state_buckets}
        assert buckets_map["STARTED"] == 1
        assert buckets_map["SUCCESS"] == 2

    def test_redis_pending_failure_degrades_to_zero(self):
        """Redis LLEN failure must not crash the overview; pending counts stay 0."""
        from app.schemas.task_monitor import TaskMonitorTaskItem

        with patch(
            "app.services.task_monitor_service._safe_queue_pending_counts",
            return_value={},
        ):
            with patch(
                "app.services.task_monitor_service._load_state_bucket_items",
                return_value=[],
            ):
                with patch(
                    "app.services.task_monitor_service._load_queue_runtime_stats",
                    return_value=({"q1"}, {"q1": 1}),
                ):
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
                        with patch(
                            "app.services.task_monitor_service._count_db_task_history",
                            return_value=1,
                        ):
                            result = _build_overview()
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
            assert task_monitor_service._load_db_task_history(offset=0, limit=10) == []


class TestCountDbTaskHistory:
    def test_count_returns_row_count(self):
        fake_db = MagicMock()
        fake_db.scalar.return_value = 42
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            return_value=fake_db,
        ):
            assert task_monitor_service._count_db_task_history() == 42

    def test_count_returns_zero_on_none(self):
        fake_db = MagicMock()
        fake_db.scalar.return_value = None
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            return_value=fake_db,
        ):
            assert task_monitor_service._count_db_task_history() == 0

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("boom"), OSError("boom"), ValueError("boom")],
    )
    def test_count_returns_zero_on_error(self, exc):
        with patch(
            "app.services.task_monitor_service.SessionLocal",
            side_effect=exc,
        ):
            assert task_monitor_service._count_db_task_history() == 0

    def test_overview_total_uses_database_count_even_when_list_is_capped(self):
        """total reflects the full filtered DB count, not the page length."""
        from app.schemas.task_monitor import TaskMonitorTaskItem

        items = [
            TaskMonitorTaskItem(
                task_id=f"task-{i}",
                name=f"t{i}",
                state="SUCCESS",
                done_at=_now(),
            )
            for i in range(2)
        ]
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=items,
        ):
            with patch(
                "app.services.task_monitor_service._safe_queue_pending_counts",
                return_value={},
            ):
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        with patch(
                            "app.services.task_monitor_service._count_db_task_history",
                            return_value=7,
                        ):
                            result = _build_overview(limit=2)
        assert len(result.tasks) == 2
        assert result.total == 7


class TestServerSidePagination:
    """LP-360: offset/limit/keyword drive server-side pagination + filtering."""

    def test_offset_limit_keyword_forwarded_to_db_load(self):
        """build_task_monitor_overview must forward offset/limit/keyword to the DB loader."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ) as mock_load:
            with patch(
                "app.services.task_monitor_service._count_db_task_history",
                return_value=0,
            ):
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        _build_overview(offset=20, limit=10, keyword="import")
        mock_load.assert_called_once_with(offset=20, limit=10, keyword="import")

    def test_keyword_filtered_total(self):
        """With a keyword, total is the filtered count returned by the counter."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ):
            with patch(
                "app.services.task_monitor_service._count_db_task_history",
                return_value=3,
            ) as mock_count:
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        result = _build_overview(keyword="import")
        mock_count.assert_called_once_with(keyword="import")
        assert result.total == 3

    def test_blank_keyword_normalized_to_none(self):
        """Whitespace-only keyword is normalized away before hitting the DB."""
        with patch(
            "app.services.task_monitor_service._load_db_task_history",
            return_value=[],
        ) as mock_load:
            with patch(
                "app.services.task_monitor_service._count_db_task_history",
                return_value=0,
            ) as mock_count:
                with patch(
                    "app.services.task_monitor_service._load_state_bucket_items",
                    return_value=[],
                ):
                    with patch(
                        "app.services.task_monitor_service._load_queue_runtime_stats",
                        return_value=(set(), {}),
                    ):
                        _build_overview(keyword="   ")
        mock_load.assert_called_once_with(offset=0, limit=10, keyword=None)
        mock_count.assert_called_once_with(keyword=None)

    def test_keyword_condition_none_when_blank(self):
        assert task_monitor_service._keyword_condition(None) is None
        assert task_monitor_service._keyword_condition("   ") is None

    def test_keyword_condition_matches_state_label(self):
        """'成功' (SUCCESS Chinese label) must produce a state IN condition."""
        cond = task_monitor_service._keyword_condition("成功")
        assert cond is not None
        from sqlalchemy import ClauseElement

        assert isinstance(cond, ClauseElement)

    def test_keyword_condition_matches_task_display_name(self):
        """'ATP 模型运行' display name must produce a name IN condition."""
        cond = task_monitor_service._keyword_condition("ATP 模型运行")
        assert cond is not None
        from sqlalchemy import ClauseElement

        assert isinstance(cond, ClauseElement)

    def test_keyword_condition_matches_default_queue_label(self):
        """'默认队列' display name must match celery/default queue names."""
        cond = task_monitor_service._keyword_condition("默认队列")
        assert cond is not None

    def test_keyword_condition_matches_raw_fields(self):
        cond = task_monitor_service._keyword_condition("task-abc")
        assert cond is not None


class TestTaskNameLabelMappingSync:
    """Keep backend TASK_NAME_LABELS in sync with the frontend TS mapping."""

    def test_backend_labels_match_ts_mapping(self):
        import re
        from pathlib import Path

        ts_path = Path(__file__).resolve().parent.parent.parent / "web" / "src" / "lib" / "celery-task-display.ts"
        assert ts_path.exists(), f"TS mapping file not found: {ts_path}"
        source = ts_path.read_text(encoding="utf-8")
        ts_keys = set(re.findall(r'"((?:app\.tasks\.)[^"]+)"\s*:', source))
        backend_keys = set(task_monitor_service.TASK_NAME_LABELS.keys())
        assert backend_keys == ts_keys, (
            "Backend TASK_NAME_LABELS drifted from web/src/lib/celery-task-display.ts. "
            f"Missing: {sorted(ts_keys - backend_keys)}; extra: {sorted(backend_keys - ts_keys)}"
        )


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
