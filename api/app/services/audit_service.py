from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy.orm import Session

from ..models.audit_log import AuditLog


def write_audit_log(
    db: Session,
    *,
    action: str,
    actor_user_id: str | None,
    detail: str | None = None,
) -> AuditLog:
    log = AuditLog(
        user_id=actor_user_id,
        action=action,
        detail=_normalize_detail(detail),
    )
    db.add(log)
    return log


def compose_audit_detail(*parts: str | None) -> str | None:
    normalized = [_normalize_part(part) for part in parts]
    items = [part for part in normalized if part]
    return "; ".join(items) if items else None


def describe_changed_fields(fields: Iterable[str]) -> str | None:
    normalized = sorted({field.strip() for field in fields if field and field.strip()})
    if not normalized:
        return None
    return f"changed_fields={','.join(normalized)}"


def summarize_values(values: Iterable[object], *, limit: int = 10) -> str:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if len(normalized) <= limit:
        return ",".join(normalized)
    visible = ",".join(normalized[:limit])
    return f"{visible},...(+{len(normalized) - limit})"


def _normalize_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    normalized = detail.strip()
    return normalized or None


def _normalize_part(part: str | None) -> str | None:
    if part is None:
        return None
    normalized = part.strip()
    return normalized or None
