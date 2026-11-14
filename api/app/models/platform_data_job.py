from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.database import Base
from .base import utcnow


class PlatformDataJob(Base):
    """平台基础数据包任务：记录每一次导入/导出任务及其产物，支撑异步轮询与产物复用。

    - 导出：request_payload_json 记录所选类别 + 筛选条件；artifact_* 指向产出的包。
    - 导入：request_payload_json 记录来源（上传文件 or 复用某 export job_id）；
      artifact_* 指向「收到的包副本」，便于再次导入或审计。
    - manifest_json：包清单（内容分类、各分类计数、schema_version、来源站点、checksum）。
    - result_summary_json：导出=文件大小/各分类计数；导入=各分类 created/updated/skipped/failed 计数。
    """

    __tablename__ = "platform_data_job"
    __table_args__ = (
        Index("idx_platform_data_job_kind", "kind"),
        Index("idx_platform_data_job_status", "status"),
        Index("idx_platform_data_job_create_date", "create_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # export / import
    status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        nullable=False,
        index=True,
    )  # pending / running / success / failed

    # 导出：所选类别 + 各自筛选条件；导入：来源（上传文件 / 复用 export job_id）+ 选定分类
    request_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 包清单：内容分类、各分类计数、schema_version、来源站点、checksum
    manifest_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 产物存储（MinIO / 文件存储）路径与索引记录 id
    artifact_storage_path: Mapped[str | None] = mapped_column(String(2048), nullable=True, index=True)
    artifact_file_id: Mapped[int | None] = mapped_column(nullable=True, index=True)

    # 导出：文件大小 / 各分类计数；导入：各分类 created/updated/skipped/failed 计数
    result_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # 失败原因
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    create_user: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finish_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
