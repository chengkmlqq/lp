from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, JsonColumn
from .base import utcnow


class WindDataPrepBatch(Base):
    """风电场数据准备批次（一次完整的数据准备快照）。

    与 LP-32 的 ``wind_lightning_density_batch`` 完全独立：独立表、接口、菜单与权限点，
    只共用通用基础设施（Celery / 对象存储 / AntD）和纯函数内核 ``wind_grid.py``。
    """

    __tablename__ = "wind_data_prep_batch"
    __table_args__ = (
        Index("idx_wdp_batch_status", "status"),
        Index("idx_wdp_batch_create_date", "create_date"),
        Index("idx_wdp_batch_is_deleted", "is_deleted"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), default="")
    wind_farm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 参数 ----
    start_lon: Mapped[float] = mapped_column(Float, default=0.0)
    start_lat: Mapped[float] = mapped_column(Float, default=0.0)
    grid_nx: Mapped[int] = mapped_column(Integer, default=0)
    grid_ny: Mapped[int] = mapped_column(Integer, default=0)
    grid_step_deg: Mapped[float] = mapped_column(Float, default=0.01)
    risk_base_s: Mapped[float] = mapped_column(Float, default=0.0)
    data_years: Mapped[int] = mapped_column(Integer, default=6)
    terrain_mode: Mapped[str] = mapped_column(String(16), default="zero")  # zero|tif

    # ---- 源与产物（对象存储 Key）----
    turbine_file_key: Mapped[str] = mapped_column(String(512), default="")
    lightning_file_key: Mapped[str] = mapped_column(String(512), default="")
    terrain_file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    turbine_file_name: Mapped[str] = mapped_column(String(255), default="")
    lightning_file_name: Mapped[str] = mapped_column(String(255), default="")
    terrain_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ---- 统计 ----
    turbine_count: Mapped[int] = mapped_column(Integer, default=0)
    lightning_total: Mapped[int] = mapped_column(Integer, default=0)
    lightning_valid: Mapped[int] = mapped_column(Integer, default=0)
    lightning_in_scope: Mapped[int] = mapped_column(Integer, default=0)
    nonzero_cell_count: Mapped[int] = mapped_column(Integer, default=0)
    zero_nl_turbine_count: Mapped[int] = mapped_column(Integer, default=0)
    nl_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    nl_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    nl_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- 状态机 ----
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed
    stage: Mapped[str] = mapped_column(String(32), default="parsing")  # parsing|computing|serializing|saving|done
    progress: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 产物文件 Key ----
    file1_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file2_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file4_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    p0abc_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    package_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    report_json: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    # ---- 审计 ----
    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    turbines: Mapped[list[WindDataPrepTurbine]] = relationship(
        "WindDataPrepTurbine",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WindDataPrepTurbine(Base):
    """风机明细：所在格编号、落雷次数及东邻格对照（用于解释修正前后差异）。"""

    __tablename__ = "wind_data_prep_turbine"
    __table_args__ = (
        Index("idx_wdp_turbine_batch_seq", "batch_id", "seq"),
        Index("idx_wdp_turbine_batch", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    batch_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("wind_data_prep_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    turbine_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    cell_i: Mapped[int] = mapped_column(Integer, default=-1)
    cell_j: Mapped[int] = mapped_column(Integer, default=-1)
    grid_id: Mapped[int] = mapped_column(Integer, default=0)
    flash_count: Mapped[int] = mapped_column(Integer, default=0)
    flash_count_east: Mapped[int] = mapped_column(Integer, default=0)  # 东邻格（错位版对照）
    nl: Mapped[float] = mapped_column(Float, default=0.0)
    density_per_km2_year: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    blade: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    circuit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_elev: Mapped[float | None] = mapped_column(Float, nullable=True)

    batch: Mapped[WindDataPrepBatch] = relationship(
        "WindDataPrepBatch", back_populates="turbines", lazy="select"
    )
