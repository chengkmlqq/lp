"""
Unit tests for TaskLogCapture (task real-time log collector).
"""
from __future__ import annotations

import logging

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


class TestWriteDrivenFlush:
    """P0：写入驱动的时间闸门 —— write() 末尾触发 maybe_flush()，任务运行中即有增量入 Redis。"""

    def test_write_triggers_maybe_flush_after_interval(self):
        buf = _TaskLogBuffer("p0-1")
        sent: list[list[str]] = []

        from app.services import task_log_service
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = lambda task_id, lines: sent.append(list(lines))
        try:
            # 首行写入：距上次 flush（构造时）超过间隔，应立即 flush
            buf._flush_interval = -1  # 强制超时，确保首次写入即 flush
            buf.write("line1\n")
            assert sent == [["line1"]], sent

            # 追加行：间隔未到时不 flush
            buf._last_flush_ts = _monotonic_now() + 100  # 人为推迟上次 flush 时间
            buf._flush_interval = 3.0
            buf.write("line2\n")
            assert sent == [["line1"]], sent  # 未触发

            # 间隔已到：再次 flush 增量
            buf._last_flush_ts = _monotonic_now() - 10
            buf.write("line3\n")
            assert sent == [["line1"], ["line2", "line3"]], sent
        finally:
            task_log_service.append_task_log_lines = original
        buf.close()

    def test_write_flush_failure_silently_degrades(self):
        buf = _TaskLogBuffer("p0-2")
        buf._flush_interval = -1

        from app.services import task_log_service
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = lambda task_id, lines: (_ for _ in ()).throw(RuntimeError("redis down"))
        try:
            buf.write("hello\n")  # 不应抛异常，Redis 不可用静默降级
            assert buf.snapshot() == "hello"
        finally:
            task_log_service.append_task_log_lines = original
        buf.close()


def _monotonic_now():
    import time
    return time.monotonic()


class TestDedup:
    """P1：同一条 Celery 日志只被捕获一次（方案 B —— root handler 跳过经 StreamHandler 的日志）。"""

    def test_capture_handler_skips_streamhandler_lines(self):
        from app.core.task_log_capture import _record_handled_by_console_handler

        import io
        import sys

        root = logging.getLogger()
        record = logging.LogRecord(
            name="app.test_capture",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="celery boundary log",
            args=(),
            exc_info=None,
        )

        # 1) 指向 sys.stderr 的 StreamHandler（Celery 场景）→ 控制台输出，应跳过（由 _TeeIO 捕获）
        stderr_handler = logging.StreamHandler(sys.stderr)
        root.addHandler(stderr_handler)
        try:
            assert _record_handled_by_console_handler(record) is True
        finally:
            root.removeHandler(stderr_handler)

        # 2) 指向 StringIO 的 StreamHandler（如 pytest LogCaptureHandler）→ 非控制台，不应跳过
        stringio_handler = logging.StreamHandler(io.StringIO())
        root.addHandler(stringio_handler)
        try:
            assert _record_handled_by_console_handler(record) is False
        finally:
            root.removeHandler(stringio_handler)

        # 3) FileHandler 不算“控制台输出”，不应被跳过
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".log") as tmp:
            file_handler = logging.FileHandler(tmp.name)
            root.addHandler(file_handler)
            try:
                assert _record_handled_by_console_handler(record) is False
            finally:
                file_handler.close()
                root.removeHandler(file_handler)

    def test_capture_handler_skips_noisy_loggers(self):
        from app.core.task_log_capture import _CaptureHandler, _is_noisy_record

        noisy = logging.LogRecord(
            name="botocore.client", level=logging.INFO, pathname=__file__,
            lineno=1, msg="noise", args=(), exc_info=None,
        )
        assert _is_noisy_record(noisy) is True

        clean = logging.LogRecord(
            name="app.my_business", level=logging.INFO, pathname=__file__,
            lineno=1, msg="business", args=(), exc_info=None,
        )
        assert _is_noisy_record(clean) is False

    def test_capture_handler_level_filtering(self):
        """P2：root handler setLevel 取配置（默认 INFO），DEBUG 不入缓冲。

        级别闸门由 ``logging.Logger.callHandlers`` 施加（``record.levelno >= handler.level``），
        因此这里用真实 logger 触发（而非直接调 emit/handle），以验证级别过滤生效。
        """
        from app.core.task_log_capture import _CaptureHandler
        from app.core.config import get_settings

        handler = _CaptureHandler()
        handler.setLevel(logging.getLevelName(get_settings().task_log_capture_level))

        TaskLogCapture.start("p2-1")
        buffer = TaskLogCapture.get("p2-1")
        from celery._state import _task_stack, push_current_task
        class _FakeTask:
            class request:
                id = "p2-1"
        t = _FakeTask()
        push_current_task(t)
        try:
            # 独立的 logger：只挂这个 capture handler，隔离 pytest 的 root 捕获 handler
            lg = logging.getLogger("p2-test-logger")
            lg.handlers = []
            lg.setLevel(logging.DEBUG)
            lg.propagate = False
            lg.addHandler(handler)
            try:
                lg.debug("debug line")
                lg.info("info line")
            finally:
                lg.removeHandler(handler)
            snapshot = buffer.snapshot()
            assert "debug line" not in snapshot
            assert "info line" in snapshot
        finally:
            _task_stack.pop()
            TaskLogCapture.stop("p2-1")


class TestCrashFallbackFlush:
    """P3：beat 兜底 flush_all 后，活跃缓冲增量可读（模拟崩溃前已 flush 的部分）。"""

    def test_flush_all_flushes_active_buffers(self):
        TaskLogCapture.start("crash-1")
        buf = TaskLogCapture.get("crash-1")
        buf._flush_interval = 9999  # 阻止写入驱动 flush
        sent: list[list[str]] = []

        from app.services import task_log_service
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = lambda task_id, lines: sent.append(list(lines))
        try:
            buf.write("line-a\nline-b")
            sent.clear()
            count = TaskLogCapture.flush_all()
            assert count == 1
            assert sent == [["line-a", "line-b"]], sent
        finally:
            task_log_service.append_task_log_lines = original
        TaskLogCapture.stop("crash-1")


class TestInstallProcessGate:
    """P4：install() 只在 worker 进程安装；API / beat 进程不替换 stdout/stderr。"""

    def test_should_install_with_worker_env(self, monkeypatch):
        import app.core.task_log_capture as tlc
        monkeypatch.setenv("PROCESS_TYPE", "worker")
        assert tlc._should_install() is True

    def test_should_not_install_with_api_env(self, monkeypatch):
        import app.core.task_log_capture as tlc
        monkeypatch.setenv("PROCESS_TYPE", "api")
        assert tlc._should_install() is False

    def test_should_install_by_worker_argv(self, monkeypatch):
        import app.core.task_log_capture as tlc
        monkeypatch.delenv("PROCESS_TYPE", raising=False)
        monkeypatch.setattr("sys.argv", ["celery", "-A", "app.core.celery_app.celery_app", "worker", "--loglevel=INFO"])
        assert tlc._should_install() is True

    def test_should_not_install_for_api_argv(self, monkeypatch):
        import app.core.task_log_capture as tlc
        monkeypatch.delenv("PROCESS_TYPE", raising=False)
        monkeypatch.setattr("sys.argv", ["uvicorn", "app.main:app", "--port", "8000"])
        assert tlc._should_install() is False

