"""风电场数据准备 Celery 任务。

与 ``wind_lightning_density_tasks``（LP-32）完全独立：独立批次表、独立事件主题，
只在基础设施层复用 Celery / 对象存储 / 任务日志采集。
"""

from __future__ import annotations

from typing import Any

from ..core.celery_app import celery_app
from ..core.database import SessionLocal
from ..services.wind_data_prep_service import (
    WIND_DATA_PREP_TOPIC,
    mark_batch_failed,
    run_batch,
)


def _capture(task_id: str, text: str) -> None:
    try:
        from ..core.task_log_capture import TaskLogCapture

        buffer = TaskLogCapture.get(task_id)
        if buffer is not None:
            buffer.write(text)
    except Exception:  # noqa: BLE001 - 日志失败不影响主流程
        pass


def _publish_batch_event(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            WIND_DATA_PREP_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/wind-data-prep"],
            dedupe_key=f"{event_name}:{payload.get('batch_id', 'unknown')}",
        )
    except Exception:  # noqa: BLE001 - 推送失败不影响任务结果
        pass


@celery_app.task(
    name="app.tasks.wind_data_prep_tasks.run_wind_data_prep_job",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
    soft_time_limit=1800,
    time_limit=3600,
)
def run_wind_data_prep_job(
    self,
    batch_id: str,
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    """风电场数据准备任务：解析 → 校验 → 生成五文件 → 落库。"""
    task_id = self.request.id
    db = SessionLocal()
    _capture(task_id, f"[{task_id}] 风电场数据准备任务启动（batch_id={batch_id}）\n")

    def on_log(text: str) -> None:
        _capture(task_id, f"[{task_id}] {text}\n")

    try:
        result = run_batch(db, batch_id, actor_user_id=actor_user_id, on_log=on_log)
        _publish_batch_event(
            "wind_data_prep.completed",
            {
                "batch_id": batch_id,
                "status": "completed",
                "turbine_count": result.get("turbine_count"),
                "files_ready": result.get("files_ready"),
            },
        )
        _capture(
            task_id,
            f"[{task_id}] 准备完成：风机 {result.get('turbine_count')} 台，"
            f"范围内落雷 {result.get('lightning_in_scope')} 条，"
            f"产物 {result.get('files_ready')}/5\n",
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
                "wind_data_prep.failed",
                {"batch_id": batch_id, "status": "failed", "error": str(exc)},
            )
        raise
    finally:
        db.close()
