# -*- coding: utf-8 -*-
"""任务实时执行日志采集器

进程级（Worker 内）按 ``task_id`` 隔离的日志采集器，负责把三类日志收集到内存缓冲，
并周期性地把增量行写入 Redis Stream（供 FastAPI SSE 端点实时读取）：

1. Celery 自身日志（``[INFO/MainProcess] Task xxx succeeded`` 等）
   --- 通过给 root logger 挂一个自定义 ``logging.Handler`` 捕获（覆盖所有冒泡日志）。
2. 用户 ``logger.info/debug/...`` --- 同上（root logger 冒泡自动覆盖，无需改业务代码）。
3. ``print()`` / traceback / ``sys.stderr`` --- 通过把 ``sys.stdout`` / ``sys.stderr``
   替换为 ``_TeeIO`` 捕获（双写：容器 stdout 保留 + 写入缓冲）。

设计要点：

- ``_TeeIO`` 和 root handler 都不绑定特定任务缓冲，而是每次写入时通过
  ``celery._state.get_current_task()`` 动态解析"当前任务"对应的缓冲。Worker 为 prefork
  单进程单任务模型，因此 sys.stdout / root handler 只需在进程启动时安装一次，随任务
  切换自动路由到正确的 task_id 缓冲，不会出现跨任务串写或丢行。
- 注册表用 ``threading.Lock`` 保护，内存缓冲超限（``task_log_max_buffer_lines``）丢最旧行并计数。
- Redis 读写统一走 ``app.services.task_log_service``（XADD/XREAD），本模块不直接连 Redis。
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from ..core.config import get_settings

_logger = logging.getLogger(__name__)


class _TaskLogBuffer:
    """单任务日志缓冲：内存行列表 + 批量写 Redis Stream + 全量出 MinIO。"""

    def __init__(self, task_id: str) -> None:
        self._task_id = task_id
        settings = get_settings()
        self._max_lines = settings.task_log_max_buffer_lines
        self._flush_interval = settings.task_log_flush_interval_seconds
        self._lines: list[str] = []
        self._dropped = 0                  # 超限被丢弃的行数
        self._flushed_count = 0            # 已成功 XADD 到 Redis 的行数（增量游标）
        self._last_flush_ts = time.monotonic()
        self._lock = threading.Lock()
        self._closed = False

    def write(self, text: str) -> None:
        """供 handler / stdout tee 调用，按行切分追加到缓冲。"""
        if not text:
            return
        lines = text.splitlines() or [text]
        with self._lock:
            if self._closed:
                return
            for line in lines:
                self._append_locked(line)

    def log(self, line: str) -> None:
        """供业务代码显式记录（等价于写入单行）。"""
        self.write(line + "\n")

    def _append_locked(self, line: str) -> None:
        if self._max_lines and len(self._lines) >= self._max_lines:
            self._dropped += 1
            self._lines.pop(0)
            # 超限丢最旧行：若被丢弃的行尚未 flush，则已 flush 游标相应前移
            if self._flushed_count > 0:
                self._flushed_count -= 1
        self._lines.append(line)

    @property
    def truncated(self) -> int:
        with self._lock:
            return self._dropped

    def flush_incremental(self) -> None:
        """XADD 自上次 flush 以来的新增行到 Redis Stream；写失败静默降级。"""
        # 跨出锁获取快照（仅增量），避免持锁做网络 IO
        with self._lock:
            if self._closed or not self._lines:
                return
            start = self._flushed_count
            if start >= len(self._lines):
                return
            snapshot = self._lines[start:]
        try:
            from ..services import task_log_service

            task_log_service.append_task_log_lines(self._task_id, snapshot)
        except Exception:  # noqa: BLE001 —— Redis 不可用不应阻断任务执行
            _logger.debug("task_log flush to redis failed for %s", self._task_id)
            return
        # 只推进已成功写入的部分；期间新追加的行留到下一次 flush
        with self._lock:
            self._flushed_count = min(len(self._lines), start + len(snapshot))

    def maybe_flush(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._closed:
                return
            if now - self._last_flush_ts < self._flush_interval:
                return
            self._last_flush_ts = now
        self.flush_incremental()

    def mark_end(self) -> None:
        """任务结束信号：写入 ``__end__`` 结束标记（不走 maxlen 截断）。"""
        try:
            from ..services.task_log_service import mark_task_log_end

            mark_task_log_end(self._task_id)
        except Exception:  # noqa: BLE001
            _logger.debug("task_log mark_end failed for %s", self._task_id)

    def snapshot(self) -> str:
        """全量文本（任务结束时，含截断标记首部）。"""
        with self._lock:
            lines = list(self._lines)
            dropped = self._dropped
        header = ""
        if dropped:
            header = f"[已截断 {dropped} 行（超过缓冲上限）]\n"
        return header + "\n".join(lines)

    def close(self) -> None:
        """标记关闭并清空内部缓冲。"""
        with self._lock:
            self._closed = True
            self._lines.clear()


class _TeeIO:
    """双写 IO：原始流 + 写入"当前任务"的日志缓冲（动态解析，不绑定具体 task）。"""

    def __init__(self, original) -> None:  # noqa: ANN001
        self._original = original

    def write(self, data: str) -> int:
        written = self._original.write(data)
        buffer = _current_buffer()
        if buffer is not None:
            try:
                buffer.write(data)
            except Exception:  # noqa: BLE001
                pass
        return written

    def flush(self) -> None:
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)


class TaskLogCapture:
    """进程级注册表：task_id → buffer。"""

    _registry: dict[str, _TaskLogBuffer] = {}
    _lock = threading.Lock()

    _root_handler: logging.Handler | None = None
    _prior_root_handlers: tuple[logging.Handler, ...] = ()

    # --- 生命周期 ---
    @classmethod
    def start(cls, task_id: str) -> None:
        """创建（或复用）task_id 对应的缓冲。Tee / root handler 在进程启动时已安装。"""
        if not task_id:
            return
        with cls._lock:
            existing = cls._registry.get(task_id)
            if existing is not None and not existing._closed:  # noqa: SLF001
                return
            cls._registry[task_id] = _TaskLogBuffer(task_id)

    @classmethod
    def stop(cls, task_id: str) -> list[str]:
        """卸载（移除注册）+ 返回全量行列表。"""
        with cls._lock:
            buffer = cls._registry.pop(task_id, None)
        if buffer is None:
            return []
        # 卸载前先 flush 剩余增量，再打结束标记
        buffer.flush_incremental()
        buffer.mark_end()
        text = buffer.snapshot()
        buffer.close()
        if text:
            return text.splitlines()
        return []

    @classmethod
    def get(cls, task_id: str) -> _TaskLogBuffer | None:
        """取缓冲；不存在（未 start / 已 stop）时返回 None，不自动创建（避免泄漏）。"""
        with cls._lock:
            buffer = cls._registry.get(task_id)
            if buffer is not None and not buffer._closed:  # noqa: SLF001
                return buffer
        return None

    @classmethod
    def flush_all(cls) -> None:
        """周期兜底任务用：处理 crash 遗留，并对仍活跃的缓冲按其周期 flush。"""
        active: list[tuple[str, _TaskLogBuffer]] = []
        with cls._lock:
            for task_id, buffer in list(cls._registry.items()):
                if buffer._closed:  # noqa: SLF001
                    cls._registry.pop(task_id, None)
                else:
                    active.append((task_id, buffer))
        for _tid, buffer in active:
            buffer.flush_incremental()

    # --- 进程启动时一次性安装 ---
    @classmethod
    def install(cls) -> None:
        """Worker 进程启动早期调用：安装 root handler + stdout/stderr Tee。"""
        # root handler：捕获所有冒泡到 root 的日志（Celery 自身日志 + 用户 logger）
        if cls._root_handler is None:
            root = logging.getLogger()
            cls._prior_root_handlers = tuple(root.handlers)
            handler = logging.Handler()

            def _emit(record: logging.LogRecord) -> None:
                buffer = _current_buffer()
                if buffer is not None:
                    try:
                        buffer.write(handler.format(record))
                    except Exception:  # noqa: BLE001
                        pass

            handler.emit = _emit
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            root.addHandler(handler)
            cls._root_handler = handler

        # stdout/stderr Tee：print() / traceback 双写
        if not isinstance(sys.stdout, _TeeIO):
            sys.stdout = _TeeIO(sys.stdout)
        if not isinstance(sys.stderr, _TeeIO):
            sys.stderr = _TeeIO(sys.stderr)


def _current_buffer() -> _TaskLogBuffer | None:
    """当前线程（任务）对应的缓冲；无任务上下文或未 start 时返回 None。"""
    from celery._state import get_current_task

    current_task = get_current_task()
    if current_task is None:
        return None
    request = getattr(current_task, "request", None)
    if request is None:
        return None
    task_id = getattr(request, "id", None)
    if not task_id:
        return None
    return TaskLogCapture.get(task_id)


# 在模块导入时（Worker 进程启动早期）安装 root handler + Tee
TaskLogCapture.install()
