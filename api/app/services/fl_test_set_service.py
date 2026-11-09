"""防雷测试集 service。

集合/用例 CRUD + 批量执行（run）+ 状态跟随 + 自动评估。

执行链路：每个用例创建真实 ``fl_analysis_job``（normal/tongtiao/mitigation）
并 start，任务上写 ``test_run_case_id`` 标记；任务状态由 run 详情读取时同步
（sync-on-read，不侵入 fl_analysis 终态写入路径），避免事件丢失导致卡死。
评估按 expected_json 容错比对，无法自动判定的挂 pending_manual 交人工。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.fl_analysis import FlAnalysisJob, FlAnalysisTowerResult
from ..models.fl_test_set import (
    FL_TEST_CALC_KINDS,
    FL_TEST_RETROFIT_MODES,
    FL_TEST_SET_CATEGORIES,
    FlTestSet,
    FlTestSetCase,
    FlTestSetRun,
    FlTestSetRunCase,
)
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.base import utcnow
from ..models.user import User
from ..schemas.fl_analysis import FlAnalysisJobCreateRequest
from ..schemas.fl_test_set import (
    FlTestCaseCreateRequest,
    FlTestCaseUpdateRequest,
    FlTestSetCreateRequest,
    FlTestSetUpdateRequest,
    FlTestVerdictRequest,
)
from .fl_analysis_service import cancel_job, create_job, get_job_by_id, start_job
from .fl_analysis_service import list_tower_results  # noqa: F401  (re-export convenience)
from .fl_test_case_tower import ensure_case_tower, is_managed_line

# 手动判定终值（不被自动评估覆盖）
_MANUAL_VERDICTS = {"manual_pass", "manual_fail"}
_PASS_VERDICTS = {"auto_pass", "manual_pass"}
_FAIL_VERDICTS = {"auto_fail", "manual_fail"}


# ─────────────────────────── 基础查询 ───────────────────────────


def _get_set(db: Session, set_id: str) -> FlTestSet:
    row = db.execute(select(FlTestSet).where(FlTestSet.id == set_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    return row


def _get_case(db: Session, case_id: str) -> FlTestSetCase:
    row = db.execute(select(FlTestSetCase).where(FlTestSetCase.id == case_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")
    return row


def _get_run(db: Session, run_id: str) -> FlTestSetRun:
    row = db.execute(select(FlTestSetRun).where(FlTestSetRun.id == run_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试执行记录不存在")
    return row


def _get_run_case(db: Session, run_case_id: str) -> FlTestSetRunCase:
    row = db.execute(
        select(FlTestSetRunCase).where(FlTestSetRunCase.id == run_case_id)
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例执行记录不存在")
    return row


def _get_actor(db: Session, actor_user_id: str | None) -> User:
    """create_job/start_job 需要 User 对象（审计日志取 actor.id）。"""
    if actor_user_id:
        row = db.execute(select(User).where(User.id == actor_user_id)).scalar_one_or_none()
        if row:
            return row
    return User(id=actor_user_id or "system", username="system", nickname="system")


# ─────────────────────────── 测试集 CRUD ───────────────────────────


def serialize_set(row: FlTestSet) -> dict[str, Any]:
    cases = row.cases or []
    runs = row.runs or []
    last_run = None
    if runs:
        latest = runs[0]
        last_run = {
            "id": latest.id,
            "status": latest.status,
            "total_cases": latest.total_cases,
            "create_date": latest.create_date.isoformat() if latest.create_date else None,
        }
    return {
        "id": row.id,
        "category": row.category if row.category in FL_TEST_SET_CATEGORIES else "fl_calc",
        "name": row.name,
        "description": row.description or "",
        "status": row.status or "enabled",
        "tags_json": list(row.tags_json or []),
        "case_count": len(cases),
        "enabled_case_count": sum(1 for c in cases if c.enabled),
        "last_run": last_run,
        "create_date": row.create_date,
        "create_user": row.create_user,
        "update_date": row.update_date,
        "update_user": row.update_user,
    }


def list_sets(
    db: Session,
    *,
    category: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(FlTestSet).order_by(FlTestSet.update_date.desc())
    total_stmt = select(func.count()).select_from(FlTestSet)
    if category:
        stmt = stmt.where(FlTestSet.category == category)
        total_stmt = total_stmt.where(FlTestSet.category == category)
    normalized = (keyword or "").strip()
    if normalized:
        like = f"%{normalized}%"
        stmt = stmt.where(FlTestSet.name.ilike(like) | FlTestSet.description.ilike(like))
        total_stmt = total_stmt.where(FlTestSet.name.ilike(like) | FlTestSet.description.ilike(like))
    total = int(db.scalar(total_stmt) or 0)
    rows = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return {"items": [serialize_set(r) for r in rows], "total": total}


def create_set(db: Session, *, payload: FlTestSetCreateRequest, actor_user_id: str | None) -> dict[str, Any]:
    row = FlTestSet(
        category=payload.category,
        name=payload.name.strip(),
        description=payload.description or "",
        status=payload.status,
        tags_json=list(payload.tags_json or []),
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(row)
    db.commit()
    return serialize_set(row)


def update_set(
    db: Session, *, set_id: str, payload: FlTestSetUpdateRequest, actor_user_id: str | None
) -> dict[str, Any]:
    row = _get_set(db, set_id)
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.description is not None:
        row.description = payload.description
    if payload.status is not None:
        row.status = payload.status
    if payload.tags_json is not None:
        row.tags_json = list(payload.tags_json)
    row.update_user = actor_user_id
    db.commit()
    return serialize_set(row)


def delete_set(db: Session, *, set_id: str) -> None:
    row = _get_set(db, set_id)
    db.delete(row)
    db.commit()


# ─────────────────────────── 用例 CRUD ───────────────────────────


def _line_brief(db: Session, line_id: str | None) -> tuple[str | None, str | None]:
    if not line_id:
        return None, None
    row = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
    if not row:
        return None, None
    return getattr(row, "code", None), getattr(row, "name", None)


def _tower_no(db: Session, line_id: str | None, tower_id: str | None) -> str | None:
    if not line_id or not tower_id:
        return None
    row = db.execute(
        select(LineTower).where(LineTower.id == tower_id, LineTower.line_id == line_id)
    ).scalar_one_or_none()
    return getattr(row, "tower_no", None) if row else None


def serialize_case(db: Session, row: FlTestSetCase) -> dict[str, Any]:
    line_code, line_name = _line_brief(db, row.line_id)
    source_job = get_job_by_id(db, row.source_job_id) if row.source_job_id else None
    return {
        "id": row.id,
        "set_id": row.set_id,
        "name": row.name or "",
        "description": row.description or "",
        "calc_kind": row.calc_kind,
        "line_id": row.line_id,
        "line_code": line_code,
        "line_name": line_name,
        "tower_id": row.tower_id,
        "tower_no": _tower_no(db, row.line_id, row.tower_id),
        "params_json": dict(row.params_json or {}),
        "mode": row.mode,
        "non_construction": row.mode == "feijianxian",
        "source_job_id": row.source_job_id,
        "source_job_name": source_job.job_name if source_job else None,
        "source_job_status": source_job.status if source_job else None,
        "selected_tower_ids": list(row.selected_tower_ids_json or []),
        "expected_json": dict(row.expected_json or {}),
        "enabled": bool(row.enabled),
        "sort_order": int(row.sort_order or 0),
        "create_date": row.create_date,
        "update_date": row.update_date,
    }


def list_cases(db: Session, *, set_id: str) -> dict[str, Any]:
    test_set = _get_set(db, set_id)
    rows = sorted(test_set.cases or [], key=lambda c: (c.sort_order or 0, c.id))
    items = [serialize_case(db, r) for r in rows]
    return {"items": items, "total": len(items)}


def _validate_case_fields(db: Session, category: str, data: dict[str, Any], *, creating: bool) -> None:
    """按集合类别校验用例字段（create/update 共用）。

    PATCH 只校验「本次提交了的字段」是否合法，不要求把必填字段全部重传；
    新建时必填字段仍然强制校验。
    """
    if category == "fl_calc":
        calc_kind = data.get("calc_kind")
        if (creating or calc_kind is not None) and calc_kind not in FL_TEST_CALC_KINDS:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="防雷计算用例必须选择计算方式（normal/tongtiao）")
        # 新版用例表单直接填「编辑杆塔」+「防雷计算」两套字段，不再绑定测试线路：
        # line_id 由 ensure_case_tower 按表单快照自动托管。旧用例若显式传了
        # line_id，仍按原语义校验（兼容历史数据）。
        line_id = (data.get("line_id") or "").strip()
        if not line_id:
            return
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        if not line:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="绑定的测试线路不存在")
        tower_id = (data.get("tower_id") or "").strip() or None
        if tower_id:
            tower = db.execute(
                select(LineTower).where(LineTower.id == tower_id, LineTower.line_id == line_id)
            ).scalar_one_or_none()
            if not tower:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目标杆塔不属于绑定的测试线路")
    else:
        mode = data.get("mode")
        if (creating or mode is not None) and mode not in FL_TEST_RETROFIT_MODES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="防雷改造用例必须选择改造口径（建线/非建线）")
        source_job_id = (data.get("source_job_id") or "").strip()
        if not source_job_id:
            if creating:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="防雷改造用例必须绑定前置防雷计算任务")
            return
        source = get_job_by_id(db, source_job_id)
        if not source:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="前置防雷计算任务不存在")
        if source.job_type not in {"normal", "tongtiao", "risk"} or source.status != "success":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="前置任务必须为已成功的普通计算/同跳/风险评估任务",
            )


def _apply_managed_tower(
    db: Session, row: FlTestSetCase, actor_user_id: str | None, *, force: bool = False
) -> None:
    """fl_calc 用例：按 params_json.tower 快照创建 / 刷新托管线路 + 单塔。

    默认只有「未绑定线路」或「绑定的是系统托管线路」的用例走这里；仍绑定
    真实测试线路的旧用例保持原样。新表单提交（带 tower 快照）时 ``force=True``，
    旧用例改用新表单也会被切到托管塔，保证「填什么就按什么算」。
    """
    if not force and row.line_id:
        line = db.execute(select(Line).where(Line.id == row.line_id)).scalar_one_or_none()
        if line is not None and not is_managed_line(line):
            return
    params = dict(row.params_json or {})
    tower_params = params.get("tower")
    if not isinstance(tower_params, dict):
        tower_params = {}
    line_id, tower_id = ensure_case_tower(
        db,
        case_id=row.id,
        case_name=row.name or "",
        tower_params=tower_params,
        actor_user_id=actor_user_id,
    )
    row.line_id = line_id
    row.tower_id = tower_id


def create_case(
    db: Session, *, set_id: str, payload: FlTestCaseCreateRequest, actor_user_id: str | None
) -> dict[str, Any]:
    test_set = _get_set(db, set_id)
    data = payload.model_dump()
    _validate_case_fields(db, test_set.category, data, creating=True)
    max_sort = db.scalar(
        select(func.max(FlTestSetCase.sort_order)).where(FlTestSetCase.set_id == set_id)
    )
    row = FlTestSetCase(
        set_id=set_id,
        name=(payload.name or "").strip(),
        description=payload.description or "",
        calc_kind=payload.calc_kind,
        line_id=payload.line_id,
        tower_id=payload.tower_id,
        params_json=dict(payload.params_json or {}),
        mode=payload.mode,
        source_job_id=payload.source_job_id,
        selected_tower_ids_json=list(payload.selected_tower_ids or []),
        expected_json=dict(payload.expected_json or {}),
        enabled=payload.enabled,
        sort_order=(max_sort or 0) + 1,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(row)
    db.flush()
    if test_set.category == "fl_calc":
        # 新表单不传 line_id；若调用方显式绑定了真实线路（旧接口），保持原语义
        bound_line = None
        if payload.line_id:
            bound_line = db.execute(select(Line).where(Line.id == payload.line_id)).scalar_one_or_none()
        force = bound_line is None or is_managed_line(bound_line)
        _apply_managed_tower(db, row, actor_user_id, force=force)
    db.commit()
    return serialize_case(db, row)


def update_case(
    db: Session, *, case_id: str, payload: FlTestCaseUpdateRequest, actor_user_id: str | None
) -> dict[str, Any]:
    row = _get_case(db, case_id)
    test_set = _get_set(db, row.set_id)
    data = payload.model_dump(exclude_unset=True)
    _validate_case_fields(db, test_set.category, data, creating=False)
    for field in ("name", "description", "calc_kind", "line_id", "tower_id", "mode", "source_job_id", "enabled"):
        if field in data:
            setattr(row, field, data[field])
    if "params_json" in data and data["params_json"] is not None:
        row.params_json = dict(data["params_json"])
    if "expected_json" in data and data["expected_json"] is not None:
        row.expected_json = dict(data["expected_json"])
    if "selected_tower_ids" in data and data["selected_tower_ids"] is not None:
        row.selected_tower_ids_json = list(data["selected_tower_ids"])
    if test_set.category == "fl_calc":
        submitted_params = data.get("params_json")
        has_tower_snapshot = isinstance(submitted_params, dict) and "tower" in submitted_params
        # 绑定真实线路（非 FLTC- 托管线路）的用例，例如由历史任务转换的回归用例：
        # 杆塔快照只是表单展示用的历史值，不能据此把计算载体切到托管塔，
        # 否则几何会变、expected_json 里的历史基准也随之失效。
        bound_line = (
            db.execute(select(Line).where(Line.id == row.line_id)).scalar_one_or_none()
            if row.line_id
            else None
        )
        force = has_tower_snapshot and (bound_line is None or is_managed_line(bound_line))
        _apply_managed_tower(db, row, actor_user_id, force=force)
    row.update_user = actor_user_id
    db.commit()
    return serialize_case(db, row)


def delete_case(db: Session, *, case_id: str) -> None:
    row = _get_case(db, case_id)
    line_id = row.line_id
    db.delete(row)
    if line_id:
        line = db.execute(select(Line).where(Line.id == line_id)).scalar_one_or_none()
        # 托管线路若已无任务引用就一并清理；有历史任务则保留（job.line_id 外键）
        if is_managed_line(line):
            used = db.scalar(
                select(func.count()).select_from(FlAnalysisJob).where(FlAnalysisJob.line_id == line_id)
            ) or 0
            if not used:
                db.delete(line)
    db.commit()


# ─────────────────────────── 批量执行（run） ───────────────────────────


def _resolve_mitigation_tower_ids(db: Session, source_job: FlAnalysisJob, case: FlTestSetCase) -> list[str]:
    """mitigation 必须带 selected_tower_ids：用例未勾选时默认取前置任务的风险杆塔
    （对齐 C# 口径 score>2；一个都没有时退化为前置任务全部结果杆塔）。"""
    if case.selected_tower_ids_json:
        return [str(t) for t in case.selected_tower_ids_json if str(t).strip()]
    run_id = source_job.latest_run_id
    stmt = select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == source_job.id)
    if run_id:
        stmt = stmt.where(FlAnalysisTowerResult.run_id == run_id)
    rows = db.execute(stmt).scalars().all()
    risky = [
        r.tower_id
        for r in rows
        if isinstance(r.result_json, dict) and isinstance(r.result_json.get("score"), (int, float)) and r.result_json["score"] > 2
    ]
    if risky:
        return risky
    return [r.tower_id for r in rows if r.tower_id]


def _build_job_request(db: Session, test_set: FlTestSet, case: FlTestSetCase) -> FlAnalysisJobCreateRequest:
    case_name = case.name or "未命名用例"
    if test_set.category == "fl_calc":
        params = dict(case.params_json or {})
        execution_options = dict(params.get("execution_options_json") or {})
        if case.tower_id and not execution_options.get("selected_tower_ids"):
            # 单塔语义：只分析绑定的目标杆塔
            execution_options["selected_tower_ids"] = [case.tower_id]
        return FlAnalysisJobCreateRequest(
            line_id=str(case.line_id),
            job_name=f"[测试] {case_name}"[:255],
            job_type=case.calc_kind or "normal",
            external_adapter=str(params.get("external_adapter") or "wine"),
            adapter_config_json=dict(params.get("adapter_config_json") or {}),
            execution_options_json=execution_options,
        )
    source_job = get_job_by_id(db, str(case.source_job_id))
    if not source_job:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="前置防雷计算任务不存在")
    return FlAnalysisJobCreateRequest(
        line_id=str(source_job.line_id),
        job_name=f"[测试] {case_name}"[:255],
        job_type="mitigation",
        external_adapter=source_job.external_adapter,
        adapter_config_json=dict(source_job.adapter_config_json or {}),
        execution_options_json={
            "source_job_id": source_job.id,
            "non_construction": case.mode == "feijianxian",
            "selected_tower_ids": _resolve_mitigation_tower_ids(db, source_job, case),
        },
    )


def start_run(
    db: Session, *, set_id: str, payload_case_ids: list[str] | None, actor_user_id: str | None
) -> dict[str, Any]:
    test_set = _get_set(db, set_id)
    if test_set.status != "enabled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试集已停用，无法发起执行")
    wanted = {c for c in (payload_case_ids or []) if c}
    cases = [c for c in (test_set.cases or []) if c.enabled and (not wanted or c.id in wanted)]
    if not cases:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有可执行的启用用例")

    actor = _get_actor(db, actor_user_id)
    now = utcnow()
    run = FlTestSetRun(set_id=set_id, status="running", total_cases=len(cases), started_at=now, create_user=actor_user_id)
    db.add(run)
    db.flush()

    for case in cases:
        run_case = FlTestSetRunCase(run_id=run.id, case_id=case.id, status="pending")
        db.add(run_case)
        db.flush()
        try:
            request = _build_job_request(db, test_set, case)
            created = create_job(db, request, actor=actor)
            job = get_job_by_id(db, created.job.id)
            if not job:
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务创建后不可见")
            job.test_run_case_id = run_case.id
            run_case.job_id = job.id
            db.commit()
            try:
                start_job(db, job.id, actor=actor)
                run_case.status = "running"
            except HTTPException as exc:
                run_case.status = "failed"
                run_case.error_message = str(exc.detail)
            db.commit()
        except HTTPException as exc:
            run_case.status = "failed"
            run_case.error_message = str(exc.detail)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — 单用例失败不阻断其余用例
            run_case.status = "failed"
            run_case.error_message = str(exc)[:500]
            db.commit()

    db.refresh(run)
    sync_run(db, run)
    return serialize_run(db, run)


def sync_run(db: Session, run: FlTestSetRun) -> None:
    """按任务当前状态同步 run_case / run 聚合（幂等，读取时调用）。"""
    changed = False
    now = utcnow()
    for run_case in run.run_cases or []:
        if not run_case.job_id:
            continue
        job = db.execute(select(FlAnalysisJob).where(FlAnalysisJob.id == run_case.job_id)).scalar_one_or_none()
        if job is None:
            continue
        if job.status == "success":
            if run_case.status != "success":
                run_case.status = "success"
                changed = True
            if run_case.verdict not in _MANUAL_VERDICTS:
                verdict, eval_json = _auto_evaluate(db, run_case.case, job)
                if run_case.verdict != verdict:
                    run_case.verdict = verdict
                    run_case.eval_json = eval_json
                    changed = True
        elif job.status == "failed":
            if run_case.status != "failed":
                run_case.status = "failed"
                run_case.error_message = run_case.error_message or job.error_message
                changed = True
        elif job.status == "cancelled":
            if run_case.status not in {"cancelled", "skipped"}:
                run_case.status = "cancelled"
                changed = True
        elif job.status in {"pending", "queued", "running", "blocked"}:
            if run_case.status not in {"running", "cancelled", "skipped"}:
                run_case.status = "running"
                changed = True

    statuses = [rc.status for rc in (run.run_cases or [])]
    terminal_states = {"success", "failed", "skipped", "cancelled"}
    if statuses and all(s in terminal_states for s in statuses):
        success_count = sum(1 for s in statuses if s == "success")
        if run.status not in {"success", "partial", "failed"}:
            run.status = "success" if success_count == len(statuses) else ("failed" if success_count == 0 else "partial")
            run.finished_at = now
            run.duration_ms = int((now - run.started_at).total_seconds() * 1000) if run.started_at else None
            changed = True
    elif run.status == "pending" and statuses:
        run.status = "running"
        changed = True

    if changed:
        db.commit()


def _run_case_counts(run_cases: list[FlTestSetRunCase]) -> dict[str, int]:
    return {
        "finished_cases": sum(1 for rc in run_cases if rc.status in {"success", "failed", "skipped", "cancelled"}),
        "passed_cases": sum(1 for rc in run_cases if rc.verdict in _PASS_VERDICTS),
        "failed_cases": sum(1 for rc in run_cases if rc.verdict in _FAIL_VERDICTS),
        "pending_manual_cases": sum(1 for rc in run_cases if rc.verdict == "pending_manual"),
    }


def serialize_run(db: Session, run: FlTestSetRun) -> dict[str, Any]:
    run_cases = sorted(run.run_cases or [], key=lambda rc: (rc.create_date is not None, rc.create_date or utcnow(), rc.id))
    job_ids = [rc.job_id for rc in run_cases if rc.job_id]
    jobs: dict[str, FlAnalysisJob] = {}
    if job_ids:
        rows = db.execute(select(FlAnalysisJob).where(FlAnalysisJob.id.in_(job_ids))).scalars().all()
        jobs = {j.id: j for j in rows}
    case_names = {rc.case_id: (rc.case.name if rc.case else "") or "" for rc in run_cases}
    items = []
    for rc in run_cases:
        job = jobs.get(rc.job_id or "")
        case = rc.case
        items.append(
            {
                "id": rc.id,
                "run_id": rc.run_id,
                "case_id": rc.case_id,
                "case_name": (case.name if case else "") or case_names.get(rc.case_id, ""),
                "job_id": rc.job_id,
                "job_name": job.job_name if job else None,
                "job_type": job.job_type if job else None,
                "job_status": job.status if job else None,
                "status": rc.status,
                "verdict": rc.verdict,
                "eval_json": dict(rc.eval_json or {}),
                "error_message": rc.error_message,
                "create_date": rc.create_date,
                "update_date": rc.update_date,
            }
        )
    counts = _run_case_counts(run.run_cases or [])
    return {
        "id": run.id,
        "set_id": run.set_id,
        "status": run.status,
        "total_cases": run.total_cases,
        **counts,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "result_summary_json": dict(run.result_summary_json or {}),
        "create_date": run.create_date,
        "create_user": run.create_user,
        "cases": items,
    }


def list_runs(db: Session, *, set_id: str, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    _get_set(db, set_id)
    total = int(
        db.scalar(select(func.count()).select_from(FlTestSetRun).where(FlTestSetRun.set_id == set_id)) or 0
    )
    run_rows = db.execute(
        select(FlTestSetRun)
        .where(FlTestSetRun.set_id == set_id)
        .order_by(FlTestSetRun.create_date.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    for run in run_rows:
        sync_run(db, run)
    items = []
    for run in run_rows:
        data = serialize_run(db, run)
        data.pop("cases", None)  # 列表页不带用例明细，详情再取
        items.append(data)
    return {"items": items, "total": total}


def get_run(db: Session, *, run_id: str) -> dict[str, Any]:
    run = _get_run(db, run_id)
    sync_run(db, run)
    return serialize_run(db, run)


def cancel_run(db: Session, *, run_id: str, actor_user_id: str | None) -> dict[str, Any]:
    run = _get_run(db, run_id)
    actor = _get_actor(db, actor_user_id)
    for run_case in run.run_cases or []:
        if run_case.status in {"success", "failed", "skipped", "cancelled"}:
            continue
        if run_case.job_id:
            job = get_job_by_id(db, run_case.job_id)
            if job and job.status in {"pending", "queued", "running", "blocked"}:
                try:
                    cancel_job(db, job_id=job.id, actor=actor)
                except HTTPException:
                    pass
        run_case.status = "cancelled"
    run.status = "cancelled"
    run.finished_at = utcnow()
    if run.started_at:
        run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    db.commit()
    db.refresh(run)
    return serialize_run(db, run)


def rerun_run_case(db: Session, *, run_case_id: str, actor_user_id: str | None) -> dict[str, Any]:
    run_case = _get_run_case(db, run_case_id)
    run = _get_run(db, run_case.run_id)
    test_set = _get_set(db, run.set_id)
    case = run_case.case
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="原用例已删除，无法重跑")
    if test_set.status != "enabled":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="测试集已停用，无法重跑")
    actor = _get_actor(db, actor_user_id)
    request = _build_job_request(db, test_set, case)
    created = create_job(db, request, actor=actor)
    job = get_job_by_id(db, created.job.id)
    if not job:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务创建后不可见")
    job.test_run_case_id = run_case.id
    run_case.job_id = job.id
    run_case.status = "running"
    run_case.verdict = None
    run_case.eval_json = {}
    run_case.error_message = None
    # run 回到运行中（重跑会把已收敛的 run 重新打开）
    run.status = "running"
    run.finished_at = None
    run.duration_ms = None
    db.commit()
    try:
        start_job(db, job.id, actor=actor)
        run_case.status = "running"
    except HTTPException as exc:
        run_case.status = "failed"
        run_case.error_message = str(exc.detail)
    db.commit()
    db.refresh(run)
    return serialize_run(db, run)


def set_verdict(
    db: Session, *, run_case_id: str, payload: FlTestVerdictRequest, actor_user_id: str | None
) -> dict[str, Any]:
    run_case = _get_run_case(db, run_case_id)
    run_case.verdict = payload.verdict
    if payload.comment:
        eval_json = dict(run_case.eval_json or {})
        eval_json["manual_comment"] = payload.comment
        eval_json["manual_by"] = actor_user_id
        run_case.eval_json = eval_json
    db.commit()
    run = _get_run(db, run_case.run_id)
    sync_run(db, run)
    return serialize_run(db, run)


# ─────────────────────────── 自动评估 ───────────────────────────


def _flat_values(payload: Any, prefix: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    """递归摊平 dict/list（深度 3），产出 (键路径, 值) 列表，供容错指标查找。"""
    pairs: list[tuple[str, Any]] = []
    if depth > 3:
        return pairs
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            pairs.append((path, value))
            pairs.extend(_flat_values(value, path, depth + 1))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            pairs.extend(_flat_values(value, prefix, depth + 1))
    return pairs


def _find_value(flat: list[tuple[str, Any]], key: str, scope: str | None = None) -> Any:
    candidates = [v for p, v in flat if p == key or p.endswith(f".{key}")]
    if scope:
        scoped = [v for p, v in flat if scope in p and p.endswith(f".{key}")]
        if scoped:
            return scoped[0]
    return candidates[0] if candidates else None


def _collect_job_flat(db: Session, job: FlAnalysisJob) -> list[tuple[str, Any]]:
    flat: list[tuple[str, Any]] = list(_flat_values(job.result_summary_json or {}))
    stmt = select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == job.id)
    if job.latest_run_id:
        stmt = stmt.where(FlAnalysisTowerResult.run_id == job.latest_run_id)
    for row in db.execute(stmt).scalars().all():
        flat.extend(_flat_values(row.result_json or {}))
    return flat


def _compare_metric(check: dict[str, Any]) -> bool | None:
    actual = check.get("actual")
    if actual is None or (isinstance(actual, str) and not actual.strip()):
        return None
    lo = check.get("min")
    hi = check.get("max")
    if lo is not None or hi is not None:
        try:
            value = float(actual)
        except (TypeError, ValueError):
            return None
        ok = True
        if lo is not None:
            ok = ok and value >= float(lo)
        if hi is not None:
            ok = ok and value <= float(hi)
        return ok
    expect = check.get("expect")
    if expect is not None:
        return str(expect).strip().lower() in str(actual).strip().lower()
    return None


def _evaluate_metrics(case: FlTestSetCase, flat: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    expected = dict(case.expected_json or {})
    checks: list[dict[str, Any]] = []
    for metric in expected.get("metrics") or []:
        if not isinstance(metric, dict) or not metric.get("key"):
            continue
        key = str(metric["key"])
        actual = _find_value(flat, key, metric.get("scope"))
        check = {
            "key": key,
            "label": metric.get("label") or key,
            "min": metric.get("min"),
            "max": metric.get("max"),
            "expect": metric.get("expect"),
            "scope": metric.get("scope"),
            "actual": actual,
        }
        check["pass"] = _compare_metric(check)
        checks.append(check)
    return checks


def _evaluate_retrofit_plan(case: FlTestSetCase, flat: list[tuple[str, Any]]) -> list[dict[str, Any]]:
    expected = dict(case.expected_json or {})
    plan = expected.get("plan") if isinstance(expected.get("plan"), dict) else expected
    checks: list[dict[str, Any]] = []
    text_blob = " | ".join(str(v) for _, v in flat if isinstance(v, (str, int, float)))

    terminal = plan.get("expected_terminal")
    if terminal:
        actual_terminal = _find_value(flat, "terminal_state") or _find_value(flat, "state")
        norm = lambda v: str(v or "").strip().lower().lstrip("s")  # noqa: E731
        checks.append(
            {
                "key": "expected_terminal",
                "label": "期望终态",
                "expect": terminal,
                "actual": actual_terminal,
                "pass": (None if actual_terminal is None else norm(actual_terminal) == norm(terminal)),
            }
        )
    for key, label, should_contain in (
        ("expected_measures", "期望措施", True),
        ("unexpected_measures", "不应出现的措施", False),
    ):
        measures = plan.get(key) or []
        if not measures:
            continue
        missing = [str(m) for m in measures if str(m) not in text_blob]
        if should_contain:
            checks.append(
                {"key": key, "label": label, "expect": measures, "actual": "命中" if not missing else f"缺少：{'、'.join(missing)}", "pass": not missing}
            )
        else:
            found = [str(m) for m in measures if str(m) in text_blob]
            checks.append(
                {"key": key, "label": label, "expect": f"不出现：{'、'.join(measures)}", "actual": "未出现" if not found else f"出现：{'、'.join(found)}", "pass": not found}
            )
    direction = plan.get("risk_direction")
    if direction:
        checks.append({"key": "risk_direction", "label": "风险变化方向", "expect": direction, "actual": None, "pass": None})
    return checks


def _auto_evaluate(db: Session, case: FlTestSetCase | None, job: FlAnalysisJob) -> tuple[str, dict[str, Any]]:
    """容错自动评估：数值区间/包含匹配；取不到值 → pending_manual。"""
    if case is None:
        return "pending_manual", {"checks": [], "comment": "用例已删除，仅支持人工判定"}
    flat = _collect_job_flat(db, job)
    if case.expected_json and (case.expected_json.get("metrics") or case.expected_json.get("plan")):
        if case.expected_json.get("metrics"):
            checks = _evaluate_metrics(case, flat)
        else:
            checks = _evaluate_retrofit_plan(case, flat)
    else:
        checks = []
    if not checks:
        return "pending_manual", {"checks": [], "comment": "用例未配置评估标准，请人工判定"}
    results = [c.get("pass") for c in checks]
    eval_json = {
        "checks": checks,
        "evaluated_at": utcnow().isoformat(),
        "abnormal_signals": list((case.expected_json or {}).get("abnormal_signals") or []),
    }
    if any(r is False for r in results):
        return "auto_fail", eval_json
    if all(r is True for r in results):
        return "auto_pass", eval_json
    return "pending_manual", eval_json
