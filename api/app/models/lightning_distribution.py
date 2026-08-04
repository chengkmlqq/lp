from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class LightningDistribution(Base):
    """雷电流地闪密度一次导入的「批次 + 统计结果 + 图片引用」记录。

    取代旧的 LightningImportBatch（分布导入部分）与 LightningDistributionPoint：
    - 原始上传文件与生成的密度图均存 MinIO，DB 只存对象 Key；
    - 落雷明细不再入库，事件明细展示逻辑全部移除；
    - 密度计算改为直接读取 MinIO 上的原始文件解析。
    """

    __tablename__ = "lightning_distribution"
    __table_args__ = (
        Index("idx_ld_region", "region_id"),
        Index("idx_ld_location_tag", "location_tag"),
        Index("idx_ld_city", "city"),
        Index("idx_ld_line_id", "line_id"),
        Index("idx_ld_status", "status"),
        Index("idx_ld_create_date", "create_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    region_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location_tag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source_file_name: Mapped[str] = mapped_column(String(255), default="upload")
    source_object_key: Mapped[str] = mapped_column(String(512), default="")
    import_type: Mapped[str] = mapped_column(String(32), default="distribution")

    # ---- 状态机 ----
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|processing|completed|failed
    stage: Mapped[str] = mapped_column(String(32), default="parsing")   # parsing|validating|statistics|rendering
    progress: Mapped[int] = mapped_column(Integer, default=0)           # 0-100
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- 元数据（校验/解析结果）----
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    valid_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # ---- 统计结果（页面展示）----
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    grid_size_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_ng: Mapped[float | None] = mapped_column(Float, nullable=True)  # Ng（次/km²/年）
    max_abs_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_abs_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    positive_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_count: Mapped[int] = mapped_column(Integer, default=0)
    unknown_count: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)  # 冗余的完整统计（不含 grid_cells，避免响应体过大）

    # ---- 图片（MinIO）----
    image_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lp_image_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)  # LP 桌面端 Voronoi 分区密度图

    # ---- 审计 ----
    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), nullable=True)
