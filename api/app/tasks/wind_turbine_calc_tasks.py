"""单风机计算 Celery 任务（LP-36）。

任务在独立的 matlab-wind worker 执行（Runtime 版本与故障判别不同，禁止复用 matlab-worker）。
三层超时互不替代：exe 软 6h / 硬 12h，Celery 软 7h / 硬 13h，Redis visibility_timeout 24h。
取消通过 cancel_requested 标志 + killpg(SIGKILL) 真正杀掉 MATLAB Runtime 进程组。
"""

from __future__ import annotations

from typing import Any

from celery.exceptions import SoftTimeLimitExceeded

from ..core.celery_app import celery_app
from ..core.config import get_settings
from ..core.database import SessionLocal
from ..services.wind_turbine_calc_service import (
    WIND_TURBINE_CALC_TOPIC,
    mark_job_failed,
    run_job,
)

_settings = get_settings()


def _t(text: str) -> str:
    try:
        from ..services.backend_lang import current_backend_lang
        from ..services.backend_text_i18n import translate_backend_text

        return translate_backend_text(text, current_backend_lang())
    except Exception:  # noqa: BLE001
        return text


def _capture(task_id: str, text: str) -> None:
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:  # noqa: BLE001
        pass


def _publish_job_event(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            WIND_TURBINE_CALC_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/wind-turbine-calc"],
            dedupe_key=f"{event_name}:{payload.get('job_id', 'unknown')}",
        )
    except Exception:  # noqa: BLE001
        pass


@celery_app.task(
    name="app.tasks.wind_turbine_calc_tasks.run_wind_turbine_calc",
    bind=True,
    acks_late=True,
    soft_time_limit=_settings.wind_turbine_calc_celery_soft_time_limit,
    time_limit=_settings.wind_turbine_calc_celery_time_limit,
)
def run_wind_turbine_calc(self, job_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """单风机计算任务：写 params.json → 调编译产物 → 解析 CSV → 落库。"""
    task_id = self.request.id
    db = SessionLocal()
    _capture(task_id, f"[{task_id}] {_t('单风机计算任务启动')}（job_id={job_id}）\n")

    def on_progress(percent: int, stage: str) -> None:
        self.update_state(state="PROGRESS", meta={"percent": percent, "stage": _t(stage)})

    def on_log(text: str) -> None:
        _capture(task_id, f"[{task_id}] {_t(text)}\n")

    try:
        result = run_job(db, job_id, params, task_id=task_id, on_progress=on_progress, on_log=on_log)
        if result.get("status") == "cancelled":
            _publish_job_event("wind_turbine_calc.cancelled", {"job_id": job_id, "status": "cancelled"})
            return result
        _publish_job_event(
            "wind_turbine_calc.completed",
            {
                "job_id": job_id,
                "status": "completed",
                "mean_failure_rate": result.get("mean_failure_rate"),
            },
        )
        return result
    except SoftTimeLimitExceeded:
        db.rollback()
        message = "任务超过 Celery 软时限（7h），已终止"
        _capture(task_id, f"[{task_id}] {message}\n")
        mark_job_failed(db, job_id, message)
        _publish_job_event("wind_turbine_calc.failed", {"job_id": job_id, "status": "failed", "error": message})
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback

        db.rollback()
        _capture(task_id, f"[{task_id}] 计算失败：{exc}\n{traceback.format_exc()}\n")
        mark_job_failed(db, job_id, str(exc))
        _publish_job_event("wind_turbine_calc.failed", {"job_id": job_id, "status": "failed", "error": str(exc)})
        raise
    finally:
        db.close()
