"""ATP 参数注册表种子生成器（SOURCE_VARS → line_binding 翻译器）。

目标：把现有 ``atp_param_resolver.SOURCE_VARS``（build_context 产出的 38 个源变量）
逐条翻译成 ``atp_param_definition`` 行（source_type=line_binding），
把 ``atp_work_atp_slots`` 的两个运行期脚本（11K0 耦合系数 / 14XXSS 电角度）
注册为 script 定义（**运行期执行仍走 atp_work_atp_slots.py**，此处为页面基线）。

设计要点（迁移零风险）：
- 种子 = 现状的忠实镜像。每个定义带 ``runtime_key``（= code 自身），
  解析时直接取 ``build_context`` 的对应键 —— 与现状逐字节一致，golden 对照保证。
- 用户后续新增参数：line_binding 用通用抽取器（binding_json 的 source/path 点路径），
  script 用沙箱求值 —— 这两个路径只在 ``runtime_key`` 不存在时启用。
- 幂等：按 code upsert；改种子后运行 seed 端点即可更新。

调用：/admin/system/seed-defaults 已挂载（见 seed_service）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.atp_param_definition import AtpParamDefinition

# --------------------------------------------------------------------------------------
# 源变量元数据翻译表（中文名/单位/绑定路径 —— 与 atp_param_resolver.build_context 取数链对应）
# source: base_tower | profile | options | context(维度)
# path:   人类可读的取数路径（文档性与前端展示用；解析仍走 runtime_key）
# --------------------------------------------------------------------------------------

_SOURCE_VAR_META: dict[str, dict[str, Any]] = {
    # 电气/任务级
    "ground_r": {"name": "接地电阻", "unit": "Ω", "source": "base_tower", "path": "ground_resistance_ohm"},
    "insul_m": {"name": "绝缘子串长", "unit": "m", "source": "profile", "path": "insulator_length_m（>100 视为 mm÷1000）"},
    "shield_h": {"name": "避雷线高度", "unit": "m", "source": "profile", "path": "shield_wire_height_m"},
    "tower_h": {"name": "呼高", "unit": "m", "source": "base_tower", "path": "circuit_geometry_json.tower_height_m 或 profile.call_height_m"},
    "voltage": {"name": "电压", "unit": "kV", "source": "base_tower", "path": "line_voltage_kv（缺省 500.0）"},
    "current_ka": {"name": "雷电流幅值", "unit": "kA", "source": "options", "path": "binary_search_current_ka 或 profile.current_a（缺省 0.0）"},
    "head_ms": {"name": "波头时间", "unit": "ms", "source": "profile", "path": "current_head_time_ms/us 或 options.head_time_min_us（缺省 2.6）"},
    "tail_ms": {"name": "波尾时间", "unit": "ms", "source": "profile", "path": "current_tail_time_ms/us 或 options.tail_time_min_us（缺省 50.0）"},
    "wave_type": {"name": "波形种类", "unit": "", "source": "profile", "path": "current_type（缺省 1）"},
    # 避雷线几何
    "lw_l": {"name": "左避雷线中距", "unit": "m", "source": "geometry", "path": "lightning_wire.left_mid_distance_m"},
    "lw_r": {"name": "右避雷线中距", "unit": "m", "source": "geometry", "path": "lightning_wire.right_mid_distance_m"},
    "lw_l_eff": {"name": "左避雷线中距(有效)", "unit": "m", "source": "geometry", "path": "左避雷中距；缺失时由保护角反推 shield_h*tan(angle_l)"},
    "lw_r_eff": {"name": "右避雷线中距(有效)", "unit": "m", "source": "geometry", "path": "右避雷中距；缺失时由保护角反推 shield_h*tan(angle_r)"},
    # I 回相几何（按相序重排后）
    "h_u": {"name": "I回上相高", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.upper（相序重排）"},
    "h_m": {"name": "I回中相高", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.middle（相序重排）"},
    "h_l": {"name": "I回下相高", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.lower（相序重排）"},
    "sp_u": {"name": "I回上相中距", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.upper（相序重排）"},
    "sp_m": {"name": "I回中相中距", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.middle（相序重排）"},
    "sp_l": {"name": "I回下相中距", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.lower（相序重排）"},
    # II/III/IV 回相几何（sihuita 四回路）
    "c1_u": {"name": "I回上相高(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.upper（相序重排）"},
    "c1_m": {"name": "I回中相高(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.middle（相序重排）"},
    "c1_l": {"name": "I回下相高(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_height_m.lower（相序重排）"},
    "c1_sp_u": {"name": "I回上相中距(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.upper（相序重排）"},
    "c1_sp_m": {"name": "I回中相中距(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.middle（相序重排）"},
    "c1_sp_l": {"name": "I回下相中距(c1)", "unit": "m", "source": "profile", "path": "geometry_layers_json.I.phase_spacing_m.lower（相序重排）"},
    "c2_u": {"name": "II回上相高(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_height_m.upper（相序重排）"},
    "c2_m": {"name": "II回中相高(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_height_m.middle（相序重排）"},
    "c2_l": {"name": "II回下相高(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_height_m.lower（相序重排）"},
    "c2_sp_u": {"name": "II回上相中距(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_spacing_m.upper（相序重排）"},
    "c2_sp_m": {"name": "II回中相中距(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_spacing_m.middle（相序重排）"},
    "c2_sp_l": {"name": "II回下相中距(c2)", "unit": "m", "source": "profile", "path": "geometry_layers_json.II.phase_spacing_m.lower（相序重排）"},
    "c3_u": {"name": "III回上相高(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_height_m.upper（相序重排）"},
    "c3_m": {"name": "III回中相高(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_height_m.middle（相序重排）"},
    "c3_l": {"name": "III回下相高(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_height_m.lower（相序重排）"},
    "c3_sp_u": {"name": "III回上相中距(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_spacing_m.upper（相序重排）"},
    "c3_sp_m": {"name": "III回中相中距(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_spacing_m.middle（相序重排）"},
    "c3_sp_l": {"name": "III回下相中距(c3)", "unit": "m", "source": "profile", "path": "geometry_layers_json.III.phase_spacing_m.lower（相序重排）"},
    "c4_u": {"name": "IV回上相高(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_height_m.upper（相序重排）"},
    "c4_m": {"name": "IV回中相高(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_height_m.middle（相序重排）"},
    "c4_l": {"name": "IV回下相高(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_height_m.lower（相序重排）"},
    "c4_sp_u": {"name": "IV回上相中距(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_spacing_m.upper（相序重排）"},
    "c4_sp_m": {"name": "IV回中相中距(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_spacing_m.middle（相序重排）"},
    "c4_sp_l": {"name": "IV回下相中距(c4)", "unit": "m", "source": "profile", "path": "geometry_layers_json.IV.phase_spacing_m.lower（相序重排）"},
}

# 维度键（build_context 也产出，参与维度匹配；注册为 line_binding）
_DIMENSION_META: dict[str, dict[str, Any]] = {
    "tower_type": {"name": "塔型", "unit": "", "source": "context", "path": "options.tower_kind / profile.tower_kind / base_tower.tower_type（缺省 ganzi）"},
    "voltage_level": {"name": "电压等级(维度)", "unit": "kV", "source": "context", "path": "= voltage"},
    "circuit_count": {"name": "回路数量(维度)", "unit": "", "source": "context", "path": "有相高数据的回路条数"},
}

# 运行期脚本基线（与 atp_work_atp_slots.py 同公式；运行期执行仍走该模块）
_SCRIPT_SEEDS: list[dict[str, Any]] = [
    {
        "code": "coupling_k0",
        "name": "耦合系数 k0（几何）",
        "unit": "",
        "deps": ["shield_h", "lw_l", "lw_r", "insul_m", "h_u", "sp_u", "voltage", "tower_type"],
        "script": (
            "# 与 atp_work_atp_slots.coupling_k0 同公式（C# fetch_CouplingCoefficient :11484-11668）\n"
            "# 运行期执行仍走 atp_work_atp_slots.py；此处为注册表基线，仅供页面查看/编辑。\n"
            "rk = 0.0055\n"
            "y1 = shield_h - v_arc(voltage) * 2.0 / 3.0\n"
            "x1 = lw_r\n"
            "x2 = -abs(lw_l)\n"
            "y2 = y1\n"
            "y3 = h_u - v_darc(voltage) * 2.0 / 3.0 - insul_m\n"
            "d31 = hypot(x1 - sp_u, y1 - y3)\n"
            "D31 = hypot(x1 - sp_u, y1 + y3)\n"
            "d32 = hypot(x2 - sp_u, y2 - y3)\n"
            "D32 = hypot(x2 - sp_u, y2 + y3)\n"
            "d12 = hypot(x2 - x1, y2 - y1)\n"
            "D12 = hypot(x2 - x1, y2 + y1)\n"
            "z11 = log(2.0 * y1 / rk)\n"
            "z12 = log(D12 / d12)\n"
            "z31 = log(D31 / d31)\n"
            "z32 = log(D32 / d32)\n"
            "result = (z31 + z32) / (z11 + z12)\n"
        ),
    },
    {
        "code": "electric_angle",
        "name": "电源电角度（−90）",
        "unit": "°",
        "deps": ["angle_deg"],
        "script": (
            "# 与 atp_work_atp_slots.rewrite_electric_angle 同规则（C# :1906-1916）：\n"
            "# 电角度 = 输入电角度 − 90；A/B/C = 该值 / −120 / −240。\n"
            "# 运行期执行仍走 atp_work_atp_slots.py；此处为注册表基线。\n"
            "result = angle_deg - 90.0\n"
        ),
    },
]

# angle_deg 从 profile 取（build_context 未产出，需在 _SCRIPT_SEEDS 挂到 line_binding 元数据）
_EXTRA_LINE_BINDINGS: dict[str, dict[str, Any]] = {
    "angle_deg": {"name": "电角度", "unit": "°", "source": "profile", "path": "angle_deg"},
}


def build_seed_definitions() -> list[dict[str, Any]]:
    """生成全部种子定义（line_binding + script）。"""
    out: list[dict[str, Any]] = []
    for code, meta in {**_SOURCE_VAR_META, **_DIMENSION_META, **_EXTRA_LINE_BINDINGS}.items():
        out.append(
            {
                "code": code,
                "name": meta["name"],
                "unit": meta.get("unit", ""),
                "data_type": "number",
                "source_type": "line_binding",
                # runtime_key=code：解析时直接取 build_context 对应键（现状镜像，零回归）
                "binding_json": {
                    "runtime_key": code,
                    "source": meta.get("source", ""),
                    "path": meta.get("path", ""),
                },
                "script_code": None,
                "deps": [],
                "enabled": True,
                "sort_order": 0,
                "description": f"线路导入的杆塔属性绑定：{meta.get('path', '')}",
            }
        )
    for seed in _SCRIPT_SEEDS:
        out.append(
            {
                "code": seed["code"],
                "name": seed["name"],
                "unit": seed.get("unit", ""),
                "data_type": "number",
                "source_type": "script",
                "binding_json": {
                    "runtime_key": seed["code"],
                    "runtime_baseline": True,
                    "source": "script",
                    "path": "运行期脚本（atp_work_atp_slots.py 基线）",
                },
                "script_code": seed["script"],
                "deps": seed["deps"],
                "enabled": True,
                "sort_order": 100,
                "description": "运行期脚本基线：页面可查看/编辑公式，执行仍走 atp_work_atp_slots.py（固定列写入）。",
            }
        )
    return out


def build_seed_definition_objects() -> list:
    """生成种子定义对象（atp_param_registry.Definition），供 resolver/config 回落路径复用。"""
    from app.services.atp_param_registry import Definition  # noqa: PLC0415

    return [
        Definition(
            code=item["code"],
            name=item["name"],
            unit=item.get("unit"),
            data_type=item.get("data_type", "number"),
            source_type=item["source_type"],
            binding_json=item.get("binding_json") or {},
            script_code=item.get("script_code"),
            deps=list(item.get("deps") or []),
            enabled=bool(item.get("enabled", True)),
            description=item.get("description"),
        )
        for item in build_seed_definitions()
    ]


def seed_param_definitions(db: Session, *, force: bool = False, operator: str | None = None) -> dict[str, int]:
    """幂等种子：按 code upsert。force=True 时覆盖已有行（含手动改动）。"""
    now = datetime.now(timezone.utc)
    existing = {row.code: row for row in db.execute(select(AtpParamDefinition)).scalars().all()}
    created = updated = skipped = 0
    for item in build_seed_definitions():
        row = existing.get(item["code"])
        if row is not None and not force:
            skipped += 1
            continue
        if row is None:
            row = AtpParamDefinition(
                id=item["code"],  # code 即 id，稳定可读
                code=item["code"],
                created_at=now,
            )
            db.add(row)
            created += 1
        else:
            updated += 1
        row.name = item["name"]
        row.unit = item["unit"] or None
        row.data_type = item["data_type"]
        row.source_type = item["source_type"]
        row.binding_json = item["binding_json"]
        row.script_code = item["script_code"]
        row.deps_json = item["deps"]
        row.enabled = bool(item["enabled"])
        row.sort_order = int(item["sort_order"])
        row.description = item.get("description")
        row.updated_at = now
        row.updated_by = operator
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}