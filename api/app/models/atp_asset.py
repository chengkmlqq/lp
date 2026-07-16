from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow


class AtpAsset(Base):
    __tablename__ = "atp_asset"
    __table_args__ = (
        UniqueConstraint("code", name="uq_atp_asset_code"),
        Index("idx_atp_asset_status", "status"),
        Index("idx_atp_asset_voltage_level", "voltage_level"),
        Index("idx_atp_asset_tower_type", "tower_type"),
        Index("idx_atp_asset_scene_type", "scene_type"),
        Index("idx_atp_asset_arrester_config", "arrester_config"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled", index=True)
    voltage_level: Mapped[str | None] = mapped_column(String(16), index=True)
    tower_type: Mapped[str | None] = mapped_column(String(64), index=True)
    scene_type: Mapped[str | None] = mapped_column(String(32), index=True)
    arrester_config: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_root_path: Mapped[str | None] = mapped_column(String(2048), index=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    latest_release_no: Mapped[int] = mapped_column(Integer, default=0)
    active_release_no: Mapped[int | None] = mapped_column(Integer)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    releases: Mapped[list[AtpAssetRelease]] = relationship(
        "AtpAssetRelease",
        back_populates="asset",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpAssetRelease.release_no.desc()",
    )
    runs: Mapped[list[AtpAssetRun]] = relationship(
        "AtpAssetRun",
        back_populates="asset",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpAssetRun.create_date.desc()",
    )


class AtpAssetRelease(Base):
    __tablename__ = "atp_asset_release"
    __table_args__ = (
        UniqueConstraint("asset_id", "release_no", name="uq_atp_asset_release_asset_no"),
        Index("idx_atp_asset_release_status", "status"),
        Index("idx_atp_asset_release_runner_kind", "runner_kind"),
        Index("idx_atp_asset_release_storage_mount", "storage_mount_code"),
        Index("idx_atp_asset_release_asset_active", "asset_id", "is_active"),
        Index("idx_atp_asset_release_asset_status", "asset_id", "status"),
        Index("idx_atp_asset_release_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    asset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_no: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    release_tag: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    voltage_level: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    tower_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scene_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scenario_code: Mapped[str | None] = mapped_column(String(64), index=True)
    runner_kind: Mapped[str] = mapped_column(String(20), default="atp", index=True)
    storage_mount_code: Mapped[str] = mapped_column(String(64), default="main", index=True)
    storage_root_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    entry_file: Mapped[str | None] = mapped_column(String(255))
    result_file: Mapped[str | None] = mapped_column(String(255))
    egm_subdir: Mapped[str | None] = mapped_column(String(255))
    egm_result_file: Mapped[str | None] = mapped_column(String(255))
    preprocess_script: Mapped[str | None] = mapped_column(String(255))
    postprocess_script: Mapped[str | None] = mapped_column(String(255))
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    validation_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    asset: Mapped[AtpAsset] = relationship("AtpAsset", back_populates="releases", lazy="selectin")
    runs: Mapped[list[AtpAssetRun]] = relationship(
        "AtpAssetRun",
        back_populates="release",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpAssetRun.create_date.desc()",
    )


class AtpAssetRun(Base):
    __tablename__ = "atp_asset_run"
    __table_args__ = (
        Index("idx_atp_asset_run_status", "status"),
        Index("idx_atp_asset_run_asset", "asset_id", "create_date"),
        Index("idx_atp_asset_run_release", "release_id", "create_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    asset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset_release.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    engine_mode: Mapped[str] = mapped_column(String(20), default="wine", index=True)
    runner_kind: Mapped[str] = mapped_column(String(20), default="atp", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    storage_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_root_path: Mapped[str | None] = mapped_column(String(2048))
    materialized_root_path: Mapped[str | None] = mapped_column(String(2048))
    engine_command: Mapped[str | None] = mapped_column(String(2000))
    working_dir: Mapped[str | None] = mapped_column(String(2000))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stdout_text: Mapped[str | None] = mapped_column(Text())
    stderr_text: Mapped[str | None] = mapped_column(Text())
    output_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text())
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    asset: Mapped[AtpAsset] = relationship("AtpAsset", back_populates="runs", lazy="selectin")
    release: Mapped[AtpAssetRelease] = relationship("AtpAssetRelease", back_populates="runs", lazy="selectin")
