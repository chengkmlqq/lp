from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMTEXT
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
    )
    job_name: Mapped[str | None] = mapped_column(String(255), index=True)
    job_type: Mapped[str] = mapped_column(String(32), default="normal")
    source_kind: Mapped[str] = mapped_column(String(32), default="line", index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    latest_run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # 2026-11-09：测试集标记——非空表示该任务由防雷测试集用例发起
    # （fl_test_set_run_case.id）。防雷计算页/防雷改造页默认排除带标记的任务，
    # 测试集页面按标记聚合查看（nullable + 无外键，历史任务不受影响）。
    test_run_case_id: Mapped[str | None] = mapped_column(String(32), index=True)
    total_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    snapshotted_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    result_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    # 塔内进度：当前正在计算的那根杆塔已完成的比例（0~1），用于进度条细分到单塔内部子步骤
    fractional_progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_step_text: Mapped[str | None] = mapped_column(String(255))
    external_adapter: Mapped[str] = mapped_column(String(32), default="placeholder")
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
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    runner_kind: Mapped[str] = mapped_column(String(32), default="placeholder")
    engine_command: Mapped[str | None] = mapped_column(String(2048))
    working_dir: Mapped[str | None] = mapped_column(String(2048))
    # ⚠️ MEDIUMTEXT（2026-11-05）：35kV 12 塔全量 ATP stdout 聚合超 TEXT 64KB 上限，
    # 收尾回写撞 DataError 1406 把已成功的任务标成 failed。单塔截断上限是 200k，
    # 12 塔聚合可达 2.4MB，TEXT 装不下。
    stdout_text: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"))
    stderr_text: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT, "mysql"))
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
    )
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    tower_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("power_line_tower.id", ondelete="CASCADE"),
        nullable=False,
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
        # ⚠️ 结果幂等（2026-09-18）：同一 run 内同一塔（snapshot）只允许一条结果。
        # 防止 Redis visibility_timeout 重投导致 execute_job 双执行时结果翻倍。
        UniqueConstraint("run_id", "snapshot_id", name="uq_fl_analysis_tower_result_run_snapshot"),
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
    )
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    snapshot_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_analysis_tower_snapshot.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    risk_level: Mapped[str | None] = mapped_column(String(32))
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