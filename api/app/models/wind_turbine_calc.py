from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, JsonColumn
from .base import utcnow


class WindTurbineCalcJob(Base):
    """单风机计算任务（一次 MATLAB 编译产物调用 = 一个 job）。

    几何/接闪器/雷电流/角度等参数全部落在任务自身，不依赖任何其它模块批次。
    核心程序视为黑盒：LP 只负责写 params.json、调度 matlab-wind worker、
    解析 results/failure_rate_by_theta.csv 并落库，不改动算法。
    """

    __tablename__ = "wind_turbine_calc_job"
    __table_args__ = (
        Index("idx_wtc_job_status", "status"),
        Index("idx_wtc_job_create_date", "create_date"),
        Index("idx_wtc_job_is_deleted", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), default="")

    # 参数
    hub_height: Mapped[float] = mapped_column(Float, default=105.5)
    receptor_radii: Mapped[list] = mapped_column(JsonColumn, nullable=False)  # list[float]
    blade_length: Mapped[float] = mapped_column(Float, default=82.6)
    start_current: Mapped[float] = mapped_column(Float, default=1.0)
    angle_list: Mapped[list] = mapped_column(JsonColumn, nullable=False)  # list[float]
    angle_count: Mapped[int] = mapped_column(Integer, default=0)

    # 使用的引擎（引擎管理里的 wind_turbine_calc 模块版本）
    engine_module: Mapped[str] = mapped_column(String(64), default="wind_turbine_calc")
    engine_version_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    engine_version_tag: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 执行状态
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed|cancelled
    stage: Mapped[str] = mapped_column(String(32), default="preparing")  # preparing|running|parsing|saving|done|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 已完成角度数占比
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 统计摘要
    mean_failure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_failure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_failure_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_failure_rate_theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_failure_rate_theta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 产物：LP 生成的曲线 PNG（对象存储 key）
    chart_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    csv_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    results: Mapped[list[WindTurbineCalcResult]] = relationship(
        "WindTurbineCalcResult",
        back_populates="job",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WindTurbineCalcResult(Base):
    """逐旋转角屏蔽失效率结果。"""

    __tablename__ = "wind_turbine_calc_result"
    __table_args__ = (
        Index("idx_wtc_result_job_theta", "job_id", "theta_deg"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    job_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("wind_turbine_calc_job.id", ondelete="CASCADE"),
        nullable=False,
    )
    theta_deg: Mapped[float] = mapped_column(Float, nullable=False)
    failure_rate: Mapped[float] = mapped_column(Float, nullable=False)
    failure_rate_pct: Mapped[float] = mapped_column(Float, nullable=False)

    job: Mapped[WindTurbineCalcJob] = relationship(
        "WindTurbineCalcJob", back_populates="results", lazy="select"
    )
