from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .user import User


class FileStorageBackend(Base):
    __tablename__ = "file_storage_backends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    driver_type: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default="enabled", index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    mounts: Mapped[list[FileStorageMount]] = relationship(
        "FileStorageMount",
        back_populates="backend",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class FileStorageMount(Base):
    __tablename__ = "file_storage_mounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    backend_id: Mapped[int] = mapped_column(
        ForeignKey("file_storage_backends.id", ondelete="CASCADE"),
        index=True,
    )
    mount_path: Mapped[str] = mapped_column(String(255), default="/", index=True)
    root_path: Mapped[str] = mapped_column(String(1024), default="/")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    backend: Mapped[FileStorageBackend] = relationship(
        "FileStorageBackend",
        back_populates="mounts",
        lazy="joined",
    )
    index_entries: Mapped[list[FileIndexEntry]] = relationship(
        "FileIndexEntry",
        back_populates="mount",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class FileIndexEntry(Base):
    __tablename__ = "file_index_entries"
    __table_args__ = (
        UniqueConstraint("mount_id", "path", name="uq_file_index_mount_path"),
        Index("idx_file_index_mount_parent_name", "mount_id", "parent_path", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mount_id: Mapped[int] = mapped_column(
        ForeignKey("file_storage_mounts.id", ondelete="CASCADE"),
        index=True,
    )
    path: Mapped[str] = mapped_column(String(2048), index=True)
    parent_path: Mapped[str] = mapped_column(String(2048), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    is_dir: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(2048))
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    mount: Mapped[FileStorageMount] = relationship(
        "FileStorageMount",
        back_populates="index_entries",
        lazy="joined",
    )
    last_synced_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        index=True,
    )
    last_synced_by_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[last_synced_by_user_id],
        lazy="selectin",
    )
