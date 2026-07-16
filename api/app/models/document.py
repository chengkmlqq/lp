from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from ..core.database import Base

if TYPE_CHECKING:
    pass


class DocumentChapter(Base):
    __tablename__ = "document_chapters"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(String(512))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chapters.id", ondelete="CASCADE"),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped[DocumentChapter | None] = relationship(
        "DocumentChapter",
        remote_side=lambda: [DocumentChapter.id],
        back_populates="children",
        lazy="selectin",
    )
    children: Mapped[list[DocumentChapter]] = relationship(
        "DocumentChapter",
        back_populates="parent",
        lazy="selectin",
        order_by="DocumentChapter.sort_order",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="chapter",
        lazy="selectin",
        order_by="Document.sort_order",
        cascade="all, delete-orphan",
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    content: Mapped[str] = mapped_column(Text)
    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chapters.id", ondelete="CASCADE"),
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="draft", index=True
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    chapter: Mapped[DocumentChapter | None] = relationship(
        "DocumentChapter",
        back_populates="documents",
        lazy="selectin",
    )
