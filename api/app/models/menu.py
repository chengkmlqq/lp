from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base

if TYPE_CHECKING:
    from .rbac import Role


class Menu(Base):
    __tablename__ = "menus"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    path: Mapped[str | None] = mapped_column(String(255), index=True)
    icon: Mapped[str | None] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("menus.id", ondelete="SET NULL"),
        index=True,
    )
    type: Mapped[str] = mapped_column(String(16), default="menu", index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(String(16), default="enabled", index=True)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    cacheable: Mapped[bool] = mapped_column(Boolean, default=False)
    component: Mapped[str | None] = mapped_column(String(255))
    permission_code: Mapped[str | None] = mapped_column(String(64), index=True)

    parent: Mapped[Menu | None] = relationship(
        "Menu",
        remote_side=lambda: [Menu.id],
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list[Menu]] = relationship(
        "Menu",
        back_populates="parent",
        lazy="selectin",
        order_by="Menu.sort_order",
    )
    roles: Mapped[list[Role]] = relationship(
        "Role",
        secondary="role_menus",
        back_populates="menus",
        lazy="selectin",
    )


class RoleMenu(Base):
    __tablename__ = "role_menus"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    menu_id: Mapped[int] = mapped_column(
        ForeignKey("menus.id", ondelete="CASCADE"),
        primary_key=True,
    )
