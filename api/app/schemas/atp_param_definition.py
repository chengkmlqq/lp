"""ATP 参数注册表 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SourceType = Literal["line_binding", "script", "constant"]


class BindingSpec(BaseModel):
    """line_binding 绑定描述：
    - runtime_key: 现状镜像键（build_context 产出）；与 source/path 二选一
    - source: base_tower | profile | options
    - path: 点路径（如 insulator_length_m / geometry_layers_json.I.phase_height_m.upper）
    - transform: mm_to_m（按 >100 启发式转米）
    - runtime_baseline: 运行期基线（执行仍走代码）
    """

    runtime_key: str | None = None
    source: str | None = None
    path: str | None = None
    transform: str | None = None
    runtime_baseline: bool | None = None


class DefinitionSummary(BaseModel):
    id: str
    code: str
    name: str
    unit: str | None = None
    data_type: str = "number"
    source_type: str = "line_binding"
    binding_json: dict[str, Any] = Field(default_factory=dict)
    script_code: str | None = None
    deps_json: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    description: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class DefinitionListResponse(BaseModel):
    items: list[DefinitionSummary] = Field(default_factory=list)
    total: int = 0


class DefinitionUpsertRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_]+$")
    name: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)
    data_type: Literal["number", "string", "bool"] = "number"
    source_type: SourceType = "line_binding"
    binding_json: dict[str, Any] = Field(default_factory=dict)
    script_code: str | None = None
    deps_json: list[str] = Field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    description: str | None = None


class BindableField(BaseModel):
    value: str  # 点路径（source.path 形式存 value）
    label: str
    source: Literal["base_tower", "profile", "options"]
    data_type: str = "number"
    unit: str | None = None
    note: str | None = None


class FieldsResponse(BaseModel):
    fields: list[BindableField] = Field(default_factory=list)
    transform_options: list[str] = Field(default_factory=lambda: ["mm_to_m"])
    source_options: list[dict[str, str]] = Field(
        default_factory=lambda: [
            {"value": "base_tower", "label": "杆塔主表（power_line_tower）"},
            {"value": "profile", "label": "塔属性（tower_profile）"},
            {"value": "options", "label": "任务执行选项（execution_options）"},
        ]
    )
    script_functions: list[str] = Field(default_factory=list)


class TestScriptRequest(BaseModel):
    script_code: str = Field(min_length=1)
    deps_json: list[str] = Field(default_factory=list)
    base_tower: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    execution_options: dict[str, Any] = Field(default_factory=dict)


class TestScriptResponse(BaseModel):
    ok: bool
    value: Any = None
    errors: list[str] = Field(default_factory=list)
    referenced: list[str] = Field(default_factory=list)


class ResolvePreviewRequest(BaseModel):
    base_tower: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] = Field(default_factory=dict)
    execution_options: dict[str, Any] = Field(default_factory=dict)
    codes: list[str] = Field(default_factory=list)


class ResolvedParam(BaseModel):
    code: str
    name: str
    unit: str | None = None
    source_type: str
    value: Any = None


class ResolvePreviewResponse(BaseModel):
    items: list[ResolvedParam] = Field(default_factory=list)


class ResolvePreviewByTowersRequest(BaseModel):
    tower_ids: list[str] = Field(min_length=1)
    execution_options: dict[str, Any] = Field(default_factory=dict)


class TowerPreviewResult(BaseModel):
    tower_id: str
    tower_no: str | None = None
    tower_type: str | None = None
    line_name: str | None = None
    ok: bool = False
    error: str | None = None
    items: list[ResolvedParam] = Field(default_factory=list)


class ResolvePreviewByTowersResponse(BaseModel):
    results: list[TowerPreviewResult] = Field(default_factory=list)
