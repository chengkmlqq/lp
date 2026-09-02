from __future__ import annotations

from typing import Any

from ..core.celery_app import celery_app

FAULT_ANALYSIS_TOPIC = "admin.fault-analysis"


def _publish_fault_analysis_event(event_name: str, payload: dict[str, Any]) -> None:
    """向 admin.fault-analysis 主题推送判别进度事件（经 Redis 桥）。"""
    try:
        from ..services.ws_event_bridge import publish_ws_event_from_worker

        publish_ws_event_from_worker(
            FAULT_ANALYSIS_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=["/api/v1/fault-analysis"],
            dedupe_key=f"{event_name}:{payload.get('analysis_id', 'unknown')}",
        )
    except Exception:
        pass


def _update_progress(analysis_id: str, progress: float, status: str | None = None, step: str | None = None) -> None:
    """更新判别进度到数据库并推送 WS 事件。

    step 仅作为当前阶段描述随 WS 事件推送；progress < 0 表示不修改数据库中的进度值。
    """
    if progress >= 0:
        try:
            from ..core.database import SessionLocal
            from ..models.fault_analysis import FaultAnalysis
            from ..models.base import utcnow

            db = SessionLocal()
            try:
                item = db.query(FaultAnalysis).filter(FaultAnalysis.id == analysis_id).first()
                if item is not None:
                    item.progress = progress
                    if status is not None:
                        item.status = status
                    item.update_date = utcnow()
                    db.commit()
            finally:
                db.close()
        except Exception:
            pass

    payload: dict[str, Any] = {
        "analysis_id": analysis_id,
        "status": status or "",
    }
    # 阶段事件（progress<0，step_callback）不携带 progress 字段，避免前端把阶段事件
    # 误当作真实进度（旧逻辑 max(-1,0)=0 会把进度条重置为 0，表现为进度不更新）。
    if progress >= 0:
        payload["progress"] = max(progress, 0)
    if step is not None:
        payload["step"] = step

    _publish_fault_analysis_event("analysis.diagnosis_progress", payload)


@celery_app.task(
    name="app.tasks.fault_diagnosis_tasks.run_fault_diagnosis_task",
    bind=True,
    # 判别任务走独立队列：仅 fquiz-matlab-worker（含 Wine + MATLAB Runtime）消费，
    # 保证 MATLAB 行波判别不因落到无 Runtime 的普通 worker 而降级。
    queue="matlab-diagnostics",
    soft_time_limit=300,
    time_limit=600,
)
def run_fault_diagnosis_task(self, analysis_id: str) -> dict[str, str]:
    task_id = self.request.id
    log_parts: list[str] = [f"[{task_id}] Starting fault diagnosis for analysis {analysis_id}"]
    try:
        from ..services.fault_diagnosis_service import run_fault_diagnosis_with_progress
        from ..core.database import SessionLocal

        _publish_fault_analysis_event("analysis.diagnosis_started", {
            "analysis_id": analysis_id,
        })

        db = SessionLocal()
        try:
            run_fault_diagnosis_with_progress(
                db, analysis_id,
                progress_callback=lambda progress, status="": _update_progress(analysis_id, progress, status or None),
                step_callback=lambda step: _update_progress(analysis_id, -1, "processing", step),
            )
            # 判别成功后生成 Word 报告
            _update_progress(analysis_id, 90, "processing", "生成Word报告")
            from ..services.fault_diagnosis_service import generate_report_docx
            try:
                generate_report_docx(db, analysis_id)
            except Exception as report_exc:
                log_parts.append(f"[{task_id}] 报告生成失败（不影响判别结果）: {report_exc}")
        finally:
            db.close()

        _update_progress(analysis_id, 100, "completed")
        _publish_fault_analysis_event("analysis.diagnosis_completed", {
            "analysis_id": analysis_id,
        })

        log_parts.append(f"[{task_id}] Fault diagnosis for analysis {analysis_id} completed")
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        return {"analysis_id": analysis_id, "status": "done"}
    except Exception as exc:
        import traceback

        _update_progress(analysis_id, 0, "failed")
        _publish_fault_analysis_event("analysis.diagnosis_failed", {
            "analysis_id": analysis_id,
            "error": str(exc),
        })

        log_parts.append(f"[{task_id}] Fault diagnosis for analysis {analysis_id} FAILED: {exc}")
        log_parts.append(traceback.format_exc())
        log_content = "\n".join(log_parts)
        try:
            from ..services.task_log_service import upload_task_log
            upload_task_log(task_id, log_content)
        except Exception:
            pass
        raise
