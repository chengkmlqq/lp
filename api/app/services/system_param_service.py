from __future__ import annotations

import asyncio
import json

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..core.param_encryption import MASK, decrypt_value, encrypt_value, is_encrypted_value
from ..models.system_param import SystemParam
from ..schemas.system_param import (
    SystemParamCreateRequest,
    SystemParamListResponse,
    SystemParamRuntimeItem,
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
    is_encrypted = bool(item.is_encrypted)
    stored_value = item.param_value or ""
    if is_encrypted:
        # 加密参数对外仅暴露掩码，密文绝不下发
        param_value = MASK if stored_value else ""
        has_value = bool(stored_value)
    else:
        param_value = stored_value
        has_value = bool(stored_value)

    return SystemParamSummary(
        id=item.id,
        param_key=item.param_key,
        param_name=item.param_name,
        param_value=param_value,
        is_encrypted=is_encrypted,
        has_value=has_value,
        description=item.description,
        status=item.status,
        category_id=item.category_id,
        created_by_user_id=item.created_by_user_id,
        updated_by_user_id=item.updated_by_user_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        created_by=serialize_user(item.created_by) if item.created_by else None,
        updated_by=serialize_user(item.updated_by) if item.updated_by else None,
    )


def _param_value_like_clause(like: str):
    # 关键词搜索时，加密参数不参与 param_value 的模糊匹配（密文/掩码无搜索意义）
    return and_(SystemParam.is_encrypted.is_(False), SystemParam.param_value.ilike(like))


def _matches_keyword_clause(like: str):
    return or_(
        SystemParam.param_key.ilike(like),
        SystemParam.param_name.ilike(like),
        _param_value_like_clause(like),
        SystemParam.description.ilike(like),
    )


def list_system_params(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    status_filter: str | None,
    category_id: int | None = None,
) -> SystemParamListResponse:
    stmt = _system_param_stmt()
    if keyword:
        normalized = keyword.strip()
        if normalized:
            like = f"%{normalized}%"
            stmt = stmt.where(_matches_keyword_clause(like))
    if status_filter in {"enabled", "disabled"}:
        stmt = stmt.where(SystemParam.status == status_filter)
    if category_id is not None:
        stmt = stmt.where(SystemParam.category_id == category_id)

    total_stmt = select(func.count()).select_from(SystemParam)
    if keyword:
        normalized = keyword.strip()
        if normalized:
            like = f"%{normalized}%"
            total_stmt = total_stmt.where(_matches_keyword_clause(like))
    if status_filter in {"enabled", "disabled"}:
        total_stmt = total_stmt.where(SystemParam.status == status_filter)
    if category_id is not None:
        total_stmt = total_stmt.where(SystemParam.category_id == category_id)

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


def get_system_param_decrypted(db: Session, param_key: str) -> str | None:
    """供"使用时解密"：仅返回 status=enabled 的参数明文；加密参数解密后返回，否则返回 None。"""
    item = get_system_param_by_key(db, param_key)
    if not item or item.status != "enabled":
        return None
    stored_value = item.param_value or ""
    if item.is_encrypted:
        if not stored_value:
            return None
        return decrypt_value(stored_value)
    return stored_value or None


def get_system_params_runtime(db: Session, keys: list[str]) -> list[SystemParamRuntimeItem]:
    """运行时解密接口：服务端解密后仅返回实际使用参数明文，供前端等消费方使用。"""
    items: list[SystemParamRuntimeItem] = []
    for key in keys:
        stripped = (key or "").strip()
        if not stripped:
            continue
        value = get_system_param_decrypted(db, stripped)
        if value is not None:
            items.append(SystemParamRuntimeItem(param_key=stripped, param_value=value))
    return items


def create_system_param(db: Session, payload: SystemParamCreateRequest, *, actor_user_id: str) -> SystemParamSummary | None:
    exists = db.scalar(select(SystemParam.id).where(SystemParam.param_key == payload.param_key.strip()))
    if exists:
        return None

    item = SystemParam(
        param_key=payload.param_key.strip(),
        param_name=payload.param_name.strip(),
        param_value=encrypt_value(payload.param_value) if payload.is_encrypted else payload.param_value,
        is_encrypted=bool(payload.is_encrypted),
        description=(payload.description or "").strip(),
        status=payload.status,
        category_id=payload.category_id,
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
        output=json.dumps({"param_id": item.id, "param_key": item.param_key, "status": item.status}),
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
            requires_refetch=[
                "/api/v1/admin/system-params",
                "/api/v1/admin/system-params/runtime",
            ],
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

    if "is_encrypted" in update_data and update_data["is_encrypted"] is not None:
        want_encrypted = bool(update_data["is_encrypted"])
    else:
        want_encrypted = bool(item.is_encrypted)

    if want_encrypted:
        # 目标为密文存储：仅当用户显式输入新值时更新，空值/占位掩码不覆盖原密文
        if "param_value" in update_data and update_data["param_value"] not in (None, "", MASK):
            item.param_value = encrypt_value(str(update_data["param_value"]))
            changed_fields.append("param_value")
        elif not is_encrypted_value(item.param_value):
            # 未提供新值：若当前为明文则补加密，保持"加密参数绝不存明文"
            if item.param_value:
                item.param_value = encrypt_value(item.param_value)
                changed_fields.append("param_value")
    else:
        # 目标为明文存储
        if "param_value" in update_data and update_data["param_value"] is not None:
            item.param_value = str(update_data["param_value"])
            changed_fields.append("param_value")
        elif item.is_encrypted and is_encrypted_value(item.param_value):
            # 关闭加密且未提供新值：解密现有密文，避免切换后值丢失
            decrypted = decrypt_value(item.param_value)
            item.param_value = decrypted if decrypted is not None else ""
            changed_fields.append("param_value")

    if want_encrypted != bool(item.is_encrypted):
        item.is_encrypted = want_encrypted
        changed_fields.append("is_encrypted")

    if "description" in update_data:
        item.description = (str(update_data["description"]) if update_data["description"] is not None else "").strip()
        changed_fields.append("description")
    if "status" in update_data and update_data["status"] is not None:
        item.status = str(update_data["status"])
        changed_fields.append("status")
    if "category_id" in update_data:
        item.category_id = update_data["category_id"]
        changed_fields.append("category_id")

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
            output=json.dumps({
                "param_id": item.id,
                "param_key": item.param_key,
                "changed_fields": changed_fields,
                "status_transition": f"{previous_status}->{item.status}" if "status" in changed_fields else None,
            }),
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
            requires_refetch=[
                "/api/v1/admin/system-params",
                f"/api/v1/admin/system-params/{saved.id}",
                "/api/v1/admin/system-params/runtime",
            ],
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
        output=json.dumps({"param_id": deleted_id, "param_key": deleted_key}),
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
