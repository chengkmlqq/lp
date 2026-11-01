"""ATP 测试线路（单塔基准）schemas。

约定：
- ``insulator_length_m`` 单位**米**（下游按「值 > 100 视为毫米」自动换算，米值安全）。
- 派生（derive）是**干跑**：只返回草稿 + 来源标注 + 阻断项，不落库。
- ``blockers`` 非空表示不可落库（避免生成跑不通的基准）；``warnings`` 是提示（如用了兜底值）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AtpTestLineStatus = Literal["enabled", "disabled", "frozen"]
AtpTestLineSourceKind = Literal["derived", "manual", "from_tower", "from_asset_run"]


# ─────────────────────────── 回路几何 ───────────────────────────


class AtpTestLineCircuitPayload(BaseModel):
    """回路几何（I~IV 回的上/中/下相中距与相高）。"""

    circuit_no: int = Field(ge=1, le=4)
    phase_sequence: str | None = Field(default=None, max_length=32)
    spacing_upper_m: float | None = None
    spacing_middle_m: float | None = None
    spacing_lower_m: float | None = None
    height_upper_m: float | None = None
    height_middle_m: float | None = None
    height_lower_m: float | None = None


class AtpTestLineCircuitSummary(AtpTestLineCircuitPayload):
    id: str


# ─────────────────────────── 主体 ───────────────────────────


class AtpTestLineGeometry(BaseModel):
    """创建/编辑时提交的工程字段（与 detail 里的同名字段一致）。"""

    voltage_level: str = Field(min_length=1, max_length=16)
    tower_type: str = Field(min_length=1, max_length=64)
    shield_wire: str = Field(default="with", max_length=16)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    structure_kind: str | None = Field(default=None, max_length=20)
    circuit_count: int = Field(default=1, ge=1, le=4)
    asset_id: str | None = None

    # 线路环境
    span_small_m: float | None = Field(default=None, gt=0, le=3000)
    span_large_m: float | None = Field(default=None, gt=0, le=3000)
    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    altitude_m: float | None = None
    terrain: str | None = Field(default=None, max_length=64)
    slope_1: float | None = None
    slope_2: float | None = None

    # 杆塔属性
    tower_no: str | None = Field(default=None, max_length=64)
    tower_model: str | None = Field(default=None, max_length=128)
    call_height_m: float | None = None
    # 单位：米
    insulator_length_m: float | None = None
    shield_wire_height_m: float | None = None
    shield_wire_left_mid_m: float | None = None
    shield_wire_right_mid_m: float | None = None
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    angle_deg: float | None = None
    phase_sequence_1: str | None = Field(default=None, max_length=32)
    phase_sequence_2: str | None = Field(default=None, max_length=32)
    phase_sequence_3: str | None = Field(default=None, max_length=32)
    phase_sequence_4: str | None = Field(default=None, max_length=32)
    arrester_a: str | None = Field(default=None, max_length=64)
    arrester_b: str | None = Field(default=None, max_length=64)
    arrester_c: str | None = Field(default=None, max_length=64)

    # 雷电流
    current_ka: float = Field(default=31.0, gt=0)
    current_type: str | None = Field(default=None, max_length=32)
    current_head_time_us: float | None = None
    current_tail_time_us: float | None = None


class AtpTestLineCreateRequest(AtpTestLineGeometry):
    code: str | None = Field(default=None, max_length=64, description="留空按电压-塔型-避雷线自动生成")
    name: str | None = Field(default=None, max_length=255)
    description: str = Field(default="", max_length=4000)
    status: AtpTestLineStatus = "enabled"
    source_kind: AtpTestLineSourceKind = "manual"
    source_asset_id: str | None = None
    source_run_id: str | None = None
    source_tower_id: str | None = None
    circuits: list[AtpTestLineCircuitPayload] = Field(default_factory=list)


class AtpTestLineUpdateRequest(BaseModel):
    """编辑（PATCH 语义：只改传入字段）。改后自动重算快照。"""

    code: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    status: AtpTestLineStatus | None = None
    voltage_level: str | None = Field(default=None, max_length=16)
    tower_type: str | None = Field(default=None, max_length=64)
    shield_wire: str | None = Field(default=None, max_length=16)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    structure_kind: str | None = Field(default=None, max_length=20)
    circuit_count: int | None = Field(default=None, ge=1, le=4)
    asset_id: str | None = None
    span_small_m: float | None = Field(default=None, gt=0, le=3000)
    span_large_m: float | None = Field(default=None, gt=0, le=3000)
    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    altitude_m: float | None = None
    terrain: str | None = Field(default=None, max_length=64)
    slope_1: float | None = None
    slope_2: float | None = None
    tower_no: str | None = Field(default=None, max_length=64)
    tower_model: str | None = Field(default=None, max_length=128)
    call_height_m: float | None = None
    insulator_length_m: float | None = None
    shield_wire_height_m: float | None = None
    shield_wire_left_mid_m: float | None = None
    shield_wire_right_mid_m: float | None = None
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    angle_deg: float | None = None
    phase_sequence_1: str | None = Field(default=None, max_length=32)
    phase_sequence_2: str | None = Field(default=None, max_length=32)
    phase_sequence_3: str | None = Field(default=None, max_length=32)
    phase_sequence_4: str | None = Field(default=None, max_length=32)
    arrester_a: str | None = Field(default=None, max_length=64)
    arrester_b: str | None = Field(default=None, max_length=64)
    arrester_c: str | None = Field(default=None, max_length=64)
    current_ka: float | None = Field(default=None, gt=0)
    current_type: str | None = Field(default=None, max_length=32)
    current_head_time_us: float | None = None
    current_tail_time_us: float | None = None
    circuits: list[AtpTestLineCircuitPayload] | None = None
    # 允许把已冻结的线路改回 enabled（冻结只禁止「自动重派生」，不禁止人工编辑）
    reset_snapshot: bool = False


class AtpTestLineSummary(BaseModel):
    """列表行：只带展示与筛选需要的字段。"""

    id: str
    code: str
    name: str
    description: str = ""
    status: str
    voltage_level: str
    tower_type: str
    shield_wire: str
    scene_type: str | None = None
    arrester_config: str | None = None
    structure_kind: str | None = None
    circuit_count: int = 1
    asset_id: str | None = None
    asset_code: str | None = None
    span_small_m: float | None = None
    span_large_m: float | None = None
    call_height_m: float | None = None
    insulator_length_m: float | None = None
    current_ka: float = 31.0
    source_kind: str = "manual"
    snapshot_hash: str | None = None
    used_count: int = 0
    last_used_at: datetime | None = None
    create_date: datetime
    update_date: datetime
    update_user: str | None = None


class AtpTestLineDetail(AtpTestLineSummary):
    """详情：附带全部工程字段、回路几何、冻结快照与派生来源标注。"""

    ground_resistance_ohm: float | None = None
    lightning_density: float | None = None
    altitude_m: float | None = None
    terrain: str | None = None
    slope_1: float | None = None
    slope_2: float | None = None
    tower_no: str | None = None
    tower_model: str | None = None
    shield_wire_height_m: float | None = None
    shield_wire_left_mid_m: float | None = None
    shield_wire_right_mid_m: float | None = None
    protection_angle_left_deg: float | None = None
    protection_angle_right_deg: float | None = None
    angle_deg: float | None = None
    phase_sequence_1: str | None = None
    phase_sequence_2: str | None = None
    phase_sequence_3: str | None = None
    phase_sequence_4: str | None = None
    arrester_a: str | None = None
    arrester_b: str | None = None
    arrester_c: str | None = None
    current_type: str | None = None
    current_head_time_us: float | None = None
    current_tail_time_us: float | None = None
    source_asset_id: str | None = None
    source_run_id: str | None = None
    source_tower_id: str | None = None
    derive_rules_json: dict[str, Any] = Field(default_factory=dict)
    snapshot_json: dict[str, Any] = Field(default_factory=dict)
    snapshot_date: datetime | None = None
    circuits: list[AtpTestLineCircuitSummary] = Field(default_factory=list)


class AtpTestLineListResponse(BaseModel):
    items: list[AtpTestLineSummary]
    total: int


# ─────────────────────────── 派生（干跑）───────────────────────────


class AtpTestLineDeriveRequest(BaseModel):
    """按维度 / 资产 / 真实杆塔派生草稿（不落库）。"""

    asset_id: str | None = Field(default=None, description="按资产维度 + 历史 run 派生")
    voltage_level: str | None = Field(default=None, max_length=16)
    tower_type: str | None = Field(default=None, max_length=64)
    shield_wire: str | None = Field(default=None, max_length=16)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
    structure_kind: str | None = Field(default=None, max_length=20)
    source_tower_id: str | None = Field(
        default=None, description="从真实线路杆塔派生（快照冻结后不随台账漂移）"
    )


class AtpTestLineIssue(BaseModel):
    field: str
    reason: str


class AtpTestLineDeriveResponse(BaseModel):
    draft: dict[str, Any]
    # 字段 → 来源（L1:run_xxx / L2:param_template / L3:tower_model / L4:dimension / L5:builtin / manual）
    sources: dict[str, str] = Field(default_factory=dict)
    blockers: list[AtpTestLineIssue] = Field(default_factory=list)
    warnings: list[AtpTestLineIssue] = Field(default_factory=list)
    suggested_code: str | None = None
    not_consumed: list[str] = Field(default_factory=list)


class AtpTestLinePreviewResponse(BaseModel):
    """装配预览：真实执行时会用的 base_tower / profile 与快照指纹。"""

    base_tower: dict[str, Any]
    profile: dict[str, Any]
    snapshot_hash: str
    not_consumed: list[str] = Field(default_factory=list)
    blockers: list[AtpTestLineIssue] = Field(default_factory=list)
    warnings: list[AtpTestLineIssue] = Field(default_factory=list)


class AtpTestLineUsageItem(BaseModel):
    kind: str  # asset / test_set_case
    id: str
    code: str | None = None
    name: str | None = None


class AtpTestLineUsageResponse(BaseModel):
    test_line_id: str
    items: list[AtpTestLineUsageItem] = Field(default_factory=list)
    total: int = 0


class AtpTestLineResolveResponse(BaseModel):
    """按资产维度反查可用测试线路（前端「测试线路」来源切换时用）。"""

    test_line: AtpTestLineSummary | None = None
    matched_by: Literal["bound", "geometry", "degraded", "none"] = "none"
    # 未命中时给前端的提示（含「一键派生」引导）
    hint: str | None = None


class AtpTestLineCloneRequest(BaseModel):
    """复制为同几何维新样本（只允许改维度键，工程参数沿用源线路）。"""

    code: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    voltage_level: str | None = Field(default=None, max_length=16)
    tower_type: str | None = Field(default=None, max_length=64)
    shield_wire: str | None = Field(default=None, max_length=16)
    scene_type: str | None = Field(default=None, max_length=32)
    arrester_config: str | None = Field(default=None, max_length=64)
