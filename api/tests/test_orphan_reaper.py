from __future__ import annotations

import os
import sys

import pytest

from app.core import orphan_reaper


def test_enable_subreaper_returns_bool() -> None:
    """enable_subreaper 在本机正常运行不抛异常（Linux 返回 True，其它平台 False）。"""
    result = orphan_reaper.enable_subreaper()
    assert isinstance(result, bool)
    # Linux CI 上应能成功设为 subreaper
    if sys.platform == "linux":
        assert result is True


def test_reap_orphans_reaps_exited_child() -> None:
    """fork 一个子进程让其退出成为僵尸后再收割，应能回收。"""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    # 等子进程退出成为僵尸（轮询 /proc/<pid>/stat 状态，不调用 waitpid 以免提前回收）
    import time

    deadline = time.time() + 5.0
    is_zombie = False
    while time.time() < deadline:
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                stat = fh.read()
                # 状态字段在右括号后（comm 可能含空格，故取最后一个 ')' 之后）
                state = stat[stat.rfind(")") + 2 : stat.rfind(")") + 3]
                if state == "Z":
                    is_zombie = True
                    break
        except FileNotFoundError:
            break
        time.sleep(0.05)
    if not is_zombie:
        # 子进程还没变僵尸（极端慢环境）——保守回收后不强制 >=1
        reaped = orphan_reaper.reap_orphans(max_batch=8)
        assert isinstance(reaped, int)
        return
    # 子进程确为僵尸，reap_orphans(-1) 应能收割它
    reaped = orphan_reaper.reap_orphans(max_batch=8)
    assert isinstance(reaped, int)
    assert reaped >= 1


def test_reap_orphans_no_children_no_error() -> None:
    """无子进程时收割不应抛异常，返回 0。"""
    reaped = orphan_reaper.reap_orphans(max_batch=8)
    assert reaped == 0


def test_start_orphan_reaper_starts_daemon_thread() -> None:
    """启动收割线程返回 daemon 线程且不立即崩溃。"""
    thread = orphan_reaper.start_orphan_reaper(interval_seconds=30.0)
    assert thread.is_alive() is True
    assert thread.daemon is True
    assert thread.name == "orphan-reaper"
    # 线程已启动，不应立刻退出（waiting on interval）
    import time

    time.sleep(0.2)
    assert thread.is_alive() is True