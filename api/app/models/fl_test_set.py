"""防雷测试集（fl test set）模型。

与既有 atp_test_set（ATP 资产单模型回归测试）相互独立：本模块面向
「防雷计算 / 防雷改造」业务测试用例的批量回归：

- 集合级分类（category）：一个测试集只装一类用例——
    fl_calc   防雷计算用例：用例自带「编辑杆塔」+「防雷计算」两套表单快照
              （params_json.tower / execution_options_json）
              + 计算方式（normal 普通计算 / tongtiao 同跳计算）+ 结果评估标准；
              用户不再准备测试线路/测试塔，line_id/tower_id 由后端按快照
              自动托管一条 FLTC- 线路 + 1 基计算塔（见 fl_test_case_tower.py）；
    retrofit  防雷改造用例：建线/非建线口径 + 前置防雷计算任务
              （source_job_id，须为成功的 normal/tongtiao 任务）
              + 参考评估方案。
- 执行（run）：逐用例创建真实的 fl_analysis_job 并 start（复用现有仿真
  链路 / WS 推送 / 结果解析），任务上打 ``test_run_case_id`` 标记——
  防雷计算页 / 防雷改造页默认排除测试任务，测试集页面按标记聚合查看。
- 评估：任务 success 后按 expected_json 自动比对（auto_pass/auto_fail），
  无法自动判定的挂 pending_manual，允许人工改判（manual_pass/manual_fail）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base
from .base import utcnow

# 集合/用例类别：fl_calc=防雷计算；retrofit=防雷改造
FL_TEST_SET_CATEGORIES: tuple[str, ...] = ("fl_calc", "retrofit")
# 防雷计算用例的计算方式（与 fl_analysis_job.job_type 对齐）
FL_TEST_CALC_KINDS: tuple[str, ...] = ("normal", "tongtiao")
# 防雷改造用例的口径：jianxian=建线；feijianxian=非建线（non_construction=true）
FL_TEST_RETROFIT_MODES: tuple[str, ...] = ("jianxian", "feijianxian")
FL_TEST_SET_STATUSES: tuple[str, ...] = ("enabled", "disabled")
FL_TEST_RUN_STATUSES: tuple[str, ...] = ("pending", "running", "success", "partial", "failed", "cancelled")
FL_TEST_RUN_CASE_STATUSES: tuple[str, ...] = ("pending", "running", "success", "failed", "skipped", "cancelled")
# verdict：auto_pass/auto_fail=自动比对结论；pending_manual=待人工；manual_pass/manual_fail=人工改判
FL_TEST_VERDICTS: tuple[str, ...] = ("auto_pass", "auto_fail", "pending_manual", "manual_pass", "manual_fail")


class FlTestSet(Base):
    __tablename__ = "fl_test_set"
    __table_args__ = (
        Index("idx_fl_test_set_status", "status"),
        Index("idx_fl_test_set_category", "category"),
        Index("idx_fl_test_set_update_date", "update_date"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    # 集合类别：fl_calc / retrofit（决定用例表单与执行链路，集内用例类别一致）
    category: Mapped[str] = mapped_column(String(20), default="fl_calc", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text(), default="")
    status: Mapped[str] = mapped_column(String(20), default="enabled")
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    cases: Mapped[list["FlTestSetCase"]] = relationship(
        "FlTestSetCase",
        back_populates="test_set",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FlTestSetCase.sort_order.asc()",
    )
    runs: Mapped[list["FlTestSetRun"]] = relationship(
        "FlTestSetRun",
        back_populates="test_set",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FlTestSetRun.create_date.desc()",
    )


class FlTestSetCase(Base):
    __tablename__ = "fl_test_set_case"
    __table_args__ = (
        Index("idx_fl_test_set_case_set", "set_id", "sort_order"),
        Index("idx_fl_test_set_case_line", "line_id"),
        Index("idx_fl_test_set_case_enabled", "set_id", "enabled"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    set_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_test_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(Text(), default="")
    # ── fl_calc（防雷计算用例）专属 ──
    # 计算方式：normal=普通计算 / tongtiao=同跳计算（即 fl_analysis_job.job_type）
    calc_kind: Mapped[str | None] = mapped_column(String(20), index=True)
    # 单塔样例载体：线路管理的测试线路（Line）+ 目标杆塔（1 基）
    line_id: Mapped[str | None] = mapped_column(String(32), index=True)
    tower_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # 计算参数快照：{"external_adapter": "wine", "adapter_config_json": {...},
    #                "execution_options_json": {...}}（与 FlAnalysisJobCreateRequest 同语义）
    params_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ── retrofit（防雷改造用例）专属 ──
    # 改造口径：jianxian=建线 / feijianxian=非建线
    mode: Mapped[str | None] = mapped_column(String(20), index=True)
    # 前置防雷计算任务：须为 status=success 的 normal/tongtiao 任务
    source_job_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # 改造目标塔（默认走前置任务高风险塔；空列表=全部交给现有 mitigation 默认逻辑）
    selected_tower_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    # ── 共用 ──
    # 评估标准（fl_calc）/ 参考评估方案（retrofit），结构见服务层 _auto_evaluate
    expected_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 用例录入时对载体/前置任务的快照指纹（预留，基准漂移提示用）
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    update_user: Mapped[str | None] = mapped_column(String(64), index=True)

    test_set: Mapped[FlTestSet] = relationship("FlTestSet", back_populates="cases", lazy="selectin")


class FlTestSetRun(Base):
    """一次批量执行（run = batch）。用例级细节在 FlTestSetRunCase。"""

    __tablename__ = "fl_test_set_run"
    __table_args__ = (
        Index("idx_fl_test_set_run_set", "set_id", "create_date"),
        Index("idx_fl_test_set_run_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    set_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_test_set.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    total_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text())
    result_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    create_user: Mapped[str | None] = mapped_column(String(64), index=True)
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    test_set: Mapped[FlTestSet] = relationship("FlTestSet", back_populates="runs", lazy="selectin")
    run_cases: Mapped[list["FlTestSetRunCase"]] = relationship(
        "FlTestSetRunCase",
        back_populates="run",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FlTestSetRunCase.create_date.asc()",
    )


class FlTestSetRunCase(Base):
    """run 内逐用例执行记录：job_id 指向本次执行创建的 fl_analysis_job。

    任务与用例的双向关联：本表 job_id → 任务；任务侧 ``test_run_case_id`` → 本表
    （防雷计算/改造页面默认排除带标记的任务）。
    """

    __tablename__ = "fl_test_set_run_case"
    __table_args__ = (
        Index("idx_fl_test_set_run_case_run", "run_id", "create_date"),
        Index("idx_fl_test_set_run_case_job", "job_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid4().hex)
    run_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_test_set_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("fl_test_set_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    job_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # 自动/人工评估明细：{"checks": [{"key","label","expect","actual","pass"}], "comment": ...}
    eval_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verdict: Mapped[str | None] = mapped_column(String(20), index=True)
    error_message: Mapped[str | None] = mapped_column(Text())
    create_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    update_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    run: Mapped[FlTestSetRun] = relationship("FlTestSetRun", back_populates="run_cases", lazy="selectin")
    case: Mapped[FlTestSetCase] = relationship("FlTestSetCase", lazy="selectin")
