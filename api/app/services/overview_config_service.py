"""「系统总览」可配置仪表盘 service：用户级卡片布局的读取/保存。

- 每用户一条配置（user_overview_config 表，widgets 存 JSON 文本）。
- 无配置时回落默认布局（= 改造前的静态观感：整行资产统计 + 整行任务总览），
  保证存量用户首次打开不空白、不改变体验。
- 保存时做结构校验：type 白名单、span 合法值、asset_keys 白名单、链接结构。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user_overview_config import UserOverviewConfig
from ..schemas.overview_config import (
    OverviewConfigRequest,
    OverviewConfigResponse,
    OverviewWidgetConfig,
)

# 合法卡片类型（与前端渲染器一一对应）
WIDGET_TYPES = {"asset_stats", "task_summary", "task_states", "quick_links"}
# 合法栅格宽度（antd 24 栅格中的常见分栏）
VALID_SPANS = {24, 12, 8, 6}
# 资产统计可勾选的 assets key 白名单（与 overview_service._ASSET_SOURCES 一致）
VALID_ASSET_KEYS = {
    "line",
    "line_tower",
    "tower_model",
    "atp_asset",
    "atp_param_template",
    "atp_param_definition",
    "lightning_amplitude",
    "lightning_distribution",
    "elevation_file_record",
    "file_index",
    "document",
    "user",
    "role",
}

DEFAULT_ASSET_KEYS: list[str] = [
    "line",
    "line_tower",
    "tower_model",
    "atp_asset",
    "atp_param_template",
    "atp_param_definition",
    "lightning_amplitude",
    "lightning_distribution",
    "elevation_file_record",
    "file_index",
    "document",
    "user",
    "role",
]


def default_widgets() -> list[OverviewWidgetConfig]:
    """默认布局：整行资产统计（全部类别）+ 整行任务总览（= 改造前观感）。"""
    return [
        OverviewWidgetConfig(
            type="asset_stats",
            title="系统资产统计",
            span=24,
            props={"asset_keys": list(DEFAULT_ASSET_KEYS)},
        ),
        OverviewWidgetConfig(type="task_summary", title="任务总览", span=24, props={}),
    ]


def _sanitize_widget(raw: dict[str, Any]) -> OverviewWidgetConfig | None:
    """单卡片结构校验（非法卡片丢弃并返回 None，不整体失败）。"""
    widget_type = raw.get("type")
    if widget_type not in WIDGET_TYPES:
        return None
    span = raw.get("span", 24)
    if span not in VALID_SPANS:
        span = 24
    props: dict[str, Any] = raw.get("props") if isinstance(raw.get("props"), dict) else {}

    if widget_type == "asset_stats":
        keys = props.get("asset_keys")
        if isinstance(keys, list):
            props["asset_keys"] = [k for k in keys if isinstance(k, str) and k in VALID_ASSET_KEYS] or DEFAULT_ASSET_KEYS
        else:
            props["asset_keys"] = list(DEFAULT_ASSET_KEYS)
    elif widget_type == "quick_links":
        links = props.get("links")
        cleaned: list[dict[str, str]] = []
        if isinstance(links, list):
            for link in links[:20]:
                if isinstance(link, dict) and isinstance(link.get("label"), str) and isinstance(link.get("href"), str):
                    cleaned.append({"label": link["label"][:50], "href": link["href"][:200]})
        props["links"] = cleaned

    title = raw.get("title")
    return OverviewWidgetConfig(
        type=widget_type,
        title=title if isinstance(title, str) and title.strip() else None,
        span=span,
        props=props,
    )


def get_overview_config(db: Session, *, user_id: str) -> OverviewConfigResponse:
    row = db.execute(
        select(UserOverviewConfig).where(UserOverviewConfig.user_id == user_id)
    ).scalar_one_or_none()
    if row is None or not row.widgets_json:
        return OverviewConfigResponse(widgets=default_widgets())

    try:
        raw_widgets = json.loads(row.widgets_json)
    except (TypeError, ValueError):
        return OverviewConfigResponse(widgets=default_widgets())

    if not isinstance(raw_widgets, list):
        return OverviewConfigResponse(widgets=default_widgets())

    widgets = [w for w in (_sanitize_widget(item) for item in raw_widgets if isinstance(item, dict)) if w is not None]
    if not widgets:
        return OverviewConfigResponse(widgets=default_widgets())
    return OverviewConfigResponse(widgets=widgets[:12])


def save_overview_config(
    db: Session,
    *,
    user_id: str,
    payload: OverviewConfigRequest,
) -> OverviewConfigResponse:
    """全量保存（校验通过后覆盖）。返回清洗后的配置，供前端回显。"""
    widgets = [w for w in (_sanitize_widget(w.model_dump()) for w in payload.widgets) if w is not None]
    if not widgets:
        widgets = default_widgets()

    row = db.execute(
        select(UserOverviewConfig).where(UserOverviewConfig.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        row = UserOverviewConfig(user_id=user_id, widgets_json="[]")
        db.add(row)
    row.widgets_json = json.dumps([w.model_dump(mode="json") for w in widgets], ensure_ascii=False)
    db.commit()
    return OverviewConfigResponse(widgets=widgets)