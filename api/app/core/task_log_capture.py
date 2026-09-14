# -*- coding: utf-8 -*-
"""任务实时执行日志采集器

进程级（Worker 内）按 ``task_id`` 隔离的日志采集器，负责把三类日志收集到内存缓冲，
并周期性地把增量行写入 Redis Stream（供 FastAPI SSE 端点实时读取）：

1. Celery 自身日志（``[INFO/MainProcess] Task xxx succeeded`` 等）
   --- 经 Celery 自身的 StreamHandler 写到 stderr，由 ``_TeeIO`` 捕获。
2. 用户 ``logger.info/debug/...`` --- 冒泡到 root 后：
   - 若 logger 链上有输出 handler（写到 stdout/stderr），文本走 ``_TeeIO`` 捕获；
   - 否则由 root 上的 ``_CaptureHandler`` 兜底捕获（避免日志丢失）。
3. ``print()`` / traceback / ``sys.stderr`` --- 通过把 ``sys.stdout`` / ``sys.stderr``
   替换为 ``_TeeIO`` 捕获（双写：容器 stdout 保留 + 写入缓冲）。

设计要点：

- ``_TeeIO`` 和 root handler 都不绑定特定任务缓冲，而是每次写入时通过
  ``celery._state.get_current_task()`` 动态解析"当前任务"对应的缓冲。Worker 为 prefork
  单进程单任务模型，因此 sys.stdout / root handler 只需在进程启动时安装一次，随任务
  切换自动路由到正确的 task_id 缓冲，不会出现跨任务串写或丢行。
- **去重（P1）**：同一条 Celery 日志会被 root handler（第 1 份）与 ``_TeeIO``（第 2 份）
  双路径命中。修复采用方案 B：``_CaptureHandler.emit`` 先判断该记录是否会经某个
  StreamHandler 写到 stdout/stderr —— 是则跳过（交给 ``_TeeIO`` 捕获），避免双写。
- **级别/噪音过滤（P2）**：root handler ``setLevel`` 取配置项（默认 INFO）；已知噪音
  logger（botocore/urllib3 等）级别提升到 WARNING，从源头不产生记录。
- 注册表用 ``threading.Lock`` 保护，内存缓冲超限（``task_log_max_buffer_lines``）丢最旧行并计数。
- Redis 读写统一走 ``app.services.task_log_service``（XADD/XREAD），本模块不直接连 Redis。
- **进程隔离（P4）**：``install()`` 仅在 worker 进程执行（``PROCESS_TYPE=worker`` 或
  命令行 ``celery ... worker``），API / beat 进程不替换 stdout/stderr。
"""

from __future__ import annotations

import logging
import os
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
        # P0：写入驱动的时间闸门 —— 距上次 flush 超过阈值则把增量写入 Redis Stream，
        # 让任务运行中前端 SSE 即可读到实时日志（无需等任务结束才一次性 flush）。
        self.maybe_flush()

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


def _handler_writes_to_console(handler: logging.Handler) -> bool:
    """handler 是否把日志写到 stdout/stderr（这类输出会被 ``_TeeIO`` 捕获去重）。

    仅当 StreamHandler 的流指向真实的终端输出（``sys.stdout`` / ``sys.stderr`` /
    ``sys.__stdout__`` / ``sys.__stderr__``，或其 ``stream`` 就是当前被 ``_TeeIO``
    包装的对象）才命中；写到文件 / StringIO / /dev/null 的 handler 不算「控制台」，
    其输出不会被 ``_TeeIO`` 捕获，不应用于去重（避免漏捕）。
    """
    if isinstance(handler, logging.FileHandler):
        return False
    if not isinstance(handler, logging.StreamHandler):
        return False
    stream = getattr(handler, "stream", None)
    if stream is None:
        return True
    console_streams = (
        sys.stdout,
        sys.stderr,
        _unwrap_tee(sys.stdout),
        _unwrap_tee(sys.stderr),
    )
    return any(stream is ref for ref in console_streams)


def _unwrap_tee(stream) -> object:
    """若 stream 是 ``_TeeIO`` 则取其所包装的原始流，便于按对象身份比对。"""
    while hasattr(stream, "_original"):
        stream = stream._original  # type: ignore[attr-defined]
    return stream


def _record_handled_by_console_handler(record: logging.LogRecord) -> bool:
    """该记录是否会经 logger 链上某个 StreamHandler 写到 stdout/stderr。"""
    logger = logging.getLogger(record.name)
    root = logging.getLogger()
    while logger is not None:
        for handler in logger.handlers:
            if _handler_writes_to_console(handler):
                return True
        if logger is root:
            break
        logger = logger.parent  # type: ignore[assignment]
    return False


def _noisy_logger_prefixes() -> list[str]:
    """配置的噪音 logger 前缀列表（如 botocore/urllib3 等）。"""
    settings = get_settings()
    return [p.strip() for p in settings.task_log_noisy_logger_prefixes.split(",") if p.strip()]


def _is_noisy_record(record: logging.LogRecord) -> bool:
    """记录是否来自噪音 logger（按 name 前缀匹配）。"""
    name = record.name
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _noisy_logger_prefixes())


class _CaptureHandler(logging.Handler):
    """root logger 上的兜底捕获 handler。

    - 级别：``setLevel(task_log_capture_level)``（默认 INFO），DEBUG 不入任务日志。
    - 去重（P1）：记录若会经某个 StreamHandler 写到 stdout/stderr，则跳过 ——
      文本由 ``_TeeIO`` 从 stdout/stderr 捕获，避免同一条日志双写。
    - 噪音（P2）：来自 botocore/urllib3 等前缀的记录直接丢弃。
    """

    def emit(self, record: logging.LogRecord) -> None:
        if _is_noisy_record(record):
            return
        if _record_handled_by_console_handler(record):
            return
        buffer = _current_buffer()
        if buffer is not None:
            try:
                buffer.write(self.format(record))
            except Exception:  # noqa: BLE001
                pass


class TaskLogCapture:
    """进程级注册表：task_id → buffer。"""

    _registry: dict[str, _TaskLogBuffer] = {}
    _lock = threading.Lock()

    _root_handler: logging.Handler | None = None
    _console_handler: logging.Handler | None = None
    _prior_root_handlers: tuple[logging.Handler, ...] = ()
    _prior_noisy_levels: dict[str, int] = {}
    _original_stdout: object = None
    _original_stderr: object = None

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
    def get_single_active(cls) -> _TaskLogBuffer | None:
        """进程内**唯一**活跃缓冲；用于没有 celery 任务上下文的并行子线程回落。

        prefork worker 每个子进程同时只跑一个任务 → 活跃缓冲最多 1 个；返回恰好 1 个时
        可判定"当前任务"就是它（子线程的日志不会丢）。0 个（无任务）或多个（线程池并发
        多任务，本部署不存在）时返回 None，避免把日志串写到别的任务。
        """
        with cls._lock:
            active = [b for b in cls._registry.values() if not b._closed]  # noqa: SLF001
        if len(active) == 1:
            return active[0]
        return None

    @classmethod
    def flush_all(cls) -> int:
        """周期兜底任务用：清理 closed 缓冲，并对仍活跃的缓冲 flush 增量。

        返回活跃缓冲数（供 beat 兜底任务记录）。
        """
        active: list[tuple[str, _TaskLogBuffer]] = []
        with cls._lock:
            for task_id, buffer in list(cls._registry.items()):
                if buffer._closed:  # noqa: SLF001
                    cls._registry.pop(task_id, None)
                else:
                    active.append((task_id, buffer))
        for _tid, buffer in active:
            buffer.flush_incremental()
        return len(active)

    # --- 进程启动时一次性安装 ---
    @classmethod
    def install(cls, *, force: bool = False) -> None:
        """Worker 进程启动早期调用：安装 root handler + stdout/stderr Tee。

        非 worker 进程（API / beat / flower 等）不安装，避免无谓包装 stdout/stderr（P4）。
        通过环境变量 ``PROCESS_TYPE=worker`` 或命令行参数（``celery ... worker``）识别。

        顺序关键：先包装 stdout/stderr 为 ``_TeeIO``，再挂 root handler。这样 root 上的
        console StreamHandler 指向 ``sys.stderr``（已被 ``_TeeIO`` 包装），日志记录写入时
        既输出到容器 stdout/stderr（docker logs 不丢），又经 ``_TeeIO`` 单次写入任务缓冲。
        """
        if not force and not _should_install():
            return

        # stdout/stderr Tee：print() / traceback 双写（容器 stdout 保留 + 写入缓冲）
        if not isinstance(sys.stdout, _TeeIO):
            cls._original_stdout = sys.stdout
            sys.stdout = _TeeIO(sys.stdout)
        if not isinstance(sys.stderr, _TeeIO):
            cls._original_stderr = sys.stderr
            sys.stderr = _TeeIO(sys.stderr)

        # root handler：捕获不经过 stdout/stderr 输出链的日志（用户 logger 兜底）
        if cls._root_handler is None:
            root = logging.getLogger()
            cls._prior_root_handlers = tuple(root.handlers)
            settings = get_settings()

            # 兜底捕获 handler：仅捕获不会经控制台 StreamHandler 输出的记录（去重 P1）。
            handler = _CaptureHandler()
            handler.setLevel(logging.getLevelName(settings.task_log_capture_level))
            handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            root.addHandler(handler)
            cls._root_handler = handler

            # 控制台 StreamHandler：指向已被 _TeeIO 包装的 sys.stderr。
            # 这样 Celery / 业务 logger 冒泡到 root 的记录：
            #   - 容器 docker logs 仍可见（输出经 _TeeIO._original 到真实 stderr）；
            #   - 同时被 _TeeIO 捕获写入任务缓冲（唯一的捕获通道，不重复）。
            # 若已有写控制台的 handler（如 Celery 已在根上挂过），则不重复添加。
            if not any(_handler_writes_to_console(h) for h in root.handlers):
                console_handler = logging.StreamHandler(sys.stderr)
                console_handler.setLevel(settings.task_log_capture_level)
                console_handler.setFormatter(
                    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
                )
                root.addHandler(console_handler)
                cls._console_handler = console_handler

            # 噪音 logger 级别提升到 WARNING：从源头不产生 DEBUG/INFO 记录，
            # 既不进任务日志，也不写容器 stdout（避免第三方库噪音）。
            for prefix in _noisy_logger_prefixes():
                noisy_logger = logging.getLogger(prefix)
                if noisy_logger.level == logging.NOTSET:
                    cls._prior_noisy_levels[prefix] = noisy_logger.level
                    noisy_logger.setLevel(logging.WARNING)

    @classmethod
    def uninstall(cls) -> None:
        """卸载 root handler + 恢复 stdout/stderr + 噪音 logger 级别（测试 / 恢复用）。"""
        root = logging.getLogger()
        if cls._root_handler is not None:
            root.removeHandler(cls._root_handler)
            cls._root_handler = None
        if cls._console_handler is not None:
            root.removeHandler(cls._console_handler)
            cls._console_handler = None
        for prefix, prior_level in cls._prior_noisy_levels.items():
            logging.getLogger(prefix).setLevel(prior_level)
        cls._prior_noisy_levels.clear()
        if isinstance(sys.stdout, _TeeIO):
            sys.stdout = cls._original_stdout or sys.__stdout__
        if isinstance(sys.stderr, _TeeIO):
            sys.stderr = cls._original_stderr or sys.__stderr__
        cls._original_stdout = None
        cls._original_stderr = None


def _setup_logging_receiver(loglevel=None, logfile=None, format=None, colorize=None, **kwargs):  # type: ignore[no-untyped-def]
    """Celery ``setup_logging`` 信号接收器（仅 worker 进程注册）。

    返回 True（非 None）告诉 Celery「日志已由我们接管」，从而：
    - 跳过 ``root.handlers = []``（不会清掉我们的 ``_CaptureHandler``）；
    - 跳过 ``worker_redirect_stdouts``（不会把 sys.stdout/stderr 换成 LoggingProxy）。

    接管后仍保留一个指向 stderr 的 StreamHandler，保证容器 ``docker logs`` 可见原始输出。
    """
    # 接管日志后，root logger 级别需要提到配置的捕获级别（默认 INFO），否则 Python
    # 默认 root level=WARNING 会过滤掉 INFO 记录，业务 logger.info() 根本不产出记录，
    # root handler / 控制台 handler 都收不到。
    settings = get_settings()
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.getLevelName(settings.task_log_capture_level))

    TaskLogCapture.install(force=True)
    return True


def _register_setup_logging_receiver() -> None:
    """注册 Celery setup_logging 信号接收器（幂等）。"""
    from celery import signals

    if getattr(_register_setup_logging_receiver, "_registered", False):
        return
    signals.setup_logging.connect(_setup_logging_receiver, weak=False)
    _register_setup_logging_receiver._registered = True


def _current_buffer() -> _TaskLogBuffer | None:
    """当前线程（任务）对应的缓冲；无任务上下文或未 start 时返回 None。

    解析顺序（2026-09-14 修复「并行优化后任务日志只剩第一行」）：
      1. ``celery._state.get_current_task()`` —— 任务主线程内的常规路径；
      2. **进程内唯一活跃缓冲** —— 并行优化（``ThreadPoolExecutor`` 跑六档/三相二分）
         开的子线程没有 celery 任务上下文（``get_current_task()`` 是 thread-local，
         子线程里恒为 None）→ 子线程的 ``logger.info`` / ``print`` 只写容器 stdout、
         不进任务日志缓冲，前端 SSE 只看得到第一行。
         worker 为 prefork 单进程单任务模型（``--concurrency=N`` = N 个独立子进程），
         同一进程内同时只处理一个任务，故回落到"唯一活跃缓冲"是安全的；
         活跃缓冲 > 1（线程池并发多任务）时返回 None —— 宁可丢日志也不串写。
    """
    from celery._state import get_current_task

    current_task = get_current_task()
    if current_task is not None:
        request = getattr(current_task, "request", None)
        task_id = getattr(request, "id", None) if request is not None else None
        if task_id:
            buffer = TaskLogCapture.get(task_id)
            if buffer is not None:
                return buffer
    return TaskLogCapture.get_single_active()


def _should_install() -> bool:
    """判断当前进程是否为 celery worker（仅 worker 需要安装采集器）。"""
    process_type = os.environ.get("PROCESS_TYPE")
    if process_type == "worker":
        return True
    if process_type == "api":
        return False
    # 未显式指定时按命令行参数识别：celery ... worker
    argv0 = os.path.basename(sys.argv[0] or "")
    return argv0.startswith("celery") and "worker" in sys.argv


# 在模块导入时（Worker 进程启动早期）安装 root handler + Tee；API / beat 等进程跳过（P4）。
# 同时注册 setup_logging 信号接收器：Celery worker 启动时调用，确保 root handler 与
# sys.stdout/stderr 不被 worker_hijack_root_logger / redirect_stdouts 清除或替换。
if _should_install():
    TaskLogCapture.install()
    _register_setup_logging_receiver()
