from __future__ import annotations

import asyncio

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models.system_param import SystemParam
from ..schemas.system_param import (
    SystemParamCreateRequest,
    SystemParamListResponse,
    SystemParamSummary,
    SystemParamUpdateRequest,
)
from .audit_service import compose_audit_detail, describe_changed_fields, write_audit_log
from .push_service import publish_topic
from .user_service import serialize_user

SYSTEM_PARAM_TOPIC = "admin.system-params"


def _system_param_stmt():
    return select(SystemParam).options(
        selectinload(SystemParam.created_by),
        selectinload(SystemParam.updated_by),
    )


def serialize_system_param(item: SystemParam) -> SystemParamSummary:
    return SystemParamSummary(
        id=item.id,
        param_key=item.param_key,
        param_name=item.param_name,
        param_value=item.param_value,
        description=item.description,
        status=item.status,
        created_by_user_id=item.created_by_user_id,
        updated_by_user_id=item.updated_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        created_by=serialize_user(item.created_by) if item.created_by else None,
        updated_by=serialize_user(item.updated_by) if item.updated_by else None,
    )


def list_system_params(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    status_filter: str | None,
) -> SystemParamListResponse:
    stmt = _system_param_stmt()
    if keyword:
        normalized = keyword.strip()
        if normalized:
            like = f"%{normalized}%"
            stmt = stmt.where(
                or_(
                    SystemParam.param_key.ilike(like),
                    SystemParam.param_name.ilike(like),
                    SystemParam.param_value.ilike(like),
                    SystemParam.description.ilike(like),
                )
            )
    if status_filter in {"enabled", "disabled"}:
        stmt = stmt.where(SystemParam.status == status_filter)

    total_stmt = select(func.count()).select_from(SystemParam)
    if keyword:
        normalized = keyword.strip()
        if normalized:
            like = f"%{normalized}%"
            total_stmt = total_stmt.where(
                or_(
                    SystemParam.param_key.ilike(like),
                    SystemParam.param_name.ilike(like),
                    SystemParam.param_value.ilike(like),
                    SystemParam.description.ilike(like),
                )
            )
    if status_filter in {"enabled", "disabled"}:
        total_stmt = total_stmt.where(SystemParam.status == status_filter)

    total = db.scalar(total_stmt) or 0
    items = (
        db.execute(
            stmt.order_by(SystemParam.updated_at.desc(), SystemParam.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return SystemParamListResponse(items=[serialize_system_param(item) for item in items], total=total)


def get_system_param_by_id(db: Session, param_id: int) -> SystemParam | None:
    return db.execute(_system_param_stmt().where(SystemParam.id == param_id)).scalar_one_or_none()


def get_system_param_by_key(db: Session, param_key: str) -> SystemParam | None:
    return db.execute(_system_param_stmt().where(SystemParam.param_key == param_key)).scalar_one_or_none()


def create_system_param(db: Session, payload: SystemParamCreateRequest, *, actor_user_id: str) -> SystemParamSummary | None:
    exists = db.scalar(select(SystemParam.id).where(SystemParam.param_key == payload.param_key.strip()))
    if exists:
        return None

    item = SystemParam(
        param_key=payload.param_key.strip(),
        param_name=payload.param_name.strip(),
        param_value=payload.param_value,
        description=(payload.description or "").strip(),
        status=payload.status,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(item)
    db.flush()
    write_audit_log(
        db,
        action="system_param.create",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"param_id={item.id}",
            f"param_key={item.param_key}",
            f"status={item.status}",
        ),
    )
    db.commit()

    saved = get_system_param_by_id(db, item.id)
    if not saved:
        return None

    _fire_and_forget(
        publish_topic(
            SYSTEM_PARAM_TOPIC,
            name="system_params.changed",
            payload={"action": "created", "param_id": saved.id, "param_key": saved.param_key},
            requires_refetch=["/api/v1/admin/system-params"],
            dedupe_key=f"system-params:created:{saved.id}",
        )
    )

    return serialize_system_param(saved)


def update_system_param(
    db: Session,
    param_id: int,
    payload: SystemParamUpdateRequest,
    *,
    actor_user_id: str,
) -> SystemParamSummary | None:
    item = get_system_param_by_id(db, param_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    changed_fields: list[str] = []
    previous_status = item.status
    if "param_name" in update_data and update_data["param_name"] is not None:
        item.param_name = str(update_data["param_name"]).strip()
        changed_fields.append("param_name")
    if "param_value" in update_data and update_data["param_value"] is not None:
        item.param_value = str(update_data["param_value"])
        changed_fields.append("param_value")
    if "description" in update_data:
        item.description = (str(update_data["description"]) if update_data["description"] is not None else "").strip()
        changed_fields.append("description")
    if "status" in update_data and update_data["status"] is not None:
        item.status = str(update_data["status"])
        changed_fields.append("status")

    item.updated_by_user_id = actor_user_id
    if changed_fields:
        write_audit_log(
            db,
            action="system_param.update",
            actor_user_id=actor_user_id,
            detail=compose_audit_detail(
                f"param_id={item.id}",
                f"param_key={item.param_key}",
                describe_changed_fields(changed_fields),
                (
                    f"status_transition={previous_status}->{item.status}"
                    if "status" in changed_fields
                    else None
                ),
            ),
        )
    db.commit()

    saved = get_system_param_by_id(db, param_id)
    if not saved:
        return None

    _fire_and_forget(
        publish_topic(
            SYSTEM_PARAM_TOPIC,
            name="system_params.changed",
            payload={"action": "updated", "param_id": saved.id, "param_key": saved.param_key},
            requires_refetch=["/api/v1/admin/system-params", f"/api/v1/admin/system-params/{saved.id}"],
            dedupe_key=f"system-params:updated:{saved.id}",
        )
    )

    return serialize_system_param(saved)


def delete_system_param(db: Session, param_id: int, *, actor_user_id: str) -> bool:
    item = get_system_param_by_id(db, param_id)
    if not item:
        return False

    deleted_id = item.id
    deleted_key = item.param_key
    write_audit_log(
        db,
        action="system_param.delete",
        actor_user_id=actor_user_id,
        detail=compose_audit_detail(
            f"param_id={deleted_id}",
            f"param_key={deleted_key}",
        ),
    )
    db.delete(item)
    db.commit()

    _fire_and_forget(
        publish_topic(
            SYSTEM_PARAM_TOPIC,
            name="system_params.changed",
            payload={"action": "deleted", "param_id": deleted_id, "param_key": deleted_key},
            requires_refetch=["/api/v1/admin/system-params"],
            dedupe_key=f"system-params:deleted:{deleted_id}",
        )
    )
    return True


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)
