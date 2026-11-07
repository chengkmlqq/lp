from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow


class AtpAsset(Base):
    __tablename__ = "atp_asset"
    __table_args__ = (
        UniqueConstraint("code", name="uq_atp_asset_code"),
        Index("idx_atp_asset_status", "status"),
        Index("idx_atp_asset_voltage_level", "voltage_level"),
        Index("idx_atp_asset_tower_type", "tower_type"),
        Index("idx_atp_asset_scene_type", "scene_type"),
        Index("idx_atp_asset_arrester_config", "arrester_config"),
        # 多版本 + 生效：同维度组定位 + 版本唯一 + 生效过滤（2026-10-29 改造）
        Index("idx_atp_asset_dim_version", "voltage_level", "tower_type",
              "scene_type", "arrester_config", "shield_wire", "version"),
        Index("idx_atp_asset_active", "voltage_level", "tower_type",
              "scene_type", "arrester_config", "shield_wire", "is_active"),
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
    # ===== 多版本 + 生效管理（2026-10-29 改造）=====
    # 同一维度组合（电压/塔型/场景/避雷器/避雷线）下可存在多个版本，
    # 由 is_active 唯一生效的版本参与仿真定位（_query 增加 is_active 过滤）。
    # version: 版本号（同维度组内唯一，自由文本，如 "v1" / "v2-rev3"）
    version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    # is_active: 当前是否生效（仿真用）。同维度组内**至多 1 条**为 True，
    # 唯一性由 activate/deactivate 事务保证（SELECT FOR UPDATE + 组内清零）。
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # ===== 版本发布管理（2026-11-05 新增）=====
    # is_published: 该版本是否已发布。发布 = 版本对仿真可见（fl_analysis 资产定位
    # 只在已发布版本中选取）；下线 = 暂停对外提供，不参与仿真定位但保留文件与记录。
    # 存量行由迁移 035 回填为已发布（行为不变）；新建默认未发布，需显式发布。
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # shield_wire: 避雷线配置维度（with/without）。110kV 无避雷线变体（ganzino 等
    # 塔型后缀）归一后落此处，塔型维度回归纯净。
    shield_wire: Mapped[str] = mapped_column(String(16), default="with", nullable=False)
    storage_mount_code: Mapped[str | None] = mapped_column(String(64), index=True)
    storage_root_path: Mapped[str | None] = mapped_column(
        String(2048),
        index=True,
        # MySQL 索引长度限制 3072B（utf8mb4）：2048*4=8192 超限，用 191 前缀索引
        index_kwargs={"mysql_length": 191},
    )
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 模型级绑定的测试线路（单塔基准）：非空时优先于几何维匹配，
    # 用于「这个模型必须用专用样本」的场景（见 models/atp_test_line.py）
    test_line_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # 槽位扫描缓存：{"scanned_at", "work_atp": {"slots": {...}, "count": N},
    #                 "geometry": {"long": {...}, ...}}见 atp_slot_scanner.scan_model_slots
    slots_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ===== 模型形态（2026-11-02 新增）=====
    # 上传时按 work.atp 的几何引用形态判定，决定仿真走哪条链路：
    #   legacy → `$INCLUDE ... .lib`（6.x/7.0/7.1，DBM）：每轮 dat→LCC→pch→lib 重算几何
    #   insert → `$INSERT ... <name><序号>.pch`（7.2+）：几何随包，pch 不再重算，
    #            但 $PARAMETER 段需规范化（去 $$ / 整数补点 / 中间变量内联）
    #   embed  → 7.2+ Enbed，几何内嵌烧死，上传即拒（存量数据可能残留）
    #   plain  → 无 LCC 的纯 RLC 工程 / 手写文件，无需重算几何
    # 判定逻辑见 services/atp_model_format.detect_model_format（不按版本指纹大小写判）
    model_format: Mapped[str] = mapped_column(String(16), default="legacy", nullable=False)
    # 上传期预检报告（services/atp_model_format.PackageInspection.as_dict()）：
    # {"model_format", "format_label", "error_count", "warning_count",
    #  "issues": [{code, level, message, fix_hint, file}], "stats": {...}}
    # error 级问题在上传口直接 400，不会落库；本字段存的是放行时的 warning 清单，
    # 供前端「模型检查」面板展示给人工处理（如 pch 目录不一致、模板缺小数点建议）。
    format_check_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ===== 异步分析状态（2026-11-03 新增）=====
    # 「形态识别 + 槽位扫描」改为上传后自动触发的 Celery 任务：
    #   判定本身只有毫秒级，但读模型包要走 OSS（每次 list/get 一次 HTTPS 往返），
    #   同步执行会把上传响应与「重新检测」按钮拖到 2~3 秒，且资产越多越慢。
    # analysis_status: pending → running → success | failed（NULL = 从未分析过）
    # analysis_token : 入队时生成的随机串，任务回写前校验；上传/重判会换 token，
    #                  旧任务发现 token 不符就直接放弃，避免慢任务覆盖新结果
    # analysis_error : 失败原因（截断 512 字），成功时清空
    analysis_status: Mapped[str | None] = mapped_column(String(20))
    analysis_error: Mapped[str | None] = mapped_column(String(512))
    analysis_token: Mapped[str | None] = mapped_column(String(32))
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analysis_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ===== 测试结论标记（2026-11-07 新增）=====
    # 与 analysis_status 区分：analysis_status 是上传期「能不能解析」，
    # test_status 是实跑仿真后的「算得对不对」：
    #   passed  = 跑通且数值合理（有结果塔、耐雷水平非 0 且未触上界）
    #   failed  = 跑不起来（KILL=12 断链 / 缺变量 / 无结果）
    #   suspect = 能算但数值异常（跳闸率越界被钳制、耐雷水平触顶、几何失真）
    #   None    = 从未测过（存量行保持空，不臆造结论）
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


class AtpAssetRun(Base):
    __tablename__ = "atp_asset_run"
    __table_args__ = (
        Index("idx_atp_asset_run_status", "status"),
        Index("idx_atp_asset_run_asset", "asset_id", "create_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    asset_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("atp_asset.id", ondelete="CASCADE"),
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

    asset: Mapped[AtpAsset] = relationship("AtpAsset", back_populates="runs", lazy="selectin")