from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import shutil
import time
from contextlib import closing
from pathlib import Path
from collections.abc import Callable
from datetime import datetime
from typing import Any, Mapping

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, noload, selectinload

logger = logging.getLogger(__name__)

from ..core.config import get_settings
from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.fl_analysis import FlAnalysisJob, FlAnalysisRun, FlAnalysisTowerResult, FlAnalysisTowerSnapshot
from ..models.line import Line
from ..models.line_tower import LineTower
from .audit_service import compose_audit_detail, write_audit_log
from ..models.tower_analysis import TowerAnalysis
from ..models.tower_circuit import TowerCircuit
from ..models.tower_lightning_result import TowerLightningResult
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
from .fl_analysis_external import ResolvedExternalWaveformJob, execute_binary_search_external, execute_external_waveform_tower_analysis, execute_multi_phase_binary_search_external, execute_shielding_binary_search_external, resolve_external_waveform_job
from .legacy_atp_adapter import ResolvedLegacyAtpJob, _normalize_tower_shape_code, execute_legacy_atp_tower_analysis, resolve_legacy_atp_job
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


class _TowerProgressTracker:
    """单根杆塔内部子步骤进度追踪（方案 C · 进度细分到塔内）。

    每根塔 = 若干「命名阶段」（基准计算 / 单相二分 / 双相二分 / … / 绕击二分 / 回填），
    每阶段带权重；二分搜索阶段的完成比例按 iteration/max_iterations 折算。
    对外只暴露一个随阶段推进单调递增的 0~1 fractional_progress，
    供 execute_job 实时写库 + 推 WS 事件，前端据此把进度条细分到单塔内部。
    注意二分收敛次数不定，该比例是「加权估计」而非精确步数，但单调且能反映真实推进。
    """

    def __init__(self, phase_weights: list[tuple[str, float]]) -> None:
        # phase_weights: [(label, weight), ...]，权重代表该阶段的相对耗时
        self._labels = [label for label, _w in phase_weights]
        self._weights = [max(w, 0.0) for _l, w in phase_weights]
        self._total = sum(self._weights) or 1.0
        self._cum = 0.0  # 已结束阶段的权重和
        self._phase_idx = 0
        self._phase_done = 0  # 当前阶段已完成的"步数"（如二分迭代次数）
        self._phase_total = 1  # 当前阶段估计总步数

    @property
    def phase_label(self) -> str:
        if self._phase_idx < len(self._labels):
            return self._labels[self._phase_idx]
        return self._labels[-1] if self._labels else ""

    def mark_phase_done(self) -> None:
        """当前阶段结束，权重累计，进入下一阶段。"""
        if self._phase_idx < len(self._weights):
            self._cum += self._weights[self._phase_idx]
        self._phase_idx += 1
        self._phase_done = 0
        self._phase_total = 1

    def report_phase_step(self, done: int, total: int, label: str | None = None) -> float:
        """当前阶段进行中上报一步（二分迭代）。返回整体 fractional_progress（0~1）。"""
        self._phase_done = max(0, done)
        if total > 0:
            self._phase_total = total
        frac = self._fraction()
        # 阶段标签可被外部覆盖（如精确的「二分搜索 第N相」）
        return max(0.0, min(1.0, frac))

    def _fraction(self) -> float:
        if self._phase_idx >= len(self._weights):
            return 1.0
        done_w = self._cum
        cur_w = self._weights[self._phase_idx]
        cur_frac = min(1.0, self._phase_done / max(1, self._phase_total))
        return min(1.0, (done_w + cur_w * cur_frac) / self._total)


def _build_tower_phase_plan(
    *,
    job_type: str,
    waveform_job_type: str,
    has_external: bool,
    has_shielding: bool,
    max_phases: int = 3,
) -> list[tuple[str, float]]:
    """按任务类型/执行路径生成一根塔内部阶段的(标签, 权重)计划。

    权重为相对耗时估计：基准计算轻(1)、单相二分中(6)、绕击二分另算(6)、回填轻(1)。
    同跳多相按 max_phases 个二分阶段展开（单回=3，双回修好后=6）。
    """
    if job_type in {"mitigation", "scenario"}:
        return [("基准计算", 1.0), ("结果回填", 0.5)]
    plan: list[tuple[str, float]] = [("收集输入/基准计算", 1.0)]
    if waveform_job_type == "normal":
        if has_external:
            plan.append(("单相反击二分", 6.0))
        if has_shielding:
            plan.append(("绕击二分", 6.0))
    elif waveform_job_type == "tongtiao":
        if has_external:
            phase_labels = ["单相", "双相", "三相", "四相", "五相", "六相"]
            for i in range(max_phases):
                plan.append((f"{phase_labels[i]}相反击二分", 6.0))
        if has_shielding:
            plan.append(("绕击二分", 6.0))
    else:
        plan.append(("综合判定", 4.0))
    plan.append(("结果回填落库", 0.5))
    return plan


def _auto_scene_type_for_options(execution_options: dict[str, Any]) -> str:
    """根据任务方法选项推断 ATP 资产场景（fanji=反击 / raoji1=绕击）。

    normal/tongtiao 普通计算主场景是反击（fanji）；当绕击方法选了 atp 而反击是
    guicheng 时，自动选资产以绕击场景为主（raoji1）。实际执行时反击与绕击各自
    独立二分（shielding_asset_id 分流），这里只决定任务级默认资产。
    """
    fanji = str(execution_options.get("fanji_naleishuiping_method") or "").strip().lower()
    raoji = str(execution_options.get("raoji_naleishuiping_method") or "").strip().lower()
    if raoji == "atp" and fanji != "atp":
        return "raoji1"
    return "fanji"


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


def job_live_counts(db: Session, job_ids: list[str]) -> dict[str, dict[str, int]]:
    """从表实时统计任务的快照数/结果数（运行期间 job.result_tower_count 收尾才写，恒 0）。

    多塔并行（0d0f1a4）后塔 worker 不写共享 job 行，result_tower_count 由 execute_job
    收尾统一写 → 运行中列表/详情显示 0。这里改为查询时按
    fl_analysis_tower_snapshot / fl_analysis_tower_result 表实时 count。
    """
    counts: dict[str, dict[str, int]] = {}
    if not job_ids:
        return counts
    counts = {jid: {"snapshotted": 0, "result": 0} for jid in job_ids}
    for jid, c in db.execute(
        select(FlAnalysisTowerSnapshot.job_id, func.count())
        .where(FlAnalysisTowerSnapshot.job_id.in_(job_ids))
        .group_by(FlAnalysisTowerSnapshot.job_id)
    ).all():
        counts[jid]["snapshotted"] = int(c)
    for jid, c in db.execute(
        select(FlAnalysisTowerResult.job_id, func.count())
        .where(FlAnalysisTowerResult.job_id.in_(job_ids))
        .group_by(FlAnalysisTowerResult.job_id)
    ).all():
        counts[jid]["result"] = int(c)
    return counts


def serialize_job(
    item: FlAnalysisJob,
    *,
    include_runs: bool = False,
    live_counts: dict[str, dict[str, int]] | None = None,
) -> FlAnalysisJobDetail | FlAnalysisJobSummary:
    line = item.line
    _live = (live_counts or {}).get(item.id) if live_counts else None
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
        "snapshotted_tower_count": _live["snapshotted"] if _live else item.snapshotted_tower_count,
        "result_tower_count": _live["result"] if _live else item.result_tower_count,
        "fractional_progress": item.fractional_progress,
        "current_step_text": item.current_step_text,
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


def delete_job(db: Session, *, job_id: str, actor: User) -> None:
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    if job.status in {"queued", "running"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已在排队或执行中，无法删除")
    db.execute(delete(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job.id))
    db.execute(delete(FlAnalysisTowerSnapshot).where(FlAnalysisTowerSnapshot.job_id == job.id))
    db.execute(delete(FlAnalysisRun).where(FlAnalysisRun.job_id == job.id))
    db.delete(job)
    write_audit_log(
        db,
        action="fl_analysis.job.delete",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"job_id={job.id}",
            f"job_name={job.job_name or '-'}",
            f"line_id={job.line_id or '-'}",
            f"job_type={job.job_type or '-'}",
        ),
    )
    db.commit()

    _publish_change(
        "fl_analysis.job.deleted",
        {"action": "job_deleted", "job_id": job_id, "line_id": job.line_id},
    )


def get_job_by_id(db: Session, job_id: str) -> FlAnalysisJob | None:
    return db.execute(select(FlAnalysisJob).where(FlAnalysisJob.id == job_id)).scalar_one_or_none()


def list_jobs(
    db: Session,
    *,
    line_id: str | None,
    status_filter: str | None,
    job_types: list[str] | None = None,
    owner_id: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> FlAnalysisJobListResponse:
    stmt = select(FlAnalysisJob)
    total_stmt = select(func.count()).select_from(FlAnalysisJob)

    if line_id:
        stmt = stmt.where(FlAnalysisJob.line_id == line_id)
        total_stmt = total_stmt.where(FlAnalysisJob.line_id == line_id)
    if status_filter:
        stmt = stmt.where(FlAnalysisJob.status == status_filter)
        total_stmt = total_stmt.where(FlAnalysisJob.status == status_filter)
    # 2026-09-30：用户级数据隔离——owner_id 非空时只列该用户提交的任务
    # （admin 在 API 层传 None=全量；普通用户传自己 → 只看自己提交的）
    if owner_id:
        stmt = stmt.where(FlAnalysisJob.create_user == owner_id)
        total_stmt = total_stmt.where(FlAnalysisJob.create_user == owner_id)
    # 2026-09-30：防雷改造页只列改造类任务（mitigation/scenario/report），
    # 防雷计算任务（normal/tongtiao）只在改造弹窗里作为前置任务下拉出现。
    normalized_types = [item for item in (job_types or []) if item]
    if normalized_types:
        stmt = stmt.where(FlAnalysisJob.job_type.in_(normalized_types))
        total_stmt = total_stmt.where(FlAnalysisJob.job_type.in_(normalized_types))

    normalized = (keyword or "").strip()
    if normalized:
        like = f"%{normalized}%"
        predicate = or_(
            FlAnalysisJob.job_name.ilike(like),
            Line.code.ilike(like),
            Line.name.ilike(like),
        )
        stmt = stmt.join(Line, FlAnalysisJob.line_id == Line.id)
        total_stmt = total_stmt.join(Line, FlAnalysisJob.line_id == Line.id)
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    total = int(db.scalar(total_stmt) or 0)
    items = db.execute(
        stmt.order_by(FlAnalysisJob.update_date.desc(), FlAnalysisJob.id.desc())
        .options(
            selectinload(FlAnalysisJob.line),
            # 抑制模型默认 lazy="selectin" 的 runs 级联（列表不需要 runs，
            # 否则自动带出 fl_analysis_run + tower_result/snapshot 整条链 8 条 SQL）
            noload(FlAnalysisJob.runs),
        )
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    live_counts = job_live_counts(db, [item.id for item in items])
    return FlAnalysisJobListResponse(
        items=[serialize_job(item, live_counts=live_counts) for item in items], total=total
    )


def list_tower_results(db: Session, *, job_id: str, run_id: str | None = None) -> FlAnalysisTowerResultListResponse:
    stmt = select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job_id)
    total_stmt = select(func.count()).select_from(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job_id)

    if run_id:
        stmt = stmt.where(FlAnalysisTowerResult.run_id == run_id)
        total_stmt = total_stmt.where(FlAnalysisTowerResult.run_id == run_id)

    total = int(db.scalar(total_stmt) or 0)
    # 按杆塔序号（seq_no）正序展示：详情页杆塔列表应对应线路塔序 1..N，
    # 而非按风险等级/创建时间排序（此前 risk_level.desc + create_date.asc 会打乱塔序）。
    items = db.execute(
        stmt.join(FlAnalysisTowerSnapshot, FlAnalysisTowerSnapshot.id == FlAnalysisTowerResult.snapshot_id)
        .order_by(FlAnalysisTowerSnapshot.seq_no.asc())
        .options(selectinload(FlAnalysisTowerResult.snapshot))
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
        # normal/tongtiao/risk：若用户在提交时勾选了杆塔子集，杆塔数按实际勾选数量落库；
        # 未勾选（空=全量）时按线路全部杆塔计数（口径与 _load_job_towers 的过滤一致，
        # 保证卡片/列表展示的任务总塔数 = 用户实际选择的塔数）。
        _selected_ids = [
            str(_id) for _id in (execution_options.get("selected_tower_ids") or []) if str(_id).strip()
        ]
        if _selected_ids:
            total_tower_count = len(_selected_ids)
        else:
            total_tower_count = int(
                db.scalar(
                    select(func.count()).select_from(LineTower).where(LineTower.line_id == line.id)
                )
                or 0
            )
    if payload.job_type in {"normal", "tongtiao"}:
        if external_adapter in {"atp", "wine"}:
            # 外部 ATP 引擎二分法默认开启（对齐 C# 桌面版二分扫描求耐雷水平）。
            # 不暴露给用户选择；仅显式 binary_search=false 时可关闭。
            execution_options.setdefault("binary_search", True)
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

    write_audit_log(
        db,
        action="fl_analysis.job.create",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"job_id={saved.id}",
            f"job_name={saved.job_name or '-'}",
            f"line_id={saved.line_id or '-'}",
            f"job_type={saved.job_type or '-'}",
            f"total_towers={saved.total_tower_count}",
        ),
    )
    db.commit()

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

    write_audit_log(
        db,
        action="fl_analysis.job.start",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"job_id={latest.id}",
            f"job_name={latest.job_name or '-'}",
            f"task_id={latest.task_id or '-'}",
        ),
    )
    db.commit()

    _publish_change(
        "fl_analysis.job.queued",
        {"action": "job_queued", "job_id": latest.id, "line_id": latest.line_id, "task_id": latest.task_id},
    )
    return FlAnalysisJobStartResponse(job=serialize_job(latest, include_runs=True), queued=True)


def cancel_job(db: Session, *, job_id: str, actor: User) -> tuple[FlAnalysisJob, bool]:
    """取消（终止）排队中 / 运行中的防雷分析任务。

    - 仅 ``pending`` / ``queued`` / ``running`` 可取消；已结束（success/failed/cancelled）→ 409
    - celery 侧：``running`` → ``revoke(terminate=True, signal="SIGTERM")``（终止 worker 子进程）；
      ``queued``/``pending`` → ``revoke(terminate=False)``（尚未执行，仅撤销，避免被 worker 取走）
    - DB 侧：``status='cancelled'`` + ``finished_at`` + ``error_message='用户取消'``
    - ⚠️ 收尾处理器（``_finish_rule_based_run`` / ``_mark_run_failed`` /
      ``_mark_job_failed_without_run``）均带「已是 cancelled 则不再覆盖」的保护 ——
      否则 revoke 与任务自然收尾竞争时会把状态翻回 success/failed
    - 另派发一个清理任务，杀掉该任务残留的 wine/tpbig/egm 孙进程（SIGTERM 只终止 worker
      子进程，孙进程可能继续跑完当前一轮，白烧 CPU）
    - 已算出的部分结果**保留**（不删数据），供追溯
    """
    job = get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="防雷分析任务不存在")
    if job.status not in {"pending", "queued", "running"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务当前状态为 {job.status}，已结束无法取消",
        )

    task_id = job.task_id
    revoke_mode = "none"
    if task_id:
        try:
            from ..core.celery_app import celery_app

            is_running = job.status == "running"
            # running 需 terminate（否则任务会继续跑完）；queued/pending 只需撤销标记
            celery_app.control.revoke(task_id, terminate=is_running, signal="SIGTERM")
            revoke_mode = "terminate" if is_running else "revoke"
        except Exception as exc:  # noqa: BLE001 —— 撤销失败不阻断状态落库（用户仍要看到已取消）
            logger.warning("撤销 celery 任务失败：job=%s task=%s err=%s", job.id, task_id, exc)
            revoke_mode = "failed"

    now = utcnow()
    # ⚠️ 顺序很关键（实测教训）：先派发清理任务（它会 SIGKILL 执行中的子进程 → 该连接断开后
    # 行锁立刻释放），再写状态。若反过来，本接口会在任务仍持锁期间空转重试（实测 17.8s 才返回）。
    _dispatch_cancel_cleanup(job_id=job.id)
    # ⚠️ 行锁坑（2026-09-14 实测）：任务运行中时 worker 侧会话会间歇性持有该 job 行锁
    # （快照计数/进度更新等），此时直接 UPDATE 会被无限期阻塞 —— 实测接口曾挂住 >30s、
    # 前端表现为「请求无响应」。对策：lock_timeout 2s + 重试；仍失败则由清理任务兜底写状态。
    status_written = _write_cancelled_status(db, job_id=job.id, actor_id=actor.id, now=now)

    write_audit_log(
        db,
        action="fl_analysis.job.cancel",
        actor_user_id=actor.id,
        detail=compose_audit_detail(
            f"job_id={job.id}",
            f"job_name={job.job_name or '-'}",
            f"task_id={task_id or '-'}",
            f"revoke={revoke_mode}",
            f"status_written={status_written}",
        ),
    )
    db.commit()

    _publish_change(
        "fl_analysis.job.cancelled",
        {
            "action": "job_cancelled",
            "job_id": job.id,
            "line_id": job.line_id,
            "task_id": task_id,
            "revoke": revoke_mode,
            "status_written": status_written,
        },
    )

    latest = get_job_by_id(db, job.id)
    return latest or job, status_written


def _write_cancelled_status(
    db: Session, *, job_id: str, actor_id: str | None, now: datetime
) -> bool:
    """把任务置为 ``cancelled``，遇行锁时按 ``lock_timeout`` + 重试（返回是否写入成功）。

    不能让接口等待未定义时长：单次尝试最多 2s 拿不到锁就放掉，最多 5 次（≈10s）。
    失败时返回 False，由 worker 侧清理任务（进程已杀、锁必已释放）补写状态。
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    last_error: Exception | None = None
    for attempt in range(6):
        try:
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            locked_job = get_job_by_id(db, job_id)
            if not locked_job:
                db.rollback()
                return False
            locked_job.status = "cancelled"
            locked_job.error_message = "用户取消"
            locked_job.finished_at = now
            locked_job.update_date = now
            locked_job.update_user = actor_id
            db.commit()
            return True
        except OperationalError as exc:  # 行锁超时（lock_timeout）等
            db.rollback()
            last_error = exc
            logger.info("取消写状态遇行锁，重试 %d/6：job=%s", attempt + 1, job_id)
            time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001 —— 其它异常也不应让接口 500
            db.rollback()
            last_error = exc
            break
    logger.warning("取消状态写入失败（交由清理任务兜底）：job=%s err=%s", job_id, last_error)
    return False


def _dispatch_cancel_cleanup(*, job_id: str) -> None:
    """取消后清理该任务残留的外部引擎子进程（best-effort，失败不影响取消结果）。"""
    try:
        from ..tasks.fl_analysis_tasks import cleanup_cancelled_fl_analysis_run

        cleanup_cancelled_fl_analysis_run.delay(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("取消清理任务派发失败：job=%s err=%s", job_id, exc)


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
        context["job"] = {
            "id": job.id,
            "name": job.job_name,
        }
        writer.writerow([_format_export_cell(getter(context)) for _header, getter in columns])

    filename = f"fl_analysis_{job.job_type}_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return filename, output.getvalue().encode("utf-8-sig")


def _execute_single_tower(db: Session, snapshot_id: str, idx, total, *, spawn) -> None:
            # 本塔使用独立 session（由 execute_job 每塔创建并传入），隔离并发事务。
            # 传入的是 snapshot.id 标量，job/run/snapshot/tower 全部用本塔 session 按 ID 反查，
            # 避免跨 session 操作 execute_job 主 session 的对象（其会 expire/detached）。
            snapshot = db.get(FlAnalysisTowerSnapshot, snapshot_id)
            if snapshot is None:
                raise RuntimeError(f"杆塔(snapshot_id={snapshot_id})在独立session不可见")
            job = get_job_by_id(db, snapshot.job_id)
            if job is None:
                raise RuntimeError(f"杆塔 {snapshot.tower_no}: 任务(job_id={snapshot.job_id})不存在")
            run = db.get(FlAnalysisRun, snapshot.run_id)
            if run is None:
                raise RuntimeError(f"杆塔 {snapshot.tower_no}: 运行记录(run_id={snapshot.run_id})不存在")
            execution_options = spawn["execution_options"]
            has_external = spawn["has_external"]
            has_legacy = spawn["has_legacy"]
            progress_update_job = spawn["progress_update_job"]
            source_result_map = spawn["source_result_map"]
            waveform_job_type = spawn["waveform_job_type"]
            towers = spawn["towers"]
            snapshots = spawn["snapshots"]
            _tower_phase_plan = spawn["_tower_phase_plan"]
            logger = spawn["logger"]
            job_type = job.job_type if job else None
            local_stdout: list[str] = []
            local_stderr: list[str] = []
            # 多塔并行：塔 worker 不得写共享 fl_analysis_run 行（run.engine_command/working_dir 是共享字段，
            # 并发 UPDATE 同一行 → 行锁竞争）。改由 execute_job 主线程归并写。这里只收集首个非空值。
            local_engine_cmds: list[str] = []
            local_working_dirs: list[str] = []
            # 重建 resolve 闭包（原 execute_job 内定义）
            def _resolve_legacy_job_for_tower(snapshot):
                # 独立 session：每塔用本塔 session 重新解析，不复用 execute_job 主 session 的缓存/默认对象
                # （否则 ResolvedLegacyAtpJob 内的 ORM 关联在跨 session 访问时 DetachedInstanceError）
                tower_type = snapshot.tower_type or ""
                try:
                    return resolve_legacy_atp_job(
                        adapter_config_json=job.adapter_config_json or {},
                        execution_options=execution_options,
                        tower_type=tower_type,
                    )
                except Exception as exc:
                    # 对齐「不具备条件抛错」：legacy 模板解析失败不回退主 session 的默认对象（跨 session 不可用）
                    raise RuntimeError(
                        f"legacy ATP 模板解析失败（tower={snapshot.tower_no} type={tower_type}）：{exc}"
                    ) from exc
            def _resolve_external_job_for_tower(snapshot):
                # 独立 session：每塔用本塔 session 重新解析资产，asset 归属本塔 session，避免 DetachedInstanceError
                tower_type = snapshot.tower_type or ""
                return resolve_external_waveform_job(
                    db,
                    external_adapter=job.external_adapter if job.external_adapter in {"atp", "wine"} else "atp",
                    adapter_config_json=job.adapter_config_json or {},
                    tower_type=tower_type,
                    line_voltage_kv=job.line.voltage_kv if job.line else None,
                    scene_type=_auto_scene_type_for_options(execution_options),
                )
            payload = {
                "base_tower_json": snapshot.base_tower_json or {},
                "profile_json": snapshot.profile_json or {},
            }
            # 每根塔独立追踪内部子步骤进度
            tower_tracker = _TowerProgressTracker(_tower_phase_plan)
            # 记录上一次二分的目标相数，用于在 tongtiao 多相循环内检测阶段切换
            _tower_last_phase_done = [False]
            _tower_last_target = [0]
            _report_tower_fractional(
                db=db, job=job, run=run, tracker=tower_tracker,
                fraction=0.0, step_label=f"开始计算杆塔 {snapshot.tower_no}",
                update_job=progress_update_job,
            )
            def _tower_on_step(done: int, total: int, label: str | None = None) -> None:
                # 从标签解析目标相数（"二分搜索 第 N 相"）；tongtiao 多相循环内各相独立二分，
                # 相数变化代表上一相阶段结束，推进 tracker 到下一阶段。
                import re as _re
                target_phase: int | None = None
                if label:
                    _m = _re.search(r"第\s*(\d+)\s*相", label)
                    if _m:
                        target_phase = int(_m.group(1))
                if target_phase is not None and _tower_last_target[0] and target_phase != _tower_last_target[0]:
                    tower_tracker.mark_phase_done()
                _tower_last_target[0] = target_phase or 0
                frac = tower_tracker.report_phase_step(done, total, label)
                _report_tower_fractional(
                    db=db, job=job, run=run, tracker=tower_tracker,
                    fraction=frac, step_label=label or tower_tracker.phase_label,
                    update_job=progress_update_job,
                )

            logger.info(
                "[ATP] 开始处理杆塔 %s（第 %d/%d 根）",
                snapshot.tower_no,
                idx,
                len(snapshots),
            )
            if job.job_type == "scenario":
                payload["profile_json"] = _apply_scenario_profile_json_overrides(snapshot.profile_json or {})
            source_result = source_result_map.get(snapshot.tower_id)
            if source_result:
                payload["source_result_json"] = source_result
            if job.job_type == "mitigation":
                if has_external:
                    # 对齐 C#：改造状态机每轮用 ATP 引擎（AllCall_CS 101）重算跳闸率/风险，
                    # 不能静默退化为规程法。注入「改后参数 → ATP 单次仿真」重算函数。
                    resolved_job = _resolve_external_job_for_tower(snapshot)
                    if resolved_job is None:
                        raise RuntimeError(f"外部 ATP/Wine 模板解析失败：{snapshot.tower_no}")

                    def _atp_recompute(
                        sim_base: Mapping[str, Any],
                        sim_profile: Mapping[str, Any],
                        _rj: ResolvedExternalWaveformJob = resolved_job,
                        _snap: FlAnalysisTowerSnapshot = snapshot,
                        _opts: dict[str, Any] = dict(execution_options),
                    ) -> dict[str, Any]:
                        # 用改造后参数构造 payload 走 ATP 单次仿真（对齐 C# AllCall_CS(101)）
                        _payload = {
                            "base_tower_json": dict(sim_base),
                            "profile_json": dict(sim_profile),
                        }
                        _baseline = grade_normal_snapshot_payload(_payload, execution_options=_opts)
                        _exec = execute_external_waveform_tower_analysis(
                            _rj,
                            db=db,
                            job=job,
                            snapshot=_snap,
                            execution_options=_opts,
                            baseline_result=_baseline,
                        )
                        return _exec.result_json or {}

                    graded = grade_mitigation_snapshot_payload(
                        payload,
                        non_construction=bool(execution_options.get("non_construction")),
                        recompute_fn=_atp_recompute,
                    )
                else:
                    # 无外部资产(placeholder/legacy 未装)：仍走规程法重算（离线兜底）
                    graded = grade_mitigation_snapshot_payload(
                        payload,
                        non_construction=bool(execution_options.get("non_construction")),
                    )
            elif waveform_job_type == "normal":
                baseline_result = grade_normal_snapshot_payload(payload, execution_options=execution_options)
                # 基准计算阶段完成，进入二分阶段
                tower_tracker.mark_phase_done()
                if has_external:
                    resolved_job = _resolve_external_job_for_tower(snapshot)
                    if resolved_job is None:
                        raise RuntimeError(f"外部 ATP/Wine 模板解析失败：{snapshot.tower_no}")
                    # 二分法默认开启（对齐 C# 桌面版 ThreadCompute5 二分雷电流扫描求耐雷水平）；
                    # 仅当显式传 binary_search=false 时回退单次仿真
                    if execution_options.get("binary_search", True):
                        execution = execute_binary_search_external(
                            resolved_job,
                            db=db,
                            job=job,
                            snapshot=snapshot,
                            execution_options=execution_options,
                            baseline_result=baseline_result,
                            payload=payload,
                            on_step=_tower_on_step,
                        )
                    else:
                        execution = execute_external_waveform_tower_analysis(
                            resolved_job,
                            db=db,
                            job=job,
                            snapshot=snapshot,
                            execution_options=execution_options,
                            baseline_result=baseline_result,
                        )
                    graded = execution.result_json
                    # 单相反击二分阶段完成
                    tower_tracker.mark_phase_done()
                    # ── 绕击（raoji1/raoji2/raoji3 = A/B/C 相）—— 普通计算同样要做 ──
                    # C# 普通计算输出含绕击耐雷水平 + 绕击跳闸率（如 500源上 1号塔
                    # 绕击耐雷 35.153 / 绕击跳闸率 1.2824），故此处与 tongtiao 同流程。
                    _raoji_values: dict[str, float | None] = {}
                    _raoji_merged = dict(graded)
                    import concurrent.futures as _cf  # noqa: PLC0415
                    _raoji_workers = max(1, int(execution_options.get("binary_search_parallel_workers") or 4))
                    _use_raoji_par = _raoji_workers > 1

                    def _run_raoji(_idx: int):
                        try:
                            _raoji_job = resolve_external_waveform_job(
                                db,
                                external_adapter=job.external_adapter
                                if job.external_adapter in {"atp", "wine"} else "atp",
                                adapter_config_json=dict(job.adapter_config_json or {}),
                                tower_type=snapshot.tower_type or "",
                                line_voltage_kv=job.line.voltage_kv if job.line else None,
                                scene_type=f"raoji{_idx}",
                            )
                        except Exception as _exc:
                            # ⚠️ 对齐 C#：raoji 资产解不出必须报错（禁静默兜底）
                            raise RuntimeError(
                                f"绕击{['A', 'B', 'C'][_idx - 1]}相: 缺少 ATP 绕击资产 "
                                f"(场景=raoji{_idx}, tower={snapshot.tower_type}, "
                                f"{job.line.voltage_kv if job.line else '?'}kV)：{_exc}"
                            ) from _exc
                        _opts = dict(execution_options)
                        if _use_raoji_par:
                            _opts["_run_subdir"] = f"raoji{_idx}"
                        return execute_shielding_binary_search_external(
                            _raoji_job,
                            db=db,
                            job=job,
                            snapshot=snapshot,
                            execution_options=_opts,
                            baseline_result=baseline_result,
                            payload=payload,
                            on_step=_tower_on_step,
                        )

                    if _use_raoji_par:
                        with _cf.ThreadPoolExecutor(max_workers=min(_raoji_workers, 3)) as _pool:
                            _raoji_execs = dict(zip((1, 2, 3), _pool.map(_run_raoji, (1, 2, 3))))
                    else:
                        _raoji_execs = {_idx: _run_raoji(_idx) for _idx in (1, 2, 3)}
                    for _idx, _sh in _raoji_execs.items():
                        _raoji_values[f"{['A', 'B', 'C'][_idx - 1]}相"] = _sh.result_json.get("shielding_withstand_ka")
                        for _key in (
                            "shielding_withstand_ka",
                            "shielding_trip_rate",
                            "shielding_alpha_deg",
                            "shielding_binary_search",
                            "shielding_raoji_index",
                        ):
                            if _key in _sh.result_json:
                                _raoji_merged[_key] = _sh.result_json[_key]
                        _raoji_merged.setdefault("shielding_raoji_by_phase", {})[
                            f"{['A', 'B', 'C'][_idx - 1]}相"
                        ] = _sh.result_json.get("shielding_withstand_ka")
                    _raoji_merged["shielding_phase_withstand_ka"] = _raoji_values
                    tower_tracker.mark_phase_done()
                    # ── 绕击跳闸率：C# EGM（rjtzl_egm*.exe）；Ic 取中间相绕击耐雷整数部分 ──
                    _vals = [v for v in _raoji_values.values() if isinstance(v, (int, float))]
                    # C# ComputeLightningProtection.cs:7891-7912：顶层「绕击耐雷水平」与 EGM 的 Ic
                    # 都取三相绕击耐雷的最小值（不是 B 相 —— 相序测试上恰好相等）
                    _egm_ic = min(_vals) if _vals else None
                    if _egm_ic is None:
                        raise RuntimeError(
                            f"{snapshot.tower_no}: 绕击耐雷水平缺失，无法计算 EGM 绕击跳闸率"
                        )
                    from .atp_egm_trip_rate import compute_shielding_trip_rate  # noqa: PLC0415

                    _egm_env = os.environ.copy()
                    _egm_env.setdefault("XDG_RUNTIME_DIR", "/tmp/.xdg")
                    _egm_rate, _egm_alpha = compute_shielding_trip_rate(
                        atp_root=Path("/app/data/wine/ATP"),
                        voltage_kv=job.line.voltage_kv if job.line else None,
                        base_tower=snapshot.base_tower_json or {},
                        profile=snapshot.profile_json or {},
                        tower_type=snapshot.tower_type or "",
                        raoji_withstand_ka=float(_egm_ic),
                        env=_egm_env,
                    )
                    _raoji_merged["shielding_trip_rate"] = _egm_rate
                    _raoji_merged["shielding_trip_rate_method"] = "egm"
                    # 普通计算：顶层绕击耐雷 = 三相最小值（C# 7891-7912）
                    if _egm_ic is not None:
                        _raoji_merged["shielding_withstand_ka"] = _egm_ic
                    graded = _raoji_merged
                    # 普通计算：顶层耐雷/跳闸率保留实际值（C# 口径），但风险等级要用
                    # EGM 之后的绕击跳闸率重算。
                    try:
                        from .fl_analysis_rules import (  # noqa: PLC0415
                            _calculate_risk_grade,
                            _normalize_lightning_inputs,
                            _risk_level_from_grade,
                        )

                        _norm = _normalize_lightning_inputs(payload)
                        _ri, _th, _rg = _calculate_risk_grade(
                            _norm,
                            graded.get("counterstrike_trip_rate"),
                            _egm_rate,
                        )
                        if _rg is not None:
                            graded["risk_grade"] = _rg
                            graded["risk_level"] = _risk_level_from_grade(_rg) or graded.get("risk_level")
                            graded["risk_index_s"] = _ri
                    except Exception as _exc:  # noqa: BLE001
                        logger.warning("[EGM] 风险等级重算失败（保留原值）：%s", _exc)
                    if execution.engine_command:
                        local_engine_cmds.append(execution.engine_command)
                    if execution.working_dir:
                        local_working_dirs.append(execution.working_dir)
                    if execution.stdout_text:
                        local_stdout.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        local_stderr.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                elif has_legacy:
                    resolved_job = _resolve_legacy_job_for_tower(snapshot)
                    if resolved_job is None:
                        raise RuntimeError(f"legacy ATP 模板解析失败：{snapshot.tower_no}")
                    execution = execute_legacy_atp_tower_analysis(
                        resolved_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    if execution.engine_command:
                        local_engine_cmds.append(execution.engine_command)
                    if execution.working_dir:
                        local_working_dirs.append(execution.working_dir)
                    if execution.stdout_text:
                        local_stdout.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        local_stderr.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                else:
                    graded = baseline_result
            elif waveform_job_type == "tongtiao":
                baseline_result = grade_tongtiao_snapshot_payload(payload, execution_options=execution_options)
                if has_external:
                    resolved_job = _resolve_external_job_for_tower(snapshot)
                    if resolved_job is None:
                        raise RuntimeError(f"外部 ATP/Wine 模板解析失败：{snapshot.tower_no}")
                    # 二分法默认开启（对齐 C# 桌面版 ThreadCompute5 二分雷电流扫描求耐雷水平）；
                    # 仅当显式传 binary_search=false 时回退单次仿真。
                    # LP-570 同跳：C# 双回 ThreadCompute5_work_atp 循环 level_lightning=1..6 逐档
                    # 二分出单/双/三..六相反击耐雷 + fjtzlDanXiang 每档跳闸率（fjType=1 配置）。
                    if execution_options.get("binary_search", True):
                        execution = execute_multi_phase_binary_search_external(
                            resolved_job,
                            db=db,
                            job=job,
                            snapshot=snapshot,
                            execution_options=execution_options,
                            baseline_result=baseline_result,
                            payload=payload,
                            on_step=_tower_on_step,
                        )
                    else:
                        execution = execute_external_waveform_tower_analysis(
                            resolved_job,
                            db=db,
                            job=job,
                            snapshot=snapshot,
                            execution_options=execution_options,
                            baseline_result=baseline_result,
                        )
                    graded = execution.result_json
                    # 多相二分阶段完成，进入下一阶段（绕击二分或结果回填）
                    tower_tracker.mark_phase_done()
                    # ── 绕击（raoji1/raoji2/raoji3 = A/B/C 相）──────────────
                    # C# ThreadCompute5_work_atp：start compute raoji1/raoji2/raoji3
                    # （Alert.txt 实测），即 A/B/C 三相各用独立 raoji 模板二分绕击耐雷水平。
                    # 对齐 C#：raoji 资产解不出 → 明确报错，绝不静默用公式兜底。
                    _method_raoji = str(
                        (job.execution_options_json or {}).get("raoji_naleishuiping_method") or ""
                        or (execution_options or {}).get("raoji_naleishuiping_method") or ""
                    ).strip().lower()
                    if _method_raoji == "atp" or (job.adapter_config_json or {}).get("shielding_asset_id"):
                        logger.info("[ATP] 绕击循环触发(tongtiao)：method_raoji=%s, scene=raoji1/2/3", _method_raoji)
                        _raoji_values: dict[str, float | None] = {}
                        _raoji_merged = dict(graded)
                        import concurrent.futures as _cf  # noqa: PLC0415
                        _raoji_workers = max(1, int(execution_options.get("binary_search_parallel_workers") or 4))
                        _use_raoji_par = _raoji_workers > 1

                        def _run_raoji(_idx: int):
                            try:
                                _raoji_job = resolve_external_waveform_job(
                                    db,
                                    external_adapter=job.external_adapter
                                    if job.external_adapter in {"atp", "wine"} else "atp",
                                    adapter_config_json=dict(job.adapter_config_json or {}),
                                    tower_type=snapshot.tower_type or "",
                                    line_voltage_kv=job.line.voltage_kv if job.line else None,
                                    scene_type=f"raoji{_idx}",
                                )
                            except Exception as _exc:
                                # ⚠️ 对齐 C#：raoji 资产解不出必须报错（禁静默兜底）
                                raise RuntimeError(
                                    f"绕击{['A', 'B', 'C'][_idx - 1]}相: 缺少 ATP 绕击资产 "
                                    f"(场景=raoji{_idx}, tower={snapshot.tower_type}, "
                                    f"{job.line.voltage_kv if job.line else '?'}kV)：{_exc}"
                                ) from _exc
                            _opts = dict(execution_options)
                            if _use_raoji_par:
                                _opts["_run_subdir"] = f"raoji{_idx}"
                            return execute_shielding_binary_search_external(
                                _raoji_job,
                                db=db,
                                job=job,
                                snapshot=snapshot,
                                execution_options=_opts,
                                baseline_result=baseline_result,
                                payload=payload,
                                on_step=_tower_on_step,
                            )

                        if _use_raoji_par:
                            with _cf.ThreadPoolExecutor(max_workers=min(_raoji_workers, 3)) as _pool:
                                _raoji_execs = dict(zip((1, 2, 3), _pool.map(_run_raoji, (1, 2, 3))))
                        else:
                            _raoji_execs = {_idx: _run_raoji(_idx) for _idx in (1, 2, 3)}
                        for _idx, _sh in _raoji_execs.items():
                            _raoji_values[f"{['A', 'B', 'C'][_idx - 1]}相"] = _sh.result_json.get("shielding_withstand_ka")
                            for _key in (
                                "shielding_withstand_ka",
                                "shielding_trip_rate",
                                "shielding_alpha_deg",
                                "shielding_binary_search",
                                "shielding_raoji_index",
                            ):
                                if _key in _sh.result_json:
                                    _raoji_merged[_key] = _sh.result_json[_key]
                            _raoji_merged.setdefault("shielding_raoji_by_phase", {})[
                                f"{['A', 'B', 'C'][_idx - 1]}相"] = _sh.result_json.get("shielding_withstand_ka")
                            if _sh.stdout_text:
                                local_stdout.append(f"[{snapshot.tower_no}][绕击{['A', 'B', 'C'][_idx - 1]}相] {_sh.stdout_text}")
                        _raoji_merged["shielding_phase_withstand_ka"] = _raoji_values
                        tower_tracker.mark_phase_done()
                        # ── 绕击跳闸率：C# EGM 电气几何模型（rjtzl_egm*.exe，wine 跑）──
                        _vals = [v for v in _raoji_values.values() if isinstance(v, (int, float))]
                        # C# ComputeLightningProtection.cs:7891-7912：顶层「绕击耐雷水平」与 EGM 的 Ic
                        # 都取三相绕击耐雷的最小值（不是 B 相 —— 相序测试上恰好相等）
                        # （(int)mRaojiCurrent），跑 egm 两轮（地面倾角1 / -地面倾角2）求和，
                        # 鼓型塔再 ÷2。已用 C# 0913 中间文件逐位验证：0.406567 ✓
                        _egm_ic = min(_vals) if _vals else None
                        if _egm_ic is None:
                            raise RuntimeError(
                                f"{snapshot.tower_no}: 绕击耐雷水平缺失，无法计算 EGM 绕击跳闸率"
                            )
                        from .atp_egm_trip_rate import compute_shielding_trip_rate  # noqa: PLC0415

                        _egm_env = os.environ.copy()
                        _egm_env.setdefault("XDG_RUNTIME_DIR", "/tmp/.xdg")
                        _egm_rate, _egm_alpha = compute_shielding_trip_rate(
                            atp_root=Path("/app/data/wine/ATP"),
                            voltage_kv=job.line.voltage_kv if job.line else None,
                            base_tower=snapshot.base_tower_json or {},
                            profile=snapshot.profile_json or {},
                            tower_type=snapshot.tower_type or "",
                            raoji_withstand_ka=float(_egm_ic),
                            env=_egm_env,
                        )
                        _raoji_merged["shielding_trip_rate"] = _egm_rate
                        _raoji_merged["shielding_trip_rate_method"] = "egm"
                        graded = _raoji_merged
                        # ── 顶层口径对齐 C# 交流同跳，并用 EGM 跳闸率重算风险等级 ──
                        # （C# 引擎对 IDout24/26 只注册不赋值 → 顶层耐雷/反击跳闸率输出 0；
                        #   风险等级 C# 用 EGM 后的绕击跳闸率算，故此处需在 EGM 之后重算）
                        graded["counterstrike_withstand_ka"] = 0.0
                        graded["counterstrike_trip_rate"] = 0.0
                        graded["shielding_withstand_ka"] = 0.0
                        try:
                            from .fl_analysis_rules import (  # noqa: PLC0415
                                _calculate_risk_grade,
                                _normalize_lightning_inputs,
                                _risk_level_from_grade,
                            )

                            _norm = _normalize_lightning_inputs(payload)
                            _ri, _th, _rg = _calculate_risk_grade(_norm, 0.0, _egm_rate)
                            if _rg is not None:
                                graded["risk_grade"] = _rg
                                graded["risk_level"] = _risk_level_from_grade(_rg) or graded.get("risk_level")
                                graded["risk_index_s"] = _ri
                        except Exception as _exc:  # noqa: BLE001
                            logger.warning("[EGM] 风险等级重算失败（保留原值）：%s", _exc)
                    if execution.engine_command:
                        local_engine_cmds.append(execution.engine_command)
                    if execution.working_dir:
                        local_working_dirs.append(execution.working_dir)
                    if execution.stdout_text:
                        local_stdout.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        local_stderr.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                elif has_legacy:
                    resolved_job = _resolve_legacy_job_for_tower(snapshot)
                    if resolved_job is None:
                        raise RuntimeError(f"legacy ATP 模板解析失败：{snapshot.tower_no}")
                    execution = execute_legacy_atp_tower_analysis(
                        resolved_job,
                        job=job,
                        snapshot=snapshot,
                        execution_options=execution_options,
                        baseline_result=baseline_result,
                    )
                    graded = execution.result_json
                    if execution.engine_command:
                        local_engine_cmds.append(execution.engine_command)
                    if execution.working_dir:
                        local_working_dirs.append(execution.working_dir)
                    if execution.stdout_text:
                        local_stdout.append(f"[{snapshot.tower_no}] {execution.stdout_text}")
                    if execution.stderr_text:
                        local_stderr.append(f"[{snapshot.tower_no}] {execution.stderr_text}")
                else:
                    graded = baseline_result
            else:
                graded = grade_snapshot_payload(payload)
            # ⚠️ 结果写入幂等（2026-09-18 修复）：同一 run 的同一塔（snapshot）结果只写一次，
            # 避免 execute_job 被 Redis 重投双执行时同塔结果翻倍。
            existing_result = db.execute(
                select(FlAnalysisTowerResult.id).where(
                    FlAnalysisTowerResult.run_id == run.id,
                    FlAnalysisTowerResult.snapshot_id == snapshot.id,
                )
            ).scalar_one_or_none()
            if existing_result is None:
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
            # (result_count 由 execute_job 主线程归并)
            # (summary 由 execute_job 主线程归并)
            # 本塔所有阶段完成：推进到末尾并回填最终进度（1.0 代表本塔完成）
            try:
                tower_tracker.mark_phase_done()
                _report_tower_fractional(
                    db=db, job=job, run=run, tracker=tower_tracker,
                    fraction=1.0, step_label=f"杆塔 {snapshot.tower_no} 计算完成",
                    update_job=progress_update_job,
                )
            except Exception:
                logger.debug("[ATP] 塔完成进度上报失败 tower=%s", snapshot.tower_no, exc_info=True)

            tower = db.get(LineTower, snapshot.tower_id)
            if tower is not None and job.job_type not in {"mitigation", "scenario"}:
                tower.risk_level = graded["risk_level"]
                tower.update_date = utcnow()
                tower.update_user = job.update_user or job.create_user
                _upsert_tower_lightning_result_from_graded(
                    db,
                    tower=tower,
                    graded=graded,
                    actor_user_id=job.update_user or job.create_user,
                )

            # 每塔完成推进度事件（LP-xxx：任务执行中逐塔实时进度，前端进度条刷新）
            try:
                _publish_change(
                    "fl_analysis.tower_done",
                    {
                        "action": "tower_done",
                        "job_id": job.id,
                        "run_id": run.id,
                        "tower_id": snapshot.tower_id,
                        "tower_no": snapshot.tower_no,
                        "seq_no": snapshot.seq_no,
                        "processed": idx,
                        "total": len(snapshots),
                        "risk_level": graded.get("risk_level"),
                    },
                )
            except Exception:
                logger.debug("[WS] 塔进度事件推送失败 tower=%s", snapshot.tower_no, exc_info=True)

            # 每塔实时落库进度计数（前端 invalidate 后能读到 result_tower_count 驱动进度条；
            # 原循环结束才统一写 job.result_tower_count，运行中 DB 恒 0 → 进度条不动）
            # ⚠️ 2026-09-15 修复：只 db.flush() 不 db.commit() 时，整个任务运行期间事务
            # 不提交，PG READ COMMITTED 下其他会话（前端轮询/API/psql）读不到任何运行中
            # 数据 → 进度恒 0%、已算塔结果运行中不可查。改为每塔完成后提交一个小事务：
            # ① 运行中进度/已算塔结果实时可见；② 中途失败保留已完成塔，不整体回滚。
            # commit 失败 = 事务级故障，必须让任务失败（不能静默吞掉继续跑坏事务）。
            # （result_tower_count 的最终值由 execute_job 收尾统一写，避免并行时多塔争写 DB 同行）
            db.commit()

            # 执行中日志流式推送（每塔完成后把该塔 stdout/stderr 行 XADD 到 Redis Stream，
            # SSE /task-logs/{id}/sse 实时增量读；MinIO 全量文件由 celery 任务兜底最终上传）
            try:
                _exec = locals().get("execution")
                _exec_out = getattr(_exec, "stdout_text", None) if _exec is not None else None
                _exec_err = getattr(_exec, "stderr_text", None) if _exec is not None else None
                if job.task_id and (_exec_out or _exec_err):
                    from ..services.task_log_service import append_task_log_lines  # noqa: PLC0415

                    _log_lines = []
                    if _exec_out:
                        _log_lines.extend(
                            f"[{snapshot.tower_no}][stdout] {line}"
                            for line in _exec_out.splitlines()
                            if line.strip()
                        )
                    if _exec_err:
                        _log_lines.extend(
                            f"[{snapshot.tower_no}][stderr] {line}"
                            for line in _exec_err.splitlines()
                            if line.strip()
                        )
                    if _log_lines:
                        append_task_log_lines(job.task_id, _log_lines)
            except Exception:
                logger.debug("[WS] 塔日志流推送失败 tower=%s", snapshot.tower_no, exc_info=True)
            return {
                "ok": True,
                "idx": idx,
                "tower_no": snapshot.tower_no,
                "graded": graded,
                "stdout": "\n".join(local_stdout),
                "stderr": "\n".join(local_stderr),
                "engine_command": (local_engine_cmds[0] if local_engine_cmds else None),
                "working_dir": (local_working_dirs[0] if local_working_dirs else None),
            }


def clean_job_run_artifacts(job_id: str) -> None:
    """清理任务（Job）完成后残留的运行结果目录（只删结果，不动引擎/资产物化目录）。

    覆盖两类运行目录：
    - fl-analysis： ``{atp_storage_root}/runs/fl-analysis/{job_id}``
    - legacy：     ``{atp_run_root}/{job_id}``

    每个任务跑完后至少命中其中一类；两类都尝试删除（``ignore_errors=True``，
    目录不存在或删除失败都不会抛出）。资产测试运行目录由
    ``atp_asset_test_service.cleanup_test_run_dir`` 单独负责，此处不处理。
    """
    from .atp_asset_service import _resolve_engine_workdir

    targets: list[Path] = []
    try:
        targets.append(_resolve_engine_workdir() / "fl-analysis" / job_id)
    except Exception:  # noqa: BLE001
        pass
    try:
        settings = get_settings()
        targets.append(Path(settings.atp_run_root).expanduser() / job_id)
    except Exception:  # noqa: BLE001
        pass

    for target in targets:
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
                logger.info("[fl-analysis] 已清理任务 %s 运行结果目录：%s", job_id, target)
        except Exception as exc:  # noqa: BLE001 —— 清理是 best-effort
            logger.warning("[fl-analysis] 清理任务 %s 运行结果目录失败 %s：%s", job_id, target, exc)


def execute_job(job_id: str) -> None:
    db = SessionLocal()
    started_perf = time.perf_counter()
    run_id: str | None = None
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            return

        # ⚠️ 幂等防重（2026-09-18 修复）：execute_job 可能被 Redis visibility_timeout
        # 超时重投重复触发（同 task 双执行）。若 job 已有未结束的 active run（running/queued），
        # 说明已有 worker 正在执行本任务，直接返回忽略重投，避免结果表翻倍。
        active_run = db.execute(
            select(FlAnalysisRun).where(
                FlAnalysisRun.job_id == job.id,
                FlAnalysisRun.status.in_(["running", "queued"]),
            )
        ).scalars().first()
        if active_run is not None:
            logger.warning(
                "[fl-analysis] 任务 %s 已有 active run %s（status=%s），忽略 Redis 重投/重复派发",
                job.id, active_run.id, active_run.status,
            )
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
                profile_json=_build_profile_json(profile, tower),
                create_date=utcnow(),
            )
            db.add(snapshot)
            snapshots.append(snapshot)
            snapshot_count += 1

        db.flush()
        # 独立 session：snapshot 必须先提交，塔的 tower_db 才能用外键引用 snapshot_id（否则
        # fl_analysis_tower_result_snapshot_id_fkey 违反 PendingRollbackError）
        db.commit()

        result_count = 0
        summary = _new_result_summary()
        tower_map = {tower.id: tower for tower in towers}
        external_job = None
        legacy_external_job = None
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        # ⚠️ 2026-09-29 修复：措施推荐(mitigation)任务也必须解析外部 ATP 资产。
        # 原条件只放行 normal/tongtiao → mitigation 永远 has_external=False →
        # 状态机每轮走规程法重算(861 行兜底)，与 C# AllCall_CS(101) ATP 重算不一致。
        if waveform_job_type in {"normal", "tongtiao"} or job.job_type == "mitigation":
            _method_fanji = str(execution_options.get("fanji_naleishuiping_method") or "").strip().lower()
            _method_raoji = str(execution_options.get("raoji_naleishuiping_method") or "").strip().lower()
            # 方法选项选了 atp（反击或绕击任一）→ 自动启用 external ATP 路径（LP-xxx 自动选资产，
            # 对齐 C# 桌面版：不要求用户在页面选资产，按线路/杆塔参数自动匹配模板）。
            # 显式 external_adapter 仍优先（老任务/脚本直传兼容）。
            # ⚠️ mitigation(措施推荐)：对齐 C# MyCanShu_2/3 每轮 AllCall_CS(101) ATP 重算，
            # 无条件走 ATP 解析（有资产就解析，无资产抛错，绝不静默规程法）。
            if (
                job.job_type == "mitigation"
                or job.external_adapter in {"atp", "wine"}
                or _method_fanji == "atp"
                or _method_raoji == "atp"
            ):
                try:
                    external_job = resolve_external_waveform_job(
                        db,
                        external_adapter=job.external_adapter if job.external_adapter in {"atp", "wine"} else "atp",
                        adapter_config_json=job.adapter_config_json or {},
                        # ⚠️ 2026-09-13 修复：原实现不传 tower_type → _auto_resolve_asset 拿不到塔型
                        # → 退到硬编码默认 "ganzi"，导致任务级资产恒为 ganzi（日志里看到的 ganzi 来源）。
                        # 传首塔塔型作为任务级代表资产；实际每塔仍在循环内按各自塔型解析。
                        tower_type=snapshots[0].tower_type if snapshots else None,
                        line_voltage_kv=job.line.voltage_kv if job.line else None,
                        scene_type=_auto_scene_type_for_options(execution_options),
                    )
                    summary["external_model_id"] = external_job.asset.id
                    summary["external_model_code"] = external_job.asset.code
                    summary["external_model_name"] = external_job.asset.name
                except Exception as exc:
                    # ⚠️ 对齐 C#：计算方法明确选了 ATP（或适配器为 atp/wine）时，必须用 ATP 引擎。
                    # 若解不出资产/引擎，直接抛错，绝不静默回退到规程公式——否则计算结果与 C# 不一致
                    # 且用户无感知（原实现 external_job=None fallback 到 placeholder，是本需求要消除的）。
                    raise RuntimeError(
                        f"计算方法已选 ATP，但无法解析 ATP 引擎/资产（job={job.id}, "
                        f"tower/voltage={job.line.voltage_kv if job.line else '?'}kV, "
                        f"scene={_auto_scene_type_for_options(execution_options)}）：{exc}"
                    ) from exc
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
        # LP-560：legacy ATP 模板支持按塔型编码细分。循环内按每塔 tower_type 解析模板并缓存，
        # 塔型无对应子目录时回退任务级默认模板（legacy_external_job）。
        legacy_job_cache: dict[str, ResolvedLegacyAtpJob | None] = {}
        external_job_cache: dict[str, ResolvedExternalWaveformJob | None] = {}

        def _resolve_legacy_job_for_tower(snapshot: FlAnalysisTowerSnapshot) -> ResolvedLegacyAtpJob | None:
            if legacy_external_job is None:
                return None
            tower_type = snapshot.tower_type or ""
            cache_key = _normalize_tower_shape_code(tower_type) or "<default>"
            if cache_key in legacy_job_cache:
                return legacy_job_cache[cache_key]
            try:
                resolved = resolve_legacy_atp_job(
                    adapter_config_json=job.adapter_config_json or {},
                    execution_options=execution_options,
                    tower_type=tower_type,
                )
            except Exception as exc:  # 塔型子目录/默认模板缺失时回退任务级默认，避免单塔失败拖垮整批
                logger.warning(
                    "[ATP] 按塔型解析模板失败（tower=%s type=%s）：%s，回退默认模板",
                    snapshot.tower_no,
                    tower_type,
                    exc,
                )
                resolved = legacy_external_job
            legacy_job_cache[cache_key] = resolved
            return resolved

        def _resolve_external_job_for_tower(snapshot: FlAnalysisTowerSnapshot) -> ResolvedExternalWaveformJob | None:
            if external_job is None:
                return None
            tower_type = snapshot.tower_type or ""
            cache_key = _normalize_tower_shape_code(tower_type) or "<default>"
            if cache_key in external_job_cache:
                return external_job_cache[cache_key]
            # ⚠️ 2026-09-13 修复：必须传「有效适配器」——job.external_adapter 对页面建的任务是
            # placeholder，而 resolve_external_waveform_job 只认 atp/wine，传 placeholder 会直接
            # 抛 "Unsupported external adapter: placeholder" → 每塔解析 100% 失败 → 回退到任务级
            # 资产（曾恒为 ganzi）。对齐任务级 resolve 的写法。
            # ⚠️ 同时不再「解析失败回退任务级模板」：按用户要求，不具备条件时抛错而非静默降级
            # （回退会让塔型不匹配、用错模型算出错误结果，且用户无感知）。
            resolved = resolve_external_waveform_job(
                db,
                external_adapter=job.external_adapter if job.external_adapter in {"atp", "wine"} else "atp",
                adapter_config_json=job.adapter_config_json or {},
                tower_type=tower_type,
                line_voltage_kv=job.line.voltage_kv if job.line else None,
                scene_type=_auto_scene_type_for_options(execution_options),
            )
            external_job_cache[cache_key] = resolved
            return resolved

        # 方案C：构建单塔内部阶段计划（进度条细分用）。shielding/外部二分是否启用对整任务一致。
        _shielding_asset_id = str((job.adapter_config_json or {}).get("shielding_asset_id") or "").strip()
        _has_shielding_plan = bool(_shielding_asset_id) and bool(execution_options.get("binary_search", True))
        _has_external_tower_plan = external_job is not None or legacy_external_job is not None
        _tower_phase_plan = _build_tower_phase_plan(
            job_type=job.job_type,
            waveform_job_type=waveform_job_type,
            has_external=_has_external_tower_plan,
            has_shielding=_has_shielding_plan,
            max_phases=3,
        )

        # 塔级并行（Step2）：tower_parallel_workers>1 且多塔时开线程池；=1 或单塔退化为串行（天然回滚开关）
        tower_parallel_workers = max(1, int(execution_options.get("tower_parallel_workers") or 2))
        # 并行时塔 worker 不写共享 fl_analysis_job 进度行（避免行锁）；串行时保留单塔实时进度
        progress_update_job = not (tower_parallel_workers > 1 and len(snapshots) > 1)

        spawn = {
            "execution_options": execution_options,
            "has_external": external_job is not None or legacy_external_job is not None,
            "has_legacy": legacy_external_job is not None,
            "progress_update_job": progress_update_job,
            "source_result_map": source_result_map,
            "waveform_job_type": waveform_job_type,
            "towers": towers,
            "snapshots": snapshots,
            "_tower_phase_plan": _tower_phase_plan,
            "logger": logger,
        }

        def _run_tower_worker(snapshot_id, idx, total, worker_spawn):
            # 单塔失败独立（语义B）：异常不外抛，返回 ok=False，其余塔不受影响
            try:
                with closing(SessionLocal()) as tower_db:
                    return _execute_single_tower(tower_db, snapshot_id, idx, total, spawn=worker_spawn)
            except Exception as exc:
                logger.exception("[ATP] 杆塔%s 计算失败（单塔独立，任务继续）", snapshot_id)
                return {"ok": False, "idx": idx, "tower_no": snapshot_id, "error": str(exc)}

        if tower_parallel_workers > 1 and len(snapshots) > 1:
            import concurrent.futures as _cfg
            with _cfg.ThreadPoolExecutor(max_workers=tower_parallel_workers) as _pool:
                _futs = [_pool.submit(_run_tower_worker, s.id, i, len(snapshots), spawn)
                         for i, s in enumerate(snapshots, start=1)]
                _outcomes = [f.result() for f in _cfg.as_completed(_futs)]
        else:
            _outcomes = [_run_tower_worker(s.id, i, len(snapshots), spawn)
                         for i, s in enumerate(snapshots, start=1)]
        # 按塔序归并（保证 tower 顺序/日志/摘要一致）
        _outcomes.sort(key=lambda o: o.get("idx", 0))
        result_count = 0
        for _out in _outcomes:
            if _out.get("ok"):
                result_count += 1
                _accumulate_result_summary(summary, _out["graded"])
                _out_so = _out.get("stdout") or ""
                _out_se = _out.get("stderr") or ""
                if _out_so:
                    stdout_chunks.append(_out_so)
                if _out_se:
                    stderr_chunks.append(_out_se)
                run.engine_command = run.engine_command or _out.get("engine_command")
                run.working_dir = run.working_dir or _out.get("working_dir")
            else:
                logger.error("[ATP] 杆塔 %s 计算失败（单塔独立，任务继续）：%s",
                             _out.get("tower_no"), _out.get("error"))

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

        # 任务终态清理：删本 job 的运行结果目录（成功路径）
        clean_job_run_artifacts(job.id)

    except Exception as exc:
        db.rollback()
        if run_id is not None:
            _mark_run_failed(db, job_id=job_id, run_id=run_id, error_message=str(exc), started_perf=started_perf)
        else:
            _mark_job_failed_without_run(db, job_id=job_id, error_message=str(exc))
        # 任务终态清理：异常路径同样清理运行结果目录
        clean_job_run_artifacts(job_id)
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

    # ⚠️ 取消是终态：用户已取消时不再把状态翻回 success（结果/日志仍保留供追溯）。
    cancelled = job.status == "cancelled"
    if cancelled:
        logger.info("任务已被取消，跳过 success 状态写回：job=%s", job.id)
    else:
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

    if cancelled:
        return

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

    # 取消是终态：任务被终止后用户看到的应是「已取消」，而不是随之而来的失败信息。
    cancelled = job.status == "cancelled"
    if not cancelled:
        job.status = "failed"
        job.error_message = error_message
    job.finished_at = now
    job.update_date = now
    db.commit()

    if cancelled:
        return

    _publish_change(
        "fl_analysis.job.failed",
        {"action": "job_failed", "job_id": job.id, "line_id": job.line_id, "run_id": run.id},
    )


def _mark_job_failed_without_run(db: Session, *, job_id: str, error_message: str) -> None:
    job = get_job_by_id(db, job_id)
    if not job:
        return
    now = utcnow()
    # 取消是终态：已取消的任务不再被写成失败。
    cancelled = job.status == "cancelled"
    if not cancelled:
        job.status = "failed"
        job.error_message = error_message
    job.finished_at = now
    job.update_date = now
    db.commit()

    if cancelled:
        return

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
        select(FlAnalysisTowerResult)
        .options(selectinload(FlAnalysisTowerResult.snapshot))
        .where(
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
    # 对齐 C# TGanTa 明细：tower_profile（几何/配置）与回路几何（I-IV 回中距/高度）
    tower = snapshot.tower if snapshot is not None else None
    tprofile_obj = tower.profile if tower is not None else None
    tprofile = {}
    if tprofile_obj is not None:
        tprofile = {
            "phase_sequence_1": getattr(tprofile_obj, "phase_sequence_1", None),
            "phase_sequence_2": getattr(tprofile_obj, "phase_sequence_2", None),
            "phase_sequence_3": getattr(tprofile_obj, "phase_sequence_3", None),
            "phase_sequence_4": getattr(tprofile_obj, "phase_sequence_4", None),
            "arrester_a": getattr(tprofile_obj, "arrester_a", None),
            "arrester_b": getattr(tprofile_obj, "arrester_b", None),
            "arrester_c": getattr(tprofile_obj, "arrester_c", None),
            "protection_angle_left_deg": getattr(tprofile_obj, "protection_angle_left_deg", None),
            "protection_angle_right_deg": getattr(tprofile_obj, "protection_angle_right_deg", None),
            "shield_wire_height_m": getattr(tprofile_obj, "shield_wire_height_m", None),
            "insulator_length_m": getattr(tprofile_obj, "insulator_length_m", None),
            "call_height_m": getattr(tprofile_obj, "call_height_m", None),
            "angle_deg": getattr(tprofile_obj, "angle_deg", None),
            "current_a": getattr(tprofile_obj, "current_a", None),
            "current_b": getattr(tprofile_obj, "current_b", None),
            "structure_kind": getattr(tprofile_obj, "structure_kind", None),
            "stroke_mode": getattr(tprofile_obj, "stroke_mode", None),
            "current_type": getattr(tprofile_obj, "current_type", None),
            "current_head_time_us": getattr(tprofile_obj, "current_head_time_us", None),
            "current_tail_time_us": getattr(tprofile_obj, "current_tail_time_us", None),
            "extra_profile_json": _safe_dict(getattr(tprofile_obj, "extra_profile_json", None)),
        }
    # 回路几何：按 circuit_no 1..4 取中距/高度（对齐 C# I-IV 回上中下相）
    circuits: list[dict[str, Any]] = []
    if tower is not None and tower.circuits is not None:
        for circ in sorted(tower.circuits, key=lambda c: getattr(c, "circuit_no", 0) or 0):
            circuits.append({
                "spacing_upper_m": getattr(circ, "spacing_upper_m", None),
                "spacing_middle_m": getattr(circ, "spacing_middle_m", None),
                "spacing_lower_m": getattr(circ, "spacing_lower_m", None),
                "height_upper_m": getattr(circ, "height_upper_m", None),
                "height_middle_m": getattr(circ, "height_middle_m", None),
                "height_lower_m": getattr(circ, "height_lower_m", None),
            })
    return {
        "item": item,
        "snapshot": snapshot,
        "tower": tower,
        "base": base,
        "profile": profile,
        "tprofile": tprofile,
        "circuits": circuits,
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
    # 对齐 C# 桌面版 TGanTa 导出明细（TaskData/TGanTaData.MyHead_ToString 列序）。
    # 所有 job_type 统一输出塔级全量明细（C# 不分类型）；mitigation 用 C# 的「措施推荐」列。
    return _csharp_aligned_export_columns()


def _csharp_aligned_export_columns() -> list[tuple[str, Callable[[dict[str, Any]], Any]]]:
    """C# 桌面版 TGanTaData.MyHead_ToString() 列头逐列对齐（2026-09-16）。

    列名/顺序完全照抄 lp-knowledge LP/TGanTaData.cs:403-500；数据从 Web 侧
    snapshot/base_tower_json/tower.profile/tower.circuits/result_json 映射。
    数据源缺失的列输出空值（保持列数/列序与 C# 一致）。
    """
    def num(*keys: str):
        def getter(ctx: dict[str, Any]) -> Any:
            for key in keys:
                # 支持 ctx['base'].get(k) / ctx['result'].get(k) 等嵌套取数
                section, _, field = key.partition(".")
                section_obj = ctx.get(section)
                if not isinstance(section_obj, dict):
                    continue
                val = section_obj.get(field)
                if val is not None:
                    return val
            return None
        return getter

    def text(*keys: str):
        def getter(ctx: dict[str, Any]) -> Any:
            for key in keys:
                section, _, field = key.partition(".")
                section_obj = ctx.get(section)
                if not isinstance(section_obj, dict):
                    continue
                val = section_obj.get(field)
                if isinstance(val, str) and val.strip():
                    return val
                if val is not None:
                    return val
            return None
        return getter

    # 回路几何（I-IV 回上中下相中距/高度），按 circuit_no 顺序取
    def circ_num(circ_idx: int, field: str):
        def getter(ctx: dict[str, Any]) -> Any:
            circuits = ctx.get("circuits") or []
            if circ_idx < len(circuits):
                return circuits[circ_idx].get(field)
            return None
        return getter

    # tprofile 取数（tower_profile 字段）
    def prof(key: str):
        return lambda ctx: (ctx.get("tprofile") or {}).get(key)

    # 多相结果展开（phase_count 1-6 → 耐雷水平/闪络相/跳闸率）
    def multiphase(phase_count: int, field: str):
        def getter(ctx: dict[str, Any]) -> Any:
            entries = ((ctx.get("result") or {}).get("multi_phase_binary_search") or {}).get("phase_entries") or []
            for entry in entries:
                if isinstance(entry, dict) and entry.get("phase_count") == phase_count:
                    return entry.get(field)
            return None
        return getter

    # A/B/C 相绕击耐雷（shielding_phase_withstand_ka dict，键为 "A相"/"B相"/"C相"）
    def shielding_phase(phase: str):
        def getter(ctx: dict[str, Any]) -> Any:
            spw = (ctx.get("result") or {}).get("shielding_phase_withstand_ka")
            if isinstance(spw, dict):
                return spw.get(phase) or spw.get(f"{phase}相")
            return None
        return getter

    # 避雷中距（extra_profile_json.lightning_wire.left/right_mid_distance_m）
    def wire_mid(side: str):
        def getter(ctx: dict[str, Any]) -> Any:
            extra = (ctx.get("tprofile") or {}).get("extra_profile_json") or {}
            lw = extra.get("lightning_wire") or {}
            return lw.get(side)
        return getter

    # 接地电阻/密度等 base 优先、inputs 兜底
    def pick(*pairs: tuple[str, str]):
        def getter(ctx: dict[str, Any]) -> Any:
            for section, field in pairs:
                section_obj = ctx.get(section)
                if isinstance(section_obj, dict):
                    val = section_obj.get(field)
                    if val is not None:
                        return val
            return None
        return getter

    # ── 列定义（顺序与 C# MyHead_ToString 完全一致）──
    cols: list[tuple[str, Callable[[dict[str, Any]], Any]]] = [
        # 任务/线路标识 1-12
        ("任务编号", lambda ctx: (ctx.get("job") or {}).get("name") or (ctx.get("job") or {}).get("id")),
        ("任务塔号", num("snapshot.tower_no") if False else lambda ctx: getattr(ctx.get("snapshot"), "tower_no", None) if ctx.get("snapshot") else None),
        ("线路编号", text("base.line_id")),
        ("序号", num("base.seq_no")),
        ("线路名称", text("base.line_name")),
        ("电压等级", num("base.line_voltage_kv")),
        ("塔号", num("base.tower_no")),
        ("参数分级编码", lambda ctx: None),  # Web 无此数据
        ("杆塔模型", num("base.tower_model")),
        ("塔形", num("base.tower_type")),
        ("经度", num("base.longitude")),
        ("纬度", num("base.latitude")),
        # 相序 13-16
        ("I回相序", prof("phase_sequence_1")),
        ("II回相序", prof("phase_sequence_2")),
        ("III回相序", prof("phase_sequence_3")),
        ("IV回相序", prof("phase_sequence_4")),
        # 避雷器 17-19
        ("A相是否安装避雷器", prof("arrester_a")),
        ("B相是否安装避雷器", prof("arrester_b")),
        ("C相是否安装避雷器", prof("arrester_c")),
        # 20
        ("接地电阻", pick(("base", "ground_resistance_ohm"), ("inputs", "ground_resistance_ohm"))),
        # 21-23
        ("左避雷中距m", wire_mid("left_mid_distance_m")),
        ("右避雷中距m", wire_mid("right_mid_distance_m")),
        ("避雷线高度m", prof("shield_wire_height_m")),
        # 24-25
        ("绝缘子串长度mm", prof("insulator_length_m")),
        ("杆塔呼高m", prof("call_height_m")),
        # I 回 26-31
        ("I回上相中距m", circ_num(0, "spacing_upper_m")),
        ("I回中相中距m", circ_num(0, "spacing_middle_m")),
        ("I回下相中距m", circ_num(0, "spacing_lower_m")),
        ("I回上相高度m", circ_num(0, "height_upper_m")),
        ("I回中相高度m", circ_num(0, "height_middle_m")),
        ("I回下相高度m", circ_num(0, "height_lower_m")),
        # II 回 32-37
        ("II回上相中距m", circ_num(1, "spacing_upper_m")),
        ("II回中相中距m", circ_num(1, "spacing_middle_m")),
        ("II回下相中距m", circ_num(1, "spacing_lower_m")),
        ("II回上相高度m", circ_num(1, "height_upper_m")),
        ("II回中相高度m", circ_num(1, "height_middle_m")),
        ("II回下相高度m", circ_num(1, "height_lower_m")),
        # III 回 38-43
        ("III回上相中距m", circ_num(2, "spacing_upper_m")),
        ("III回中相中距m", circ_num(2, "spacing_middle_m")),
        ("III回下相中距m", circ_num(2, "spacing_lower_m")),
        ("III回上相高度m", circ_num(2, "height_upper_m")),
        ("III回中相高度m", circ_num(2, "height_middle_m")),
        ("III回下相高度m", circ_num(2, "height_lower_m")),
        # IV 回 44-49
        ("IV回上相中距m", circ_num(3, "spacing_upper_m")),
        ("IV回中相中距m", circ_num(3, "spacing_middle_m")),
        ("IV回下相中距m", circ_num(3, "spacing_lower_m")),
        ("IV回上相高度m", circ_num(3, "height_upper_m")),
        ("IV回中相高度m", circ_num(3, "height_middle_m")),
        ("IV回下相高度m", circ_num(3, "height_lower_m")),
        # 50-52
        ("小号侧档距", num("base.span_small_m")),
        ("大号侧档距", num("base.span_large_m")),
        ("电角度", prof("angle_deg")),
        # 53-54
        ("雷电流幅值a", pick(("inputs", "current_a"), ("base", "current_a"))),
        ("雷电流幅值b", pick(("inputs", "current_b"), ("base", "current_b"))),
        # 55-56
        ("地面倾角1", num("base.slope_1")),
        ("地面倾角2", num("base.slope_2")),
        # 57-59
        ("海拔m", num("base.altitude_m")),
        ("地形", text("base.terrain")),
        ("地闪密度", num("base.lightning_density")),
        # 60-64
        ("直线或耐张杆塔", prof("structure_kind")),
        ("雷电流波形种类", prof("current_type")),
        ("波头时间/μs", prof("current_head_time_us")),
        ("波尾时间/μs", prof("current_tail_time_us")),
        ("绕击反击", prof("stroke_mode")),
        # 65-68
        ("反击耐雷水平kA", num("result.counterstrike_withstand_ka")),
        ("反击跳闸率(次/100km.a)", num("result.counterstrike_trip_rate")),
        ("绕击耐雷水平kA", num("result.shielding_withstand_ka")),
        ("绕击跳闸率(次/100km.a)", num("result.shielding_trip_rate")),
        # 69
        ("雷击风险等级", text("result.risk_level")),
        # 70-72
        ("A相绕击耐雷水平kA", shielding_phase("A")),
        ("B相绕击耐雷水平kA", shielding_phase("B")),
        ("C相绕击耐雷水平kA", shielding_phase("C")),
        # 73-90：单~六相 × (耐雷水平/闪络相/跳闸率)
        ("单相反击耐雷水平kA", multiphase(1, "counterstrike_withstand_ka")),
        ("单相闪络相", multiphase(1, "flashover_phase")),
        ("单相反击跳闸率(次/100km.a)", multiphase(1, "trip_rate")),
        ("双相反击耐雷水平kA", multiphase(2, "counterstrike_withstand_ka")),
        ("双相闪络相", multiphase(2, "flashover_phase")),
        ("双相反击跳闸率(次/100km.a)", multiphase(2, "trip_rate")),
        ("三相反击耐雷水平kA", multiphase(3, "counterstrike_withstand_ka")),
        ("三相闪络相", multiphase(3, "flashover_phase")),
        ("三相反击跳闸率(次/100km.a)", multiphase(3, "trip_rate")),
        ("四相反击耐雷水平kA", multiphase(4, "counterstrike_withstand_ka")),
        ("四相闪络相", multiphase(4, "flashover_phase")),
        ("四相反击跳闸率(次/100km.a)", multiphase(4, "trip_rate")),
        ("五相反击耐雷水平kA", multiphase(5, "counterstrike_withstand_ka")),
        ("五相闪络相", multiphase(5, "flashover_phase")),
        ("五相反击跳闸率(次/100km.a)", multiphase(5, "trip_rate")),
        ("六相反击耐雷水平kA", multiphase(6, "counterstrike_withstand_ka")),
        ("六相闪络相", multiphase(6, "flashover_phase")),
        ("六相反击跳闸率(次/100km.a)", multiphase(6, "trip_rate")),
        # 91-94
        ("原因分析", text("result.cause_analysis")),
        ("措施推荐", text("result.mitigation_recommendation")),
        ("保护角", num("result.shielding_alpha_deg")),
        ("普通计算结果", text("result.summary_text")),
    ]
    return cols


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
        ("绝缘子闪络判据", lambda ctx: ctx["workflow"].get("flashover_method")),
        ("是否海拔修正", lambda ctx: ctx["workflow"].get("altitude_correction")),
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
        "circuit_geometry_json": _build_legacy_geometry_from_circuits(tower.circuits),
        "lightning_result_json": _build_legacy_lightning_result(tower.lightning_result),
        "raw_extra_json": tower.raw_extra_json or {},
    }


def _upsert_tower_lightning_result_from_graded(
    db: Session,
    *,
    tower: LineTower,
    graded: dict[str, Any],
    actor_user_id: str,
) -> None:
    """将计算引擎输出的雷电结果写回 tower_lightning_result 子表。"""
    now = utcnow()
    result = tower.lightning_result
    if result is None:
        result = TowerLightningResult(
            tower_id=tower.id,
            create_date=now,
            update_date=now,
        )
        tower.lightning_result = result
    result.counterstroke_indicator = _as_int_or_none(graded.get("stroke_mode") or graded.get("counterstroke_indicator"))
    result.counterstroke_withstand_ka = _as_float_or_none(
        graded.get("counterstrike_withstand_ka") or graded.get("counterstroke_withstand_ka")
    )
    result.counterstroke_trip_rate = _as_float_or_none(
        graded.get("counterstrike_trip_rate") or graded.get("counterstroke_trip_rate")
    )
    result.shielding_withstand_ka = _as_float_or_none(
        graded.get("shielding_withstand_ka")
    )
    result.shielding_trip_rate = _as_float_or_none(
        graded.get("shielding_trip_rate")
    )
    result.angle_deg = _as_float_or_none(graded.get("angle_deg"))
    result.current_a_ka = _as_float_or_none(graded.get("current_a"))
    result.current_b_ka = _as_float_or_none(graded.get("current_b"))
    result.risk_level = _normalize_risk_level_text(graded.get("risk_level"))
    result.update_date = now


def _as_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_risk_level_text(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    return text


def _build_legacy_geometry_from_circuits(circuits: list[TowerCircuit]) -> dict[str, Any]:
    circuit_key_by_no = {1: "I", 2: "II", 3: "III", 4: "IV"}
    result: dict[str, Any] = {}
    for circuit in circuits:
        circuit_key = circuit_key_by_no.get(circuit.circuit_no)
        if circuit_key is None:
            continue
        result[circuit_key] = {
            "phase_spacing_m": {
                "upper": circuit.spacing_upper_m,
                "middle": circuit.spacing_middle_m,
                "lower": circuit.spacing_lower_m,
            },
            "phase_height_m": {
                "upper": circuit.height_upper_m,
                "middle": circuit.height_middle_m,
                "lower": circuit.height_lower_m,
            },
        }
    return result


def _build_legacy_lightning_result(item: TowerLightningResult | None) -> dict[str, Any]:
    if item is None:
        return {}
    return {
        "counterstroke_indicator": item.counterstroke_indicator,
        "counterstroke_withstand_ka": item.counterstroke_withstand_ka,
        "counterstroke_trip_rate": item.counterstroke_trip_rate,
        "shielding_withstand_ka": item.shielding_withstand_ka,
        "shielding_trip_rate": item.shielding_trip_rate,
        "angle_deg": item.angle_deg,
        "current_a": item.current_a_ka,
        "current_b": item.current_b_ka,
        "risk_level": item.risk_level,
    }


def _build_profile_json(profile: TowerProfile | None, tower: LineTower | None = None) -> dict[str, Any]:
    if profile is None:
        return {}
    result = {
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
        "extra_profile_json": profile.extra_profile_json or {},
    }
    if tower is not None:
        result["geometry_layers_json"] = _build_legacy_geometry_from_circuits(tower.circuits)
        # LP-570 透传 extra_profile_json.lightning_wire（避雷线中距/高度），供
        # _merge_geometry_layers 合并进计算几何——此前计算链路拿不到真实中距（回填 10m 默认值）
        _lw = (profile.extra_profile_json or {}).get("lightning_wire")
        if isinstance(_lw, dict):
            _geo_layers = dict(result["geometry_layers_json"])
            _geo_layers["lightning_wire"] = dict(_lw)
            result["geometry_layers_json"] = _geo_layers
        analysis = tower.analysis
        if analysis is not None:
            result["cause_analysis"] = analysis.cause_analysis
            result["mitigation_recommendation"] = analysis.mitigation_recommendation
    return result


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
        if job_type in {"normal", "tongtiao"}:
            include_tower_ids = normalized.get("include_tower_ids") or normalized.get("selected_tower_ids") or []
            if isinstance(include_tower_ids, list):
                normalized["selected_tower_ids"] = list(dict.fromkeys(str(item).strip() for item in include_tower_ids if str(item).strip()))
            else:
                normalized["selected_tower_ids"] = []
        else:
            normalized.pop("selected_tower_ids", None)
            normalized.pop("include_tower_ids", None)
        if job_type == "tongtiao":
            # 对齐 C# Form_TongTiaoJiSuan.cs:226-229：同跳任务的跳闸率方法固定「规程」、
            # 绕击跳闸率固定「EGM」，C# 不提供给用户配置；此处兜底，保证 API 直建的同跳任务
            # 与界面/桌面版行为一致（这两个值会作为 ATP 模板 CAL_MODE 的取值来源）。
            normalized.setdefault("fanji_tzl_method", "guicheng")
            normalized.setdefault("raoji_tzl_method", "egm")
            # ⚠️ 对齐 C#：同跳的耐雷水平计算方法固定为 ATP（C# ThreadCompute5 同跳分支写死
            # mFanJi_NaiLeiShuiPing/mRaoJi_NaiLeiShuiPing = "ATP"，界面无选择）。这里**强制覆盖**
            # 用户传值（不是 setdefault），因为 C# 同跳不可选、固定 ATP。由此 execute_job 里
            # _method_fanji=_method_raoji="atp" → 必然走 ATP 引擎；无资产/未配引擎时抛错而不是
            # 静默回退到规程公式（避免计算结果与 C# 不一致）。
            normalized["fanji_naleishuiping_method"] = "atp"
            normalized["raoji_naleishuiping_method"] = "atp"
        if job_type == "normal":
            # ⚠️ 对齐 C#：普通计算的耐雷水平方法**默认走 ATP 引擎**（C# 桌面版 ThreadCompute
            # 恒用 ATP/tpbig，不存在"规程公式"这条计算路径）。
            # 用 setdefault（非强制）：用户在页面显式选了规程法仍尊重其选择。
            # 不加这个默认值 → execute_job 里 _method_fanji/_method_raoji 都非 atp、且
            # external_adapter 是 placeholder → external/legacy 两条分支都不进 →
            # 结果用规程公式算（与 C# 差 18%+，且绕击跳闸率完全不对）。
            normalized.setdefault("fanji_naleishuiping_method", "atp")
            normalized.setdefault("raoji_naleishuiping_method", "atp")
            normalized.setdefault("raoji_tzl_method", "egm")
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
    # ⚠️ 2026-09-27 修复：兼容 base_job_id（早期前端 payload 字段名）与 source_job_id 双写
    source_job_id = str(execution_options.get("source_job_id") or execution_options.get("base_job_id") or "")
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
    # ⚠️ 2026-09-27 修复：前驱类型由「仅 risk」放宽为 normal/tongtiao/risk ——
    # C# 逻辑（Form5_CuoShiTuiJian）的前驱是「普通计算已完成」（Finished1_PuTongJiSuan），
    # 前端措施推荐页也筛 normal/tongtiao；旧实现强制 risk 导致 UI 创建必 400（千万次实测）。
    if source_job.job_type not in {"normal", "tongtiao", "risk"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前驱任务必须为普通计算/同跳/风险评估任务")
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
    if job.job_type in {"mitigation", "report", "scenario"}:
        # 既有任务类型：强制 selected_tower_ids 全部命中
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
    # normal/tongtiao 等：selected_tower_ids 非空时按勾选过滤（空=全量），不强制校验
    selected_ids = set(execution_options.get("selected_tower_ids") or [])
    if not selected_ids:
        return towers
    return [tower for tower in towers if tower.id in selected_ids]


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
        .options(selectinload(FlAnalysisTowerResult.snapshot))
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
    """推送 fl-analysis 变更事件到 WS topic。

    Web(FastAPI) 进程：asyncio 事件循环存在 → publish_topic 直接推本地 WS 连接。
    Celery worker：无事件循环 → 走 Redis Stream 桥（publish_ws_event_from_worker，
    Web 进程 ws_event_forwarder 读到后转发给前端），否则进度静默丢弃。
    """
    try:
        asyncio.get_running_loop()
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
    except RuntimeError:
        from .ws_event_bridge import publish_ws_event_from_worker  # noqa: PLC0415

        try:
            publish_ws_event_from_worker(
                FL_ANALYSIS_TOPIC,
                name=event_name,
                payload=payload,
                requires_refetch=[],
                dedupe_key=f"fl-analysis:{event_name}:{payload.get('job_id', '-')}:"
                f"{payload.get('run_id', payload.get('line_id', '-'))}",
            )
        except Exception:
            logger.exception("[WS] worker 上下文推送事件失败 event=%s", event_name)


def _report_tower_fractional(
    *,
    db: Session,
    job: FlAnalysisJob,
    run: FlAnalysisRun,
    tracker: _TowerProgressTracker,
    fraction: float,
    step_label: str,
    update_job: bool = True,
) -> None:
    """把当前塔内进度（fractional_progress + 步骤文字）实时写库并推 WS 事件。

    供 execute_job 在每个塔内子步骤（基准/二分迭代/绕击/回填）后调用，前端 invalidate
    刷新后读到最新值，进度条据此细分到单塔内部。
    写入失败仅告警，不阻断任务主体逻辑。

    update_job=False：多塔并行时塔 worker 不得写共享 fl_analysis_job 行（否则多塔并发
    UPDATE 同一行 → Postgres 行级锁竞争 → 死锁卡死）。此时只推 WS、不设 job 字段、不 flush。
    进度行的最终值由 execute_job 主线程按塔序归并写入。
    """
    if update_job:
        job.fractional_progress = round(fraction, 4)
        job.current_step_text = step_label
        try:
            db.flush()
        except Exception:
            logger.debug("[DB] 塔内进度落库失败 job=%s", job.id, exc_info=True)
    try:
        _publish_change(
            "fl_analysis.tower_step",
            {
                "action": "tower_step",
                "job_id": job.id,
                "run_id": run.id,
                "step_key": tracker.phase_label or step_label,
                "step": step_label,
                "fractional_progress": round(fraction, 4),
            },
        )
    except Exception:
        logger.debug("[WS] 塔内进度事件推送失败 job=%s", job.id, exc_info=True)


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(coro)
