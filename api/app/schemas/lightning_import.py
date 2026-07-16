from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .lightning import LightningPolarity


class LightningImportBatchSummary(BaseModel):
    """文件导入批次摘要"""
    batch_id: str  # 使用 source_file_name + create_date 的哈希作为批次ID
    source_file_name: str | None = None
    import_time: datetime
    event_count: int
    region_id: str | None = None
    location_tag: str | None = None
    city: str | None = None
    event_year: int | None = None
    is_synthetic: bool = False
    notes: str | None = None

    # 统计信息
    max_abs_current_ka: float | None = None
    avg_abs_current_ka: float | None = None
    positive_count: int = 0
    negative_count: int = 0

    # 导入元数据
    create_user: str | None = None


class LightningImportBatchListResponse(BaseModel):
    items: list[LightningImportBatchSummary]
    total: int
    limit: int
    offset: int


class LightningImportBatchEventItem(BaseModel):
    """导入批次中的单个事件"""
    id: str
    event_id: str
    longitude: float | None = None
    latitude: float | None = None
    current_ka: float | None = None
    abs_current_ka: float | None = None
    polarity: LightningPolarity
    event_time: datetime | None = None


class LightningImportBatchEventsResponse(BaseModel):
    batch_id: str
    source_file_name: str | None = None
    import_time: datetime
    events: list[LightningImportBatchEventItem]
    total: int
