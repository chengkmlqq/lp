from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    atp_asset,
    atp_param_definition,
    atp_param_template,
    document,
    elevation,
    file_storage,
    lightning_amplitude,
    lightning_distribution,
    line,
    line_tower,
    rbac,
    scheduled_task,
    tower_model,
    user,
)
from ..models.base import utcnow
from ..schemas.overview import AssetStatItem, OverviewTasksSummary, SystemOverviewResponse
from .task_monitor_service import build_task_monitor_overview

# (key, label, model, 对应管理页面路由)
_ASSET_SOURCES: list[tuple[str, str, type, str | None]] = [
    ("line", "线路", line.Line, "/admin/power-lines"),
    ("line_tower", "杆塔", line_tower.LineTower, "/admin/power-lines"),
    ("tower_model", "杆塔模型", tower_model.TowerModel, "/admin/tower-models"),
    ("atp_asset", "ATP模型", atp_asset.AtpAsset, "/admin/atp-models"),
    ("atp_param_template", "ATP参数模板", atp_param_template.AtpParamTemplate, "/admin/atp-param-templates"),
    ("atp_param_definition", "ATP参数定义", atp_param_definition.AtpParamDefinition, "/admin/atp-params"),
    ("lightning_amplitude", "闪电幅值记录", lightning_amplitude.LightningAmplitude, "/admin/lightning-currents"),
    (
        "lightning_distribution",
        "地闪密度记录",
        lightning_distribution.LightningDistribution,
        "/admin/lightning-distribution",
    ),
    ("elevation_file_record", "高程文件记录", elevation.ElevationFileRecord, "/admin/elevation-records"),
    ("file_index", "文件索引", file_storage.FileIndexEntry, "/admin/files"),
    ("document", "文档", document.Document, "/admin/documents"),
    ("user", "用户", user.User, "/admin/users"),
    ("role", "角色", rbac.Role, "/admin/roles"),
]


def _count_rows(db: Session, model: type) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def build_system_overview(db: Session) -> SystemOverviewResponse:
    assets = [
        AssetStatItem(key=key, label=label, count=_count_rows(db, model), route=route)
        for key, label, model, route in _ASSET_SOURCES
    ]

    monitor = build_task_monitor_overview(offset=0, limit=1)
    tasks = OverviewTasksSummary(
        total=monitor.total,
        queue_pending_total=monitor.queue_pending_total,
        scheduled_tasks=_count_rows(db, scheduled_task.ScheduledTask),
        state_buckets=monitor.task_state_buckets,
    )
    return SystemOverviewResponse(generated_at=utcnow(), assets=assets, tasks=tasks)