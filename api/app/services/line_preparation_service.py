from __future__ import annotations

from typing import Any

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.tower_profile import TowerProfile

PREPARATION_LABELS = {
    "lightning_current": "雷电流幅值",
    "lightning_density": "地闪密度",
    "ground_slope": "地面倾角",
}

PREPARATION_SOURCE_KEY = "preparation_sources"


def summarize_line_preparations(
    db: Session,
    lines: list[Line],
    *,
    tower_count_map: dict[str, int] | None = None,
    counts: dict[str, dict[str, int]] | None = None,
) -> dict[str, dict[str, Any]]:
    line_ids = [line.id for line in lines]
    if not line_ids:
        return {}

    if counts is None:
        counts = _load_preparation_count_maps(db, line_ids=line_ids, tower_count_map=tower_count_map)
    summaries: dict[str, dict[str, Any]] = {}
    for line in lines:
        tower_total = counts["tower"].get(line.id, 0)
        current_ready = counts["lightning_current"].get(line.id, 0)
        density_ready = counts["lightning_density"].get(line.id, 0)
        slope_ready = counts["ground_slope"].get(line.id, 0)
        summaries[line.id] = _build_summary(
            line,
            tower_total=tower_total,
            current_ready=current_ready,
            density_ready=density_ready,
            slope_ready=slope_ready,
        )
    return summaries


def summarize_line_preparation(
    db: Session,
    line: Line,
    *,
    tower_count: int | None = None,
) -> dict[str, Any]:
    tower_count_map = {line.id: tower_count} if tower_count is not None else None
    return summarize_line_preparations(db, [line], tower_count_map=tower_count_map).get(line.id, {})


def record_line_preparation_source(
    line: Line,
    *,
    component: str,
    payload: dict[str, Any],
) -> None:
    line_params = dict(line.lightning_param_json or {})
    sources = _extract_preparation_sources(line_params)
    sources[component] = {
        **dict(payload),
        "component": component,
        "label": PREPARATION_LABELS.get(component, component),
    }
    line_params[PREPARATION_SOURCE_KEY] = sources
    line.lightning_param_json = line_params


def _build_summary(
    line: Line,
    *,
    tower_total: int,
    current_ready: int,
    density_ready: int,
    slope_ready: int,
) -> dict[str, Any]:
    line_params = dict(line.lightning_param_json or {})
    current_a = _coerce_float(line_params.get("雷电流幅值a"))
    current_b = _coerce_float(line_params.get("雷电流幅值b"))
    sources = _extract_preparation_sources(line_params)

    current_summary = _build_component_summary(
        component="lightning_current",
        tower_total=tower_total,
        ready_count=current_ready,
        source=sources.get("lightning_current"),
        values={
            "current_a": current_a,
            "current_b": current_b,
        },
        line_ready=(current_a is not None and current_b is not None),
    )
    density_summary = _build_component_summary(
        component="lightning_density",
        tower_total=tower_total,
        ready_count=density_ready,
        source=sources.get("lightning_density"),
    )
    slope_summary = _build_component_summary(
        component="ground_slope",
        tower_total=tower_total,
        ready_count=slope_ready,
        source=sources.get("ground_slope"),
    )

    items = [current_summary, density_summary, slope_summary]
    missing_items = [str(item["label"]) for item in items if not bool(item["ready"])]
    return {
        "all_ready": not missing_items,
        "missing_items": missing_items,
        "lightning_current": current_summary,
        "lightning_density": density_summary,
        "ground_slope": slope_summary,
    }


def _build_component_summary(
    *,
    component: str,
    tower_total: int,
    ready_count: int,
    source: dict[str, Any] | None,
    values: dict[str, Any] | None = None,
    line_ready: bool = True,
) -> dict[str, Any]:
    ready = tower_total > 0 and ready_count >= tower_total and line_ready
    return {
        "key": component,
        "label": PREPARATION_LABELS.get(component, component),
        "ready": ready,
        "status": "ready" if ready else "missing",
        "tower_total_count": tower_total,
        "tower_ready_count": min(ready_count, tower_total),
        "missing_tower_count": max(tower_total - ready_count, 0),
        "line_ready": line_ready,
        "values": dict(values or {}),
        "source": dict(source or {}),
    }


def load_line_preparation_counts(db: Session, line_ids: list[str]) -> dict[str, dict[str, int]]:
    """供列表接口一次性预取四个准备度计数（塔数可同时复用给 tower_count）。"""
    return _count_tower_preparations(db, line_ids)


def _load_preparation_count_maps(
    db: Session,
    *,
    line_ids: list[str],
    tower_count_map: dict[str, int] | None,
) -> dict[str, dict[str, int]]:
    counts = _count_tower_preparations(db, line_ids)
    return {
        # 线路列表已批量统计过塔数时直接复用，避免同一份 COUNT 再跑一次
        "tower": tower_count_map or counts["tower"],
        "lightning_current": counts["lightning_current"],
        "lightning_density": counts["lightning_density"],
        "ground_slope": counts["ground_slope"],
    }


def _count_tower_preparations(db: Session, line_ids: list[str]) -> dict[str, dict[str, int]]:
    """一次分组查询取回塔数 / 地闪密度 / 地面倾角 / 雷电流四个准备度计数。

    ⚠️ 性能（2026-11-10）：原先塔数、地闪密度、倾角、雷电流各发一条 GROUP BY，
    在跨公网 MySQL 上每条都要吃一次 RTT（约 30–45ms）。四条合并为一条条件聚合后
    线路列表少约 100ms。LineTower ↔ TowerProfile 是 1:1（uq_tower_profile_tower_id），
    外连接不会放大行数，因此 COUNT(*) 仍等于塔数。
    """
    if not line_ids:
        return {"tower": {}, "lightning_density": {}, "ground_slope": {}, "lightning_current": {}}

    has_density = func.sum(case((LineTower.lightning_density.is_not(None), 1), else_=0))
    has_slopes = func.sum(
        case(
            (and_(LineTower.slope_1.is_not(None), LineTower.slope_2.is_not(None)), 1),
            else_=0,
        )
    )
    has_currents = func.sum(
        case(
            (
                and_(
                    TowerProfile.current_a.is_not(None),
                    TowerProfile.current_b.is_not(None),
                ),
                1,
            ),
            else_=0,
        )
    )

    rows = db.execute(
        select(
            LineTower.line_id,
            func.count(LineTower.id),
            has_density,
            has_slopes,
            has_currents,
        )
        .select_from(LineTower)
        .outerjoin(TowerProfile, TowerProfile.tower_id == LineTower.id)
        .where(LineTower.line_id.in_(line_ids))
        .group_by(LineTower.line_id)
    ).all()

    maps: dict[str, dict[str, int]] = {
        "tower": {},
        "lightning_density": {},
        "ground_slope": {},
        "lightning_current": {},
    }
    for line_id, tower_total, density_ready, slope_ready, current_ready in rows:
        key = str(line_id)
        maps["tower"][key] = int(tower_total or 0)
        maps["lightning_density"][key] = int(density_ready or 0)
        maps["ground_slope"][key] = int(slope_ready or 0)
        maps["lightning_current"][key] = int(current_ready or 0)
    return maps


def _extract_preparation_sources(line_params: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = line_params.get(PREPARATION_SOURCE_KEY)
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = dict(value)
    return normalized


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
