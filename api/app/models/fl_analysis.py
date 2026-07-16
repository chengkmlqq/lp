from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line
    from .line_tower import LineTower


class FlAnalysisJob(Base):
    __tablename__ = "fl_analysis_job"
    __table_args__ = (
        Index("idx_fl_analysis_job_line", "line_id"),
        Index("idx_fl_analysis_job_status", "status"),
        Index("idx_fl_analysis_job_type", "job_type"),
        Index("idx_fl_analysis_job_adapter", "external_adapter"),
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
    job_name: Mapped[str | None] = mapped_column(String(255), index=True)
    job_type: Mapped[str] = mapped_column(String(32), default="normal", index=True)
    source_kind: Mapped[str] = mapped_column(String(32), default="line", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    total_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshotted_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    result_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    external_adapter: Mapped[str] = mapped_column(String(32), default="placeholder", index=True)
    adapter_config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    execution_options_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
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
    runs: Mapped[list[FlAnalysisRun]] = relationship(
        "FlAnalysisRun",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FlAnalysisRun.create_date.desc()",
    )


class FlAnalysisRun(Base):
    __tablename__ = "fl_analysis_run"
    __table_args__ = (
        Index("idx_fl_analysis_run_job", "job_id"),
        Index("idx_fl_analysis_run_status", "status"),
        Index("idx_fl_analysis_run_runner", "runner_kind"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    runner_kind: Mapped[str] = mapped_column(String(32), default="placeholder", index=True)
    engine_command: Mapped[str | None] = mapped_column(String(2048))
    working_dir: Mapped[str | None] = mapped_column(String(2048))
    stdout_text: Mapped[str | None] = mapped_column(Text)
    stderr_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    snapshot_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    result_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
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

    job: Mapped[FlAnalysisJob] = relationship("FlAnalysisJob", lazy="selectin")


class FlAnalysisTowerSnapshot(Base):
    __tablename__ = "fl_analysis_tower_snapshot"
    __table_args__ = (
        Index("idx_fl_analysis_tower_snapshot_job", "job_id"),
        Index("idx_fl_analysis_tower_snapshot_run", "run_id"),
        Index("idx_fl_analysis_tower_snapshot_tower", "tower_id"),
        Index("idx_fl_analysis_tower_snapshot_seq", "run_id", "seq_no"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tower_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("power_line_tower.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq_no: Mapped[int] = mapped_column(Integer, default=0)
    tower_no: Mapped[str] = mapped_column(String(64), index=True)
    tower_model: Mapped[str | None] = mapped_column(String(128), index=True)
    tower_type: Mapped[str | None] = mapped_column(String(32), index=True)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float)
    terrain: Mapped[str | None] = mapped_column(String(64), index=True)
    base_tower_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    job: Mapped[FlAnalysisJob] = relationship("FlAnalysisJob", lazy="selectin")
    run: Mapped[FlAnalysisRun] = relationship("FlAnalysisRun", lazy="selectin")
    tower: Mapped[LineTower] = relationship("LineTower", lazy="selectin")


class FlAnalysisTowerResult(Base):
    __tablename__ = "fl_analysis_tower_result"
    __table_args__ = (
        Index("idx_fl_analysis_tower_result_job", "job_id"),
        Index("idx_fl_analysis_tower_result_run", "run_id"),
        Index("idx_fl_analysis_tower_result_snapshot", "snapshot_id"),
        Index("idx_fl_analysis_tower_result_status", "status"),
        Index("idx_fl_analysis_tower_result_risk", "risk_level"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_job.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_tower_snapshot.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), index=True)
    summary_text: Mapped[str | None] = mapped_column(Text)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )

    job: Mapped[FlAnalysisJob] = relationship("FlAnalysisJob", lazy="selectin")
    run: Mapped[FlAnalysisRun] = relationship("FlAnalysisRun", lazy="selectin")
    snapshot: Mapped[FlAnalysisTowerSnapshot] = relationship("FlAnalysisTowerSnapshot", lazy="selectin")