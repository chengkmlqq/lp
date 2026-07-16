from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from fastapi import HTTPException, status

from ..core.config import get_settings
from ..models.base import utcnow
from ..schemas.flower_monitor import (
    FlowerTaskItem,
    FlowerWorkerItem,
    FlowerWorkerTaskOverviewResponse,
    FlowerWorkerTaskSummary,
    FlowerWorkersOverviewResponse,
    FlowerWorkersSummary,
)


def build_workers_overview(*, force_refresh: bool) -> FlowerWorkersOverviewResponse:
    refresh = "true" if force_refresh else "false"
    workers_map = _call_flower_json(f"/api/workers?refresh={refresh}")
    status_map = _call_flower_json("/api/workers?status=true")
    if not force_refresh and isinstance(workers_map, dict) and not workers_map and isinstance(status_map, dict) and status_map:
        # Flower may return an empty workers cache before a refresh; self-heal once.
        workers_map = _call_flower_json("/api/workers?refresh=true")
    if not isinstance(workers_map, dict):
        workers_map = {}
    if not isinstance(status_map, dict):
        status_map = {}

    worker_names = sorted(set(workers_map.keys()) | set(status_map.keys()))
    workers: list[FlowerWorkerItem] = []
    for worker_name in worker_names:
        worker_raw = _as_record(workers_map.get(worker_name))
        is_online = bool(status_map.get(worker_name))
        workers.append(_normalize_worker(worker_name, worker_raw, is_online))

    workers.sort(key=lambda item: (0 if item.status == "ONLINE" else 1, item.worker))
    summary = FlowerWorkersSummary(
        total=len(workers),
        online=sum(1 for item in workers if item.status == "ONLINE"),
        offline=sum(1 for item in workers if item.status != "ONLINE"),
    )
    return FlowerWorkersOverviewResponse(
        generated_at=utcnow(),
        workers=workers,
        summary=summary,
    )


def build_worker_task_overview(
    *,
    worker: str,
    force_refresh: bool,
    recent_limit: int,
) -> FlowerWorkerTaskOverviewResponse:
    normalized_worker = worker.strip()
    if not normalized_worker:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="worker is required")

    refresh = "true" if force_refresh else "false"
    safe_recent_limit = max(1, min(200, int(recent_limit)))
    # NOTE:
    # Flower 2.0 may return 404 "Unknown worker" for `/api/workers?...&workername=...`
    # even when the worker exists in `/api/workers?status=true` and `/api/tasks`.
    # Use the full workers snapshot and then pick the target worker locally.
    workers_map = _call_flower_json(f"/api/workers?refresh={refresh}")
    tasks_map = _call_flower_json(
        f"/api/tasks?limit={safe_recent_limit}&workername={quote_plus(normalized_worker)}"
    )
    worker_raw = _pick_worker_raw(_as_record(workers_map), normalized_worker)
    active_tasks = _build_snapshot_tasks(normalized_worker, worker_raw, "ACTIVE")
    reserved_tasks = _build_snapshot_tasks(normalized_worker, worker_raw, "RESERVED")
    scheduled_tasks = _build_snapshot_tasks(normalized_worker, worker_raw, "SCHEDULED")
    recent_tasks = _build_recent_tasks(normalized_worker, _as_record(tasks_map))
    summary = FlowerWorkerTaskSummary(
        active=len(active_tasks),
        reserved=len(reserved_tasks),
        scheduled=len(scheduled_tasks),
        recent=len(recent_tasks),
    )
    return FlowerWorkerTaskOverviewResponse(
        generated_at=utcnow(),
        worker=normalized_worker,
        active_tasks=active_tasks,
        reserved_tasks=reserved_tasks,
        scheduled_tasks=scheduled_tasks,
        recent_tasks=recent_tasks,
        summary=summary,
    )


def _call_flower_json(path: str) -> Any:
    settings = get_settings()
    url = f"{settings.resolved_flower_api_base_url}{path}"
    headers = {"Accept": "application/json"}
    basic_auth = settings.resolved_flower_basic_auth
    if basic_auth:
        token = base64.b64encode(basic_auth.encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    timeout = max(3, int(settings.flower_api_timeout_seconds))
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=f"flower request timeout: {path}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"flower request failed: {path}: {exc}") from exc
    if response.status_code >= 400:
        detail = (response.text or "").strip() or response.reason_phrase or "flower error"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"flower error {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"flower returned non-json payload: {path}")


def _normalize_worker(worker_name: str, worker_raw: dict[str, Any], is_online: bool) -> FlowerWorkerItem:
    stats = _as_record(worker_raw.get("stats"))
    return FlowerWorkerItem(
        worker=worker_name,
        status="ONLINE" if is_online else "OFFLINE",
        queue_names=_parse_active_queue_names(worker_raw.get("active_queues")),
        registered_count=len(_as_array(worker_raw.get("registered"))),
        processed_count=_parse_processed_count(stats.get("total")),
        concurrency=_safe_int(_as_record(stats.get("pool")).get("max-concurrency") or _as_record(stats.get("pool")).get("max_concurrency")),
        prefetch_count=_safe_int(stats.get("prefetch_count")),
        active_count=len(_as_array(worker_raw.get("active"))),
        reserved_count=len(_as_array(worker_raw.get("reserved"))),
        scheduled_count=len(_as_array(worker_raw.get("scheduled"))),
        last_heartbeat_at=_parse_datetime(worker_raw.get("timestamp")),
    )


def _pick_worker_raw(workers_map: dict[str, Any], worker_name: str) -> dict[str, Any]:
    if worker_name in workers_map:
        return _as_record(workers_map.get(worker_name))
    entries = list(workers_map.items())
    if len(entries) == 1:
        return _as_record(entries[0][1])
    normalized = worker_name.strip().lower()
    for name, value in entries:
        if str(name).strip().lower() == normalized:
            return _as_record(value)
    return {}


def _build_snapshot_tasks(worker_name: str, worker_raw: dict[str, Any], source: str) -> list[FlowerTaskItem]:
    key = source.lower()
    snapshot = _as_array(worker_raw.get(key))
    items: list[FlowerTaskItem] = []
    for index, raw in enumerate(snapshot, start=1):
        items.append(
            _normalize_task_item(
                raw,
                source=source,
                fallback_task_id=f"{worker_name}:{source}:{index}",
                default_worker=worker_name,
            )
        )
    return items


def _build_recent_tasks(worker_name: str, tasks_map: dict[str, Any]) -> list[FlowerTaskItem]:
    items: list[FlowerTaskItem] = []
    for task_id, raw in tasks_map.items():
        item = _normalize_task_item(raw, source="RECENT", fallback_task_id=str(task_id), default_worker=worker_name)
        if item.worker.strip().lower() != worker_name.strip().lower():
            continue
        items.append(item)
    items.sort(
        key=lambda item: _sortable_timestamp(
            item.received_at or item.started_at or item.finished_at or item.eta
        ),
        reverse=True,
    )
    return items


def _normalize_task_item(
    raw_task: Any,
    *,
    source: str,
    fallback_task_id: str,
    default_worker: str,
) -> FlowerTaskItem:
    raw = _as_record(raw_task)
    request = _as_record(raw.get("request"))
    task_data = dict(raw)
    if request:
        task_data.update(request)
    task_id = _safe_text(task_data.get("uuid") or task_data.get("id") or fallback_task_id) or fallback_task_id
    task_name = _safe_text(task_data.get("name") or task_data.get("type")) or "-"
    worker_name = _safe_text(task_data.get("worker") or task_data.get("hostname")) or default_worker
    state_raw = _safe_text(task_data.get("state"))
    state = state_raw.upper() if state_raw else ("UNKNOWN" if source == "RECENT" else source)
    queue_name = _extract_queue_name(task_data)
    return FlowerTaskItem(
        task_id=task_id,
        name=task_name,
        state=state,
        source=source,
        worker=worker_name,
        queue_name=queue_name,
        args_text=_stringify_payload(task_data.get("args")),
        kwargs_text=_stringify_payload(task_data.get("kwargs")),
        eta=_parse_datetime(task_data.get("eta")),
        received_at=_parse_datetime(task_data.get("received") or task_data.get("timestamp")),
        started_at=_parse_datetime(task_data.get("started") or task_data.get("time_start")),
        finished_at=_parse_datetime(task_data.get("succeeded") or task_data.get("failed") or task_data.get("revoked")),
        runtime_seconds=_safe_float(task_data.get("runtime")),
        result_text=_stringify_payload(task_data.get("result")),
        exception_text=_stringify_payload(task_data.get("exception")),
    )


def _parse_active_queue_names(raw: Any) -> list[str]:
    values = []
    for item in _as_array(raw):
        name = _safe_text(_as_record(item).get("name"))
        if name:
            values.append(name)
    return sorted(set(values))


def _parse_processed_count(raw_total: Any) -> int:
    total = _as_record(raw_total)
    count = 0
    for value in total.values():
        count += _safe_int(value)
    return count


def _extract_queue_name(task_data: dict[str, Any]) -> str | None:
    delivery = _as_record(task_data.get("delivery_info"))
    routing_key = _safe_text(delivery.get("routing_key"))
    if routing_key:
        return routing_key
    exchange = _safe_text(task_data.get("exchange") or delivery.get("exchange"))
    return exchange


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        if numeric < 1e11:
            numeric *= 1000
        try:
            return datetime.fromtimestamp(numeric / 1000, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.replace(".", "", 1).isdigit():
        try:
            return _parse_datetime(float(text))
        except ValueError:
            return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stringify_payload(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False)
        except TypeError:
            text = str(value)
    text = text.strip()
    if not text:
        return None
    if len(text) > 1000:
        return text[:997] + "..."
    return text


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _as_record(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _sortable_timestamp(value: datetime | None) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()
