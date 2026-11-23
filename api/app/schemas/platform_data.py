from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# 可选导出的包类别
PLATFORM_DATA_CATEGORIES = ["dimensions", "system_params", "atp_models"]


class PlatformDataExportRequest(BaseModel):
    """导出请求：勾选要打包的类别 + 各自筛选条件。"""

    categories: list[str] = Field(..., min_length=1, description="要导出的类别：dimensions / system_params / atp_models")
    # 2026-11-23：bundle=LP 平台互导包；atp_tree=D 盘 ATP 目录树，只导出 ATP 模型。
    layout: Literal["bundle", "atp_tree"] = Field(
        default="bundle",
        description="导出布局：bundle=平台数据包；atp_tree=电压/塔型/场景/措施目录树，供 C# 直接使用",
    )
    # ATP 模型筛选条件（沿用 export_assets_zip 的维度过滤口径）
    # 维度值为单值字符串或字符串数组（下拉多选）：同维度 OR、跨维度 AND；兼容历史单值格式。
    # 支持的 key：voltage_level / tower_type / scene / arrester_config / shield_wire。
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="ATP 模型筛选条件，如 {'voltage_level': ['500kV', '220kV'], 'scene': ['plain']}；"
        "也兼容历史单值 {'voltage_level': '500kV'}",
    )


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
