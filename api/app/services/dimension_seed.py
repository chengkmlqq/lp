"""ATP/FL 维度种子生成器（13 类型 + 65 值，ORM 幂等，兼容 PG/MySQL/SQLite）。

取代历史 PG 方言 SQL 种子（seed_atp_dimensions.sql / seed_atp_dimensions_supplement.sql /
seed_fl_analysis_dimensions.sql / disable_fanji_tzl_egm.sql / disable_risk_job_type_dimension.sql）：
- 数据用 Python 常量表达（不依赖 gen_random_uuid / NOW() AT TIME ZONE / ON CONFLICT 等方言特性）；
- 通过 SQLAlchemy ORM 写入，天然跨 postgresql / mysql / sqlite；
- 幂等：code 已存在则跳过，force=True 才覆盖（默认不覆盖手动改动，与 atp_param_definition_seed 同语义）；
- 禁用项（fl_analysis risk/mitigation/report/scenario 等）直接以 is_enabled=False 写入，
  不再需要单独的 disable 迁移。

调用：init_db() 启动自动播种（幂等缺失补齐）+ /admin/system/seed-defaults 端点（见 seed_service）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType

# --------------------------------------------------------------------------------------
# 维度类型（13 个）：code -> {name, description, sort_order, is_enabled}
# --------------------------------------------------------------------------------------
DIMENSION_TYPES: list[dict[str, Any]] = [
    {"code": "voltage_level", "name": "电压等级", "description": "来源：ATP 模型管理页面「电压等级」下拉选（迁移）", "sort_order": 0},
    {"code": "tower_type", "name": "塔型", "description": "来源：ATP 模型管理页面「塔型」下拉选（迁移）", "sort_order": 1},
    {"code": "scenario", "name": "场景", "description": "来源：ATP 模型管理页面「场景」下拉选（迁移）", "sort_order": 2},
    {"code": "arrester_combination", "name": "避雷器配置组合", "description": "来源：ATP 模型管理页面「避雷器配置组合」下拉选（迁移）", "sort_order": 3},
    {"code": "tower_topology_kind", "name": "杆塔拓扑类型", "description": "来源：线路管理「专用编辑器类型」拓扑选择（迁移）", "sort_order": 4},
    {"code": "fl_analysis_job_type", "name": "FL分析任务类型", "description": "来源：FL分析创建任务表单「任务类型」下拉选（迁移）", "sort_order": 5},
    {"code": "current_waveform", "name": "雷电流波形", "description": "来源：FL分析创建任务表单「雷电流波形」下拉选（迁移）", "sort_order": 6},
    {"code": "flashover_method", "name": "闪络判据", "description": "来源：FL分析创建任务表单「闪络判据」下拉选（迁移）", "sort_order": 7},
    {"code": "altitude_correction", "name": "海拔修正", "description": "来源：FL分析创建任务表单「海拔修正」下拉选（迁移）", "sort_order": 8},
    {"code": "fanji_naleishuiping_method", "name": "反击耐雷水平方法", "description": "来源：FL分析创建任务表单「反击耐雷水平」方法选择", "sort_order": 9},
    {"code": "raoji_naleishuiping_method", "name": "绕击耐雷水平方法", "description": "来源：FL分析创建任务表单「绕击耐雷水平」方法选择", "sort_order": 10},
    {"code": "fanji_tzl_method", "name": "反击跳闸率方法", "description": "来源：FL分析创建任务表单「反击跳闸率」方法选择", "sort_order": 11},
    {"code": "raoji_tzl_method", "name": "绕击跳闸率方法", "description": "来源：FL分析创建任务表单「绕击跳闸率」方法选择", "sort_order": 12},
]

# --------------------------------------------------------------------------------------
# 维度值：code -> [(item_code, name, sort_order, is_enabled)]
# --------------------------------------------------------------------------------------
DIMENSION_ITEMS: dict[str, list[tuple[str, str, int, bool]]] = {
    "voltage_level": [
        ("35", "35kV", 0, True),
        ("66", "66kV", 1, True),
        ("110", "110kV", 2, True),
        ("220", "220kV", 3, True),
        ("330", "330kV", 4, True),
        ("500", "500kV", 5, True),
        ("750", "750kV", 6, True),
        ("800", "800kV", 7, True),
        ("1000", "1000kV", 8, True),
    ],
    "tower_type": [
        ("ganzi", "干字塔", 0, True),
        ("guxing", "鼓型塔", 1, True),
        ("guxingd", "鼓型双回路塔", 2, True),
        ("jiubei", "酒杯塔", 3, True),
        ("maotou", "猫头塔", 4, True),
        ("shangzi", "上字塔", 5, True),
        ("sihuita", "四回路塔", 6, True),
        ("vzhiliu", "直流V型塔", 7, True),
        ("zhiliu", "直流塔", 8, True),
        # 无避雷线变体(ganzino/guxingno/... )已于 2026-10-30 归一为 shield_wire=without 维度,
        # 不再作为独立塔型。删除后同塔型的"无避雷线"由 shield_wire 字段表达。
    ],
    "scenario": [
        ("fanji", "反击", 0, True),
        ("raoji1", "绕击1", 1, True),
        ("raoji2", "绕击2", 2, True),
        ("raoji3", "绕击3", 3, True),
    ],
    "arrester_combination": [
        ("M1", "M1", 0, True),
        ("M2", "M2", 1, True),
        ("M3", "M3", 2, True),
        ("M12", "M12", 3, True),
        ("M13", "M13", 4, True),
        ("M23", "M23", 5, True),
        ("M123", "M123", 6, True),
        ("noM", "noM", 7, True),
        ("shuzhi-noM", "树直-noM", 8, True),
    ],
    "tower_topology_kind": [
        ("single", "单回", 0, True),
        ("double", "双回", 1, True),
        ("quad", "四回", 2, True),
        ("dc", "直流", 3, True),
    ],
    # risk/mitigation/report/scenario 为内部类型（前端创建表单不展示）
    "fl_analysis_job_type": [
        ("normal", "普通计算", 0, True),
        ("tongtiao", "同跳计算", 1, True),
        ("risk", "风险评估", 2, False),
        ("mitigation", "措施推荐", 3, False),
        ("report", "报告", 4, False),
        ("scenario", "场景", 5, False),
    ],
    "current_waveform": [
        ("heidler", "Heidler", 0, True),
        ("double_slope", "双斜角", 1, True),
        ("double_exponential", "双指数", 2, True),
    ],
    "flashover_method": [
        ("guideline", "规程法", 0, True),
        ("intersection", "相交法", 1, True),
        ("leader_development", "先导发展法", 2, True),
    ],
    "altitude_correction": [
        ("none", "无", 0, True),
        ("formula1", "推荐公式1", 1, True),
        ("formula2", "推荐公式2", 2, True),
    ],
    "fanji_naleishuiping_method": [
        ("guicheng", "规程", 0, True),
        ("atp", "ATP", 1, True),
    ],
    "raoji_naleishuiping_method": [
        ("guicheng", "规程", 0, True),
        ("atp", "ATP", 1, True),
    ],
    # 反击跳闸率方法（无 EGM；EGM 仅保留于绕击）
    "fanji_tzl_method": [
        ("none", "无", 0, True),
        ("guicheng", "规程", 1, True),
    ],
    "raoji_tzl_method": [
        ("none", "无", 0, True),
        ("guicheng", "规程", 1, True),
        ("egm", "EGM", 2, True),
    ],
}


def build_dimension_types() -> list[dict[str, Any]]:
    return [dict(item, is_enabled=True) for item in DIMENSION_TYPES]


def build_dimension_items() -> list[dict[str, Any]]:
    """展开为(item)记录列表：{dimension_type, code, name, sort_order, is_enabled}。"""
    return [
        {"dimension_type": type_code, "code": code, "name": name, "sort_order": sort_order, "is_enabled": enabled}
        for type_code, items in DIMENSION_ITEMS.items()
        for code, name, sort_order, enabled in items
    ]


def seed_dimensions(db: Session, *, force: bool = False, operator: str | None = None) -> dict[str, int]:
    """幂等种子：类型按 code、值按 (type_id, code) 存在性判断。

    force=True 时覆盖已有行（含手动改动，慎用）；默认只补缺失（不覆盖）。
    返回 {"created": int, "updated": int, "skipped": int, "types": int, "items": int}。
    """
    now = datetime.now(timezone.utc)
    created = updated = skipped = 0

    # 已有类型（code -> row）
    existing_types = {row.code: row for row in db.execute(select(DimensionType)).scalars().all()}
    for item in build_dimension_types():
        row = existing_types.get(item["code"])
        if row is not None and not force:
            skipped += 1
            continue
        if row is None:
            row = DimensionType(code=item["code"], create_date=now, update_date=now)
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = item["name"]
        row.description = item.get("description")
        row.is_enabled = bool(item.get("is_enabled", True))
        row.sort_order = int(item.get("sort_order", 0))
        row.update_date = now
        row.update_user = operator
    db.flush()

    # 已有值（type_id + code -> row），type_id 关联类型表
    type_rows = db.execute(select(DimensionType)).scalars().all()
    type_id_by_code = {row.code: row.id for row in type_rows}
    existing_items: dict[tuple[str, str], DimensionItem] = {}
    for row in db.execute(select(DimensionItem)).scalars().all():
        existing_items[(row.type_id or "", row.code)] = row

    for spec in build_dimension_items():
        type_code = spec["dimension_type"]
        type_id = type_id_by_code.get(type_code)
        if not type_id:
            # 类型缺失（force 循环里可能新建但未 flush 前 ID 为空兜底），跳过并记 skipped
            skipped += 1
            continue
        key = (type_id, spec["code"])
        row = existing_items.get(key)
        if row is not None and not force:
            skipped += 1
            continue
        if row is None:
            row = DimensionItem(
                dimension_type=type_code,
                type_id=type_id,
                code=spec["code"],
                create_date=now,
                update_date=now,
            )
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = spec["name"]
        row.is_enabled = bool(spec["is_enabled"])
        row.sort_order = int(spec["sort_order"])
        row.update_date = now
        row.update_user = operator
    db.flush()

    return {"created": created, "updated": updated, "skipped": skipped,
            "types": len(DIMENSION_TYPES), "items": len(build_dimension_items())}