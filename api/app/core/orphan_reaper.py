"""容器化外部引擎孤儿进程回收（根治 zombie 堆积）。

背景（2026-09-16 生产实测）：
    fl-analysis 任务以 ``subprocess.run(wine tpbig.exe ...)`` 调用外部引擎。wine 启动时会
    fork 出常驻的 ``wineserver``（后台 daemon），wineserver 再 fork 出执行子进程。当中间
    进程退出后，仍存活的孙进程（wineserver 及其子进程）会被 reparent 到最近的存活祖先——
    即 celery worker 主进程。Celery 主进程默认不设 ``PR_SET_CHILD_SUBREAPER``，也没有
    ``waitpid(-1, WNOHANG)`` 收割循环，这些孤儿孙进程退出后一律变僵尸且无人回收。

    实测一例：92 塔任务串行跑了 4.8 小时后，wine-worker 主进程下累积了 19033 个僵尸，
    占满宿主进程表槽位 → ``wineserver: fork: Resource temporarily unavailable``（EAGAIN）
    → 任务在第 27 塔 fork 时失败。

根治：把 celery worker 设为本进程树的 child-subreaper，并用一个后台守护线程周期
   ``waitpid(-1, WNOHANG)`` 收割所有 orphaned / 已退出的子进程（含 reparent 上来的孙进程）。
   这样无论 wine 怎么 fork/daemonize，任何孤儿子进程退出后都会被立即回收，不再堆积。

用法（在 celery worker 启动处调用）：
    from .orphan_reaper import enable_subreaper, start_orphan_reaper
    enable_subreaper()
    start_orphan_reaper(interval_seconds=10.0)
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading

_logger = logging.getLogger(__name__)

# PR_SET_CHILD_SUBREAPER = 36（内核 3.4+）
_PR_SET_CHILD_SUBREAPER = 36


def enable_subreaper() -> bool:
    """把当前进程设为本进程树的 child subreaper。

    设为 subreaper 后，本进程将成为所有亡故后代的收养者：任何 reparent 上来的孤儿
    （wineserver / tpbig 的孙进程等）都改由本进程领养，从而可被本进程 waitpid 收割。
    仅 Linux 生效（prctl 系统调用）；返回是否成功设置。
    """
    if not hasattr(os, "getpid"):
        return False
    libc = getattr(ctypes, "CDLL", None)
    if libc is None:
        return False
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    try:
        result = libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except (OSError, AttributeError) as exc:  # 平台不支持时静默忽略
        _logger.debug("enable_subreaper: prctl 不可用：%s", exc)
        return False
    if result == 0:
        _logger.info("已设当前进程（pid=%d）为 child subreaper", os.getpid())
        return True
    return False


def reap_orphans(max_batch: int = 512) -> int:
    """非阻塞收割所有已退出/孤儿子进程，返回本次收割数量。

    用 ``waitpid(-1, WNOHANG)`` 轮询，收回任何已退出的直接子进程
    （含 subreaper 领养的孤儿孙进程）。最大批量上限保护单次调用不至于过久。
    """
    reaped = 0
    for _ in range(max_batch):
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break  # 无子进程
        except OSError:
            break
        if pid == 0:
            break  # 无已退出子进程
        reaped += 1
    if reaped:
        _logger.info("orphan_reaper: 收割了 %d 个孤儿/僵尸子进程", reaped)
    return reaped


def start_orphan_reaper(*, interval_seconds: float = 10.0) -> threading.Thread:
    """启动一个后台守护线程，周期收割孤儿/僵尸子进程。

    interval_seconds：每次 waitpid 轮询间隔。默认 10s，兼顾回收及时性与 CPU 开销；
    ``reap_orphans`` 本身是 O(子进程数) 且 WNOHANG 非阻塞，每轮开销极小。
    返回已启动的线程（便于测试/关停）。
    """
    stop = threading.Event()

    def _loop() -> None:
        while not stop.is_set():
            try:
                reap_orphans()
            except Exception as exc:  # noqa: BLE001 —— 收割异常不应导致线程崩溃
                _logger.warning("orphan_reaper 收割异常：%s", exc)
            stop.wait(interval_seconds)

    thread = threading.Thread(target=_loop, name="orphan-reaper", daemon=True)
    thread.start()
    return thread