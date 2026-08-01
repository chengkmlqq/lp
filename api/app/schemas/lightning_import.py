from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LightningImportBatchSummary(BaseModel):
    """文件导入批次摘要（雷电流波形导入使用）。"""
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
    line_id: str | None = None
    line_name: str | None = None

    # 导入状态（waveform 类型可用）
    status: str | None = None  # pending / processing / completed / failed
    task_id: str | None = None

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
