"""ATP 测试线路（单塔基准）模型。

背景：ATP 模型测试的输入本质上需要「一基杆塔 + 一档线路」的完整物理描述
（呼高、绝缘子串长、避雷线高度与左右中距、保护角、相序、回路几何、档距、
接地电阻……），但系统此前没有任何一等实体承载它 —— 只能手工填两个 JSON，
或者从外业台账里随手挑一基真实杆塔（同一维度组挑不同塔 → 结果不可比）。

``atp_test_line`` 就是这个受控实体：与 ``atp_asset`` 同构的维度键 +
``snapshot_json`` 冻结快照。执行测试时优先用快照装配 ``base_tower``/``profile``，
保证「同一条测试线路 → 逐字节相同的输入 → 可复现的回归基准」。

为什么不复用 ``power_line`` / ``power_line_tower``：
那张表是外业台账，会随实测资料持续更新，且出现在线路管理/地图/统计里；
测试基准必须可冻结、可复现、独立命名空间。

维度分工（与 atp_asset 一致）：
- **几何维** ``voltage_level × tower_type × shield_wire`` —— 决定杆塔几何，唯一键；
- **标签维** ``scene_type × arrester_config`` —— 不改变几何，只用于模型选择与参数规则。

``asset_id`` 非空时表示「某模型专用样本」（优先命中）；为空表示该几何维组共享基准。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

# 状态：enabled（可参与解析）/ disabled（停用）/ frozen（冻结，禁止自动重派生）
TEST_LINE_STATUSES: tuple[str, ...] = ("enabled", "disabled", "frozen")
# 溯源类型
TEST_LINE_SOURCE_KINDS: tuple[str, ...] = (
    "derived",       # 按维度/资产/历史 run 派生
    "manual",        # 人工从零填写
    "from_tower",    # 从真实线路杆塔派生
    "from_asset_run",  # 从资产历史成功 run 派生
)


class AtpTestLine(Base):
    """单塔基准（测试线路）。"""

    __tablename__ = "atp_test_line"
    __table_args__ = (
        # code 全局唯一；几何维组唯一性由 (voltage, tower_type, shield_wire, asset_id) 保证。
        # ⚠️ MySQL 唯一索引里 NULL 不参与判重（多行 NULL 互不冲突），因此「共享基准」
        # 的唯一性改由应用层 + uq 组合键里的空串归一保证：asset_id 为空时统一存空串，
        # 见 service._normalize_asset_id。
        UniqueConstraint("code", name="uq_atp_test_line_code"),
        UniqueConstraint(
            "voltage_level", "tower_type", "shield_wire", "asset_id",
            name="uq_atp_test_line_geometry_key",
        ),
        Index("idx_atp_test_line_geometry", "voltage_level", "tower_type", "shield_wire"),
        Index("idx_atp_test_line_asset", "asset_id"),
        Index("idx_atp_test_line_status", "status"),
        Index("idx_atp_test_line_scene", "scene_type"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled", nullable=False)

    # ===== 维度键 =====
    voltage_level: Mapped[str] = mapped_column(String(16), nullable=False)
    # 塔型基名（已归一化，如 guxing / maotou，见 fl_analysis_external._normalize_tower_shape_code）
    tower_type: Mapped[str] = mapped_column(String(64), nullable=False)
    shield_wire: Mapped[str] = mapped_column(String(16), default="with", nullable=False)
    # 标签维：不参与唯一键
    scene_type: Mapped[str | None] = mapped_column(String(32))
    arrester_config: Mapped[str | None] = mapped_column(String(64))
    structure_kind: Mapped[str | None] = mapped_column(String(20))
    circuit_count: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)

    # ===== 绑定 =====
    # 非空 = 某 ATP 模型专用样本；空串 = 该几何维组共享基准（MySQL 唯一索引口径见上）
    asset_id: Mapped[str | None] = mapped_column(
        String(32),
        ForeignKey("atp_asset.id", ondelete="SET NULL"),
        index=True,
    )

    # ===== 线路环境（→ base_tower）=====
    span_small_m: Mapped[float | None] = mapped_column(Float)
    span_large_m: Mapped[float | None] = mapped_column(Float)
    ground_resistance_ohm: Mapped[float | None] = mapped_column(Float)
    lightning_density: Mapped[float | None] = mapped_column(Float)
    # ⚠️ 以下三项（海拔/地形/地面倾角）当前在几何与仿真管线里**无消费方**，
    # 仅做记录与展示；compare.json 里会显式标注 not_consumed=true，不假装生效。
    altitude_m: Mapped[float | None] = mapped_column(Float)
    terrain: Mapped[str | None] = mapped_column(String(64))
    slope_1: Mapped[float | None] = mapped_column(Float)
    slope_2: Mapped[float | None] = mapped_column(Float)

    # ===== 杆塔属性（→ base_tower + profile）=====
    tower_no: Mapped[str | None] = mapped_column(String(64))
    tower_model: Mapped[str | None] = mapped_column(String(128))
    call_height_m: Mapped[float | None] = mapped_column(Float)
    # 绝缘子串长：**单位 米**（TowerProfile 里历史存毫米，下游 build_context 按
    # 「>100 视为 mm」自动换算，因此 <100 的米值两边都安全）
    insulator_length_m: Mapped[float | None] = mapped_column(Float)
    shield_wire_height_m: Mapped[float | None] = mapped_column(Float)
    shield_wire_left_mid_m: Mapped[float | None] = mapped_column(Float)
    shield_wire_right_mid_m: Mapped[float | None] = mapped_column(Float)
    protection_angle_left_deg: Mapped[float | None] = mapped_column(Float)
    protection_angle_right_deg: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float | None] = mapped_column(Float)
    phase_sequence_1: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_2: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_3: Mapped[str | None] = mapped_column(String(32))
    phase_sequence_4: Mapped[str | None] = mapped_column(String(32))
    # 与 TowerProfile 同口径：字符串（可空串），非布尔
    arrester_a: Mapped[str | None] = mapped_column(String(64))
    arrester_b: Mapped[str | None] = mapped_column(String(64))
    arrester_c: Mapped[str | None] = mapped_column(String(64))

    # ===== 雷电流 =====
    current_ka: Mapped[float] = mapped_column(Float, default=31.0, nullable=False)
    current_type: Mapped[str | None] = mapped_column(String(32))
    current_head_time_us: Mapped[float | None] = mapped_column(Float)
    current_tail_time_us: Mapped[float | None] = mapped_column(Float)

    # ===== 溯源与冻结 =====
    source_kind: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    source_asset_id: Mapped[str | None] = mapped_column(String(32))
    source_run_id: Mapped[str | None] = mapped_column(String(32))
    source_tower_id: Mapped[str | None] = mapped_column(String(32))
    # 逐字段来源标注：{"call_height_m": "L3:tower_model", ...}
    derive_rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 冻结快照：{"base_tower": {...}, "profile": {...}, "not_consumed": [...]}
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    snapshot_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    circuits: Mapped[list[AtpTestLineCircuit]] = relationship(
        "AtpTestLineCircuit",
        back_populates="test_line",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpTestLineCircuit.circuit_no.asc()",
    )


class AtpTestLineCircuit(Base):
    """测试线路的回路几何（1:N，≤4 回）。

    四回塔必须 4 套独立几何 —— 否则 LCC 判定导体重合、不产 ``.pch``
    （见 atp_asset_test_service 无杆塔合成几何处的同类踩坑注释）。
    """

    __tablename__ = "atp_test_line_circuit"
    __table_args__ = (
        UniqueConstraint("test_line_id", "circuit_no", name="uq_atp_test_line_circuit_no"),
        Index("idx_atp_test_line_circuit_line", "test_line_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    test_line_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_test_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    circuit_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    phase_sequence: Mapped[str | None] = mapped_column(String(32))
    spacing_upper_m: Mapped[float | None] = mapped_column(Float)
    spacing_middle_m: Mapped[float | None] = mapped_column(Float)
    spacing_lower_m: Mapped[float | None] = mapped_column(Float)
    height_upper_m: Mapped[float | None] = mapped_column(Float)
    height_middle_m: Mapped[float | None] = mapped_column(Float)
    height_lower_m: Mapped[float | None] = mapped_column(Float)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    test_line: Mapped[AtpTestLine] = relationship("AtpTestLine", back_populates="circuits")


__all__ = [
    "AtpTestLine",
    "AtpTestLineCircuit",
    "TEST_LINE_SOURCE_KINDS",
    "TEST_LINE_STATUSES",
]
