from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models.base import utcnow
from ..models.dimension_item import DimensionItem
from ..models.dimension_type import DimensionType
from ..models.user import User
from ..schemas.dimension_type import (
    DimensionTypeCreateRequest,
    DimensionTypeSummary,
    DimensionTypeTreeItem,
    DimensionTypeUpdateRequest,
)
from .push_service import publish_topic

DIMENSION_TYPE_TOPIC = "admin.dimension-types"


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)


def serialize_dimension_type(item: DimensionType) -> DimensionTypeSummary:
    return DimensionTypeSummary(
        id=item.id,
        code=item.code,
        name=item.name,
        parent_id=item.parent_id,
        description=item.description,
        is_enabled=item.is_enabled,
        sort_order=item.sort_order,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
    )


def serialize_type_tree(item: DimensionType) -> DimensionTypeTreeItem:
    return DimensionTypeTreeItem(
        id=item.id,
        code=item.code,
        name=item.name,
        parent_id=item.parent_id,
        description=item.description,
        is_enabled=item.is_enabled,
        sort_order=item.sort_order,
        create_date=item.create_date,
        create_user=item.create_user,
        update_date=item.update_date,
        update_user=item.update_user,
        children=[serialize_type_tree(child) for child in item.children],
    )


def get_dimension_type_by_id(db: Session, type_id: str) -> DimensionType | None:
    return db.scalar(select(DimensionType).where(DimensionType.id == type_id))


def get_dimension_type_tree(db: Session) -> list[DimensionTypeTreeItem]:
    stmt = (
        select(DimensionType)
        .options(selectinload(DimensionType.children))
        .where(DimensionType.parent_id.is_(None))
        .order_by(DimensionType.sort_order)
    )
    roots = db.execute(stmt).scalars().all()
    return [serialize_type_tree(root) for root in roots]


def create_dimension_type(
    db: Session,
    payload: DimensionTypeCreateRequest,
    actor: User,
) -> DimensionTypeSummary | None:
    existing = db.scalar(select(DimensionType).where(DimensionType.code == payload.code.strip()))
    if existing:
        return None

    if payload.parent_id:
        parent = get_dimension_type_by_id(db, payload.parent_id)
        if not parent:
            return None

    item = DimensionType(
        code=payload.code.strip(),
        name=payload.name.strip(),
        parent_id=payload.parent_id,
        description=payload.description,
        is_enabled=payload.is_enabled,
        sort_order=payload.sort_order,
        create_user=actor.id,
        update_user=actor.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    _fire_and_forget(publish_topic(DIMENSION_TYPE_TOPIC, name="dimension_types.changed", payload={"action": "created"}))
    return serialize_dimension_type(item)


def update_dimension_type(
    db: Session,
    type_id: str,
    payload: DimensionTypeUpdateRequest,
    actor: User,
) -> DimensionTypeSummary | None:
    item = get_dimension_type_by_id(db, type_id)
    if not item:
        return None

    if payload.code is not None:
        code = payload.code.strip()
        existing = db.scalar(
            select(DimensionType).where(
                DimensionType.code == code,
                DimensionType.id != type_id,
            )
        )
        if existing:
            return None
        item.code = code

    if payload.name is not None:
        if payload.name.strip():
            item.name = payload.name.strip()

    if payload.parent_id is not None:
        if payload.parent_id:
            parent = get_dimension_type_by_id(db, payload.parent_id)
            if not parent:
                return None
            if payload.parent_id == type_id:
                return None
        item.parent_id = payload.parent_id

    if payload.description is not None:
        item.description = payload.description

    if payload.is_enabled is not None:
        item.is_enabled = payload.is_enabled

    if payload.sort_order is not None:
        item.sort_order = payload.sort_order

    item.update_date = utcnow()
    item.update_user = actor.id

    db.commit()
    db.refresh(item)

    _fire_and_forget(publish_topic(DIMENSION_TYPE_TOPIC, name="dimension_types.changed", payload={"action": "updated"}))
    return serialize_dimension_type(item)


def delete_dimension_type(db: Session, type_id: str) -> bool:
    item = get_dimension_type_by_id(db, type_id)
    if not item:
        return False

    # 删除保护：有维度值引用（type_id）拒绝删除
    referenced = db.scalar(
        select(DimensionItem.id).where(DimensionItem.type_id == type_id).limit(1)
    )
    if referenced is not None:
        return False

    db.delete(item)
    db.commit()

    _fire_and_forget(publish_topic(DIMENSION_TYPE_TOPIC, name="dimension_types.changed", payload={"action": "deleted"}))
    return True


def get_type_by_code(db: Session, code: str) -> DimensionType | None:
    return db.scalar(select(DimensionType).where(DimensionType.code == code))