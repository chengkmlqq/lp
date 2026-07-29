from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models.param_category import SystemParamCategory
from ..models.system_param import SystemParam
from ..schemas.param_category import (
    ParamCategoryCreate,
    ParamCategoryTreeItem,
    ParamCategoryUpdate,
)


def serialize_category_tree(cat: SystemParamCategory) -> ParamCategoryTreeItem:
    return ParamCategoryTreeItem(
        id=cat.id,
        name=cat.name,
        parent_id=cat.parent_id,
        sort_order=cat.sort_order,
        children=[serialize_category_tree(child) for child in cat.children],
    )


def get_category_tree(db: Session) -> list[ParamCategoryTreeItem]:
    stmt = (
        select(SystemParamCategory)
        .options(selectinload(SystemParamCategory.children))
        .where(SystemParamCategory.parent_id.is_(None))
        .order_by(SystemParamCategory.sort_order)
    )
    roots = db.execute(stmt).scalars().all()
    return [serialize_category_tree(root) for root in roots]


def create_category(db: Session, payload: ParamCategoryCreate) -> ParamCategoryTreeItem:
    item = SystemParamCategory(
        name=payload.name.strip(),
        parent_id=payload.parent_id,
        sort_order=payload.sort_order,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    # Reload with children for the tree response
    loaded = db.execute(
        select(SystemParamCategory)
        .options(selectinload(SystemParamCategory.children))
        .where(SystemParamCategory.id == item.id)
    ).scalar_one()
    return serialize_category_tree(loaded)


def update_category(db: Session, category_id: int, payload: ParamCategoryUpdate) -> ParamCategoryTreeItem | None:
    item = db.get(SystemParamCategory, category_id)
    if not item:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        item.name = str(update_data["name"]).strip()
    if "parent_id" in update_data:
        item.parent_id = update_data["parent_id"]
    if "sort_order" in update_data and update_data["sort_order"] is not None:
        item.sort_order = update_data["sort_order"]

    db.commit()

    loaded = db.execute(
        select(SystemParamCategory)
        .options(selectinload(SystemParamCategory.children))
        .where(SystemParamCategory.id == category_id)
    ).scalar_one()
    return serialize_category_tree(loaded)


def delete_category(db: Session, category_id: int) -> bool:
    item = db.get(SystemParamCategory, category_id)
    if not item:
        return False

    # Check if any params reference this category
    param_count = db.scalar(
        select(SystemParam.id).where(SystemParam.category_id == category_id).limit(1)
    )
    if param_count is not None:
        return False

    db.delete(item)
    db.commit()
    return True