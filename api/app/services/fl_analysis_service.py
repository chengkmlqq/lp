from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.fl_analysis import FlAnalysisJob, FlAnalysisRun, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.tower_profile import TowerProfile
from ..models.user import User
from ..schemas.fl_analysis import (
    FlAnalysisJobCreateRequest,
    FlAnalysisJobCreateResponse,
    FlAnalysisJobDetail,
    FlAnalysisJobListResponse,
    FlAnalysisJobStartResponse,
    FlAnalysisJobSummary,
    FlAnalysisRunSummary,
    FlAnalysisTowerResultListResponse,
    FlAnalysisTowerResultSummary,
)
from .atp_asset_service import _truncate_output
from .fl_analysis_external import execute_external_waveform_tower_analysis, resolve_external_waveform_job
from .legacy_atp_adapter import execute_legacy_atp_tower_analysis, resolve_legacy_atp_job
from .fl_analysis_report import build_report_document, build_report_summary_payload
from .fl_analysis_rules import (
    grade_mitigation_snapshot_payload,
    grade_normal_snapshot_payload,
    grade_snapshot_payload,
    grade_tongtiao_snapshot_payload,
)
from .line_preparation_service import summarize_line_preparation
from .push_service import publish_topic

FL_ANALYSIS_TOPIC = "admin.fl-analysis"


def serialize_run(item: FlAnalysisRun) -> FlAnalysisRunSummary:
    return FlAnalysisRunSummary(
        id=item.id,
        job_id=item.job_id,
        status=item.status,
        runner_kind=item.runner_kind,
        engine_command=item.engine_command,
        working_dir=item.working_dir,
        error_message=item.error_message,
        snapshot_tower_count=item.snapshot_tower_count,
        result_tower_count=item.result_tower_count,
        duration_ms=item.duration_ms,
        started_at=item.started_at,
        finished_at=item.finished_at,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_job(item: FlAnalysisJob, *, include_runs: bool = False) -> FlAnalysisJobDetail | FlAnalysisJobSummary:
    line = item.line
    payload: dict[str, Any] = {
        "id": item.id,
        "line_id": item.line_id,
        "line_code": line.code if line else None,
        "line_name": line.name if line else None,
        "job_name": item.job_name,
        "job_type": item.job_type,
        "source_kind": item.source_kind,
        "status": item.status,
        "task_id": item.task_id,
        "latest_run_id": item.latest_run_id,
        "total_tower_count": item.total_tower_count,
        "snapshotted_tower_count": item.snapshotted_tower_count,
        "result_tower_count": item.result_tower_count,
        "external_adapter": item.external_adapter,
        "adapter_config_json": item.adapter_config_json or {},
        "execution_options_json": item.execution_options_json or {},
        "result_summary_json": item.result_summary_json or {},
        "error_message": item.error_message,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "create_date": item.create_date,
        "create_user": item.create_user,
        "update_date": item.update_date,
        "update_user": item.update_user,
    }
    if include_runs:
        payload["runs"] = [serialize_run(run) for run in item.runs]
        return FlAnalysisJobDetail(**payload)
    return FlAnalysisJobSummary(**payload)


def serialize_tower_result(item: FlAnalysisTowerResult) -> FlAnalysisTowerResultSummary:
    snapshot = item.snapshot
    return FlAnalysisTowerResultSummary(
        id=item.id,
        job_id=item.job_id,
        run_id=item.run_id,
        snapshot_id=item.snapshot_id,
        tower_id=snapshot.tower_id,
        seq_no=snapshot.seq_no,
        tower_no=snapshot.tower_no,
        tower_model=snapshot.tower_model,
        tower_type=snapshot.tower_type,
        status=item.status,
        risk_level=item.risk_level,
        summary_text=item.summary_text,
        result_json=item.result_json or {},
        create_date=item.create_date,
        update_date=item.update_date,
    )


def get_job_by_id(db: Session, job_id: str) -> FlAnalysisJob | None:
    return db.execute(select(FlAnalysisJob).where(FlAnalysisJob.id == job_id)).scalar_one_or_none()


def list_jobs(
    db: Session,
    *,
    line_id: str | None,
    status_filter: str | None,
    limit: int,
) -> FlAnalysisJobListResponse:
    stmt = select(FlAnalysisJob)
    total_stmt = select(func.count()).select_from(FlAnalysisJob)

    if line_id:
        stmt = stmt.where(FlAnalysisJob.line_id == line_id)
        total_stmt = total_stmt.where(FlAnalysisJob.line_id == line_id)
    if status_filter:
        stmt = stmt.where(FlAnalysisJob.status == status_filter)
        total_stmt = total_stmt.where(FlAnalysisJob.status == status_filter)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(FlAnalysisJob.update_date.desc(), FlAnalysisJob.id.desc()).limit(limit)
    ).scalars().all()
    return FlAnalysisJobListResponse(items=[serialize_job(item) for item in items], total=total)


def list_tower_results(db: Session, *, job_id: str, run_id: str | None = None) -> FlAnalysisTowerResultListResponse:
    stmt = select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job_id)
    total_stmt = select(func.count()).select_from(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job_id)

    if run_id:
        stmt = stmt.where(FlAnalysisTowerResult.run_id == run_id)
        total_stmt = total_stmt.where(FlAnalysisTowerResult.run_id == run_id)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(FlAnalysisTowerResult.risk_level.desc(), FlAnalysisTowerResult.create_date.asc())
    ).scalars().all()
    return FlAnalysisTowerResultListResponse(items=[serialize_tower_result(item) for item in items], total=total)


def create_job(
    db: Session,
    payload: FlAnalysisJobCreateRequest,
    *,
    actor: User,
) -> FlAnalysisJobCreateResponse:
    line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
    if not line:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线路不存在")

    if payload.job_type in {"normal", "tongtiao", "risk"}:
        preparation = summarize_line_preparation(db, line)
        missing_items = [str(item) for item in preparation.get("missing_items") or []]
        if missing_items:
            missing_text = "、".join(missing_items)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"线路参数准备未完成：{missing_text}。请先完成相关回填后再创建任务。",
            )

    execution_options = _normalize_execution_options(payload.job_type, payload.execution_options_json or {})
    external_adapter = payload.external_adapter
    adapter_config_json = payload.adapter_config_json or {}
    if payload.job_type == "mitigation":
        total_tower_count = _validate_mitigation_options(db, line_id=line.id, execution_options=execution_options)
    elif payload.job_type == "report":
        total_tower_count = _validate_report_options(db, line_id=line.id, execution_options=execution_options)
    elif payload.job_type == "scenario":
        scenario_config = _validate_scenario_options(db, line_id=line.id, execution_options=execution_options)
        total_tower_count = int(scenario_config["total_tower_count"])
        execution_options = dict(scenario_config["execution_options"])
        external_adapter = str(scenario_config["external_adapter"])
        adapter_config_json = dict(scenario_config["adapter_config_json"])
    else:
        total_tower_count = int(
            db.scalar(
                select(func.count()).select_from(LineTower).where(LineTower.line_id == line.id)
            )
            or 0
        )
    if payload.job_type in {"normal", "tongtiao"}:
        if external_adapter in {"atp", "wine"}:
            try:
                resolve_external_waveform_job(
                    db,
                    external_adapter=external_adapter,
                    adapter_config_json=adapter_config_json,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        elif external_adapter == "legacy_atp":
            try:
                resolve_legacy_atp_job(
                    adapter_config_json=adapter_config_json,
                    execution_options=execution_options,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        elif external_adapter != "placeholder":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="普通计算和同跳计算仅支持 placeholder/atp/wine/legacy_atp 适配器",
            )
    if total_tower_count <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可分析的杆塔数据")

    now = utcnow()
    job = FlAnalysisJob(
        line_id=line.id,
        job_name=(payload.job_name or "").strip() or None,
        job_type=payload.job_type,
        source_kind="line",
        status="pending",
        total_tower_count=total_tower_count,
        external_adapter=external_adapter,
        adapter_config_json=adapter_config_json,
        execution_options_json=execution_options,
        result_summary_json={},
        create_date=now,
        create_user=actor.id,
        update_date=now,
        update_user=actor.id,
    )
    db.add(job)
    db.commit()

    saved = get_job_by_id(db, job.id)
    if not saved:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="创建防雷分析任务失败")

    _publish_change(
        "fl_analysis.job.created",
        {"action": "job_created", "job_id": saved.id, "line_id": saved.line_id},
    )
    return FlAnalysisJobCreateResponse(job=serialize_job(saved, include_runs=True))


def start_job(
    db: Session,
    job_id: str,
    *,
    actor: User,
) -> FlAnalysisJobStartResponse:
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已在排队或执行中")

    try:
        task = _dispatch_fl_analysis_task(job_id=job.id)
    except Exception as exc:
        job.error_message = str(exc)
        job.update_date = utcnow()
        job.update_user = actor.id
        db.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"任务派发失败: {exc}") from exc

    job.status = "queued"
    job.task_id = getattr(task, "id", None)
    job.error_message = None
    job.finished_at = None
    job.update_date = utcnow()
    job.update_user = actor.id
    db.commit()

    latest = get_job_by_id(db, job.id)
    if not latest:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务派发后查询失败")

    _publish_change(
        "fl_analysis.job.queued",
        {"action": "job_queued", "job_id": latest.id, "line_id": latest.line_id, "task_id": latest.task_id},
    )
    return FlAnalysisJobStartResponse(job=serialize_job(latest, include_runs=True), queued=True)


def download_report_document(db: Session, *, job_id: str) -> tuple[str, bytes]:
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    if job.job_type != "report":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅报告任务支持文档下载")
    if job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告任务尚未成功完成")

    execution_options = _normalize_execution_options(job.job_type, job.execution_options_json or {})
    generated_at = _read_report_generated_at(job) or job.finished_at or utcnow()
    report_data = _prepare_report_payload(db, job=job, execution_options=execution_options, generated_at=generated_at)
    return build_report_document(report_data)


def download_result_csv(db: Session, *, job_id: str, run_id: str | None = None) -> tuple[str, bytes]:
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    if job.job_type == "report":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告任务请使用报告下载入口")

    target_run_id = run_id or job.latest_run_id
    if not target_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当前任务暂无可导出的结果")

    rows = _load_result_rows(db, job_id=job.id, run_id=target_run_id)
    return export_fl_analysis_results_to_csv(job, rows)


def export_fl_analysis_results_to_csv(job: FlAnalysisJob, rows: list[FlAnalysisTowerResult]) -> tuple[str, bytes]:
    columns = _result_export_columns(job.job_type)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([header for header, _getter in columns])

    for item in rows:
        context = _build_result_export_context(item)
        writer.writerow([_format_export_cell(getter(context)) for _header, getter in columns])

    filename = f"fl_analysis_{job.job_type}_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return filename, output.getvalue().encode("utf-8-sig")


def execute_job(job_id: str) -> None:
    db = SessionLocal()
    started_perf = time.perf_counter()
    run_id: str | None = None
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            return

        now = utcnow()
        job.status = "running"
        job.started_at = now
        job.finished_at = None
        job.error_message = None
        job.result_summary_json = {}
        job.update_date = now

        run = FlAnalysisRun(
            job_id=job.id,
            status="running",
            runner_kind=job.external_adapter,
            started_at=now,
            create_date=now,
            create_user=job.update_user or job.create_user,
            update_date=now,
            update_user=job.update_user or job.create_user,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        job.latest_run_id = run.id
        db.commit()

        _publish_change(
            "fl_analysis.job.running",
            {"action": "job_running", "job_id": job.id, "line_id": job.line_id, "run_id": run.id},
        )

        execution_options = _normalize_execution_options(job.job_type, job.execution_options_json or {})
        if job.job_type == "report":
            _execute_report_job(
                db,
                job=job,
                run=run,
                execution_options=execution_options,
                started_perf=started_perf,
            )
            return

        waveform_job_type = _resolve_waveform_job_type(job_type=job.job_type, execution_options=execution_options)
        towers = _load_job_towers(db, job=job, execution_options=execution_options)
        if not towers:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前线路没有可分析的杆塔数据")
        source_result_map = _load_source_result_map(db, execution_options=execution_options) if job.job_type == "mitigation" else {}
        if job.job_type == "mitigation" and not source_result_map:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱风险任务结果已失效，请重新生成措施推荐任务")

        tower_ids = [tower.id for tower in towers]
        profile_rows = db.execute(select(TowerProfile).where(TowerProfile.tower_id.in_(tower_ids))).scalars().all()
        profile_map = {item.tower_id: item for item in profile_rows}

        db.execute(delete(FlAnalysisTowerResult).where(FlAnalysisTowerResult.run_id == run.id))
        db.execute(delete(FlAnalysisTowerSnapshot).where(FlAnalysisTowerSnapshot.run_id == run.id))
        db.flush()

        snapshot_count = 0
        snapshots: list[FlAnalysisTowerSnapshot] = []
        for tower in towers:
            profile = profile_map.get(tower.id)
            snapshot = FlAnalysisTowerSnapshot(
                job_id=job.id,
                run_id=run.id,
                tower_id=tower.id,
                seq_no=tower.seq_no,
                tower_no=tower.tower_no,
                tower_model=tower.tower_model,
                tower_type=tower.tower_type,
                longitude=tower.longitude,
                latitude=tower.latitude,
                altitude_m=tower.altitude_m,
                terrain=tower.terrain,
                base_tower_json=_build_base_tower_json(tower, job.line),
                profile_json=_build_profile_json(profile),
                create_date=utcnow(),
            )
            db.add(snapshot)
            snapshots.append(snapshot)
            snapshot_count += 1

        db.flush()

        result_count = 0
        summary = _new_result_summary()
        tower_map = {tower.id: tower for tower in towers}
        external_job = None
        legacy_external_job = None
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        if waveform_job_type in {"normal", "tongtiao"}:
            if job.external_adapter in {"atp", "wine"}:
                external_job = resolve_external_waveform_job(
                    db,
                    external_adapter=job.external_adapter,
                    adapter_config_json=job.adapter_config_json or {},
                )
                summary["external_model_id"] = external_job.model.id
                summary["external_model_code"] = external_job.model.code
                summary["external_model_name"] = external_job.model.name
                summary["external_version_id"] = external_job.version.id
                summary["external_version_no"] = external_job.version.version_no
            elif job.external_adapter == "legacy_atp":
                legacy_external_job = resolve_legacy_atp_job(
                    adapter_config_json=job.adapter_config_json or {},
                    execution_options=execution_options,
                )
                summary["external_model_id"] = legacy_external_job.template_identifier
                summary["external_model_code"] = legacy_external_job.calculation_mode
                summary["external_model_name"] = legacy_external_job.template_dir.name
                summary["external_version_id"] = legacy_external_job.template_identifier
                summary["external_version_no"] = 1
        for snapshot in snapshots:
            payload = {
                "base_tower_json": snapshot.base_tower_json or {},
                "profile_json": snapshot.profile_json or {},
            }
            if job.job_type == "scenario":
                payload["profile_json"] = _apply_scenario_profile_json_overrides(snapshot.profile_json or {})
            source_result = source_result_map.get(snapshot.tower_id)
            if source_result:
                payload["source_result_json"] = source_result
            if job.job_type == "mitigation":
                graded = grade_mitigation_snapshot_payload(
                    payload,
                    non_construction=bool(execution_options.get("non_construction")),
                )
            elif waveform_job_type == "normal":
                baseline_result = grade_normal_snapshot_payload(payload, execution_options=execution_options)
                if external_job is not None:
                    execution = execute_external_waveform_tower_analysis(
                        external_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    run.engine_command = run.engine_command or execution.engine_command
                    run.working_dir = run.working_dir or execution.working_dir
                    if execution.stdout_text:
                        stdout_chunks.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        stderr_chunks.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                elif legacy_external_job is not None:
                    execution = execute_legacy_atp_tower_analysis(
                        legacy_external_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    run.engine_command = run.engine_command or execution.engine_command
                    run.working_dir = run.working_dir or execution.working_dir
                    if execution.stdout_text:
                        stdout_chunks.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        stderr_chunks.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                else:
                    graded = baseline_result
            elif waveform_job_type == "tongtiao":
                baseline_result = grade_tongtiao_snapshot_payload(payload, execution_options=execution_options)
                if external_job is not None:
                    execution = execute_external_waveform_tower_analysis(
                        external_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    run.engine_command = run.engine_command or execution.engine_command
                    run.working_dir = run.working_dir or execution.working_dir
                    if execution.stdout_text:
                        stdout_chunks.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        stderr_chunks.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                elif legacy_external_job is not None:
                    execution = execute_legacy_atp_tower_analysis(
                        legacy_external_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    run.engine_command = run.engine_command or execution.engine_command
                    run.working_dir = run.working_dir or execution.working_dir
                    if execution.stdout_text:
                        stdout_chunks.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        stderr_chunks.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                else:
                    graded = baseline_result
            else:
                graded = grade_snapshot_payload(payload)
            db.add(
                FlAnalysisTowerResult(
                    job_id=job.id,
                    run_id=run.id,
                    snapshot_id=snapshot.id,
                    status="success",
                    risk_level=graded["risk_level"],
                    summary_text=graded["summary_text"],
                    result_json=graded,
                    create_date=utcnow(),
                    update_date=utcnow(),
                )
            )
            result_count += 1
            _accumulate_result_summary(summary, graded)

            tower = tower_map.get(snapshot.tower_id)
            if tower is not None and job.job_type not in {"mitigation", "scenario"}:
                tower.risk_level = graded["risk_level"]
                tower.update_date = utcnow()
                tower.update_user = job.update_user or job.create_user

        run.snapshot_tower_count = snapshot_count
        run.result_tower_count = result_count
        job.total_tower_count = len(towers)
        job.snapshotted_tower_count = snapshot_count
        job.result_tower_count = result_count
        if job.job_type == "mitigation":
            summary["selected_tower_count"] = len(towers)
            summary["source_job_id"] = execution_options.get("source_job_id")
            summary["source_run_id"] = execution_options.get("source_run_id")
            summary["non_construction"] = bool(execution_options.get("non_construction"))
        elif job.job_type == "scenario":
            summary["selected_tower_count"] = len(towers)
            summary["source_job_id"] = execution_options.get("source_job_id")
            summary["source_run_id"] = execution_options.get("source_run_id")
            summary["source_job_type"] = execution_options.get("source_job_type")
            summary["mitigation_job_id"] = execution_options.get("mitigation_job_id")
            summary["mitigation_job_name"] = execution_options.get("mitigation_job_name")
            summary["risk_job_id"] = execution_options.get("risk_job_id")
            summary["risk_job_name"] = execution_options.get("risk_job_name")
            summary["base_job_id"] = execution_options.get("base_job_id")
            summary["base_job_name"] = execution_options.get("base_job_name")
            summary["base_job_type"] = waveform_job_type
            summary["workflow"] = _workflow_summary_from_execution_options(execution_options)
            if external_job is not None:
                summary["external_engine_adapter"] = job.external_adapter
        elif waveform_job_type in {"normal", "tongtiao"}:
            summary["workflow"] = _workflow_summary_from_execution_options(execution_options)
            if external_job is not None or legacy_external_job is not None:
                summary["external_engine_adapter"] = job.external_adapter
        if stdout_chunks:
            run.stdout_text = _truncate_output("\n\n".join(stdout_chunks))
        if stderr_chunks:
            run.stderr_text = _truncate_output("\n\n".join(stderr_chunks))
        db.commit()

        _finish_rule_based_run(
            db,
            job_id=job.id,
            run_id=run.id,
            started_perf=started_perf,
            summary=summary,
            adapter_status="executed" if external_job is not None or legacy_external_job is not None else "computed",
        )

    except Exception as exc:
        db.rollback()
        if run_id is not None:
            _mark_run_failed(db, job_id=job_id, run_id=run_id, error_message=str(exc), started_perf=started_perf)
        else:
            _mark_job_failed_without_run(db, job_id=job_id, error_message=str(exc))
    finally:
        db.close()


def _dispatch_fl_analysis_task(*, job_id: str):
    from ..tasks.fl_analysis_tasks import execute_fl_analysis_job

    return execute_fl_analysis_job.delay(job_id)


def _finish_rule_based_run(
    db: Session,
    *,
    job_id: str,
    run_id: str,
    started_perf: float,
    summary: dict[str, Any],
    adapter_status: str = "computed",
) -> None:
    job = get_job_by_id(db, job_id)
    run = db.execute(select(FlAnalysisRun).where(FlAnalysisRun.id == run_id)).scalar_one_or_none()
    if not job or not run:
        return

    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    now = utcnow()

    run.status = "success"
    run.error_message = None
    run.duration_ms = max(duration_ms, 0)
    run.finished_at = now
    run.update_date = now

    job.status = "success"
    job.error_message = None
    job.result_summary_json = {
        **summary,
        "adapter_status": adapter_status,
        "external_adapter": job.external_adapter,
    }
    job.finished_at = now
    job.update_date = now
    db.commit()

    _publish_change(
        "fl_analysis.job.success",
        {
            "action": "job_success",
            "job_id": job.id,
            "line_id": job.line_id,
            "run_id": run.id,
            "summary": job.result_summary_json,
        },
    )


def _mark_run_failed(
    db: Session,
    *,
    job_id: str,
    run_id: str,
    error_message: str,
    started_perf: float,
) -> None:
    run = db.execute(select(FlAnalysisRun).where(FlAnalysisRun.id == run_id)).scalar_one_or_none()
    job = get_job_by_id(db, job_id)
    if not run or not job:
        return

    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    now = utcnow()
    run.status = "failed"
    run.error_message = error_message
    run.duration_ms = max(duration_ms, 0)
    run.finished_at = now
    run.update_date = now

    job.status = "failed"
    job.error_message = error_message
    job.finished_at = now
    job.update_date = now
    db.commit()

    _publish_change(
        "fl_analysis.job.failed",
        {"action": "job_failed", "job_id": job.id, "line_id": job.line_id, "run_id": run.id},
    )


def _mark_job_failed_without_run(db: Session, *, job_id: str, error_message: str) -> None:
    job = get_job_by_id(db, job_id)
    if not job:
        return
    now = utcnow()
    job.status = "failed"
    job.error_message = error_message
    job.finished_at = now
    job.update_date = now
    db.commit()

    _publish_change(
        "fl_analysis.job.failed",
        {"action": "job_failed", "job_id": job.id, "line_id": job.line_id},
    )


def _execute_report_job(
    db: Session,
    *,
    job: FlAnalysisJob,
    run: FlAnalysisRun,
    execution_options: dict[str, Any],
    started_perf: float,
) -> None:
    source_job_id = str(execution_options.get("source_job_id") or "")
    source_run_id = str(execution_options.get("source_run_id") or "")
    selected_tower_ids = list(execution_options.get("selected_tower_ids") or [])

    if not source_job_id or not source_run_id or not selected_tower_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告任务缺少来源结果或选塔范围")

    source_rows = _load_result_rows(db, job_id=source_job_id, run_id=source_run_id)
    source_row_map = {
        item.snapshot.tower_id: item
        for item in source_rows
        if item.snapshot is not None and item.snapshot.tower_id
    }
    selected_source_rows: list[FlAnalysisTowerResult] = []
    for tower_id in selected_tower_ids:
        item = source_row_map.get(tower_id)
        if item is None or item.snapshot is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告任务的杆塔范围已失效，请重新生成任务")
        selected_source_rows.append(item)

    db.execute(delete(FlAnalysisTowerResult).where(FlAnalysisTowerResult.run_id == run.id))
    db.execute(delete(FlAnalysisTowerSnapshot).where(FlAnalysisTowerSnapshot.run_id == run.id))
    db.flush()

    snapshot_pairs: list[tuple[FlAnalysisTowerSnapshot, FlAnalysisTowerResult]] = []
    for source_item in selected_source_rows:
        source_snapshot = source_item.snapshot
        snapshot = FlAnalysisTowerSnapshot(
            job_id=job.id,
            run_id=run.id,
            tower_id=source_snapshot.tower_id,
            seq_no=source_snapshot.seq_no,
            tower_no=source_snapshot.tower_no,
            tower_model=source_snapshot.tower_model,
            tower_type=source_snapshot.tower_type,
            longitude=source_snapshot.longitude,
            latitude=source_snapshot.latitude,
            altitude_m=source_snapshot.altitude_m,
            terrain=source_snapshot.terrain,
            base_tower_json=source_snapshot.base_tower_json or {},
            profile_json=source_snapshot.profile_json or {},
            create_date=utcnow(),
        )
        db.add(snapshot)
        snapshot_pairs.append((snapshot, source_item))

    db.flush()

    result_count = 0
    for snapshot, source_item in snapshot_pairs:
        db.add(
            FlAnalysisTowerResult(
                job_id=job.id,
                run_id=run.id,
                snapshot_id=snapshot.id,
                status="success",
                risk_level=source_item.risk_level,
                summary_text=source_item.summary_text,
                result_json=source_item.result_json or {},
                create_date=utcnow(),
                update_date=utcnow(),
            )
        )
        result_count += 1

    run.snapshot_tower_count = len(snapshot_pairs)
    run.result_tower_count = result_count
    job.total_tower_count = len(snapshot_pairs)
    job.snapshotted_tower_count = len(snapshot_pairs)
    job.result_tower_count = result_count
    db.commit()

    generated_at = utcnow()
    summary = build_report_summary_payload(
        _prepare_report_payload(db, job=job, execution_options=execution_options, generated_at=generated_at)
    )

    _finish_rule_based_run(
        db,
        job_id=job.id,
        run_id=run.id,
        started_perf=started_perf,
        summary=summary,
    )


def _prepare_report_payload(
    db: Session,
    *,
    job: FlAnalysisJob,
    execution_options: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    risk_job_id = str(execution_options.get("risk_job_id") or "")
    risk_run_id = str(execution_options.get("risk_run_id") or "")
    selected_tower_ids = list(execution_options.get("selected_tower_ids") or [])
    if not risk_job_id or not risk_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告任务缺少风险评估来源")

    risk_job = get_job_by_id(db, risk_job_id)
    if risk_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联风险任务不存在")

    risk_rows = [_serialize_report_row(item) for item in _load_result_rows(db, job_id=risk_job_id, run_id=risk_run_id)]
    selected_risk_rows = _filter_rows_by_tower_ids(risk_rows, selected_tower_ids)
    if len(selected_risk_rows) != len(selected_tower_ids):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告任务的风险结果已失效，请重新生成任务")

    mitigation_job_id = str(execution_options.get("mitigation_job_id") or "")
    mitigation_run_id = str(execution_options.get("mitigation_run_id") or "")
    mitigation_job = get_job_by_id(db, mitigation_job_id) if mitigation_job_id else None
    selected_mitigation_rows: list[dict[str, Any]] = []
    if mitigation_job is not None and mitigation_run_id:
        mitigation_rows = [
            _serialize_report_row(item)
            for item in _load_result_rows(db, job_id=mitigation_job_id, run_id=mitigation_run_id)
        ]
        selected_mitigation_rows = _filter_rows_by_tower_ids(mitigation_rows, selected_tower_ids)

    scenario_job_id = str(execution_options.get("scenario_job_id") or "")
    scenario_run_id = str(execution_options.get("scenario_run_id") or "")
    scenario_job = get_job_by_id(db, scenario_job_id) if scenario_job_id else None
    selected_scenario_rows: list[dict[str, Any]] = []
    if scenario_job is not None and scenario_run_id:
        scenario_rows = [
            _serialize_report_row(item)
            for item in _load_result_rows(db, job_id=scenario_job_id, run_id=scenario_run_id)
        ]
        selected_scenario_rows = _filter_rows_by_tower_ids(scenario_rows, selected_tower_ids)

    source_job = get_job_by_id(db, str(execution_options.get("source_job_id") or ""))
    line = risk_job.line or job.line
    mitigation_execution_options = mitigation_job.execution_options_json or {} if mitigation_job is not None else {}
    non_construction = bool(
        execution_options.get("non_construction")
        or mitigation_execution_options.get("non_construction")
        or mitigation_execution_options.get("mitigation_mode") == "non_construction"
        or any(bool(_safe_dict(item.get("result_json")).get("non_construction")) for item in selected_mitigation_rows)
    )

    return {
        "line": {
            "name": line.name if line else None,
            "code": line.code if line else None,
            "voltage_kv": line.voltage_kv if line else None,
        },
        "report": {
            "job_name": job.job_name,
            "generated_at": generated_at,
            "source_job_id": source_job.id if source_job else None,
            "source_job_type": source_job.job_type if source_job else None,
            "source_job_name": source_job.job_name if source_job else None,
            "risk_job_id": risk_job.id,
            "risk_job_name": risk_job.job_name,
            "mitigation_job_id": mitigation_job.id if mitigation_job else None,
            "mitigation_job_name": mitigation_job.job_name if mitigation_job else None,
            "scenario_job_id": scenario_job.id if scenario_job else None,
            "scenario_job_name": scenario_job.job_name if scenario_job else None,
            "scenario_base_job_type": (
                _resolve_waveform_job_type(
                    job_type=scenario_job.job_type,
                    execution_options=scenario_job.execution_options_json or {},
                )
                if scenario_job is not None
                else None
            ),
            "non_construction": non_construction,
        },
        "risk_rows": risk_rows,
        "selected_risk_rows": selected_risk_rows,
        "selected_mitigation_rows": selected_mitigation_rows,
        "selected_scenario_rows": selected_scenario_rows,
    }


def _serialize_report_row(item: FlAnalysisTowerResult) -> dict[str, Any]:
    snapshot = item.snapshot
    return {
        "tower_id": snapshot.tower_id if snapshot else None,
        "seq_no": snapshot.seq_no if snapshot else 0,
        "tower_no": snapshot.tower_no if snapshot else None,
        "tower_model": snapshot.tower_model if snapshot else None,
        "tower_type": snapshot.tower_type if snapshot else None,
        "base_tower_json": snapshot.base_tower_json if snapshot else {},
        "profile_json": snapshot.profile_json if snapshot else {},
        "risk_level": item.risk_level,
        "summary_text": item.summary_text,
        "result_json": item.result_json or {},
    }


def _filter_rows_by_tower_ids(rows: list[dict[str, Any]], tower_ids: list[str]) -> list[dict[str, Any]]:
    row_map = {
        str(item.get("tower_id")): item
        for item in rows
        if item.get("tower_id") is not None
    }
    selected_rows: list[dict[str, Any]] = []
    for tower_id in tower_ids:
        item = row_map.get(tower_id)
        if item is not None:
            selected_rows.append(item)
    return selected_rows


def _load_result_rows(db: Session, *, job_id: str, run_id: str) -> list[FlAnalysisTowerResult]:
    rows = db.execute(
        select(FlAnalysisTowerResult).where(
            FlAnalysisTowerResult.job_id == job_id,
            FlAnalysisTowerResult.run_id == run_id,
        )
    ).scalars().all()
    return sorted(
        rows,
        key=lambda item: (
            item.snapshot.seq_no if item.snapshot is not None else 0,
            item.create_date,
            item.id,
        ),
    )


def _build_result_export_context(item: FlAnalysisTowerResult) -> dict[str, Any]:
    snapshot = item.snapshot
    base = _safe_dict(snapshot.base_tower_json if snapshot is not None else None)
    profile = _safe_dict(snapshot.profile_json if snapshot is not None else None)
    result = _safe_dict(item.result_json)
    inputs = _safe_dict(result.get("inputs"))
    workflow = _safe_dict(result.get("workflow"))
    selected_case = _safe_dict(result.get("selected_case"))
    actions = [entry for entry in result.get("mitigation_actions") or [] if isinstance(entry, dict)]
    reason_details = [entry for entry in result.get("reason_details") or [] if isinstance(entry, dict)]
    return {
        "item": item,
        "snapshot": snapshot,
        "base": base,
        "profile": profile,
        "result": result,
        "inputs": inputs,
        "workflow": workflow,
        "selected_case": selected_case,
        "actions": actions,
        "actions_by_code": {
            str(action.get("code") or "").strip(): action
            for action in actions
            if str(action.get("code") or "").strip()
        },
        "reason_details": reason_details,
    }


def _result_export_columns(job_type: str) -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    columns = _common_result_export_columns()
    if job_type == "mitigation":
        return columns + _mitigation_result_export_columns()
    if job_type == "normal":
        return columns + _normal_result_export_columns() + _risk_result_export_columns()
    if job_type == "tongtiao":
        return columns + _normal_result_export_columns() + _tongtiao_result_export_columns() + _risk_result_export_columns()
    return columns + _risk_result_export_columns()


def _common_result_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    return [
        ("序号", lambda ctx: ctx["snapshot"].seq_no if ctx["snapshot"] is not None else None),
        ("杆塔号", lambda ctx: ctx["snapshot"].tower_no if ctx["snapshot"] is not None else None),
        ("杆塔模型", lambda ctx: ctx["snapshot"].tower_model if ctx["snapshot"] is not None else None),
        (
            "塔型",
            lambda ctx: _pick_export_value(
                ctx["snapshot"].tower_type if ctx["snapshot"] is not None else None,
                ctx["base"].get("tower_type"),
                ctx["profile"].get("structure_kind"),
            ),
        ),
        ("反击方式", lambda ctx: _pick_export_value(ctx["profile"].get("stroke_mode"), ctx["inputs"].get("stroke_mode"))),
        ("雷电流幅值a", lambda ctx: _pick_export_number(ctx["inputs"].get("current_a"), ctx["profile"].get("current_a"))),
        ("雷电流幅值b", lambda ctx: _pick_export_number(ctx["inputs"].get("current_b"), ctx["profile"].get("current_b"))),
        ("地闪密度", lambda ctx: _pick_export_number(ctx["inputs"].get("lightning_density"), ctx["base"].get("lightning_density"))),
        ("波头时间/μs", lambda ctx: _pick_export_number(ctx["profile"].get("current_head_time_us"))),
        ("波尾时间/μs", lambda ctx: _pick_export_number(ctx["profile"].get("current_tail_time_us"))),
        ("地面倾角1", lambda ctx: _pick_export_number(ctx["base"].get("slope_1"))),
        ("地面倾角2", lambda ctx: _pick_export_number(ctx["base"].get("slope_2"))),
        ("海拔(m)", lambda ctx: _pick_export_number(ctx["base"].get("altitude_m"))),
        ("地形", lambda ctx: ctx["base"].get("terrain")),
        ("接地电阻(Ω)", lambda ctx: _pick_export_number(ctx["inputs"].get("ground_resistance_ohm"), ctx["base"].get("ground_resistance_ohm"))),
        ("绝缘子串长(mm)", lambda ctx: _pick_export_number(ctx["inputs"].get("insulator_length_mm"))),
        ("保护角(°)", lambda ctx: _pick_export_number(ctx["inputs"].get("protection_angle_deg"))),
    ]


def _normal_result_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    return [
        ("最不利波头时间(μs)", lambda ctx: _pick_export_number(ctx["selected_case"].get("head_time_us"))),
        ("最不利波尾时间(μs)", lambda ctx: _pick_export_number(ctx["selected_case"].get("tail_time_us"))),
        ("雷电流波形", lambda ctx: ctx["workflow"].get("current_waveform")),
        ("闪络判据", lambda ctx: ctx["workflow"].get("flashover_method")),
        ("海拔修正", lambda ctx: ctx["workflow"].get("altitude_correction")),
        ("感应电压公式", lambda ctx: ctx["workflow"].get("induced_voltage_formula")),
        ("扫描点数", lambda ctx: _pick_export_number(ctx["workflow"].get("scan_point_count"))),
    ]


def _tongtiao_result_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    return [
        ("主导相组", lambda ctx: ctx["result"].get("dominant_phase_set")),
        ("闪络相", lambda ctx: ctx["result"].get("flashover_phase")),
        ("相别结果(JSON)", lambda ctx: ctx["result"].get("phase_results") or []),
        ("多相结果(JSON)", lambda ctx: ctx["result"].get("multi_phase_results") or []),
    ]


def _risk_result_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    return [
        ("反击耐雷水平(kA)", lambda ctx: _pick_export_number(ctx["result"].get("counterstrike_withstand_ka"))),
        ("反击跳闸率", lambda ctx: _pick_export_number(ctx["result"].get("counterstrike_trip_rate"))),
        ("绕击耐雷水平(kA)", lambda ctx: _pick_export_number(ctx["result"].get("shielding_withstand_ka"))),
        ("绕击跳闸率", lambda ctx: _pick_export_number(ctx["result"].get("shielding_trip_rate"))),
        ("风险等级", lambda ctx: _format_export_risk_level(_pick_export_value(ctx["item"].risk_level, ctx["result"].get("risk_level")))),
        ("风险档次", lambda ctx: _pick_export_number(ctx["result"].get("risk_grade"))),
        ("得分", lambda ctx: _pick_export_number(ctx["result"].get("score"))),
        ("高风险原因", lambda ctx: ctx["result"].get("cause_analysis")),
        ("措施建议", lambda ctx: ctx["result"].get("mitigation_recommendation")),
        ("原因明细(JSON)", lambda ctx: ctx["reason_details"]),
        ("综合结论", lambda ctx: _pick_export_value(ctx["item"].summary_text, ctx["result"].get("summary_text"))),
    ]


def _mitigation_result_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    return [
        ("当前风险等级", lambda ctx: _format_export_risk_level(ctx["result"].get("current_risk_level"))),
        ("当前得分", lambda ctx: _pick_export_number(ctx["result"].get("current_score"))),
        ("预期风险等级", lambda ctx: _format_export_risk_level(_pick_export_value(ctx["result"].get("expected_risk_level"), ctx["item"].risk_level))),
        ("预期得分", lambda ctx: _pick_export_number(ctx["result"].get("expected_score"), ctx["result"].get("score"))),
        ("改造结论", lambda ctx: ctx["result"].get("recommendation_result")),
        ("推荐措施", lambda ctx: ctx["result"].get("mitigation_recommendation")),
        ("推荐动作", lambda ctx: _join_action_summaries(ctx["actions"])),
        ("保护角推荐值(°)", lambda ctx: _pick_export_number(_read_action_value(_read_export_action(ctx, "shielding_geometry"), "target_value"))),
        ("保护角原始值(°)", lambda ctx: _pick_export_number(ctx["inputs"].get("protection_angle_deg"))),
        ("绝缘子串长推荐值(mm)", lambda ctx: _pick_export_number(_read_action_value(_read_export_action(ctx, "insulator_upgrade"), "target_value"))),
        ("绝缘子串长原始值(mm)", lambda ctx: _pick_export_number(_read_action_value(_read_export_action(ctx, "insulator_upgrade"), "current_value"), ctx["inputs"].get("insulator_length_mm"))),
        ("接地电阻推荐值(Ω)", lambda ctx: _pick_export_number(_read_action_value(_read_export_action(ctx, "grounding_upgrade"), "target_value"))),
        ("接地电阻原始值(Ω)", lambda ctx: _pick_export_number(_read_action_value(_read_export_action(ctx, "grounding_upgrade"), "current_value"), ctx["inputs"].get("ground_resistance_ohm"), ctx["base"].get("ground_resistance_ohm"))),
        ("安装避雷器", lambda ctx: ctx["result"].get("recommendation_result")),
        ("避雷器推荐相别", lambda ctx: _read_action_phase_text(_read_export_action(ctx, "arrester_install"))),
        ("高风险原因", lambda ctx: ctx["result"].get("cause_analysis")),
        ("原因明细(JSON)", lambda ctx: ctx["reason_details"]),
        ("推荐动作明细(JSON)", lambda ctx: ctx["actions"]),
        ("综合结论", lambda ctx: _pick_export_value(ctx["item"].summary_text, ctx["result"].get("summary_text"))),
    ]


def _read_export_action(ctx: dict[str, Any], code: str) -> dict[str, Any] | None:
    return ctx["actions_by_code"].get(code)


def _read_action_value(action: dict[str, Any] | None, key: str) -> Any:
    if action is None:
        return None
    return action.get(key)


def _read_action_phase_text(action: dict[str, Any] | None) -> str | None:
    if action is None:
        return None
    phases = action.get("phases")
    if not isinstance(phases, list):
        return None
    values = [str(phase).strip() for phase in phases if str(phase).strip()]
    return ",".join(values) if values else None


def _join_action_summaries(actions: list[dict[str, Any]]) -> str | None:
    values = [str(action.get("summary") or "").strip() for action in actions if str(action.get("summary") or "").strip()]
    if not values:
        return None
    return "；".join(values)


def _format_export_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if isinstance(value, (dict, list)):
        return _json_dumps_compact(value)
    return str(value)


def _safe_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _json_dumps_compact(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _pick_export_value(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _pick_export_number(*values: Any) -> float | int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return value
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _format_export_risk_level(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized == "high":
        return "高风险"
    if normalized == "medium":
        return "中风险"
    if normalized == "low":
        return "低风险"
    return str(value)


def _read_report_generated_at(job: FlAnalysisJob) -> datetime | None:
    value = (job.result_summary_json or {}).get("generated_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_base_tower_json(tower: LineTower, line: Line | None) -> dict[str, Any]:
    return {
        "tower_id": tower.id,
        "line_id": tower.line_id,
        "line_name": line.name if line else None,
        "line_voltage_kv": line.voltage_kv if line else None,
        "line_phase_sequence_json": (line.phase_sequence_json or {}) if line else {},
        "line_arrester_install_json": (line.arrester_install_json or {}) if line else {},
        "line_lightning_param_json": (line.lightning_param_json or {}) if line else {},
        "seq_no": tower.seq_no,
        "tower_no": tower.tower_no,
        "tower_model": tower.tower_model,
        "tower_type": tower.tower_type,
        "longitude": tower.longitude,
        "latitude": tower.latitude,
        "altitude_m": tower.altitude_m,
        "terrain": tower.terrain,
        "ground_resistance_ohm": tower.ground_resistance_ohm,
        "lightning_density": tower.lightning_density,
        "span_small_m": tower.span_small_m,
        "span_large_m": tower.span_large_m,
        "slope_1": tower.slope_1,
        "slope_2": tower.slope_2,
        "risk_level": tower.risk_level,
        "circuit_geometry_json": tower.circuit_geometry_json or {},
        "lightning_result_json": tower.lightning_result_json or {},
        "raw_extra_json": tower.raw_extra_json or {},
    }


def _build_profile_json(profile: TowerProfile | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        "phase_sequence_1": profile.phase_sequence_1,
        "phase_sequence_2": profile.phase_sequence_2,
        "phase_sequence_3": profile.phase_sequence_3,
        "phase_sequence_4": profile.phase_sequence_4,
        "arrester_a": profile.arrester_a,
        "arrester_b": profile.arrester_b,
        "arrester_c": profile.arrester_c,
        "protection_angle_left_deg": profile.protection_angle_left_deg,
        "protection_angle_right_deg": profile.protection_angle_right_deg,
        "shield_wire_height_m": profile.shield_wire_height_m,
        "insulator_length_m": profile.insulator_length_m,
        "call_height_m": profile.call_height_m,
        "angle_deg": profile.angle_deg,
        "current_a": profile.current_a,
        "current_b": profile.current_b,
        "structure_kind": profile.structure_kind,
        "stroke_mode": profile.stroke_mode,
        "current_type": profile.current_type,
        "current_head_time_us": profile.current_head_time_us,
        "current_tail_time_us": profile.current_tail_time_us,
        "geometry_layers_json": profile.geometry_layers_json or {},
        "extra_profile_json": profile.extra_profile_json or {},
    }


def _grade_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return grade_snapshot_payload(payload)


def _new_result_summary() -> dict[str, Any]:
    return {
        "risk_counts": {"high": 0, "medium": 0, "low": 0},
        "baseline_risk_counts": {"high": 0, "medium": 0, "low": 0},
        "score_total": 0,
        "score_average": 0,
        "arrester_required_count": 0,
        "action_total": 0,
        "scan_point_total": 0,
        "scan_point_average": 0,
    }


def _accumulate_result_summary(summary: dict[str, Any], graded: dict[str, Any]) -> None:
    risk_counts = summary.setdefault("risk_counts", {"high": 0, "medium": 0, "low": 0})
    risk_level = str(graded.get("risk_level") or "low")
    risk_counts[risk_level] = int(risk_counts.get(risk_level, 0)) + 1
    current_risk_level = str(graded.get("current_risk_level") or "")
    if current_risk_level:
        baseline_counts = summary.setdefault("baseline_risk_counts", {"high": 0, "medium": 0, "low": 0})
        baseline_counts[current_risk_level] = int(baseline_counts.get(current_risk_level, 0)) + 1

    score = int(graded.get("score") or 0)
    summary["score_total"] = int(summary.get("score_total", 0)) + score
    total_count = sum(int(value) for value in risk_counts.values())
    summary["score_average"] = round(summary["score_total"] / total_count, 2) if total_count else 0
    summary["action_total"] = int(summary.get("action_total", 0)) + len(graded.get("mitigation_actions") or [])
    if graded.get("recommendation_result") == "需要安装避雷器":
        summary["arrester_required_count"] = int(summary.get("arrester_required_count", 0)) + 1
    workflow = graded.get("workflow") or {}
    scan_point_count = _as_int((workflow or {}).get("scan_point_count")) or 0
    if scan_point_count > 0:
        summary["scan_point_total"] = int(summary.get("scan_point_total", 0)) + scan_point_count
        summary["scan_point_average"] = round(summary["scan_point_total"] / total_count, 2) if total_count else 0


def _normalize_execution_options(job_type: str, execution_options: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(execution_options or {})
    selected_ids = normalized.get("selected_tower_ids") or normalized.get("tower_ids") or []
    if isinstance(selected_ids, list):
        normalized["selected_tower_ids"] = list(dict.fromkeys(str(item).strip() for item in selected_ids if str(item).strip()))
    else:
        normalized["selected_tower_ids"] = []
    source_job_id = str(normalized.get("source_job_id") or "").strip()
    if source_job_id:
        normalized["source_job_id"] = source_job_id
    else:
        normalized.pop("source_job_id", None)
    source_run_id = str(normalized.get("source_run_id") or "").strip()
    if source_run_id:
        normalized["source_run_id"] = source_run_id
    else:
        normalized.pop("source_run_id", None)
    mitigation_job_id = str(normalized.get("mitigation_job_id") or "").strip()
    if mitigation_job_id:
        normalized["mitigation_job_id"] = mitigation_job_id
    else:
        normalized.pop("mitigation_job_id", None)
    mitigation_run_id = str(normalized.get("mitigation_run_id") or "").strip()
    if mitigation_run_id:
        normalized["mitigation_run_id"] = mitigation_run_id
    else:
        normalized.pop("mitigation_run_id", None)
    risk_job_id = str(normalized.get("risk_job_id") or "").strip()
    if risk_job_id:
        normalized["risk_job_id"] = risk_job_id
    else:
        normalized.pop("risk_job_id", None)
    risk_run_id = str(normalized.get("risk_run_id") or "").strip()
    if risk_run_id:
        normalized["risk_run_id"] = risk_run_id
    else:
        normalized.pop("risk_run_id", None)
    scenario_job_id = str(normalized.get("scenario_job_id") or "").strip()
    if scenario_job_id:
        normalized["scenario_job_id"] = scenario_job_id
    else:
        normalized.pop("scenario_job_id", None)
    scenario_run_id = str(normalized.get("scenario_run_id") or "").strip()
    if scenario_run_id:
        normalized["scenario_run_id"] = scenario_run_id
    else:
        normalized.pop("scenario_run_id", None)
    base_job_id = str(normalized.get("base_job_id") or "").strip()
    if base_job_id:
        normalized["base_job_id"] = base_job_id
    else:
        normalized.pop("base_job_id", None)
    base_run_id = str(normalized.get("base_run_id") or "").strip()
    if base_run_id:
        normalized["base_run_id"] = base_run_id
    else:
        normalized.pop("base_run_id", None)
    base_job_type = str(normalized.get("base_job_type") or "").strip()
    if base_job_type:
        normalized["base_job_type"] = base_job_type
    else:
        normalized.pop("base_job_type", None)
    for text_key in ("base_job_name", "mitigation_job_name", "risk_job_name"):
        text_value = str(normalized.get(text_key) or "").strip()
        if text_value:
            normalized[text_key] = text_value
        else:
            normalized.pop(text_key, None)
    source_job_type = str(normalized.get("source_job_type") or "").strip()
    if source_job_type:
        normalized["source_job_type"] = source_job_type
    else:
        normalized.pop("source_job_type", None)
    normalized["non_construction"] = bool(
        normalized.get("non_construction")
        or normalized.get("mitigation_mode") == "non_construction"
    )
    if job_type == "mitigation":
        normalized.pop("current_waveform", None)
        normalized.pop("flashover_method", None)
        normalized.pop("altitude_correction", None)
        normalized.pop("induced_voltage_formula", None)
        normalized.pop("head_time_min_us", None)
        normalized.pop("head_time_max_us", None)
        normalized.pop("head_time_step_us", None)
        normalized.pop("tail_time_min_us", None)
        normalized.pop("tail_time_max_us", None)
        normalized.pop("tail_time_step_us", None)
        normalized.pop("mitigation_job_id", None)
        normalized.pop("mitigation_run_id", None)
        normalized.pop("risk_job_id", None)
        normalized.pop("risk_run_id", None)
        normalized.pop("scenario_job_id", None)
        normalized.pop("scenario_run_id", None)
        normalized.pop("base_job_id", None)
        normalized.pop("base_run_id", None)
        normalized.pop("base_job_type", None)
        normalized.pop("base_job_name", None)
        normalized.pop("mitigation_job_name", None)
        normalized.pop("risk_job_name", None)
        normalized.pop("source_job_type", None)
    elif job_type == "report":
        normalized.pop("current_waveform", None)
        normalized.pop("flashover_method", None)
        normalized.pop("altitude_correction", None)
        normalized.pop("induced_voltage_formula", None)
        normalized.pop("head_time_min_us", None)
        normalized.pop("head_time_max_us", None)
        normalized.pop("head_time_step_us", None)
        normalized.pop("tail_time_min_us", None)
        normalized.pop("tail_time_max_us", None)
        normalized.pop("tail_time_step_us", None)
        normalized.pop("non_construction", None)
        normalized.pop("base_job_id", None)
        normalized.pop("base_run_id", None)
        normalized.pop("base_job_type", None)
        normalized.pop("base_job_name", None)
        normalized.pop("mitigation_job_name", None)
        normalized.pop("risk_job_name", None)
    elif job_type == "scenario":
        normalized["current_waveform"] = _normalize_choice(
            normalized.get("current_waveform") or normalized.get("current_type"),
            allowed={"heidler", "double_slope", "double_exponential"},
            aliases={
                "Heidler": "heidler",
                "双斜角": "double_slope",
                "双指数": "double_exponential",
            },
            default="heidler",
        )
        normalized["flashover_method"] = _normalize_choice(
            normalized.get("flashover_method"),
            allowed={"guideline", "intersection", "leader_development"},
            aliases={
                "规程法": "guideline",
                "相交法": "intersection",
                "先导发展法": "leader_development",
            },
            default="intersection",
        )
        normalized["altitude_correction"] = _normalize_choice(
            normalized.get("altitude_correction"),
            allowed={"none", "formula1", "formula2"},
            aliases={
                "无": "none",
                "推荐公式1": "formula1",
                "推荐公式2": "formula2",
            },
            default="none",
        )
        normalized["induced_voltage_formula"] = _normalize_choice(
            normalized.get("induced_voltage_formula"),
            allowed={"formula1", "formula2"},
            aliases={
                "公式1": "formula1",
                "公式2": "formula2",
            },
            default="formula1",
        )
        normalized["head_time_min_us"] = _normalize_positive_number(normalized.get("head_time_min_us"), default=2.6)
        normalized["head_time_max_us"] = _normalize_positive_number(normalized.get("head_time_max_us"), default=2.6)
        normalized["head_time_step_us"] = _normalize_positive_number(normalized.get("head_time_step_us"), default=0.1)
        normalized["tail_time_min_us"] = _normalize_positive_number(normalized.get("tail_time_min_us"), default=50.0)
        normalized["tail_time_max_us"] = _normalize_positive_number(normalized.get("tail_time_max_us"), default=50.0)
        normalized["tail_time_step_us"] = _normalize_positive_number(normalized.get("tail_time_step_us"), default=1.0)
        normalized.pop("scenario_job_id", None)
        normalized.pop("scenario_run_id", None)
        normalized.pop("non_construction", None)
    elif job_type in {"normal", "tongtiao"}:
        normalized["current_waveform"] = _normalize_choice(
            normalized.get("current_waveform") or normalized.get("current_type"),
            allowed={"heidler", "double_slope", "double_exponential"},
            aliases={
                "Heidler": "heidler",
                "双斜角": "double_slope",
                "双指数": "double_exponential",
            },
            default="heidler",
        )
        normalized["flashover_method"] = _normalize_choice(
            normalized.get("flashover_method"),
            allowed={"guideline", "intersection", "leader_development"},
            aliases={
                "规程法": "guideline",
                "相交法": "intersection",
                "先导发展法": "leader_development",
            },
            default="intersection",
        )
        normalized["altitude_correction"] = _normalize_choice(
            normalized.get("altitude_correction"),
            allowed={"none", "formula1", "formula2"},
            aliases={
                "无": "none",
                "推荐公式1": "formula1",
                "推荐公式2": "formula2",
            },
            default="none",
        )
        normalized["induced_voltage_formula"] = _normalize_choice(
            normalized.get("induced_voltage_formula"),
            allowed={"formula1", "formula2"},
            aliases={
                "公式1": "formula1",
                "公式2": "formula2",
            },
            default="formula1",
        )
        normalized["head_time_min_us"] = _normalize_positive_number(normalized.get("head_time_min_us"), default=2.6)
        normalized["head_time_max_us"] = _normalize_positive_number(normalized.get("head_time_max_us"), default=2.6)
        normalized["head_time_step_us"] = _normalize_positive_number(normalized.get("head_time_step_us"), default=0.1)
        normalized["tail_time_min_us"] = _normalize_positive_number(normalized.get("tail_time_min_us"), default=50.0)
        normalized["tail_time_max_us"] = _normalize_positive_number(normalized.get("tail_time_max_us"), default=50.0)
        normalized["tail_time_step_us"] = _normalize_positive_number(normalized.get("tail_time_step_us"), default=1.0)
        normalized.pop("selected_tower_ids", None)
        normalized.pop("source_job_id", None)
        normalized.pop("source_run_id", None)
        normalized.pop("mitigation_job_id", None)
        normalized.pop("mitigation_run_id", None)
        normalized.pop("risk_job_id", None)
        normalized.pop("risk_run_id", None)
        normalized.pop("scenario_job_id", None)
        normalized.pop("scenario_run_id", None)
        normalized.pop("base_job_id", None)
        normalized.pop("base_run_id", None)
        normalized.pop("base_job_type", None)
        normalized.pop("base_job_name", None)
        normalized.pop("mitigation_job_name", None)
        normalized.pop("risk_job_name", None)
        normalized.pop("source_job_type", None)
        normalized.pop("non_construction", None)
    else:
        normalized.pop("current_waveform", None)
        normalized.pop("flashover_method", None)
        normalized.pop("altitude_correction", None)
        normalized.pop("induced_voltage_formula", None)
        normalized.pop("head_time_min_us", None)
        normalized.pop("head_time_max_us", None)
        normalized.pop("head_time_step_us", None)
        normalized.pop("tail_time_min_us", None)
        normalized.pop("tail_time_max_us", None)
        normalized.pop("tail_time_step_us", None)
        normalized.pop("selected_tower_ids", None)
        normalized.pop("source_job_id", None)
        normalized.pop("source_run_id", None)
        normalized.pop("mitigation_job_id", None)
        normalized.pop("mitigation_run_id", None)
        normalized.pop("risk_job_id", None)
        normalized.pop("risk_run_id", None)
        normalized.pop("scenario_job_id", None)
        normalized.pop("scenario_run_id", None)
        normalized.pop("base_job_id", None)
        normalized.pop("base_run_id", None)
        normalized.pop("base_job_type", None)
        normalized.pop("base_job_name", None)
        normalized.pop("mitigation_job_name", None)
        normalized.pop("risk_job_name", None)
        normalized.pop("source_job_type", None)
        normalized.pop("non_construction", None)
    return normalized


def _validate_mitigation_options(db: Session, *, line_id: str, execution_options: dict[str, Any]) -> int:
    source_job_id = str(execution_options.get("source_job_id") or "")
    if not source_job_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="措施推荐任务缺少前驱风险任务")
    selected_tower_ids = execution_options.get("selected_tower_ids") or []
    if not selected_tower_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="措施推荐任务至少需要选择一座高风险杆塔")

    source_job = get_job_by_id(db, source_job_id)
    if not source_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="前驱风险任务不存在")
    if source_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱风险任务与当前线路不匹配")
    if source_job.job_type != "risk":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱任务必须为风险评估任务")
    if source_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱风险任务尚未成功完成")

    source_run_id = _resolve_source_run_id(source_job)
    if not source_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱风险任务缺少可复用结果")
    allowed_tower_ids = _load_result_tower_ids(db, job_id=source_job.id, run_id=source_run_id)
    if not allowed_tower_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱风险任务暂无可复用杆塔结果")
    invalid_ids = [tower_id for tower_id in selected_tower_ids if tower_id not in allowed_tower_ids]
    if invalid_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="措施推荐任务包含无效的杆塔选择")
    execution_options["source_run_id"] = source_run_id
    return len(selected_tower_ids)


def _validate_report_options(db: Session, *, line_id: str, execution_options: dict[str, Any]) -> int:
    source_job_id = str(execution_options.get("source_job_id") or "")
    if not source_job_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告任务缺少来源任务")
    selected_tower_ids = execution_options.get("selected_tower_ids") or []
    if not selected_tower_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告任务至少需要选择一座杆塔")

    source_job = get_job_by_id(db, source_job_id)
    if not source_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报告来源任务不存在")
    if source_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告来源任务与当前线路不匹配")
    if source_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告来源任务尚未成功完成")
    if source_job.job_type not in {"risk", "mitigation"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅风险评估或措施推荐任务可生成报告")

    source_run_id = _resolve_source_run_id(source_job)
    if not source_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告来源任务缺少可复用结果")

    execution_options["source_job_id"] = source_job.id
    execution_options["source_job_type"] = source_job.job_type
    execution_options["source_run_id"] = source_run_id

    if source_job.job_type == "risk":
        risk_job = source_job
        mitigation_job = None
        provided_mitigation_job_id = str(execution_options.get("mitigation_job_id") or "")
        if provided_mitigation_job_id:
            mitigation_job = _validate_report_mitigation_job(
                db,
                line_id=line_id,
                risk_job_id=risk_job.id,
                mitigation_job_id=provided_mitigation_job_id,
            )
        else:
            mitigation_job = _find_latest_success_mitigation_job(db, line_id=line_id, source_job_id=risk_job.id)

        execution_options["risk_job_id"] = risk_job.id
        execution_options["risk_run_id"] = source_run_id
        allowed_tower_ids = _load_report_candidate_tower_ids(
            db,
            job_id=risk_job.id,
            run_id=source_run_id,
            exclude_low_risk=True,
        )
        if mitigation_job is not None:
            mitigation_run_id = _resolve_source_run_id(mitigation_job)
            if not mitigation_run_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联措施任务缺少可复用结果")
            execution_options["mitigation_job_id"] = mitigation_job.id
            execution_options["mitigation_run_id"] = mitigation_run_id
        else:
            execution_options.pop("mitigation_job_id", None)
            execution_options.pop("mitigation_run_id", None)
        scenario_job = (
            _find_latest_success_scenario_job(db, line_id=line_id, mitigation_job_id=mitigation_job.id)
            if mitigation_job is not None
            else None
        )
    else:
        mitigation_job = source_job
        risk_job_id = str((mitigation_job.execution_options_json or {}).get("source_job_id") or "")
        if not risk_job_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="措施推荐任务缺少关联风险任务，无法生成报告")
        risk_job = get_job_by_id(db, risk_job_id)
        if not risk_job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联风险任务不存在")
        if risk_job.line_id != line_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务与当前线路不匹配")
        if risk_job.job_type != "risk" or risk_job.status != "success":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务尚未成功完成")

        risk_run_id = _resolve_source_run_id(risk_job)
        if not risk_run_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务缺少可复用结果")

        execution_options["risk_job_id"] = risk_job.id
        execution_options["risk_run_id"] = risk_run_id
        execution_options["mitigation_job_id"] = mitigation_job.id
        execution_options["mitigation_run_id"] = source_run_id
        allowed_tower_ids = _load_report_candidate_tower_ids(
            db,
            job_id=mitigation_job.id,
            run_id=source_run_id,
            exclude_low_risk=False,
        )
        scenario_job = _find_latest_success_scenario_job(db, line_id=line_id, mitigation_job_id=mitigation_job.id)

    if not allowed_tower_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="报告来源任务暂无可复用杆塔结果")

    if scenario_job is not None:
        scenario_run_id = _resolve_source_run_id(scenario_job)
        if not scenario_run_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联复算任务缺少可复用结果")
        execution_options["scenario_job_id"] = scenario_job.id
        execution_options["scenario_run_id"] = scenario_run_id
    else:
        execution_options.pop("scenario_job_id", None)
        execution_options.pop("scenario_run_id", None)

    invalid_ids = [tower_id for tower_id in selected_tower_ids if tower_id not in allowed_tower_ids]
    if invalid_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="报告任务包含无效的杆塔选择")
    return len(selected_tower_ids)


def _validate_report_mitigation_job(
    db: Session,
    *,
    line_id: str,
    risk_job_id: str,
    mitigation_job_id: str,
) -> FlAnalysisJob:
    mitigation_job = get_job_by_id(db, mitigation_job_id)
    if not mitigation_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联措施任务不存在")
    if mitigation_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联措施任务与当前线路不匹配")
    if mitigation_job.job_type != "mitigation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅措施推荐任务可作为报告关联任务")
    if mitigation_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联措施任务尚未成功完成")
    source_job_id = str((mitigation_job.execution_options_json or {}).get("source_job_id") or "")
    if source_job_id != risk_job_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联措施任务不属于当前风险评估任务")
    return mitigation_job


def _find_latest_success_mitigation_job(db: Session, *, line_id: str, source_job_id: str) -> FlAnalysisJob | None:
    rows = db.execute(
        select(FlAnalysisJob)
        .where(
            FlAnalysisJob.line_id == line_id,
            FlAnalysisJob.job_type == "mitigation",
            FlAnalysisJob.status == "success",
        )
        .order_by(FlAnalysisJob.update_date.desc(), FlAnalysisJob.id.desc())
    ).scalars().all()
    for item in rows:
        if str((item.execution_options_json or {}).get("source_job_id") or "") == source_job_id:
            return item
    return None


def _find_latest_success_scenario_job(db: Session, *, line_id: str, mitigation_job_id: str) -> FlAnalysisJob | None:
    rows = db.execute(
        select(FlAnalysisJob)
        .where(
            FlAnalysisJob.line_id == line_id,
            FlAnalysisJob.job_type == "scenario",
            FlAnalysisJob.status == "success",
        )
        .order_by(FlAnalysisJob.update_date.desc(), FlAnalysisJob.id.desc())
    ).scalars().all()
    for item in rows:
        if str((item.execution_options_json or {}).get("mitigation_job_id") or "") == mitigation_job_id:
            return item
    return None


def _load_job_towers(db: Session, *, job: FlAnalysisJob, execution_options: dict[str, Any]) -> list[LineTower]:
    towers = db.execute(
        select(LineTower).where(LineTower.line_id == job.line_id).order_by(LineTower.seq_no.asc())
    ).scalars().all()
    if job.job_type not in {"mitigation", "report", "scenario"}:
        return towers
    selected_ids = set(execution_options.get("selected_tower_ids") or [])
    scoped_towers = [tower for tower in towers if tower.id in selected_ids]
    if len(scoped_towers) != len(selected_ids):
        detail = "措施推荐任务的杆塔范围已失效，请重新生成任务"
        if job.job_type == "report":
            detail = "报告任务的杆塔范围已失效，请重新生成任务"
        elif job.job_type == "scenario":
            detail = "加装避雷器复算任务的杆塔范围已失效，请重新生成任务"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    return scoped_towers


def _validate_scenario_options(db: Session, *, line_id: str, execution_options: dict[str, Any]) -> dict[str, Any]:
    mitigation_job_id = str(execution_options.get("source_job_id") or "")
    if not mitigation_job_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="加装避雷器复算任务缺少前驱措施任务")
    selected_tower_ids = execution_options.get("selected_tower_ids") or []
    if not selected_tower_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="加装避雷器复算任务至少需要选择一座杆塔")
    base_job_id = str(execution_options.get("base_job_id") or "")
    if not base_job_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="加装避雷器复算任务缺少复用的计算任务")

    mitigation_job = get_job_by_id(db, mitigation_job_id)
    if not mitigation_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="前驱措施任务不存在")
    if mitigation_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱措施任务与当前线路不匹配")
    if mitigation_job.job_type != "mitigation":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱任务必须为措施推荐任务")
    if mitigation_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱措施任务尚未成功完成")
    mitigation_run_id = _resolve_source_run_id(mitigation_job)
    if not mitigation_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱措施任务缺少可复用结果")
    allowed_tower_ids = _load_report_candidate_tower_ids(
        db,
        job_id=mitigation_job.id,
        run_id=mitigation_run_id,
        exclude_low_risk=True,
    )
    if not allowed_tower_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱措施任务没有可复算的中高风险杆塔")
    invalid_ids = [tower_id for tower_id in selected_tower_ids if tower_id not in allowed_tower_ids]
    if invalid_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="加装避雷器复算任务包含无效的杆塔选择")

    risk_job_id = str((mitigation_job.execution_options_json or {}).get("source_job_id") or "")
    if not risk_job_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱措施任务缺少关联风险任务")
    risk_job = get_job_by_id(db, risk_job_id)
    if not risk_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="关联风险任务不存在")
    if risk_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务与当前线路不匹配")
    if risk_job.job_type != "risk" or risk_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务尚未成功完成")
    risk_run_id = _resolve_source_run_id(risk_job)
    if not risk_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="关联风险任务缺少可复用结果")

    base_job = get_job_by_id(db, base_job_id)
    if not base_job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="复用计算任务不存在")
    if base_job.line_id != line_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="复用计算任务与当前线路不匹配")
    if base_job.job_type not in {"normal", "tongtiao"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="仅普通计算或同跳计算任务可作为复算基线")
    if base_job.status != "success":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="复用计算任务尚未成功完成")
    base_run_id = _resolve_source_run_id(base_job)
    if not base_run_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="复用计算任务缺少可复用结果")
    base_tower_ids = _load_result_tower_ids(db, job_id=base_job.id, run_id=base_run_id)
    missing_from_base = [tower_id for tower_id in selected_tower_ids if tower_id not in base_tower_ids]
    if missing_from_base:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="复算杆塔不在所选基线计算结果中")

    scenario_options = _normalize_execution_options(base_job.job_type, base_job.execution_options_json or {})
    scenario_options.update(
        {
            "selected_tower_ids": list(selected_tower_ids),
            "source_job_id": mitigation_job.id,
            "source_run_id": mitigation_run_id,
            "source_job_type": mitigation_job.job_type,
            "mitigation_job_id": mitigation_job.id,
            "mitigation_job_name": mitigation_job.job_name,
            "mitigation_run_id": mitigation_run_id,
            "risk_job_id": risk_job.id,
            "risk_job_name": risk_job.job_name,
            "risk_run_id": risk_run_id,
            "base_job_id": base_job.id,
            "base_job_name": base_job.job_name,
            "base_job_type": base_job.job_type,
            "base_run_id": base_run_id,
        }
    )
    return {
        "total_tower_count": len(selected_tower_ids),
        "execution_options": scenario_options,
        "external_adapter": base_job.external_adapter or "placeholder",
        "adapter_config_json": base_job.adapter_config_json or {},
    }


def _load_source_result_map(db: Session, *, execution_options: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source_job_id = str(execution_options.get("source_job_id") or "")
    source_run_id = str(execution_options.get("source_run_id") or "")
    if not source_job_id or not source_run_id:
        return {}
    rows = db.execute(
        select(FlAnalysisTowerResult)
        .where(FlAnalysisTowerResult.job_id == source_job_id, FlAnalysisTowerResult.run_id == source_run_id)
    ).scalars().all()
    result: dict[str, dict[str, Any]] = {}
    for item in rows:
        if item.snapshot and item.snapshot.tower_id:
            result[item.snapshot.tower_id] = item.result_json or {}
    return result


def _load_result_tower_ids(db: Session, *, job_id: str, run_id: str) -> set[str]:
    rows = db.execute(
        select(FlAnalysisTowerSnapshot.tower_id).where(
            FlAnalysisTowerSnapshot.job_id == job_id,
            FlAnalysisTowerSnapshot.run_id == run_id,
        )
    ).scalars().all()
    return {str(item) for item in rows if item}


def _load_report_candidate_tower_ids(
    db: Session,
    *,
    job_id: str,
    run_id: str,
    exclude_low_risk: bool,
) -> set[str]:
    rows = _load_result_rows(db, job_id=job_id, run_id=run_id)
    tower_ids: set[str] = set()
    for item in rows:
        if item.snapshot is None or not item.snapshot.tower_id:
            continue
        if exclude_low_risk and item.risk_level == "low":
            continue
        tower_ids.add(str(item.snapshot.tower_id))
    return tower_ids


def _resolve_waveform_job_type(*, job_type: str, execution_options: dict[str, Any]) -> str:
    if job_type == "scenario":
        base_job_type = str(execution_options.get("base_job_type") or "").strip()
        if base_job_type in {"normal", "tongtiao"}:
            return base_job_type
    return job_type


def _apply_scenario_profile_json_overrides(profile_json: dict[str, Any]) -> dict[str, Any]:
    profile = dict(profile_json or {})
    profile["arrester_a"] = "是"
    profile["arrester_b"] = "是"
    profile["arrester_c"] = "是"
    return profile


def _resolve_source_run_id(job: FlAnalysisJob) -> str | None:
    if job.latest_run_id:
        return job.latest_run_id
    if job.runs:
        return job.runs[0].id
    return None


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _placeholder_message_for_adapter(adapter: str) -> str:
    if adapter == "wine":
        return "Wine 外部程序适配器已预留，真实执行链路尚未接入"
    if adapter == "atp":
        return "ATP 适配器已预留，真实执行链路尚未接入"
    if adapter == "custom":
        return "自定义外部程序适配器已预留，真实执行链路尚未接入"
    return "外部分析适配器尚未接入，当前仅完成任务骨架与快照链路"


def _workflow_summary_from_execution_options(execution_options: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_waveform": execution_options.get("current_waveform"),
        "flashover_method": execution_options.get("flashover_method"),
        "altitude_correction": execution_options.get("altitude_correction"),
        "induced_voltage_formula": execution_options.get("induced_voltage_formula"),
        "head_time_range_us": {
            "min": execution_options.get("head_time_min_us"),
            "max": execution_options.get("head_time_max_us"),
            "step": execution_options.get("head_time_step_us"),
        },
        "tail_time_range_us": {
            "min": execution_options.get("tail_time_min_us"),
            "max": execution_options.get("tail_time_max_us"),
            "step": execution_options.get("tail_time_step_us"),
        },
    }


def _normalize_choice(
    value: Any,
    *,
    allowed: set[str],
    aliases: dict[str, str],
    default: str,
) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    normalized = aliases.get(text, aliases.get(text.lower(), text.lower()))
    return normalized if normalized in allowed else default


def _normalize_positive_number(value: Any, *, default: float) -> float:
    parsed = _as_float(value)
    if parsed is None or parsed <= 0:
        return default
    return round(parsed, 4)


def _publish_change(event_name: str, payload: dict[str, Any]) -> None:
    _fire_and_forget(
        publish_topic(
            FL_ANALYSIS_TOPIC,
            name=event_name,
            payload=payload,
            requires_refetch=[],
            dedupe_key=f"fl-analysis:{event_name}:{payload.get('job_id', '-')}:"
            f"{payload.get('run_id', payload.get('line_id', '-'))}",
        )
    )


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)
