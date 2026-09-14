# -*- coding: utf-8 -*-
"""外部引擎（wine / tpbig / rjtzl_egm*.exe）长耗时调用的**进度心跳**。

背景（2026-09-14 实测）：
    ATP 主仿真（tpbig）、LCC 几何重生成、EGM 绕击跳闸率（`rjtzl_egm*.exe`，单次约 113s）
    等外部引擎调用单次可长达数分钟。调用处用 ``subprocess.run(..., capture_output=True)``
    阻塞等待 —— 子进程输出要等退出后才可见，期间任务日志/前端**完全静默**。
    实测一例：1 塔同跳任务在 ``raoji2`` 之后 **4.5 分钟零日志**，用户观感是"任务卡死 /
    日志不实时"（实际仍在计算，随后正常成功）。

方案：
    把 ``subprocess.run`` 放到守护线程执行，主线程每 ``atp_run_heartbeat_seconds``（默认 20s）
    写一行心跳（``logger.info`` + stdout，均会被 TaskLogCapture 采进任务日志 → 前端 SSE）。
    对外语义与原实现**完全一致**：返回 ``CompletedProcess``；超时抛 ``TimeoutExpired``；
    启动失败抛 ``OSError``（异常对象原样带回调用线程再抛）。
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from typing import Any, Sequence

_logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_SECONDS = 20.0


def _heartbeat_seconds() -> float:
    """取配置的心跳间隔（秒）；配置不可用/非正数时回落默认值。"""
    try:
        from .config import get_settings

        value = float(getattr(get_settings(), "atp_run_heartbeat_seconds", DEFAULT_HEARTBEAT_SECONDS))
    except Exception:  # noqa: BLE001 —— 心跳配置异常不应影响计算
        return DEFAULT_HEARTBEAT_SECONDS
    return value if value > 0 else DEFAULT_HEARTBEAT_SECONDS


def run_with_heartbeat(
    command: Sequence[str],
    *,
    cwd: Any = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    label: str = "",
    heartbeat_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """执行外部命令，运行期间周期性地打心跳日志。

    ``label`` 用于心跳文案（如 ``杆塔 P1（level4）``），便于前端一眼看出"哪个步骤还在算"。
    """
    interval = float(heartbeat_seconds or _heartbeat_seconds())
    started = time.monotonic()
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["result"] = subprocess.run(
                list(command),
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except BaseException as exc:  # noqa: BLE001 —— 原样带回调用线程再抛，保持原语义
            box["exc"] = exc

    thread = threading.Thread(target=_worker, name="atp-engine", daemon=True)
    thread.start()
    while True:
        thread.join(interval)
        if not thread.is_alive():
            break
        elapsed = int(time.monotonic() - started)
        tail = f"，超时上限 {int(timeout)}s" if timeout else ""
        where = f"：{label}" if label else ""
        _logger.info("[ENGINE] 运行心跳%s，已耗时 %ds%s", where, elapsed, tail)
        print(f"[ENGINE][HEARTBEAT] 运行中{where}，已耗时 {elapsed}s{tail}", file=sys.stdout, flush=True)

    if "exc" in box:
        raise box["exc"]
    return box["result"]
