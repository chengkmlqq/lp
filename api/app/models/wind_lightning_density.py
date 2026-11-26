from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base, JsonColumn
from .base import utcnow


class WindLightningDensityBatch(Base):
    """风电场地闪密度统计批次（一次「风机点位 + 雷电定位」计算的完整快照）。

    与 ``lightning_distribution``（GB/T 40621 地闪密度统计）完全独立：表、接口、
    权限、页面互不共享，只复用通用基础设施（Celery / 对象存储 / AntD）。

    算法口径以核心程序 ``地闪密度/density.py`` 为准：
    - 统计范围为风机经纬度 min/max 四周各外扩 ``margin_deg``（默认 0.01°）；
    - 网格步长 ``grid_step_deg``（默认 0.01°），``arange(min, max+step, step)`` 含终点；
    - 密度 = 网格落雷计数 ÷ 统计年限（``density_per_cell_year``）；
      ``density_per_km2_year`` 再除以网格面积（按核心程序 1°=100km 口径，0.01° 格 = 1km²）。
    """

    __tablename__ = "wind_lightning_density_batch"
    __table_args__ = (
        Index("idx_wld_batch_status", "status"),
        Index("idx_wld_batch_create_date", "create_date"),
        Index("idx_wld_batch_is_deleted", "is_deleted"),
        Index("idx_wld_batch_prep_batch_id", "prep_batch_id"),
        # 批次名后端生成且全局唯一；并发撞名由 create_batch 捕获 IntegrityError 后重试。
        Index("uq_wld_batch_name", "batch_name", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    batch_name: Mapped[str] = mapped_column(String(255), default="")
    wind_farm_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 来源「风电场数据准备」批次 id（复用其风机/雷电源文件）；历史手工上传批次为空。
    prep_batch_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # ---- 参数（默认值与 density.py 一致）----
    grid_step_deg: Mapped[float] = mapped_column(Float, default=0.01)
    margin_deg: Mapped[float] = mapped_column(Float, default=0.01)
    data_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    years_source: Mapped[str] = mapped_column(String(32), default="auto")  # auto|fixed

    # ---- 源文件（对象存储 Key）----
    turbine_source_file_name: Mapped[str] = mapped_column(String(255), default="")
    turbine_object_key: Mapped[str] = mapped_column(String(512), default="")
    lightning_source_file_name: Mapped[str] = mapped_column(String(255), default="")
    lightning_object_key: Mapped[str] = mapped_column(String(512), default="")

    # ---- 解析结果 ----
    turbine_count: Mapped[int] = mapped_column(Integer, default=0)
    total_records: Mapped[int] = mapped_column(Integer, default=0)
    valid_records: Mapped[int] = mapped_column(Integer, default=0)
    skipped_records: Mapped[int] = mapped_column(Integer, default=0)

    # ---- 研究范围与网格 ----
    bbox_min_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_max_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_min_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    bbox_max_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_x_count: Mapped[int] = mapped_column(Integer, default=0)
    grid_y_count: Mapped[int] = mapped_column(Integer, default=0)
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- 统计结果 ----
    overall_density: Mapped[float | None] = mapped_column(Float, nullable=True)  # 次/(km²·年)
    peak_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    # ---- 状态机 ----
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed
    stage: Mapped[str] = mapped_column(String(32), default="parsing")  # parsing|computing|rendering|saving
    progress: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 出图 ----
    image_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # LP-83：4 种预生成图（bilinear/nearest × km2/cell）的 object key。
    # 键为 "bilinear-km2" / "bilinear-cell" / "nearest-km2" / "nearest-cell"；
    # image_object_key 保留为默认图（bilinear-km2）以兼容旧批次。
    image_variants_json: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)

    # ---- 审计 ----
    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    cells: Mapped[list[WindLightningDensityCell]] = relationship(
        "WindLightningDensityCell",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="select",
    )
    turbines: Mapped[list[WindLightningDensityTurbine]] = relationship(
        "WindLightningDensityTurbine",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WindLightningDensityCell(Base):
    """批次内一个网格（0.01° 默认）的落雷计数与密度。

    只落库「有落雷或有风机」的网格，避免 500×500 网格时写入 25 万行空值；
    零值网格由统计卡与出图重建时补齐。
    """

    __tablename__ = "wind_lightning_density_cell"
    __table_args__ = (
        Index("idx_wld_cell_batch_ij", "batch_id", "cell_i", "cell_j"),
        Index("idx_wld_cell_batch", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    batch_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("wind_lightning_density_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    cell_i: Mapped[int] = mapped_column(Integer, nullable=False)  # 经度方向列号（0 基）
    cell_j: Mapped[int] = mapped_column(Integer, nullable=False)  # 纬度方向行号（0 基）

    center_lon: Mapped[float] = mapped_column(Float, default=0.0)
    center_lat: Mapped[float] = mapped_column(Float, default=0.0)
    min_lon: Mapped[float] = mapped_column(Float, default=0.0)
    max_lon: Mapped[float] = mapped_column(Float, default=0.0)
    min_lat: Mapped[float] = mapped_column(Float, default=0.0)
    max_lat: Mapped[float] = mapped_column(Float, default=0.0)

    strike_count: Mapped[int] = mapped_column(Integer, default=0)
    density_per_cell_year: Mapped[float] = mapped_column(Float, default=0.0)
    density_per_km2_year: Mapped[float] = mapped_column(Float, default=0.0)
    turbine_count: Mapped[int] = mapped_column(Integer, default=0)

    batch: Mapped[WindLightningDensityBatch] = relationship(
        "WindLightningDensityBatch", back_populates="cells", lazy="select"
    )


class WindLightningDensityTurbine(Base):
    """风机点位及其所在网格快照（用于导出 file_3/file_4 与风机表展示）。"""

    __tablename__ = "wind_lightning_density_turbine"
    __table_args__ = (
        Index("idx_wld_turbine_batch_seq", "batch_id", "seq"),
        Index("idx_wld_turbine_batch", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    batch_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("wind_lightning_density_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    seq: Mapped[int] = mapped_column(Integer, default=1)
    turbine_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lon: Mapped[float] = mapped_column(Float, default=0.0)
    lat: Mapped[float] = mapped_column(Float, default=0.0)
    cell_i: Mapped[int] = mapped_column(Integer, default=-1)
    cell_j: Mapped[int] = mapped_column(Integer, default=-1)
    cell_density: Mapped[float] = mapped_column(Float, default=0.0)

    batch: Mapped[WindLightningDensityBatch] = relationship(
        "WindLightningDensityBatch", back_populates="turbines", lazy="select"
    )
