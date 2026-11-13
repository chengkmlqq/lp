from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow


class AtpModel(Base):
    """模型主表（LP-11：模型/版本拆表）。

    一行 = 一个模型组（由五维 + 避雷线唯一确定）。模型级字段从原来的
    ``atp_asset``（一行一版本，字段每行重复）上提到这里，版本归属从
    「五维组合相等」改为 ``atp_asset_version.model_id`` 外键。

    ``code`` 为**去掉 ``-vN`` 段**的模型编码（如 ``ATP66-shangzi-raoji2-M123``），
    生成时必须做去重校验；版本级旧 ``code``（含 ``-vN``）由 ``version_code``
    原样保留，保证导出文件名 / 日志 / 报告等外部引用不失效（决策 2）。
    """

    __tablename__ = "atp_model"
    __table_args__ = (
        UniqueConstraint("code", name="uq_atp_model_code"),
        Index("idx_atp_model_status", "status"),
        # 五维组合索引：按维度反查模型 / 回填 model_id 用（维度可为 NULL）
        Index(
            "idx_atp_model_dim",
            "voltage_level", "tower_type", "scene_type", "arrester_config", "shield_wire",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")
    voltage_level: Mapped[str | None] = mapped_column(String(16))
    tower_type: Mapped[str | None] = mapped_column(String(64))
    scene_type: Mapped[str | None] = mapped_column(String(32))
    arrester_config: Mapped[str | None] = mapped_column(String(64))
    shield_wire: Mapped[str] = mapped_column(String(16), default="with", nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)


class AtpAssetVersion(Base):
    """版本表（LP-11：由 ``atp_asset`` 一步改名而来）。

    **沿用旧 ``atp_asset.id`` 作为主键**：三张外键表、仿真定位里存的资产 id、
    日志 / 报告引用全部不用改数据（硬约束）。存储路径字符串也保持不变。

    过渡期（P1–P3）采用双写：模型级字段（``name`` / ``description`` /
    ``status`` / 五维 / ``shield_wire``）仍保留在本表并随 ``atp_model``
    同步更新，使只读兼容视图 ``atp_asset`` 能原样映射给尚未切换的旧代码；
    这些冗余列在 P4 清理阶段才删除。新增 ``model_id``（版本归属）与
    ``version_code``（原样保留旧 ``code``）。
    """

    __tablename__ = "atp_asset_version"
    __table_args__ = (
        UniqueConstraint("code", name="uq_atp_asset_version_code"),
        UniqueConstraint("version_code", name="uq_atp_asset_version_version_code"),
        # 组内版本唯一；model_id 可为 NULL（过渡期存量/回滚），NULL 互不冲突
        UniqueConstraint("model_id", "version", name="uq_atp_asset_version_model_version"),
        Index("idx_atp_asset_version_status", "status"),
        Index("idx_atp_asset_version_voltage_level", "voltage_level"),
        Index("idx_atp_asset_version_tower_type", "tower_type"),
        Index("idx_atp_asset_version_scene_type", "scene_type"),
        Index("idx_atp_asset_version_arrester_config", "arrester_config"),
        Index("idx_atp_asset_version_model", "model_id"),
        # 多版本 + 生效：保留旧维度定位索引，仿真定位与版本历史过渡期仍可用
        Index("idx_atp_asset_version_dim_version", "voltage_level", "tower_type",
              "scene_type", "arrester_config", "shield_wire", "version"),
        Index("idx_atp_asset_version_active", "voltage_level", "tower_type",
              "scene_type", "arrester_config", "shield_wire", "is_active"),
        Index("idx_atp_asset_version_model_published", "model_id", "is_published"),
        Index("idx_atp_asset_version_model_state", "model_id", "publish_state"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    # 版本归属（LP-11）：外键在迁移脚本中以 ALTER TABLE ... ADD CONSTRAINT 落地，
    # ORM 侧保持普通列，避免各内存库/测试建表时的 FK 依赖与方言差异。
    model_id: Mapped[str | None] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    # version_code：原样保留旧 code（含 -vN），供外部引用；过渡期与 code 同值。
    version_code: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")
    voltage_level: Mapped[str | None] = mapped_column(String(16))
    tower_type: Mapped[str | None] = mapped_column(String(64))
    scene_type: Mapped[str | None] = mapped_column(String(32))
    arrester_config: Mapped[str | None] = mapped_column(String(64))
    # ===== 多版本 + 生效管理 =====
    version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ===== 版本发布管理 =====
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ===== 发布生命周期状态 =====
    publish_state: Mapped[str | None] = mapped_column(String(20), index=True)
    release_notes: Mapped[str | None] = mapped_column(String(1000))
    shield_wire: Mapped[str] = mapped_column(String(16), default="with", nullable=False)
    storage_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_root_path: Mapped[str | None] = mapped_column(
        String(2048),
        index=True,
        index_kwargs={"mysql_length": 191},
    )
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_line_id: Mapped[str | None] = mapped_column(String(32), index=True)
    slots_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ===== 模型形态 =====
    model_format: Mapped[str] = mapped_column(String(16), default="legacy", nullable=False)
    format_check_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ===== 异步分析状态 =====
    analysis_status: Mapped[str | None] = mapped_column(String(20))
    analysis_error: Mapped[str | None] = mapped_column(String(512))
    analysis_token: Mapped[str | None] = mapped_column(String(32))
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ===== 测试结论标记 =====
    test_status: Mapped[str | None] = mapped_column(String(16), index=True)
    test_message: Mapped[str | None] = mapped_column(String(512))
    test_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    runs: Mapped[list[AtpAssetRun]] = relationship(
        "AtpAssetRun",
        back_populates="asset",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AtpAssetRun.create_date.desc()",
    )


# 过渡期兼容别名（双写阶段）：约 20 个引用文件仍以 ``AtpAsset`` 导入，保持
# 旧名可用，避免一次性改名牵连过广；新代码一律使用 ``AtpAssetVersion``。
# P4 清理阶段删除该别名，并把所有引用收敛到新名。
AtpAsset = AtpAssetVersion


class AtpAssetRun(Base):
    __tablename__ = "atp_asset_run"
    __table_args__ = (
        Index("idx_atp_asset_run_status", "status"),
        Index("idx_atp_asset_run_asset", "asset_id", "create_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    asset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    engine_mode: Mapped[str] = mapped_column(String(20), default="wine", index=True)
    runner_kind: Mapped[str] = mapped_column(String(20), default="atp", index=True)
    task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    storage_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_root_path: Mapped[str | None] = mapped_column(String(2048))
    materialized_root_path: Mapped[str | None] = mapped_column(String(2048))
    engine_command: Mapped[str | None] = mapped_column(String(2000))
    working_dir: Mapped[str | None] = mapped_column(String(2000))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    stdout_text: Mapped[str | None] = mapped_column(Text())
    stderr_text: Mapped[str | None] = mapped_column(Text())
    output_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text())
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    asset: Mapped[AtpAssetVersion] = relationship("AtpAssetVersion", back_populates="runs", lazy="selectin")
