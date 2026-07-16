from __future__ import annotations

import json
import os
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from ..core.database import SessionLocal
from ..models.base import utcnow
from ..models.worker_registry import WorkerRegistry


def register_worker(
    *,
    worker_name: str,
    status: str,
    queues: list[str] | None = None,
    pid: int | None = None,
    heartbeat_increment: bool = False,
    metadata: dict[str, Any] | None = None,
) -> None:
    normalized_worker = worker_name.strip()
    if not normalized_worker:
        return

    now = utcnow()
    queues_csv = _normalize_queues(queues)
    metadata_text = _to_json_text(metadata)
    normalized_status = (status or "").strip().lower() or "online"
    normalized_pid = _coerce_pid(pid)

    db = SessionLocal()
    try:
        row = db.execute(
            select(WorkerRegistry).where(WorkerRegistry.worker_name == normalized_worker)
        ).scalar_one_or_none()
        if row is None:
            row = WorkerRegistry(
                worker_name=normalized_worker,
                status=normalized_status,
                queues_csv=queues_csv,
                pid=normalized_pid,
                heartbeat_count=1 if heartbeat_increment else 0,
                first_seen_at=now,
                last_seen_at=now,
                metadata_json=metadata_text,
                create_date=now,
                update_date=now,
            )
            db.add(row)
            db.commit()
            return

        row.status = normalized_status
        if queues_csv is not None:
            row.queues_csv = queues_csv
        if normalized_pid is not None:
            row.pid = normalized_pid
        if heartbeat_increment:
            row.heartbeat_count = int(row.heartbeat_count or 0) + 1
        if metadata_text is not None:
            row.metadata_json = metadata_text
        row.last_seen_at = now
        row.update_date = now
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def mark_worker_offline(worker_name: str) -> None:
    normalized_worker = worker_name.strip()
    if not normalized_worker:
        return
    now = utcnow()
    db = SessionLocal()
    try:
        row = db.execute(
            select(WorkerRegistry).where(WorkerRegistry.worker_name == normalized_worker)
        ).scalar_one_or_none()
        if row is None:
            row = WorkerRegistry(
                worker_name=normalized_worker,
                status="offline",
                heartbeat_count=0,
                first_seen_at=now,
                last_seen_at=now,
                create_date=now,
                update_date=now,
            )
            db.add(row)
            db.commit()
            return
        row.status = "offline"
        row.last_seen_at = now
        row.update_date = now
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def sweep_offline_workers(*, ttl_seconds: int) -> int:
    safe_ttl = max(10, int(ttl_seconds))
    threshold = utcnow() - timedelta(seconds=safe_ttl)
    db = SessionLocal()
    changed = 0
    try:
        rows = db.execute(
            select(WorkerRegistry).where(
                WorkerRegistry.status == "online",
                WorkerRegistry.last_seen_at < threshold,
            )
        ).scalars().all()
        if not rows:
            return 0
        now = utcnow()
        for row in rows:
            row.status = "offline"
            row.update_date = now
            changed += 1
        db.commit()
        return changed
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def _normalize_queues(queues: list[str] | None) -> str | None:
    if queues is None:
        return None
    normalized = sorted({item.strip() for item in queues if isinstance(item, str) and item.strip()})
    if not normalized:
        return ""
    return ",".join(normalized)


def _to_json_text(value: dict[str, Any] | None) -> str | None:
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = json.dumps({"repr": repr(value)}, ensure_ascii=False)
    if len(text) > 3900:
        text = text[:3897] + "..."
    return text


def _coerce_pid(value: int | None) -> int | None:
    if value is not None:
        try:
            pid = int(value)
        except (TypeError, ValueError):
            pid = None
        if pid and pid > 0:
            return pid
    fallback = os.getpid()
    return fallback if fallback > 0 else None
