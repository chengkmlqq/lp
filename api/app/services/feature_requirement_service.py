"""功能需求单：CRUD + 列表筛选。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.feature_requirement import FeatureRequirement
from app.schemas.feature_requirement import (
    PRIORITIES,
    STATUSES,
    RequirementCreate,
    RequirementUpdate,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_requirements(
    db: Session,
    *,
    keyword: str | None = None,
    module: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FeatureRequirement], int]:
    stmt = select(FeatureRequirement)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(FeatureRequirement.title.ilike(like), FeatureRequirement.description.ilike(like))
        )
    if module:
        stmt = stmt.where(FeatureRequirement.module == module)
    if status:
        stmt = stmt.where(FeatureRequirement.status == status)
    if priority:
        stmt = stmt.where(FeatureRequirement.priority == priority)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(FeatureRequirement.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    return list(db.scalars(stmt).all()), int(total)


def get_requirement(db: Session, requirement_id: str) -> FeatureRequirement | None:
    return db.get(FeatureRequirement, requirement_id)


def create_requirement(db: Session, payload: RequirementCreate, *, operator: str | None = None) -> FeatureRequirement:
    row = FeatureRequirement(
        id=uuid.uuid4().hex,
        title=payload.title.strip(),
        module=(payload.module or None),
        priority=payload.priority or "\u4e2d",
        status=payload.status or "\u5f85\u5904\u7406",
        description=payload.description,
        created_by=operator,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_requirement(db: Session, row: FeatureRequirement, payload: RequirementUpdate) -> FeatureRequirement:
    data = payload.model_dump(exclude_unset=True)
    if "title" in data and data["title"]:
        row.title = data["title"].strip()
    for field in ("module", "priority", "status", "description"):
        if field in data:
            setattr(row, field, data[field])
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return row


def delete_requirement(db: Session, row: FeatureRequirement) -> None:
    db.delete(row)
    db.commit()


def list_modules(db: Session) -> list[str]:
    rows = db.execute(
        select(FeatureRequirement.module).where(FeatureRequirement.module.is_not(None)).distinct()
    ).all()
    values = {str(r[0]).strip() for r in rows if r[0]}
    for preset in ("\u9632\u96f7\u8ba1\u7b97", "\u53c2\u6570\u6a21\u677f", "\u96f7\u7535\u5b9a\u4f4d", "\u57fa\u7840\u6570\u636e", "\u5176\u4ed6"):
        values.add(preset)
    return sorted(values)


def meta() -> dict[str, list[str]]:
    return {"priorities": list(PRIORITIES), "statuses": list(STATUSES)}
