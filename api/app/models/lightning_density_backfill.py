from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

if TYPE_CHECKING:
    from .line import Line


class LightningDensityBackfillTask(Base):
    """地闪密度回填历史记录（每次回填生成一条，最新在上）。

    与雷电流回填历史（lightning_current_backfill_task）对齐；回填操作由
    Celery 异步驱动（prepare_line_lightning_density_job），本表同时承载
    任务状态机（status/progress/task_id/error_message）与「哪次回填、用了哪个
    分布、回填了多少塔、Ng 范围」的历史快照，供回填记录 tab 展示。
    """

    __tablename__ = "lightning_density_backfill_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    line_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("power_line.id", ondelete="CASCADE"), nullable=False, index=True
    )
    distribution_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    prepared_by_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    radius_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_years: Mapped[float | None] = mapped_column(Float, nullable=True)

    updated_tower_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_geo_count: Mapped[int] = mapped_column(Integer, default=0)

    avg_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    strike_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    # ---- 异步任务状态机（对齐 lightning_current_backfill_task，LP-432 模式）----
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 本次回填生成的「沿线圆」密度图对象键（每次回填各自一张，互不覆盖）
    circle_image_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    line: Mapped[Line] = relationship("Line", lazy="selectin")