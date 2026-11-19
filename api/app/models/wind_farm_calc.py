from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, JsonColumn
from .base import utcnow


class WindFarmCalcJob(Base):
    """风电场计算任务（一次 Wine 调用 = 一个 job）。

    输入只来自 LP-33 的已完成数据准备批次，不开放用户直接上传 file_1~4 / P0.abc。
    """

    __tablename__ = "wind_farm_calc_job"
    __table_args__ = (
        Index("idx_wfc_job_status", "status"),
        Index("idx_wfc_job_prep_batch", "prep_batch_id"),
        Index("idx_wfc_job_create_date", "create_date"),
        Index("idx_wfc_job_is_deleted", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), default="")
    prep_batch_id: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    engine_md5: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed|cancelled
    stage: Mapped[str] = mapped_column(String(32), default="fetching")  # fetching|preflight|running|parsing|saving|done|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    stdout_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    output_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    preflight_json: Mapped[dict | None] = mapped_column(JsonColumn, nullable=True)

    turbine_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_I_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_II_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_III_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_IV_count: Mapped[int] = mapped_column(Integer, default=0)
    shutdown_count: Mapped[int] = mapped_column(Integer, default=0)
    circuit_shutdown_count: Mapped[int] = mapped_column(Integer, default=0)
    farm_shutdown_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_mismatch_count: Mapped[int] = mapped_column(Integer, default=0)

    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    results: Mapped[list[WindFarmCalcResult]] = relationship(
        "WindFarmCalcResult",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WindFarmCalcResult(Base):
    """逐台风机计算结果（GBK 原文保留在 raw_line 仅供对照）。"""

    __tablename__ = "wind_farm_calc_result"
    __table_args__ = (
        Index("idx_wfc_result_job_seq", "job_id", "seq"),
        Index("idx_wfc_result_job_risk", "job_id", "risk_level"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("wind_farm_calc_job.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    turbine_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    value_v: Mapped[float] = mapped_column(Float, default=0.0)
    risk_level: Mapped[int] = mapped_column(Integer, default=1)
    suggestion_code: Mapped[int] = mapped_column(Integer, default=1)
    suggestion_text: Mapped[str] = mapped_column(String(64), default="无")
    circuit_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_line: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[WindFarmCalcJob] = relationship(
        "WindFarmCalcJob", back_populates="results", lazy="select"
    )
