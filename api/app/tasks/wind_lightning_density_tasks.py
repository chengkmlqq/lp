"""风电场地闪密度统计 Celery 任务。

与 ``lightning_tasks`` 的地闪分布导入完全独立（独立批次表、独立事件主题），
只在基础设施层面复用 Celery / 对象存储 / 任务日志采集。
"""

from __future__ import annotations

from typing import Any

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..services.wind_lightning_density_service import (
    WIND_LIGHTNING_DENSITY_TOPIC,
    mark_batch_failed,
    run_batch,
)


def _capture(task_id: str, text: str) -> None:
    """写入 TaskLogCapture 缓冲（实时日志流 + 终态日志的权威来源）。"""
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:  # noqa: BLE001 - 日志失败不影响主流程
        pass


def _publish_batch_event(event_name: str, payload: dict[str, Any]) -> None:
    """经 Redis Stream 事件桥向 Web 进程推送批次事件。"""
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            WIND_LIGHTNING_DENSITY_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/wind-lightning-density"],
            dedupe_key=f"{event_name}:{payload.get('batch_id', 'unknown')}",
        )
    except Exception:  # noqa: BLE001 - 推送失败不影响任务结果
        pass


@celery_app.task(
    name="app.tasks.wind_lightning_density_tasks.run_wind_lightning_density_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_wind_lightning_density_job(
    self,
    batch_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """风电场地闪密度统计任务：解析 → 统计 → 落库 → 出图。"""
    task_id = self.request.id
    db = SessionLocal()
    _capture(task_id, f"[{task_id}] 风电场地闪密度统计任务启动（batch_id={batch_id}）\n")
    try:
        result = run_batch(db, batch_id, actor_user_id=actor_user_id)
        _publish_batch_event(
            "wind_lightning_density.completed",
            {
                "batch_id": batch_id,
                "status": "completed",
                "turbine_count": result.get("turbine_count"),
                "valid_records": result.get("valid_records"),
            },
        )
        _capture(
            task_id,
            f"[{task_id}] 统计完成：风机 {result.get('turbine_count')} 台，"
            f"范围内落雷 {result.get('valid_records')} 条，网格 {result.get('grid')}\n",
        )
        return result
    except Exception as exc:  # noqa: BLE001 - 统一转批次失败状态
        import traceback

        db.rollback()
        _capture(task_id, f"[{task_id}] 任务执行失败：{exc}\n{traceback.format_exc()}\n")
        try:
            mark_batch_failed(db, batch_id, str(exc))
        finally:
            _publish_batch_event(
                "wind_lightning_density.failed",
                {"batch_id": batch_id, "status": "failed", "error": str(exc)},
            )
        raise
    finally:
        db.close()
