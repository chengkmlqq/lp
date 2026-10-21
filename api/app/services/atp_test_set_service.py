"""ATP 测试集（test set）服务。

分层：测试集（atp_test_set）→ 用例（atp_test_set_case，绑定资产+计算类型+参数快照）
→ 执行（atp_test_set_run，聚合用例级 atp_asset_run）。

执行完全复用「单模型测试」管线（atp_asset_test_service.create_test_run，
materialize → geometry → simulate），每个用例一条 atp_asset_run，
统一写入 ``batch_id = <set_run 的 batch_marker>`` 与
``test_set_id / test_set_run_id / test_set_case_id / job_kind`` 元数据
（见 models.atp_test_set.TEST_SET_RUN_META_KEYS，worker 重建 JSON 时保留），
聚合/回归对比按这些标记查询，不引入新的执行代码路径。
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter, defaultdict
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..models.atp_test_set import AtpTestSet, AtpTestSetCase, AtpTestSetRun
from ..models.base import utcnow
from ..schemas.atp_asset import AtpAssetTestRunRequest
from ..schemas.atp_test_set import (
    AtpTestSetCaseCreateRequest,
    AtpTestSetCaseReorderRequest,
    AtpTestSetCaseUpdateRequest,
    AtpTestSetCreateRequest,
    AtpTestSetExecuteRequest,
    AtpTestSetUpdateRequest,
)

JOB_KIND_LABELS = {"normal": "普通计算", "tongtiao": "同跳计算"}
_BATCH_PREFIX = "setrun"


# ─────────────────────────── 基础查询 ───────────────────────────


def get_set_by_id(db: Session, set_id: str) -> AtpTestSet | None:
    return db.execute(
        select(AtpTestSet).where(AtpTestSet.id == set_id)
    ).scalar_one_or_none()


def get_case_by_id(db: Session, case_id: str) -> AtpTestSetCase | None:
    return db.execute(
        select(AtpTestSetCase).where(AtpTestSetCase.id == case_id)
    ).scalar_one_or_none()


def _case_summary(case: AtpTestSetCase) -> dict[str, Any]:
    asset = case.asset
    return {
        "id": case.id,
        "set_id": case.set_id,
        "asset_id": case.asset_id,
        "asset_code": getattr(asset, "code", "") or "",
        "asset_name": getattr(asset, "name", "") or "",
        "voltage_level": getattr(asset, "voltage_level", None),
        "tower_type": getattr(asset, "tower_type", None),
        "scene_type": getattr(asset, "scene_type", None),
        "arrester_config": getattr(asset, "arrester_config", None),
        "job_kind": case.job_kind,
        "name": case.name or "",
        "description": case.description or "",
        "params_json": case.params_json or {},
        "expected_json": case.expected_json or {},
        "enabled": case.enabled,
        "sort_order": case.sort_order,
        "create_date": case.create_date,
        "update_date": case.update_date,
    }


# ─────────────────────────── 测试集 CRUD ───────────────────────────


def list_sets(
    db: Session, *, limit: int = 50, offset: int = 0, keyword: str | None = None
) -> dict[str, Any]:
    stmt = select(AtpTestSet)
    if keyword and keyword.strip():
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(AtpTestSet.name.ilike(kw), AtpTestSet.description.ilike(kw)))
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar() or 0
    rows = (
        db.execute(
            stmt.order_by(AtpTestSet.update_date.desc()).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )
    items = [serialize_set_summary(db, row) for row in rows]
    return {"items": items, "total": total}


def serialize_set_summary(db: Session, row: AtpTestSet) -> dict[str, Any]:
    cases = row.cases or []
    enabled = [c for c in cases if c.enabled]
    last_run: dict[str, Any] | None = None
    if row.runs:
        latest = row.runs[0]
        last_run = {
            "run_id": latest.id,
            "status": latest.status,
            "create_date": latest.create_date,
            "total_cases": latest.total_cases,
        }
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "status": row.status,
        "tags_json": row.tags_json or [],
        "case_count": len(cases),
        "enabled_case_count": len(enabled),
        "last_run": last_run,
        "create_date": row.create_date,
        "create_user": row.create_user,
        "update_date": row.update_date,
        "update_user": row.update_user,
    }


def create_set(
    db: Session, *, payload: AtpTestSetCreateRequest, actor_user_id: str | None
) -> dict[str, Any]:
    row = AtpTestSet(
        name=payload.name.strip(),
        description=payload.description or "",
        status=payload.status,
        tags_json=list(payload.tags_json or []),
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_set_summary(db, row)


def update_set(
    db: Session,
    *,
    set_id: str,
    payload: AtpTestSetUpdateRequest,
    actor_user_id: str | None,
) -> dict[str, Any]:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.description is not None:
        row.description = payload.description
    if payload.status is not None:
        row.status = payload.status
    if payload.tags_json is not None:
        row.tags_json = list(payload.tags_json)
    row.update_user = actor_user_id
    row.update_date = utcnow()
    db.commit()
    db.refresh(row)
    return serialize_set_summary(db, row)


def delete_set(db: Session, *, set_id: str) -> None:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    db.delete(row)  # cascade 删除用例与执行记录（FK ON DELETE CASCADE 兜底）
    db.commit()


# ─────────────────────────── 用例 CRUD ───────────────────────────


def list_cases(db: Session, *, set_id: str) -> dict[str, Any]:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    cases = db.execute(
        select(AtpTestSetCase)
        .options(joinedload(AtpTestSetCase.asset))
        .where(AtpTestSetCase.set_id == set_id)
        .order_by(AtpTestSetCase.sort_order.asc(), AtpTestSetCase.create_date.asc())
    ).scalars().all()
    return {"items": [_case_summary(c) for c in cases], "total": len(cases)}


def create_case(
    db: Session,
    *,
    set_id: str,
    payload: AtpTestSetCaseCreateRequest,
    actor_user_id: str | None,
) -> dict[str, Any]:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    if payload.sort_order is None:
        max_order = (
            db.execute(
                select(func.max(AtpTestSetCase.sort_order)).where(
                    AtpTestSetCase.set_id == set_id
                )
            ).scalar()
            or 0
        )
        sort_order = int(max_order) + 1
    else:
        sort_order = int(payload.sort_order)
    case = AtpTestSetCase(
        set_id=set_id,
        asset_id=payload.asset_id,
        job_kind=payload.job_kind,
        name=(payload.name or "").strip(),
        description=payload.description or "",
        params_json=dict(payload.params_json or {}),
        expected_json=dict(payload.expected_json or {}),
        enabled=payload.enabled,
        sort_order=sort_order,
        create_user=actor_user_id,
        update_user=actor_user_id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    # 确保 asset 关系已加载（serialize 需要）
    case = db.execute(
        select(AtpTestSetCase)
        .options(joinedload(AtpTestSetCase.asset))
        .where(AtpTestSetCase.id == case.id)
    ).scalar_one()
    return _case_summary(case)


def update_case(
    db: Session,
    *,
    case_id: str,
    payload: AtpTestSetCaseUpdateRequest,
    actor_user_id: str | None,
) -> dict[str, Any]:
    case = get_case_by_id(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")
    if payload.asset_id is not None:
        case.asset_id = payload.asset_id
    if payload.job_kind is not None:
        case.job_kind = payload.job_kind
    if payload.name is not None:
        case.name = (payload.name or "").strip()
    if payload.description is not None:
        case.description = payload.description
    if payload.params_json is not None:
        case.params_json = dict(payload.params_json)
    if payload.expected_json is not None:
        case.expected_json = dict(payload.expected_json)
    if payload.enabled is not None:
        case.enabled = payload.enabled
    if payload.sort_order is not None:
        case.sort_order = int(payload.sort_order)
    case.update_user = actor_user_id
    case.update_date = utcnow()
    db.commit()
    case = db.execute(
        select(AtpTestSetCase)
        .options(joinedload(AtpTestSetCase.asset))
        .where(AtpTestSetCase.id == case_id)
    ).scalar_one()
    return _case_summary(case)


def delete_case(db: Session, *, case_id: str) -> None:
    case = get_case_by_id(db, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试用例不存在")
    db.delete(case)
    db.commit()


def reorder_cases(
    db: Session, *, set_id: str, payload: AtpTestSetCaseReorderRequest
) -> dict[str, Any]:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    ordered_ids = list(payload.case_ids or [])
    cases = db.execute(
        select(AtpTestSetCase).where(AtpTestSetCase.set_id == set_id)
    ).scalars().all()
    by_id = {c.id: c for c in cases}
    unknown = [cid for cid in ordered_ids if cid not in by_id]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"用例不属于该测试集：{unknown[:5]}",
        )
    rank = {cid: idx for idx, cid in enumerate(ordered_ids)}
    for c in cases:
        if c.id in rank:
            c.sort_order = rank[c.id]
    # 未列出的用例按原 sort_order 排在指定顺序之后
    tail = sorted((c for c in cases if c.id not in rank), key=lambda c: c.sort_order)
    for idx, c in enumerate(tail):
        c.sort_order = len(ordered_ids) + idx
    db.commit()
    return list_cases(db, set_id=set_id)


# ─────────────────────────── 执行测试集 ───────────────────────────


def _build_case_run_payload(
    case: AtpTestSetCase, *, timeout_seconds: int | None, dry_run: bool
) -> AtpAssetTestRunRequest:
    """把用例参数快照还原成单模型测试请求。

    缺省值与单模型测试保持一致（stages 默认全跑、current_ka 默认 31），
    显式给过的字段不允许被覆盖。execute 级 timeout/dry_run 仅在用例未显式
    指定时生效。
    """
    params = dict(case.params_json or {})
    if timeout_seconds is not None and not params.get("timeout_seconds"):
        params["timeout_seconds"] = int(timeout_seconds)
    if dry_run:
        params["dry_run"] = True
    return AtpAssetTestRunRequest.model_validate(params)


def execute_set(
    db: Session,
    *,
    set_id: str,
    payload: AtpTestSetExecuteRequest,
    actor_user_id: str | None,
) -> dict[str, Any]:
    """发起一次测试集执行：逐用例 create_test_run（复用单模型测试管线）。"""
    from .atp_asset_service import get_asset_by_id
    from .atp_asset_test_service import create_test_run

    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")

    all_cases = db.execute(
        select(AtpTestSetCase)
        .options(joinedload(AtpTestSetCase.asset))
        .where(AtpTestSetCase.set_id == set_id)
        .order_by(AtpTestSetCase.sort_order.asc(), AtpTestSetCase.create_date.asc())
    ).scalars().all()
    if not all_cases:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="测试集还没有用例，请先添加用例"
        )

    requested = set(payload.case_ids or [])
    if requested:
        unknown = [cid for cid in requested if cid not in {c.id for c in all_cases}]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"用例不属于该测试集：{unknown[:5]}",
            )
        target_cases = [c for c in all_cases if c.id in requested]
    else:
        target_cases = [c for c in all_cases if c.enabled]
    if not target_cases:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="没有可执行的用例（全部被禁用或未勾选）",
        )

    # 资产有效性前置校验：避免部分成功后才发现某用例的资产被删
    errors: list[dict[str, Any]] = []
    for case in target_cases:
        if get_asset_by_id(db, case.asset_id) is None:
            errors.append(
                {
                    "case_id": case.id,
                    "asset_id": case.asset_id,
                    "job_kind": case.job_kind,
                    "error": f"用例绑定的 ATP 资产不存在：{case.asset_id}",
                }
            )
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="存在无效用例（资产已被删除）："
            + "；".join(f"{e['case_id']}({e['error']})" for e in errors[:5]),
        )

    run = AtpTestSetRun(
        set_id=set_id,
        status="running",
        total_cases=len(target_cases),
        batch_marker=f"{_BATCH_PREFIX}-{uuid4().hex[:16]}",
        started_at=utcnow(),
        create_user=actor_user_id,
        result_summary_json={"launched": 0, "errors": []},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    launched = 0
    for case in target_cases:
        try:
            single_payload = _build_case_run_payload(
                case, timeout_seconds=payload.timeout_seconds, dry_run=payload.dry_run
            )
            create_test_run(
                db,
                asset_id=case.asset_id,
                payload=single_payload,
                actor_user_id=actor_user_id,
                batch_id=run.batch_marker,
                extra_meta={
                    "test_set_id": set_id,
                    "test_set_run_id": run.id,
                    "test_set_case_id": case.id,
                    "test_set_case_name": (case.name or "").strip() or case.asset_id,
                    "job_kind": case.job_kind,
                },
            )
            launched += 1
        except HTTPException as exc:
            errors.append({"case_id": case.id, "error": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001 - 单用例失败不阻断整批
            errors.append({"case_id": case.id, "error": str(exc)})

    run.result_summary_json = {"launched": launched, "errors": errors}
    run.update_date = utcnow()
    if launched == 0:
        # 全部派发失败：直接标记失败，不留在 running 状态等不到结果
        run.status = "failed"
        run.finished_at = utcnow()
        run.error_message = "全部用例派发失败：" + "；".join(
            str(e.get("error", "")) for e in errors[:5]
        )
    db.commit()
    db.refresh(run)

    return {
        "run_id": run.id,
        "set_id": set_id,
        "batch_marker": run.batch_marker,
        "status": run.status,
        "total_cases": run.total_cases,
        "launched": launched,
        "skipped": len(target_cases) - launched,
        "errors": errors,
    }


# ─────────────────────────── 执行记录查询/报告/回归对比 ───────────────────────────


def _runs_by_marker(db: Session, marker: str) -> list:
    """该执行批次的所有用例级 atp_asset_run（按创建时间升序）。"""
    from ..models.atp_asset import AtpAssetRun

    return db.execute(
        select(AtpAssetRun)
        .options(joinedload(AtpAssetRun.asset))
        .where(AtpAssetRun.result_summary_json["batch_id"].as_string() == marker)
        .order_by(AtpAssetRun.create_date.asc())
    ).scalars().all()


def _flashover_of(run_summary: dict[str, Any]) -> tuple[int | None, list[str]]:
    """从 atp_asset_run 的 result_summary_json 取闪络相数与相列表。"""
    summary = run_summary.get("result_summary_json") or {}
    stages = summary.get("stages") if isinstance(summary.get("stages"), dict) else {}
    sim = stages.get("simulate") if isinstance(stages, dict) else None
    metrics = sim.get("metrics") if isinstance(sim, dict) else {}
    fc = metrics.get("flashover_count")
    phases = metrics.get("flashover_phases") if isinstance(metrics.get("flashover_phases"), list) else []
    return (int(fc) if isinstance(fc, (int, float)) else None), [str(p) for p in phases]


def _case_flashover_from_run(run) -> tuple[int | None, list[str]]:
    summary = run.result_summary_json or {}
    stages = summary.get("stages") if isinstance(summary.get("stages"), dict) else {}
    sim = stages.get("simulate") if isinstance(stages, dict) else None
    metrics = sim.get("metrics") if isinstance(sim, dict) else {}
    fc = metrics.get("flashover_count")
    phases = metrics.get("flashover_phases") if isinstance(metrics.get("flashover_phases"), list) else []
    return (int(fc) if isinstance(fc, (int, float)) else None), [str(p) for p in phases]


def _current_ka_of(run) -> float | None:
    payload = (run.result_summary_json or {}).get("compare") or {}
    case_info = payload.get("case") or {}
    raw = case_info.get("current_ka") if isinstance(case_info, dict) else None
    if raw is None:
        sim = (run.result_summary_json or {}).get("stages") or {}
        sim_stage = sim.get("simulate") or {}
        raw = (sim_stage.get("metrics") or {}).get("current_ka")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def get_set_run(db: Session, *, run_id: str) -> dict[str, Any]:
    """执行批次详情：用例级结果 + 分组报告 + 与上一执行的回归对比。"""
    run = db.execute(
        select(AtpTestSetRun).where(AtpTestSetRun.id == run_id)
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集执行记录不存在")

    test_set = run.test_set
    marker = run.batch_marker or ""
    case_runs = _runs_by_marker(db, marker) if marker else []
    dispatch_errors = (run.result_summary_json or {}).get("errors") or []

    # 用例归属映射（case_id → case；用例被删后仍有 run 记录兜底）
    case_map: dict[str, AtpTestSetCase] = {}
    if test_set is not None:
        case_map = {c.id: c for c in (test_set.cases or [])}

    items: list[dict[str, Any]] = []
    for cr in case_runs:
        meta = cr.result_summary_json or {}
        case_id = str(meta.get("test_set_case_id") or "")
        case = case_map.get(case_id)
        job_kind = str(meta.get("job_kind") or (case.job_kind if case else "normal"))
        asset = cr.asset
        flashover, phases = _case_flashover_from_run(cr)
        items.append(
            {
                "run_id": cr.id,
                "case_id": case_id,
                "case_name": str(meta.get("test_set_case_name") or (case.name if case else "") or case_id),
                "asset_id": cr.asset_id,
                "asset_code": getattr(asset, "code", "") or cr.asset_id,
                "asset_name": getattr(asset, "name", "") or cr.asset_id,
                "voltage_level": getattr(asset, "voltage_level", None),
                "tower_type": getattr(asset, "tower_type", None),
                "scene_type": getattr(asset, "scene_type", None),
                "arrester_config": getattr(asset, "arrester_config", None),
                "job_kind": job_kind,
                "status": cr.status,
                "duration_ms": cr.duration_ms,
                "error_message": cr.error_message,
                "flashover_count": flashover,
                "flashover_phases": phases,
                "current_ka": _current_ka_of(cr),
                "result_summary_json": cr.result_summary_json or {},
                "previous": None,
            }
        )
    # 派发即失败的用例（无 run 记录）补成 failed 项
    launched_ids = {it["case_id"] for it in items if it["case_id"]}
    for err in dispatch_errors:
        cid = str(err.get("case_id") or "")
        if not cid or cid in launched_ids:
            continue
        case = case_map.get(cid)
        items.append(
            {
                "run_id": None,
                "case_id": cid,
                "case_name": (case.name if case else "") or cid,
                "asset_id": getattr(case, "asset_id", "") if case else "",
                "asset_code": getattr(getattr(case, "asset", None), "code", "") if case else "",
                "asset_name": getattr(getattr(case, "asset", None), "name", "") if case else "",
                "voltage_level": getattr(getattr(case, "asset", None), "voltage_level", None) if case else None,
                "tower_type": getattr(getattr(case, "asset", None), "tower_type", None) if case else None,
                "scene_type": getattr(getattr(case, "asset", None), "scene_type", None) if case else None,
                "arrester_config": getattr(getattr(case, "asset", None), "arrester_config", None) if case else None,
                "job_kind": getattr(case, "job_kind", "normal") if case else "normal",
                "status": "failed",
                "duration_ms": None,
                "error_message": str(err.get("error") or "派发失败"),
                "flashover_count": None,
                "flashover_phases": [],
                "current_ka": None,
                "result_summary_json": {},
                "previous": None,
            }
        )

    # 计数 + 报告
    counts = {"pending": 0, "running": 0, "success": 0, "failed": 0}
    for it in items:
        st = it["status"] or "pending"
        counts[st if st in counts else "failed"] += 1
    all_done = (counts["pending"] + counts["running"]) == 0 and bool(items)
    if all_done and run.status != "failed":
        run.status = "success" if counts["failed"] == 0 else "failed"
        if run.finished_at is None:
            run.finished_at = utcnow()
            if run.started_at is not None:
                run.duration_ms = max(
                    int((run.finished_at - run.started_at).total_seconds() * 1000), 0
                )
        run.update_date = utcnow()
        db.commit()
    elif not all_done and run.status == "failed":
        # 全部派发失败时 run 已是 failed，但 items 可能为空 → 保持 failed
        pass

    report = _build_set_run_report(items)
    regression, has_previous = _build_regression(db, run=run, items=items)
    report["regression"] = regression

    return {
        "run_id": run.id,
        "set_id": run.set_id,
        "set_name": test_set.name if test_set else "",
        "status": run.status,
        "batch_marker": marker,
        "total_cases": run.total_cases,
        "counts": counts,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_ms": run.duration_ms,
        "error_message": run.error_message,
        "create_user": run.create_user,
        "create_date": run.create_date,
        "update_date": run.update_date,
        "report": report,
        "items": items,
        "has_previous_run": has_previous,
    }


def _build_set_run_report(items: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "success": 0, "failed": 0, "flashover_counts": Counter()}
    )
    failure_reasons: Counter[str] = Counter()
    flashover_total: Counter[str] = Counter()

    for it in items:
        key = " / ".join(
            [
                JOB_KIND_LABELS.get(str(it.get("job_kind") or ""), str(it.get("job_kind") or "-")),
                str(it.get("voltage_level") or "-"),
                str(it.get("tower_type") or "-"),
                str(it.get("scene_type") or "-"),
            ]
        )
        g = groups[key]
        g["total"] += 1
        if it.get("status") == "success":
            g["success"] += 1
        elif it.get("status") == "failed":
            g["failed"] += 1
            reason = (str(it.get("error_message") or "未知错误")).splitlines()[0][:120]
            failure_reasons[reason] += 1
        fc = it.get("flashover_count")
        if fc is not None:
            flashover_total[str(fc)] += 1
            g["flashover_counts"][str(fc)] += 1

    group_report = []
    for key, g in sorted(groups.items()):
        total = g["total"]
        group_report.append(
            {
                "group": key,
                "total": total,
                "success": g["success"],
                "failed": g["failed"],
                "pass_rate": round(g["success"] / total * 100, 1) if total else 0,
                "flashover_count_distribution": {
                    str(k): v for k, v in sorted(g["flashover_counts"].items())
                },
            }
        )

    return {
        "overall_pass_rate": round(
            sum(g["success"] for g in groups.values()) / len(items) * 100, 1
        )
        if items
        else 0,
        "counts": {
            k: sum(1 for it in items if it.get("status") == k)
            for k in ("pending", "running", "success", "failed")
        },
        "groups": group_report,
        "failure_reasons_top": [
            {"reason": r, "count": c} for r, c in failure_reasons.most_common(10)
        ],
        "regression": {},
    }


def _build_regression(
    db: Session, *, run: AtpTestSetRun, items: list[dict[str, Any]]
) -> tuple[dict[str, Any], bool]:
    """与「上一次执行」逐用例对比：状态变化 + 闪络相数变化。"""
    prev_run = db.execute(
        select(AtpTestSetRun)
        .where(
            AtpTestSetRun.set_id == run.set_id,
            AtpTestSetRun.id != run.id,
            AtpTestSetRun.status.in_(("success", "failed")),
        )
        .order_by(AtpTestSetRun.create_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if prev_run is None or not prev_run.batch_marker:
        return _empty_regression(), False

    prev_items: dict[str, dict[str, Any]] = {}
    for pr in _runs_by_marker(db, prev_run.batch_marker):
        meta = pr.result_summary_json or {}
        cid = str(meta.get("test_set_case_id") or "")
        if not cid:
            continue
        fc, phases = _case_flashover_from_run(pr)
        prev_items[cid] = {
            "status": pr.status,
            "flashover_count": fc,
            "flashover_phases": phases,
        }

    stats = {"unchanged": 0, "changed": 0, "regressed": 0, "improved": 0, "flashover_changed": 0}
    for it in items:
        cid = str(it.get("case_id") or "")
        prev = prev_items.get(cid)
        if prev is None:
            continue
        same_status = prev["status"] == it.get("status")
        same_flashover = prev["flashover_count"] == it.get("flashover_count")
        it["previous"] = {
            "run_id": prev_run.id,
            "status": prev["status"],
            "flashover_count": prev["flashover_count"],
            "flashover_phases": prev["flashover_phases"],
        }
        if same_status and same_flashover:
            stats["unchanged"] += 1
            continue
        stats["changed"] += 1
        if not same_flashover and prev["flashover_count"] is not None:
            stats["flashover_changed"] += 1
        if prev["status"] == "success" and it.get("status") != "success":
            stats["regressed"] += 1
        elif prev["status"] != "success" and it.get("status") == "success":
            stats["improved"] += 1

    report = _empty_regression()
    report.update({"counts": stats})
    return report, True


def _empty_regression() -> dict[str, Any]:
    return {
        "counts": {
            "first_run": 0,
            "unchanged": 0,
            "changed": 0,
            "regressed": 0,
            "improved": 0,
            "flashover_changed": 0,
        }
    }


def list_set_runs(
    db: Session, *, set_id: str, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    row = get_set_by_id(db, set_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="测试集不存在")
    total = (
        db.execute(
            select(func.count())
            .select_from(AtpTestSetRun)
            .where(AtpTestSetRun.set_id == set_id)
        ).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(AtpTestSetRun)
            .where(AtpTestSetRun.set_id == set_id)
            .order_by(AtpTestSetRun.create_date.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = []
    for r in rows:
        counts = {"pending": 0, "running": 0, "success": 0, "failed": 0}
        if r.batch_marker:
            for cr in _runs_by_marker(db, r.batch_marker):
                st = cr.status or "pending"
                counts[st if st in counts else "failed"] += 1
        all_done = (counts["pending"] + counts["running"]) == 0 and (
            counts["success"] + counts["failed"] > 0
        )
        items.append(
            {
                "run_id": r.id,
                "set_id": r.set_id,
                "set_name": row.name,
                "status": ("success" if counts["failed"] == 0 else "failed") if all_done else r.status,
                "batch_marker": r.batch_marker,
                "total_cases": r.total_cases,
                "counts": counts,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "duration_ms": r.duration_ms,
                "error_message": r.error_message,
                "create_user": r.create_user,
                "create_date": r.create_date,
                "update_date": r.update_date,
                "report": None,
                "items": [],
                "has_previous_run": False,
            }
        )
    return {"items": items, "total": total}


# ─────────────────────────── 报告下载 ───────────────────────────


def build_set_run_report_zip(db: Session, *, run_id: str) -> tuple[bytes, str]:
    """生成测试集执行报告包：report.xlsx(多 Sheet) + detail.csv + report.json。

    失败时回退纯 JSON zip（openpyxl 不可用等）。
    """
    summary = get_set_run(db, run_id=run_id)
    report = summary.get("report") or {}
    items = summary.get("items") or []
    counts = summary.get("counts") or {}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font

            wb = Workbook()
            ws = wb.active
            ws.title = "汇总"
            ws.append(["测试集执行报告", ""])
            ws.append(["执行批次", summary.get("run_id", "")])
            ws.append(["测试集", summary.get("set_name", "")])
            ws.append(["状态", summary.get("status", "")])
            ws.append(["总数", summary.get("total_cases", 0)])
            ws.append(["成功", counts.get("success", 0)])
            ws.append(["失败", counts.get("failed", 0)])
            ws.append(["通过率(%)", report.get("overall_pass_rate", 0)])
            reg_counts = (report.get("regression") or {}).get("counts") or {}
            ws.append(["回归-变更", reg_counts.get("changed", 0)])
            ws.append(["回归-回退", reg_counts.get("regressed", 0)])
            # ⚠️ TIMESTAMPTZ 带 tzinfo，openpyxl 拒绝写入 → 先转 ISO 字符串
            ws.append(["发起时间", _fmt_dt(summary.get("create_date"))])
            ws.append(["完成时间", _fmt_dt(summary.get("finished_at"))])
            for cell in ws[1]:
                cell.font = Font(bold=True, size=14)

            ws2 = wb.create_sheet("分组通过率")
            ws2.append(["计算类型/电压/塔型/场景", "总数", "成功", "失败", "通过率(%)", "闪络相数分布"])
            for g in report.get("groups", []):
                ws2.append(
                    [
                        g.get("group"),
                        g.get("total"),
                        g.get("success"),
                        g.get("failed"),
                        g.get("pass_rate"),
                        str(g.get("flashover_count_distribution") or {}),
                    ]
                )

            ws3 = wb.create_sheet("失败原因TOP")
            ws3.append(["失败原因", "数量"])
            for r in report.get("failure_reasons_top", []):
                ws3.append([r.get("reason"), r.get("count")])

            ws4 = wb.create_sheet("明细")
            ws4.append(
                [
                    "用例",
                    "计算类型",
                    "资产编码",
                    "资产名称",
                    "电压",
                    "塔型",
                    "场景",
                    "状态",
                    "闪络相数",
                    "上次闪络相数",
                    "耗时(ms)",
                    "错误信息",
                ]
            )
            for it in items:
                prev = it.get("previous") or {}
                ws4.append(
                    [
                        it.get("case_name"),
                        JOB_KIND_LABELS.get(str(it.get("job_kind") or ""), it.get("job_kind")),
                        it.get("asset_code"),
                        it.get("asset_name"),
                        it.get("voltage_level") or "",
                        it.get("tower_type") or "",
                        it.get("scene_type") or "",
                        it.get("status"),
                        it.get("flashover_count") if it.get("flashover_count") is not None else "",
                        prev.get("flashover_count") if prev.get("flashover_count") is not None else "",
                        it.get("duration_ms"),
                        (str(it.get("error_message") or ""))[:200],
                    ]
                )
            for sheet in (ws2, ws3, ws4):
                for row in sheet.iter_rows():
                    for cell in row:
                        cell.alignment = Alignment(vertical="top", wrap_text=True)
            zf.writestr("report.xlsx", _wb_to_bytes(wb))
        except Exception:
            zf.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))

        import csv

        csv_buf = io.StringIO()
        writer = csv.writer(csv_buf)
        writer.writerow(
            [
                "用例", "计算类型", "资产编码", "资产名称", "电压", "塔型", "场景",
                "状态", "闪络相数", "上次闪络相数", "耗时(ms)", "错误信息",
            ]
        )
        for it in items:
            prev = it.get("previous") or {}
            writer.writerow(
                [
                    it.get("case_name"),
                    JOB_KIND_LABELS.get(str(it.get("job_kind") or ""), it.get("job_kind")),
                    it.get("asset_code"),
                    it.get("asset_name"),
                    it.get("voltage_level") or "",
                    it.get("tower_type") or "",
                    it.get("scene_type") or "",
                    it.get("status"),
                    it.get("flashover_count") if it.get("flashover_count") is not None else "",
                    prev.get("flashover_count") if prev.get("flashover_count") is not None else "",
                    it.get("duration_ms"),
                    (str(it.get("error_message") or ""))[:200],
                ]
            )
        zf.writestr("detail.csv", csv_buf.getvalue())
        zf.writestr(
            "report.json",
            json.dumps(
                {
                    "summary": {
                        "run_id": summary.get("run_id"),
                        "set_name": summary.get("set_name"),
                        "status": summary.get("status"),
                        "counts": counts,
                    },
                    "report": report,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return buf.getvalue(), f"atp-test-set-{run_id}.zip"


def _wb_to_bytes(workbook) -> bytes:
    import io as _io

    out = _io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _fmt_dt(value: object) -> str:
    """datetime → ISO 字符串（openpyxl 不接受带 tzinfo 的 datetime）。"""
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)
