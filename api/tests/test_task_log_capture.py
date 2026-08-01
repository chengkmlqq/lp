"""
Unit tests for TaskLogCapture (task real-time log collector).
"""
from __future__ import annotations

import pytest

from app.core.task_log_capture import TaskLogCapture, _TaskLogBuffer, _current_buffer


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个用例前后清空注册表，避免跨用例串行残留。"""
    TaskLogCapture._registry.clear()
    yield
    TaskLogCapture._registry.clear()


class TestTaskLogBuffer:
    def test_write_and_snapshot(self):
        buf = _TaskLogBuffer("task-1")
        buf.write("line1\nline2")
        buf.log("line3")
        snapshot = buf.snapshot()
        assert snapshot == "line1\nline2\nline3"
        buf.close()

    def test_write_empty_text_is_noop(self):
        buf = _TaskLogBuffer("task-2")
        buf.write("")
        buf.write("\n")
        assert buf.snapshot() == ""
        buf.close()

    def test_buffer_cap_drops_oldest_and_counts(self):
        buf = _TaskLogBuffer("task-3")
        buf._max_lines = 3
        buf.write("1\n2\n3\n4\n5")
        assert buf.truncated == 2
        snapshot = buf.snapshot()
        assert snapshot.startswith("[已截断 2 行")
        assert "3" in snapshot
        assert "5" in snapshot
        assert "1" not in snapshot
        buf.close()

    def test_close_clears_buffer(self):
        buf = _TaskLogBuffer("task-4")
        buf.write("hello")
        buf.close()
        assert buf.snapshot() == ""

    def test_flush_incremental_only_sends_new_lines(self):
        """flush 应只推送自上次以来的新增行（增量游标），避免重复。"""
        buf = _TaskLogBuffer("task-5")
        buf.write("line1\nline2")

        sent: list[list[str]] = []

        def _fake_append(task_id: str, lines: list[str]) -> None:
            sent.append(list(lines))

        from app.services import task_log_service
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = _fake_append
        try:
            buf.flush_incremental()
            assert sent == [["line1", "line2"]]

            # 追加新行后再 flush，只应发送新增行
            buf.write("line3\nline4")
            buf.flush_incremental()
            assert sent == [["line1", "line2"], ["line3", "line4"]]
        finally:
            task_log_service.append_task_log_lines = original
        buf.close()

    def test_flush_incremental_after_drop_keeps_cursor_consistent(self):
        """超限丢最旧行后，flush 游标不应超过 buffer 长度。"""
        buf = _TaskLogBuffer("task-6")
        buf._max_lines = 3

        from app.services import task_log_service
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = lambda task_id, lines: None
        try:
            # 先写入并 flush 两行（cursor=2）
            buf.write("a\nb")
            buf.flush_incremental()
            assert buf._flushed_count == 2
            # 再写入超过上限：c d e，触发 a、b 被丢弃（均为已 flush 行，cursor 随之前移）
            buf.write("c\nd\ne")
            assert buf.truncated == 2  # a、b 被丢
            assert buf._flushed_count == 0
            # flush 剩余行（自 c 起），不应越界或崩溃
            buf.flush_incremental()
            buf.flush_incremental()
        finally:
            task_log_service.append_task_log_lines = original
        buf.close()


class TestTaskLogCaptureLifecycle:
    def test_start_stop_roundtrip(self):
        TaskLogCapture.start("t-1")
        buf = TaskLogCapture.get("t-1")
        assert buf is not None
        buf.log("hello")
        lines = TaskLogCapture.stop("t-1")
        assert lines == ["hello"]
        # stop 后 get 返回 None（不自动重建）
        assert TaskLogCapture.get("t-1") is None

    def test_stop_unstarted_returns_empty(self):
        assert TaskLogCapture.stop("never-started") == []

    def test_start_is_idempotent(self):
        TaskLogCapture.start("t-2")
        first = TaskLogCapture.get("t-2")
        TaskLogCapture.start("t-2")
        second = TaskLogCapture.get("t-2")
        assert first is second
        TaskLogCapture.stop("t-2")

    def test_start_empty_task_id_is_noop(self):
        TaskLogCapture.start("")
        assert TaskLogCapture._registry == {}

    def test_multiple_tasks_are_isolated(self):
        TaskLogCapture.start("t-a")
        TaskLogCapture.start("t-b")
        TaskLogCapture.get("t-a").log("msg-a")
        TaskLogCapture.get("t-b").log("msg-b")
        assert TaskLogCapture.stop("t-a") == ["msg-a"]
        assert TaskLogCapture.stop("t-b") == ["msg-b"]


class TestCurrentBufferRouting:
    def test_current_buffer_resolves_per_task(self):
        from celery._state import _task_stack, push_current_task

        class _FakeTask:
            class request:
                id = None

        TaskLogCapture.start("ctx-1")
        t1 = _FakeTask()
        t1.request.id = "ctx-1"
        push_current_task(t1)
        try:
            assert _current_buffer() is TaskLogCapture.get("ctx-1")
        finally:
            _task_stack.pop()

        TaskLogCapture.start("ctx-2")
        t2 = _FakeTask()
        t2.request.id = "ctx-2"
        push_current_task(t2)
        try:
            assert _current_buffer() is TaskLogCapture.get("ctx-2")
            # 切到 ctx-2 后不再命中 ctx-1 的缓冲
            assert _current_buffer() is not TaskLogCapture.get("ctx-1")
        finally:
            _task_stack.pop()

        # 无任务上下文时返回 None
        assert _current_buffer() is None
        TaskLogCapture.stop("ctx-1")
        TaskLogCapture.stop("ctx-2")

    def test_current_buffer_returns_none_for_unstarted(self):
        from celery._state import _task_stack, push_current_task

        class _FakeTask:
            class request:
                id = None

        t = _FakeTask()
        t.request.id = "not-started"
        push_current_task(t)
        try:
            assert _current_buffer() is None
        finally:
            _task_stack.pop()


class TestFlushAll:
    def test_flush_all_removes_closed_and_flushes_active(self):
        TaskLogCapture.start("f-1")
        TaskLogCapture.stop("f-1")  # 已 close，应被清理
        TaskLogCapture.start("f-2")
        TaskLogCapture.flush_all()
        assert "f-1" not in TaskLogCapture._registry
        assert "f-2" in TaskLogCapture._registry
        TaskLogCapture.stop("f-2")
