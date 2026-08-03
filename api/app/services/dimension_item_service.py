from __future__ import annotations

import asyncio

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.dimension_item import DimensionItem
from ..models.dimension_type import DimensionType
from ..models.user import User
from ..schemas.dimension_item import (
    DimensionItemCreateRequest,
    DimensionItemListResponse,
    DimensionItemSummary,
    DimensionItemTreeNode,
    DimensionItemUpdateRequest,
)
from .dimension_type_service import get_type_by_code
from .push_service import publish_topic

DIMENSION_ITEM_TOPIC = "admin.dimension-items"


def _fire_and_forget(coro: object) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return
    loop.create_task(coro)


def serialize_dimension_item(item: DimensionItem) -> DimensionItemSummary:
    type_name = item.type.name if item.type else None
    return DimensionItemSummary(
        id=item.id,
        dimension_type=item.dimension_type,
        type_id=item.type_id,
        type_name=type_name,
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


def list_dimension_items(
    db: Session,
    *,
    limit: int,
    offset: int,
    keyword: str | None,
    dimension_type: str | None,
    enabled: bool | None,
    type_id: str | None = None,
) -> DimensionItemListResponse:
    stmt = select(DimensionItem)
    total_stmt = select(func.count()).select_from(DimensionItem)

    resolved_type_id = _resolve_type_filter(db, type_id, dimension_type)
    if resolved_type_id:
        stmt = stmt.where(DimensionItem.type_id == resolved_type_id)
        total_stmt = total_stmt.where(DimensionItem.type_id == resolved_type_id)

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        like = f"%{normalized_keyword}%"
        predicate = or_(
            DimensionItem.code.ilike(like),
            DimensionItem.name.ilike(like),
        )
        stmt = stmt.where(predicate)
        total_stmt = total_stmt.where(predicate)

    if enabled is not None:
        stmt = stmt.where(DimensionItem.is_enabled == enabled)
        total_stmt = total_stmt.where(DimensionItem.is_enabled == enabled)

    total = int(db.scalar(total_stmt) or 0)
    stmt = stmt.order_by(DimensionItem.sort_order, DimensionItem.create_date.desc()).limit(limit).offset(offset)
    items = list(db.scalars(stmt).all())

    return DimensionItemListResponse(
        items=[serialize_dimension_item(item) for item in items],
        total=total,
    )


def _resolve_type_filter(db: Session, type_id: str | None, dimension_type: str | None) -> str | None:
    if type_id:
        return type_id
    if dimension_type:
        resolved = get_type_by_code(db, dimension_type.strip())
        if resolved:
            return resolved.id
    return None


def get_dimension_tree(
    db: Session,
    dimension_type: str | None = None,
    type_id: str | None = None,
) -> list[DimensionItemTreeNode]:
    stmt = select(DimensionItem).order_by(DimensionItem.sort_order, DimensionItem.create_date)

    resolved_type_id = _resolve_type_filter(db, type_id, dimension_type)
    if resolved_type_id:
        stmt = stmt.where(DimensionItem.type_id == resolved_type_id)

    items = list(db.scalars(stmt).all())

    item_map: dict[str, DimensionItemTreeNode] = {}
    for item in items:
        type_name = item.type.name if item.type else None
        item_map[item.id] = DimensionItemTreeNode(
            id=item.id,
            dimension_type=item.dimension_type,
            type_id=item.type_id,
            type_name=type_name,
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
            children=[],
        )

    root_nodes: list[DimensionItemTreeNode] = []
    for node in item_map.values():
        if node.parent_id and node.parent_id in item_map:
            item_map[node.parent_id].children.append(node)
        else:
            root_nodes.append(node)

    return root_nodes


def get_dimension_item_by_id(db: Session, item_id: str) -> DimensionItem | None:
    return db.scalar(select(DimensionItem).where(DimensionItem.id == item_id))


def _resolve_type_for_item(db: Session, type_id: str | None, dimension_type: str | None):
    """创建/更新时解析类型：优先 type_id，其次按 code 解析 dimension_type。

    返回 (resolved_type_id, resolved_type_code)：
    - 若 type_id 给定但类型不存在 -> 返回 (None, ...) 表示无效。
    - 若 dimension_type 能匹配到类型 -> 返回其 id。
    - 老数据无类型时允许 type_id 为 None。
    """
    if type_id:
        resolved = db.get(DimensionType, type_id)
        if not resolved:
            return None, None
        return resolved.id, resolved.code
    if dimension_type:
        resolved = get_type_by_code(db, dimension_type.strip())
        if resolved:
            return resolved.id, resolved.code
    return None, None


def create_dimension_item(
    db: Session,
    payload: DimensionItemCreateRequest,
    actor: User,
) -> DimensionItemSummary | None:
    resolved_type_id, resolved_type_code = _resolve_type_for_item(db, payload.type_id, payload.dimension_type)
    if payload.type_id and resolved_type_id is None:
        # 显式传了 type_id 但类型不存在
        return None

    if payload.type_id is not None or resolved_type_id is not None:
        existing = db.scalar(
            select(DimensionItem).where(
                DimensionItem.type_id == resolved_type_id,
                DimensionItem.code == payload.code,
            )
        )
        if existing:
            return None

    if payload.parent_id:
        parent = get_dimension_item_by_id(db, payload.parent_id)
        if not parent:
            return None

    item = DimensionItem(
        dimension_type=resolved_type_code or payload.dimension_type,
        type_id=resolved_type_id,
        code=payload.code,
        name=payload.name,
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

    _fire_and_forget(publish_topic(DIMENSION_ITEM_TOPIC, name="dimension_items.changed", payload={"action": "created"}))
    return serialize_dimension_item(item)


def update_dimension_item(
    db: Session,
    item_id: str,
    payload: DimensionItemUpdateRequest,
    actor: User,
) -> DimensionItemSummary | None:
    item = get_dimension_item_by_id(db, item_id)
    if not item:
        return None

    # 解析类型变更：(type_id, code) 查重基于解析后的最终类型
    if payload.type_id is not None:
        resolved = db.get(DimensionType, payload.type_id)
        if not resolved:
            return None
        item.type_id = resolved.id
        item.dimension_type = resolved.code
    elif payload.dimension_type is not None:
        resolved = get_type_by_code(db, payload.dimension_type.strip())
        if resolved:
            item.type_id = resolved.id
            item.dimension_type = resolved.code
        else:
            item.dimension_type = payload.dimension_type.strip()

    if payload.code is not None:
        existing = db.scalar(
            select(DimensionItem).where(
                DimensionItem.type_id == item.type_id,
                DimensionItem.code == payload.code,
                DimensionItem.id != item_id,
            )
        )
        if existing:
            return None
        item.code = payload.code

    if payload.name is not None:
        item.name = payload.name

    if payload.parent_id is not None:
        if payload.parent_id:
            parent = get_dimension_item_by_id(db, payload.parent_id)
            if not parent:
                return None
            if payload.parent_id == item_id:
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

    _fire_and_forget(publish_topic(DIMENSION_ITEM_TOPIC, name="dimension_items.changed", payload={"action": "updated"}))
    return serialize_dimension_item(item)


def delete_dimension_item(db: Session, item_id: str) -> bool:
    item = get_dimension_item_by_id(db, item_id)
    if not item:
        return False

    children = db.scalars(select(DimensionItem).where(DimensionItem.parent_id == item_id)).all()
    if children:
        return False

    db.delete(item)
    db.commit()

    _fire_and_forget(publish_topic(DIMENSION_ITEM_TOPIC, name="dimension_items.changed", payload={"action": "deleted"}))
    return True