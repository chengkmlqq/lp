from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# 可选导出的包类别
PLATFORM_DATA_CATEGORIES = ["dimensions", "system_params", "atp_models"]


class PlatformDataExportRequest(BaseModel):
    """导出请求：勾选要打包的类别 + 各自筛选条件。"""

    categories: list[str] = Field(..., min_length=1, description="要导出的类别：dimensions / system_params / atp_models")
    # ATP 模型筛选条件（沿用 export_assets_zip 的维度过滤口径）
    filters: dict[str, Any] = Field(default_factory=dict, description="ATP 模型筛选条件，如 {'voltage_level': '500kV'}")


class PlatformDataImportReuseRequest(BaseModel):
    """导入请求（复用某次导出产物）：直接指定历史 export job_id，免去重复上传。"""

    source_job_id: str = Field(..., description="要复用的历史导出 job_id")


class PlatformDataJobSummary(BaseModel):
    """任务列表项。"""

    id: str
    kind: str
    status: str
    categories: list[str] | None = None
    schema_version: str | None = None
    artifact_filename: str | None = None
    source_site: str | None = None
    create_date: datetime | None = None
    finish_date: datetime | None = None
    result_summary: dict[str, Any] | None = None
    error_message: str | None = None


class PlatformDataJobDetail(PlatformDataJobSummary):
    """任务详情（含请求与清单）。"""

    request_payload: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] | None = None
    artifact_storage_path: str | None = None
    artifact_file_id: int | None = None


class PlatformDataJobListResponse(BaseModel):
    total: int
    items: list[PlatformDataJobSummary]
