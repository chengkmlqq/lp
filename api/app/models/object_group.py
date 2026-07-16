from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class ObjectGroup(Base):
    __tablename__ = "obj_group"
    __table_args__ = (
        UniqueConstraint("name", "type", "create_user", name="uq_obj_group_name_type_create_user"),
        Index("idx_obj_group_type", "type"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str | None] = mapped_column(String(64), index=True)
    descr: Mapped[str | None] = mapped_column(String(512))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)


class ObjectGroupRelation(Base):
    __tablename__ = "obj_group_obj_rela"
    __table_args__ = (
        UniqueConstraint("group_id", "obj_id", name="uq_obj_group_obj_rela_group_obj"),
        Index("idx_obj_group_obj_rela_group", "group_id"),
        Index("idx_obj_group_obj_rela_obj", "obj_id"),
    )

    rela_id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    group_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("obj_group.id", ondelete="CASCADE"),
        nullable=False,
    )
    obj_id: Mapped[str] = mapped_column(String(32), nullable=False)
