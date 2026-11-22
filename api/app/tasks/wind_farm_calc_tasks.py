"""风电场计算 Celery 任务（LP-35）。

三层超时互不替代：本模块用 Celery 软 7h / 硬 13h 兜底（必须大于 exe 的软 6h / 硬 12h，
否则 Celery 先杀 worker 会留下 Wine 孤儿）；exe 自身的软硬上限与进程组收割在
``wind_farm_calc_service.run_job`` 中实现。Wine 孤儿收割沿用 ``app/core/orphan_reaper.py``。
"""

from __future__ import annotations

import socket
import time
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app
from ..core.config import get_settings
from ..core.database import SessionLocal
from ..services.wind_farm_calc_service import (
    WIND_FARM_CALC_TOPIC,
    mark_job_failed,
    run_job,
    wine_binary_command,
    write_wine_probe_cache,
)
from ..services.wine_probe import probe_wine_binary

_settings = get_settings()


def _t(text: str) -> str:
    """任务日志/阶段文案遵循 LP-34 的 APP_LANGUAGE（未收录短语保持原文）。"""
    try:
        from ..services.backend_lang import current_backend_lang
        from ..services.backend_text_i18n import translate_backend_text

        return translate_backend_text(text, current_backend_lang())
    except Exception:  # noqa: BLE001 - 翻译失败不阻断任务
        return text


def _capture(task_id: str, text: str) -> None:
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:  # noqa: BLE001 - 日志失败不影响主流程
        pass


def _publish_job_event(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            WIND_FARM_CALC_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/wind-farm-calc"],
            dedupe_key=f"{event_name}:{payload.get('job_id', 'unknown')}",
        )
    except Exception:  # noqa: BLE001 - 推送失败不影响任务结果
        pass


@celery_app.task(
    name="app.tasks.wind_farm_calc_tasks.run_wind_farm_calc",
    bind=True,
    acks_late=True,
    soft_time_limit=_settings.wind_farm_calc_celery_soft_time_limit,
    time_limit=_settings.wind_farm_calc_celery_time_limit,
)
def run_wind_farm_calc(self, job_id: str) -> dict[str, Any]:
    """风电场计算任务：Wine 调度 exe → GBK 解析 → 结果逐台落库。"""
    task_id = self.request.id
    db = SessionLocal()
    _capture(task_id, f"[{task_id}] {_t('风电场计算任务启动')}（job_id={job_id}）\n")

    def on_progress(percent: int, stage: str) -> None:
        self.update_state(state="PROGRESS", meta={"percent": percent, "stage": _t(stage)})

    def on_log(text: str) -> None:
        # 只把降噪后的关键行写入任务日志，exe 的全部 stdout 落在工作目录日志文件
        _capture(task_id, f"[{task_id}] {_t(text)}\n")

    try:
        result = run_job(db, job_id, task_id=task_id, on_progress=on_progress, on_log=on_log)
        if result.get("status") == "cancelled":
            _publish_job_event("wind_farm_calc.cancelled", {"job_id": job_id, "status": "cancelled"})
            return result
        _publish_job_event(
            "wind_farm_calc.completed",
            {
                "job_id": job_id,
                "status": "completed",
                "turbine_count": result.get("turbine_count"),
                "risk_mismatch_count": result.get("risk_mismatch_count"),
            },
        )
        return result
    except SoftTimeLimitExceeded:
        db.rollback()
        message = "任务超过 Celery 软时限（7h），已终止"
        _capture(task_id, f"[{task_id}] {message}\n")
        mark_job_failed(db, job_id, message)
        _publish_job_event("wind_farm_calc.failed", {"job_id": job_id, "status": "failed", "error": message})
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转任务失败状态
        import traceback

        db.rollback()
        _capture(task_id, f"[{task_id}] 计算失败：{exc}\n{traceback.format_exc()}\n")
        mark_job_failed(db, job_id, str(exc))
        _publish_job_event(
            "wind_farm_calc.failed",
            {"job_id": job_id, "status": "failed", "error": str(exc)},
        )
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.wind_farm_calc_tasks.probe_wine_engine",
    acks_late=False,
)
def probe_wine_engine() -> dict[str, Any]:
    """在执行 worker 内探测 Wine 能力（LP-69）。

    API 容器不装 wine，预检只能由 ``wind_farm_calc`` 队列的 worker 反映真实执行环境。
    探测结果写入 Redis 缓存，``GET /api/v1/wind-farm-calc/engine`` 只读缓存，不再在 API
    容器里 `shutil.which("wine")` 误判引擎不可用。
    """
    binary = wine_binary_command()
    probe = probe_wine_binary(binary, timeout_seconds=10)
    payload = {
        "available": probe.available,
        "version": probe.version,
        "error": probe.error,
        "binary": binary,
        "worker": socket.gethostname(),
        "checked_at": time.time(),
    }
    write_wine_probe_cache(payload)
    return payload
