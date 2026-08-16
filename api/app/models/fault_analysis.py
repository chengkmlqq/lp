from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow


class FaultAnalysis(Base):
    __tablename__ = "fault_analysis"
    __table_args__ = (
        Index("idx_fault_analysis_line", "line_id"),
        Index("idx_fault_analysis_status", "status"),
        Index("idx_fault_analysis_risk", "risk_level"),
    )

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=lambda: uuid4().hex,
    )
    title: Mapped[str | None] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    line_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("power_line.id", ondelete="SET NULL"),
        index=True,
    )
    line_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), index=True)

    # 故障基本信息
    fault_time: Mapped[str | None] = mapped_column(String(64))
    fault_type: Mapped[str | None] = mapped_column(String(255))
    fault_phase: Mapped[str | None] = mapped_column(String(32))
    fault_duration_ms: Mapped[float | None] = mapped_column(Float)
    station: Mapped[str | None] = mapped_column(String(255))
    reclosure_status: Mapped[str | None] = mapped_column(String(32))

    # 电气参数
    fault_voltage_v: Mapped[float | None] = mapped_column(Float)
    fault_current_a: Mapped[float | None] = mapped_column(Float)
    max_zero_current_a: Mapped[float | None] = mapped_column(Float)
    zero_compensation: Mapped[float | None] = mapped_column(Float)
    fault_resistance_ohm: Mapped[float | None] = mapped_column(Float)
    line_length_km: Mapped[float | None] = mapped_column(Float)
    line_angle_deg: Mapped[float | None] = mapped_column(Float)
    line_impedance_ohm: Mapped[float | None] = mapped_column(Float)

    # 雷电信息
    lightning_current_ka: Mapped[float | None] = mapped_column(Float)
    lightning_longitude: Mapped[float | None] = mapped_column(Float)
    lightning_latitude: Mapped[float | None] = mapped_column(Float)

    # 测距
    wave_distance_km: Mapped[float | None] = mapped_column(Float)
    traveling_wave_distance_km: Mapped[float | None] = mapped_column(Float)
    optical_position: Mapped[str | None] = mapped_column(String(64))
    optical_device_location: Mapped[str | None] = mapped_column(String(255))

    # 置信度
    confidence: Mapped[float | None] = mapped_column(Float)

    # 结果
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 上传的判别输入文件（判别系统字段名 -> 共享卷内相对路径），由判别任务读取
    upload_files: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 进度（0-100，异步判别任务执行过程中递增）
    progress: Mapped[float] = mapped_column(Float, default=0)

    # 审计
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    # 关联
    line = relationship("Line", lazy="selectin")
