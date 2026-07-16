from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line
    from .user import User


class ElevationDataset(Base):
    __tablename__ = "elevation_dataset"
    __table_args__ = (
        Index("idx_elevation_dataset_status", "status"),
        Index("idx_elevation_dataset_usage_status", "usage_status"),
        Index("idx_elevation_dataset_mount_code", "mount_code"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str | None] = mapped_column(String(128), index=True)
    file_format: Mapped[str] = mapped_column(String(32), default="csv", index=True)
    mount_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dataset_dir: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    resolution_m: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    usage_status: Mapped[str] = mapped_column(String(32), default="idle", index=True)
    analysis_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    analysis_status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    analysis_error_message: Mapped[str | None] = mapped_column(Text)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terrain_status: Mapped[str] = mapped_column(String(32), default="not_supported", index=True)
    terrain_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    terrain_error_message: Mapped[str | None] = mapped_column(Text)
    terrain_root_path: Mapped[str | None] = mapped_column(String(2048))
    terrain_url_template: Mapped[str | None] = mapped_column(String(2048))
    terrain_min_zoom: Mapped[int | None] = mapped_column(Integer)
    terrain_max_zoom: Mapped[int | None] = mapped_column(Integer)
    terrain_bounds: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    terrain_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    bbox_min_lon: Mapped[float | None] = mapped_column(Float)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float)
    bbox_min_lat: Mapped[float | None] = mapped_column(Float)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float)
    data_source_type: Mapped[str] = mapped_column(String(32), default="generic", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)


class ElevationApplyJob(Base):
    __tablename__ = "elevation_apply_job"
    __table_args__ = (
        Index("idx_elevation_apply_job_status", "status"),
        Index("idx_elevation_apply_job_line", "line_id"),
        Index("idx_elevation_apply_job_dataset", "dataset_id"),
        Index("idx_elevation_apply_job_file_record", "file_record_id"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    line_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("power_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("elevation_dataset.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_record_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("elevation_file_record.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(32), default="fill_null_only", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    total_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_geo_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    line: Mapped[Line] = relationship("Line", lazy="selectin")
    dataset: Mapped[ElevationDataset | None] = relationship("ElevationDataset", lazy="selectin")
    file_record: Mapped[ElevationFileRecord | None] = relationship("ElevationFileRecord", lazy="selectin", foreign_keys=[file_record_id])


class ElevationDataImportJob(Base):
    __tablename__ = "elevation_data_import_job"
    __table_args__ = (
        Index("idx_elevation_data_import_job_status", "status"),
        Index("idx_elevation_data_import_job_dataset", "dataset_id"),
        Index("idx_elevation_data_import_job_file_record", "file_record_id"),
        Index("idx_elevation_data_import_job_create_date", "create_date"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("elevation_dataset.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    file_record_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("elevation_file_record.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    detail_message: Mapped[str | None] = mapped_column(Text)
    trigger_analysis: Mapped[bool] = mapped_column(Boolean, default=True)
    analysis_task_queued: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    uploaded_file_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_file_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_file_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    imported_files_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    staged_files_json: Mapped[list[dict[str, str | None]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    dataset: Mapped[ElevationDataset | None] = relationship("ElevationDataset", lazy="selectin")
    file_record: Mapped[ElevationFileRecord | None] = relationship("ElevationFileRecord", lazy="selectin", foreign_keys=[file_record_id])


class ElevationDatasetFileMeta(Base):
    __tablename__ = "elevation_dataset_file_meta"
    __table_args__ = (
        Index("idx_elevation_file_meta_dataset", "dataset_id"),
        Index("idx_elevation_file_meta_path", "dataset_id", "file_path"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("elevation_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    bbox_min_lon: Mapped[float | None] = mapped_column(Float)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float)
    bbox_min_lat: Mapped[float | None] = mapped_column(Float)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    dataset: Mapped[ElevationDataset] = relationship("ElevationDataset", lazy="selectin")


class ElevationFileRecord(Base):
    __tablename__ = "elevation_file_record"
    __table_args__ = (
        Index("idx_elevation_file_record_status", "status"),
        Index("idx_elevation_file_record_mount_code", "mount_code"),
        Index("idx_elevation_file_record_analysis_status", "analysis_status"),
        Index("idx_elevation_file_record_terrain_status", "terrain_status"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    file_format: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(512), index=True)
    mount_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resolution_m: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    bbox_min_lon: Mapped[float | None] = mapped_column(Float)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float)
    bbox_min_lat: Mapped[float | None] = mapped_column(Float)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    analysis_status: Mapped[str] = mapped_column(String(32), default="not_started", index=True)
    analysis_error_message: Mapped[str | None] = mapped_column(Text)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terrain_status: Mapped[str] = mapped_column(String(32), default="not_supported", index=True)
    terrain_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    terrain_error_message: Mapped[str | None] = mapped_column(Text)
    terrain_root_path: Mapped[str | None] = mapped_column(String(2048))
    terrain_url_template: Mapped[str | None] = mapped_column(String(2048))
    terrain_min_zoom: Mapped[int | None] = mapped_column(Integer)
    terrain_max_zoom: Mapped[int | None] = mapped_column(Integer)
    terrain_bounds: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    terrain_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    data_source_type: Mapped[str] = mapped_column(String(32), default="generic", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)
