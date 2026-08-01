from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class LightningAmplitude(Base):
    """雷电流幅值一次导入的「状态机 + 元数据 + 波形特征统计 + MinIO 引用」记录。

    取代旧的 LightningCurrentEvent / LightningCurrentSample / LightningImportBatch：
    - 原始上传文件直接存 MinIO，DB 只存对象 Key，不再写容器临时盘；
    - 波形采样明细不再入库（Sample 表删除），波形详情弹窗删除；
    - 异步任务只做「解析 → 特征提取 → 统计回写」，状态机对标 LightningDistribution；
    - 峰值超越概率 P 曲线基于本表 peak_abs_current_ka（仅 completed 记录）聚合。
    """

    __tablename__ = "lightning_amplitude"
    __table_args__ = (
        Index("idx_la_status", "status"),
        Index("idx_la_region", "region_id"),
        Index("idx_la_city", "city"),
        Index("idx_la_create_date", "create_date"),
        Index("idx_la_peak_abs", "peak_abs_current_ka"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)

    # ---- 事件标识 ----
    event_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    source_file_name: Mapped[str] = mapped_column(String(255), default="upload")
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- MinIO 引用 ----
    source_object_key: Mapped[str] = mapped_column(String(512), default="")

    # ---- 状态机（对标 LightningDistribution）----
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)           # 0-100
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 采样信息（解析回写）----
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    sample_interval_us: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampling_frequency_hz: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- 波形特征（解析提取，全部保留）----
    peak_current_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_abs_current_ka: Mapped[float | None] = mapped_column(Float, nullable=True)
    wavefront_time_t1_us: Mapped[float | None] = mapped_column(Float, nullable=True)
    half_value_time_t2_us: Mapped[float | None] = mapped_column(Float, nullable=True)
    steepness_ka_per_us: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_integral_j_ohm: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_shape: Mapped[str | None] = mapped_column(String(32), nullable=True)
    polarity: Mapped[str] = mapped_column(String(16), default="unknown")
    stroke_count: Mapped[int] = mapped_column(Integer, default=1)
    stroke_peaks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # ---- 元数据 ----
    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    install_position: Mapped[str | None] = mapped_column(String(128), nullable=True)
    weather_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pressure_hpa: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 审计 ----
    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
