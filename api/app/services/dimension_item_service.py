from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.dimension_item import DimensionItem
from ..models.user import User
from ..schemas.dimension_item import (
    DimensionItemCreateRequest,
    DimensionItemListResponse,
    DimensionItemSummary,
    DimensionItemTreeNode,
    DimensionItemUpdateRequest,
)
from .push_service import publish_topic

DIMENSION_ITEM_TOPIC = "admin.dimension-items"


def serialize_dimension_item(item: DimensionItem) -> DimensionItemSummary:
    return DimensionItemSummary(
        id=item.id,
        dimension_type=item.dimension_type,
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
) -> DimensionItemListResponse:
    stmt = select(DimensionItem)
    total_stmt = select(func.count()).select_from(DimensionItem)

    if dimension_type:
        stmt = stmt.where(DimensionItem.dimension_type == dimension_type)
        total_stmt = total_stmt.where(DimensionItem.dimension_type == dimension_type)

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


def get_dimension_tree(
    db: Session,
    dimension_type: str | None = None,
) -> list[DimensionItemTreeNode]:
    stmt = select(DimensionItem).order_by(DimensionItem.sort_order, DimensionItem.create_date)

    if dimension_type:
        stmt = stmt.where(DimensionItem.dimension_type == dimension_type)

    items = list(db.scalars(stmt).all())

    item_map: dict[str, DimensionItemTreeNode] = {}
    for item in items:
        item_map[item.id] = DimensionItemTreeNode(
            id=item.id,
            dimension_type=item.dimension_type,
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


def create_dimension_item(
    db: Session,
    payload: DimensionItemCreateRequest,
    actor: User,
) -> DimensionItemSummary | None:
    existing = db.scalar(
        select(DimensionItem).where(
            DimensionItem.dimension_type == payload.dimension_type,
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
        dimension_type=payload.dimension_type,
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

    publish_topic(DIMENSION_ITEM_TOPIC)
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

    if payload.code is not None:
        existing = db.scalar(
            select(DimensionItem).where(
                DimensionItem.dimension_type == item.dimension_type,
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

    publish_topic(DIMENSION_ITEM_TOPIC)
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

    publish_topic(DIMENSION_ITEM_TOPIC)
    return True
