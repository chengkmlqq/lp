"""ATP 测试集（test set）模型。

测试集 = 一组测试用例（atp_test_set_case），每个用例绑定一个 ATP 资产
（atp_asset）与一种计算类型（普通计算 normal / 同跳计算 tongtiao），
并携带测试参数快照与预期结果。执行测试集时逐用例走现有的
「单模型测试」管线（materialize → geometry → simulate，见
atp_asset_test_service.create_test_run），并打上统一的 batch 标记
（atp_test_set_run.batch_marker），供聚合进度/报告/回归对比。

目的：ATP 模型更新或程序逻辑更新后，一键批量回归「普通计算 / 同跳计算」
仿真测试，确认模型行为未回退（与上次执行对比闪络相数/通过率）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

TEST_SET_JOB_KINDS: tuple[str, ...] = ("normal", "tongtiao")
# 执行测试集时写入每个用例 atp_asset_run.result_summary_json 的标记键
TEST_SET_RUN_META_KEYS: tuple[str, ...] = (
    "batch_id",
    "test_set_id",
    "test_set_run_id",
    "test_set_case_id",
    "test_set_case_name",
    "job_kind",
)


class AtpTestSet(Base):
    __tablename__ = "atp_test_set"
    __table_args__ = (
        Index("idx_atp_test_set_status", "status"),
        Index("idx_atp_test_set_update_date", "update_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    cases: Mapped[list[AtpTestSetCase]] = relationship(
        "AtpTestSetCase",
        back_populates="test_set",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpTestSetCase.sort_order.asc()",
    )
    runs: Mapped[list[AtpTestSetRun]] = relationship(
        "AtpTestSetRun",
        back_populates="test_set",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpTestSetRun.create_date.desc()",
    )


class AtpTestSetCase(Base):
    __tablename__ = "atp_test_set_case"
    __table_args__ = (
        Index("idx_atp_test_set_case_set", "set_id", "sort_order"),
        Index("idx_atp_test_set_case_asset", "asset_id"),
        Index("idx_atp_test_set_case_enabled", "set_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    set_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_test_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 计算类型：normal = 普通计算 / tongtiao = 同跳计算
    job_kind: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text(), default="")
    # 测试参数快照（与 AtpAssetTestRunRequest 同语义：stages/tower_kind/voltage_kv/
    # scene/current_ka/params_source/execution_options/base_tower/profile/timeout_seconds...）
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 预期结果（可选，回归断言用）：如 {"flashover_count": 2, "pass": true}
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    test_set: Mapped[AtpTestSet] = relationship("AtpTestSet", back_populates="cases", lazy="selectin")
    asset: Mapped[Any] = relationship("AtpAsset", lazy="selectin")


class AtpTestSetRun(Base):
    """一次测试集执行记录。

    用例级别的执行细节不在此表 —— 每个用例各自生成一条 atp_asset_run，
    通过 ``batch_marker``（写入 result_summary_json.batch_id）关联；
    本表只承担「集合级」的发起记录与聚合入口（进度/报告/回归对比）。
    """

    __tablename__ = "atp_test_set_run"
    __table_args__ = (
        Index("idx_atp_test_set_run_set", "set_id", "create_date"),
        Index("idx_atp_test_set_run_status", "status"),
        Index("idx_atp_test_set_run_marker", "batch_marker"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    set_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_test_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    batch_marker: Mapped[str | None] = mapped_column(String(64), index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text())
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    test_set: Mapped[AtpTestSet] = relationship("AtpTestSet", back_populates="runs", lazy="selectin")
