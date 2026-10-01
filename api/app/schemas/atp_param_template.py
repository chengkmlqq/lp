"""ATP 参数模板（配置化）请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DIMENSION_FIELDS = ("tower_type", "voltage_level", "circuit_count", "scene_type", "arrester_config", "structure_kind")


class SlotSpec(BaseModel):
    expr: str | None = None
    value: str | None = None
    when: str | None = None
    else_: str | None = Field(default=None, alias="else")
    fmt: int = 2
    enabled: bool = True

    model_config = {"populate_by_name": True}


class TemplateSummary(BaseModel):
    id: str
    name: str
    marker: str | None = None
    tower_type: str | None = None
    voltage_level: str | None = None
    circuit_count: int | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    structure_kind: str | None = None
    priority: int = Field(default=100, ge=0, le=10_000)
    mode: str = "merge"
    enabled: bool = True
    fallback_to: str | None = None
    fallback_enabled: bool = True
    specificity: int = 0
    defined_slots: int = 0
    slot_names: list[str] = Field(default_factory=list)
    defined_defaults: int = 0
    updated_at: datetime | None = None
    updated_by: str | None = None


class TemplateDetail(TemplateSummary):
    slots: dict[str, Any] = Field(default_factory=dict)
    # 「无杆塔测试」用的默认上下文变量（{变量名: 默认值}）
    defaults: dict[str, Any] = Field(default_factory=dict)
    # 槽位 → 引用参数解析（{槽位名: [{code, name, source_type, via}]}）
    slot_params: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    # 注册表参数来源总表（{code: {name, source_type, via}}）
    param_sources: dict[str, dict[str, Any]] = Field(default_factory=dict)


class TemplateListResponse(BaseModel):
    items: list[TemplateSummary]
    total: int


class TemplateUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    marker: str | None = Field(default=None, max_length=64)
    tower_type: str | None = Field(default=None, max_length=64)
    voltage_level: str | None = Field(default=None, max_length=16)
    circuit_count: int | None = None
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    structure_kind: str | None = Field(default=None, max_length=32)
    priority: int = Field(default=100, ge=0, le=10_000)
    mode: Literal["merge", "replace"] = "merge"
    enabled: bool = True
    fallback_to: str | None = Field(default=None, max_length=64)
    fallback_enabled: bool = True
    slots: dict[str, Any] = Field(default_factory=dict)
    # 「无杆塔测试」用的默认上下文变量；不传则保持原值（更新时）
    defaults: dict[str, Any] | None = None


class TreeNode(BaseModel):
    key: str
    label: str
    node_type: Literal["global", "group", "rule"]
    dimension: str | None = None
    # 匹配维度摘要（值 null/缺省 = 通配）；卡片视图展示用
    dimensions: dict[str, Any] | None = None
    rule_id: str | None = None
    has_template: bool = False
    defined_slots: int = 0
    effective_slots: int = 0
    status: Literal["own", "inherit"] = "inherit"
    inherited_from: str | None = None
    overridden_by: list[str] = Field(default_factory=list)
    children: list["TreeNode"] = Field(default_factory=list)


class TreeResponse(BaseModel):
    total: int = 0
    root: TreeNode


class ResolvePreviewRequest(BaseModel):
    tower_type: str | None = None
    voltage_level: float | None = None
    circuit_count: int | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    structure_kind: str | None = None
    tower_id: str | None = None
    rule_id: str | None = None
    current_ka: float | None = None


class ResolvedSlot(BaseModel):
    slot: str
    value: str
    source: str
    inherited: bool = False


class ResolvePreviewResponse(BaseModel):
    chain: list[str] = Field(default_factory=list)
    tower_kind: str | None = None
    slots: list[ResolvedSlot] = Field(default_factory=list)
    diff: list[ResolvedSlot] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)


class MetaResponse(BaseModel):
    tower_types: list[dict[str, Any]] = Field(default_factory=list)
    voltages: list[str] = Field(default_factory=list)
    scene_types: list[dict[str, Any]] = Field(default_factory=list)
    arrester_configs: list[dict[str, Any]] = Field(default_factory=list)
    slot_names: list[str] = Field(default_factory=list)


class DeriveRequest(BaseModel):
    parent_id: str
    tower_type: str | None = None
    voltage_level: str | None = None
    circuit_count: int | None = None
    scene_type: str | None = None
    arrester_config: str | None = None
    structure_kind: str | None = None


class DeriveResponse(BaseModel):
    suggested_name: str
    dimensions: dict[str, Any] = Field(default_factory=dict)
    inherited_slots: dict[str, str] = Field(default_factory=dict)
    chain: list[str] = Field(default_factory=list)
    slots: dict[str, Any] = Field(default_factory=dict)
