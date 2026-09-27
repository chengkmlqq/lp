"""ATP 参数注册表种子生成器（49 个参数，全部常规化来源）。

改造目标（2026-09-27，用户指令「不想要'现状计算链路'特殊来源」）：
- 不再使用 runtime_key 现状镜像；每个参数用常规三类来源显式表达：
  · line_binding source/path（+transform）：直接从线路导入数据域取原始字段；
  · script：显式公式（pick() 从原始域取数 + 回退/换算/相序重排口径写死在脚本里）；
  · constant：字面量（当前无）。
- description 写清「来源 + 口径」，可读可审计。
- 与 C# 口径（compute_csharp_atp_params / build_context）逐字节一致，由
  scripts/atp_param_registry_golden_test.py 全矩阵对照保证。

口径对照基准 = atp_param_resolver.build_context（C# 公式的 Python 等价物）：
- 相序重排后的几何已由 build_context 产出为 ``geometry_permuted`` 键，
  script 用 pick("geometry_permuted", "I.phase_height_m.upper") 等取数，
  与 h_u/sp_u/c1~c4 的取值链路同一口径。
- pick 域白名单：base_tower / profile / options / geometry_permuted。

调用：/admin/system/seed-defaults 已挂载（见 seed_service）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.atp_param_definition import AtpParamDefinition

# --------------------------------------------------------------------------------------
# 定义清单（49 个）：每项 = {code, name, unit, source_type, binding_json,
#                        script_code?, deps?, description}
# --------------------------------------------------------------------------------------


def _lb(source: str, path: str, **extra) -> dict[str, Any]:
    """line_binding 绑定 JSON（source/path 点路径抽取；可选 transform）。"""
    out: dict[str, Any] = {"source": source, "path": path}
    out.update(extra)
    return out


def _def(code, name, unit, source_type, binding, description, script=None, deps=()):
    return {
        "code": code,
        "name": name,
        "unit": unit,
        "data_type": "number",
        "source_type": source_type,
        "binding_json": binding,
        "script_code": script,
        "deps": list(deps),
        "enabled": True,
        "sort_order": 0,
        "description": description,
    }


# =============================== A 档：字段直取（line_binding source/path） ============
_A_LINE_BINDINGS: list[dict[str, Any]] = [
    _def(
        "ground_r", "接地电阻", "Ω", "line_binding",
        _lb("base_tower", "ground_resistance_ohm"),
        "来源：base_tower.ground_resistance_ohm（杆塔基础-接地电阻）。口径：原值直取，单位 Ω。",
    ),
    _def(
        "shield_h", "避雷线高度", "m", "line_binding",
        _lb("profile", "shield_wire_height_m"),
        "来源：profile.shield_wire_height_m（档距剖面-避雷线对地高度）。口径：原值直取，单位 m。",
    ),
    _def(
        "insul_m", "绝缘子串长", "m", "line_binding",
        _lb("profile", "insulator_length_m", transform="mm_to_m"),
        "来源：profile.insulator_length_m（档距剖面-绝缘子串长，原始单位毫米）。口径：>100 视为 mm÷1000 转 m（启发式，与 build_context 一致）。",
    ),
    _def(
        "angle_deg", "电角度", "°", "line_binding",
        _lb("profile", "angle_deg"),
        "来源：profile.angle_deg（档距剖面-电角度）。口径：原值直取；供 electric_angle 计算（电角度−90）。",
    ),
]

# =============================== B 档：回退/缺省/换算链（script + pick 原始域） =========
_B_SCRIPTS: list[dict[str, Any]] = [
    _def(
        "tower_h", "呼高", "m", "script",
        {},
        "来源：base_tower.circuit_geometry_json.tower_height_m；缺失时回退 profile.call_height_m。口径：or 回退链（0 视为缺失，与 build_context 一致）。",
        script="v1 = pick(\"base_tower\", \"circuit_geometry_json.tower_height_m\")\nv2 = pick(\"profile\", \"call_height_m\")\nresult = v1 or v2",
    ),
    _def(
        "voltage", "电压", "kV", "script",
        {},
        "来源：base_tower.line_voltage_kv。口径：or 回退（0 视为缺失），缺省 500.0 kV（与 build_context 一致）。",
        script="v = pick(\"base_tower\", \"line_voltage_kv\")\nresult = v or 500.0",
    ),
    _def(
        "current_ka", "雷电流幅值", "kA", "script",
        {},
        "来源：options.binary_search_current_ka（任务二分电流优先）；缺失时回退 profile.current_a；再缺省 0.0。口径：or 回退链（0 视为缺失，与 build_context 一致）。",
        script="v1 = pick(\"options\", \"binary_search_current_ka\")\nv2 = pick(\"profile\", \"current_a\")\nresult = v1 or v2 or 0.0",
    ),
    _def(
        "head_ms", "波头时间", "ms", "script",
        {},
        "来源：profile.current_head_time_ms → profile.current_head_time_us → options.head_time_min_us。口径：依次回退，缺省 2.6；ms/us 数值直接用（C# 语义，见 build_context 注释）。",
        script="h1 = pick(\"profile\", \"current_head_time_ms\")\nh2 = pick(\"profile\", \"current_head_time_us\")\nh3 = pick(\"options\", \"head_time_min_us\")\nresult = h1 if h1 is not None else (h2 if h2 is not None else (h3 if h3 is not None else 2.6))",
    ),
    _def(
        "tail_ms", "波尾时间", "ms", "script",
        {},
        "来源：profile.current_tail_time_ms → profile.current_tail_time_us → options.tail_time_min_us。口径：依次回退，缺省 50.0；ms/us 数值直接用（C# 语义）。",
        script="t1 = pick(\"profile\", \"current_tail_time_ms\")\nt2 = pick(\"profile\", \"current_tail_time_us\")\nt3 = pick(\"options\", \"tail_time_min_us\")\nresult = t1 if t1 is not None else (t2 if t2 is not None else (t3 if t3 is not None else 50.0))",
    ),
    _def(
        "wave_type", "波形种类", "", "script",
        {},
        "来源：profile.current_type。口径：or 回退（0 视为缺失）+ int 转换，缺省 1（与 build_context 一致）。",
        script="v = pick(\"profile\", \"current_type\")\nresult = int(v or 1)",
    ),
    _def(
        "tower_type", "塔型", "", "script",
        {},
        "来源：options.tower_kind → profile.tower_kind → base_tower.tower_type。口径：or 回退链（0/空串视为缺失），缺省 ganzi（与 build_context 一致）。",
        script="v1 = pick(\"options\", \"tower_kind\")\nv2 = pick(\"profile\", \"tower_kind\")\nv3 = pick(\"base_tower\", \"tower_type\")\nresult = v1 or v2 or v3 or \"ganzi\"",
    ),
    _def(
        "lw_l", "左避雷线中距", "m", "script",
        {},
        "来源：base_tower.circuit_geometry_json.lightning_wire.left_mid_distance_m → cg.left_mid_distance_m → profile.geometry_layers_json.lightning_wire.left_mid_distance_m。口径：三级回退，与 build_context 一致。",
        script="v1 = pick(\"base_tower\", \"circuit_geometry_json.lightning_wire.left_mid_distance_m\")\nv2 = pick(\"base_tower\", \"circuit_geometry_json.left_mid_distance_m\")\nv3 = pick(\"profile\", \"geometry_layers_json.lightning_wire.left_mid_distance_m\")\nresult = v1 if v1 is not None else (v2 if v2 is not None else v3)",
    ),
    _def(
        "lw_r", "右避雷线中距", "m", "script",
        {},
        "来源：base_tower.circuit_geometry_json.lightning_wire.right_mid_distance_m → cg.right_mid_distance_m → profile.geometry_layers_json.lightning_wire.right_mid_distance_m。口径：三级回退，与 build_context 一致。",
        script="v1 = pick(\"base_tower\", \"circuit_geometry_json.lightning_wire.right_mid_distance_m\")\nv2 = pick(\"base_tower\", \"circuit_geometry_json.right_mid_distance_m\")\nv3 = pick(\"profile\", \"geometry_layers_json.lightning_wire.right_mid_distance_m\")\nresult = v1 if v1 is not None else (v2 if v2 is not None else v3)",
    ),
    _def(
        "lw_l_eff", "左避雷线中距(有效)", "m", "script",
        {},
        "来源：同 lw_l 三级回退（base_tower.circuit_geometry_json → cg 顶层 → profile 几何）；全缺时由保护角反推 shield_wire_height_m*tan(radians(protection_angle_left_deg))。口径：is-None 语义（0 合法），与 build_context 一致。",
        script="v1 = pick(\"base_tower\", \"circuit_geometry_json.lightning_wire.left_mid_distance_m\")\nv2 = pick(\"base_tower\", \"circuit_geometry_json.left_mid_distance_m\")\nv3 = pick(\"profile\", \"geometry_layers_json.lightning_wire.left_mid_distance_m\")\nbase = v1 if v1 is not None else (v2 if v2 is not None else v3)\ns_h = pick(\"profile\", \"shield_wire_height_m\")\nang = pick(\"profile\", \"protection_angle_left_deg\")\nresult = base if base is not None else (s_h * tan(radians(ang)) if (ang is not None and s_h is not None) else None)",
    ),
    _def(
        "lw_r_eff", "右避雷线中距(有效)", "m", "script",
        {},
        "来源：同 lw_r 三级回退；全缺时由保护角反推 shield_wire_height_m*tan(radians(protection_angle_right_deg))。口径：is-None 语义（0 合法），与 build_context 一致。",
        script="v1 = pick(\"base_tower\", \"circuit_geometry_json.lightning_wire.right_mid_distance_m\")\nv2 = pick(\"base_tower\", \"circuit_geometry_json.right_mid_distance_m\")\nv3 = pick(\"profile\", \"geometry_layers_json.lightning_wire.right_mid_distance_m\")\nbase = v1 if v1 is not None else (v2 if v2 is not None else v3)\ns_h = pick(\"profile\", \"shield_wire_height_m\")\nang = pick(\"profile\", \"protection_angle_right_deg\")\nresult = base if base is not None else (s_h * tan(radians(ang)) if (ang is not None and s_h is not None) else None)",
    ),
]

# =============================== C 档：相序重排几何（script + pick geometry_permuted） ===
# 相高/中距一律从 build_context 产出的「重排后几何」取，口径 = C# 相序映射
# （atp_phase_sequence，见 build_context 注释）。
_C_GEOM_SPECS: list[tuple[str, str, str, str]] = [
    # (code, 中文名, 回路层, 字段)
    ("h_u", "I回上相高", "I", "phase_height_m.upper"),
    ("h_m", "I回中相高", "I", "phase_height_m.middle"),
    ("h_l", "I回下相高", "I", "phase_height_m.lower"),
    ("sp_u", "I回上相中距", "I", "phase_spacing_m.upper"),
    ("sp_m", "I回中相中距", "I", "phase_spacing_m.middle"),
    ("sp_l", "I回下相中距", "I", "phase_spacing_m.lower"),
    ("c1_u", "I回上相高(c1)", "I", "phase_height_m.upper"),
    ("c1_m", "I回中相高(c1)", "I", "phase_height_m.middle"),
    ("c1_l", "I回下相高(c1)", "I", "phase_height_m.lower"),
    ("c1_sp_u", "I回上相中距(c1)", "I", "phase_spacing_m.upper"),
    ("c1_sp_m", "I回中相中距(c1)", "I", "phase_spacing_m.middle"),
    ("c1_sp_l", "I回下相中距(c1)", "I", "phase_spacing_m.lower"),
    ("c2_u", "II回上相高(c2)", "II", "phase_height_m.upper"),
    ("c2_m", "II回中相高(c2)", "II", "phase_height_m.middle"),
    ("c2_l", "II回下相高(c2)", "II", "phase_height_m.lower"),
    ("c2_sp_u", "II回上相中距(c2)", "II", "phase_spacing_m.upper"),
    ("c2_sp_m", "II回中相中距(c2)", "II", "phase_spacing_m.middle"),
    ("c2_sp_l", "II回下相中距(c2)", "II", "phase_spacing_m.lower"),
    ("c3_u", "III回上相高(c3)", "III", "phase_height_m.upper"),
    ("c3_m", "III回中相高(c3)", "III", "phase_height_m.middle"),
    ("c3_l", "III回下相高(c3)", "III", "phase_height_m.lower"),
    ("c3_sp_u", "III回上相中距(c3)", "III", "phase_spacing_m.upper"),
    ("c3_sp_m", "III回中相中距(c3)", "III", "phase_spacing_m.middle"),
    ("c3_sp_l", "III回下相中距(c3)", "III", "phase_spacing_m.lower"),
    ("c4_u", "IV回上相高(c4)", "IV", "phase_height_m.upper"),
    ("c4_m", "IV回中相高(c4)", "IV", "phase_height_m.middle"),
    ("c4_l", "IV回下相高(c4)", "IV", "phase_height_m.lower"),
    ("c4_sp_u", "IV回上相中距(c4)", "IV", "phase_spacing_m.upper"),
    ("c4_sp_m", "IV回中相中距(c4)", "IV", "phase_spacing_m.middle"),
    ("c4_sp_l", "IV回下相中距(c4)", "IV", "phase_spacing_m.lower"),
]

_C_GEOM_DEFS: list[dict[str, Any]] = [
    _def(
        code, name, "m", "script",
        {},
        f"来源：profile.geometry_layers_json.{cid} 回相几何（原始台账列）。口径：按回路相序重排（atp_phase_sequence，C# 相序映射）后取 {field}，与 build_context 同口径。",
        script=f"result = pick(\"geometry_permuted\", \"{cid}.{field}\")",
    )
    for code, name, cid, field in _C_GEOM_SPECS
]

# =============================== D 档：维度键（script） ================================
_D_DEFS: list[dict[str, Any]] = [
    _def(
        "voltage_level", "电压等级(维度)", "kV", "script",
        {},
        "来源：= voltage（base_tower.line_voltage_kv，缺省 500.0）。口径：or 回退（0 视为缺失），维度匹配用，与电压同值（与 build_context 一致）。",
        script="v = pick(\"base_tower\", \"line_voltage_kv\")\nresult = v or 500.0",
    ),
    _def(
        "circuit_count", "回路数量(维度)", "", "script",
        {},
        "来源：geometry_permuted 各回路（I~IV）是否存在上/中/下相高数据。口径：有相高数据的回路条数，与 build_context 一致（维度匹配用）。",
        script=(
            "r1 = 1 if (pick(\"geometry_permuted\", \"I.phase_height_m.upper\") is not None "
            "or pick(\"geometry_permuted\", \"I.phase_height_m.middle\") is not None "
            "or pick(\"geometry_permuted\", \"I.phase_height_m.lower\") is not None) else 0\n"
            "r2 = 1 if (pick(\"geometry_permuted\", \"II.phase_height_m.upper\") is not None "
            "or pick(\"geometry_permuted\", \"II.phase_height_m.middle\") is not None "
            "or pick(\"geometry_permuted\", \"II.phase_height_m.lower\") is not None) else 0\n"
            "r3 = 1 if (pick(\"geometry_permuted\", \"III.phase_height_m.upper\") is not None "
            "or pick(\"geometry_permuted\", \"III.phase_height_m.middle\") is not None "
            "or pick(\"geometry_permuted\", \"III.phase_height_m.lower\") is not None) else 0\n"
            "r4 = 1 if (pick(\"geometry_permuted\", \"IV.phase_height_m.upper\") is not None "
            "or pick(\"geometry_permuted\", \"IV.phase_height_m.middle\") is not None "
            "or pick(\"geometry_permuted\", \"IV.phase_height_m.lower\") is not None) else 0\n"
            "result = r1 + r2 + r3 + r4"
        ),
    ),
]

# =============================== E 档：计算脚本（常规 script，运行期执行） ==============
# 运行期执行走注册表脚本（不再依赖 atp_work_atp_slots 基线）；公式与 C# 逐字节对齐
# （fetch_CouplingCoefficient :11484-11668 / :1906-1916），golden 测试验证。
_E_SCRIPTS: list[dict[str, Any]] = [
    _def(
        "coupling_k0", "耦合系数 k0（几何）", "", "script",
        {},
        "来源：几何公式计算（镜像法）。口径：rk=0.0055 导体半径，按避雷线/相导线几何+镜像距离算耦合系数，与 C# fetch_CouplingCoefficient :11484-11668 同公式；依赖 shield_h/lw_l/lw_r/insul_m/h_u/sp_u/voltage/tower_type。",
        script=(
            "# 镜像法耦合系数（与 C# fetch_CouplingCoefficient :11484-11668 同公式）\n"
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
        deps=("shield_h", "lw_l", "lw_r", "insul_m", "h_u", "sp_u", "voltage", "tower_type"),
    ),
    _def(
        "electric_angle", "电源电角度（−90）", "°", "script",
        {},
        "来源：angle_deg（profile.angle_deg）减 90。口径：电角度 = 输入电角度 − 90；A/B/C 相 = 该值 / −120 / −240（C# :1906-1916，与 atp_work_atp_slots.rewrite_electric_angle 同规则）。",
        script="result = angle_deg - 90.0\n",
        deps=("angle_deg",),
    ),
]

# =============================== 汇总 ==================================================

def _all_definitions() -> list[dict[str, Any]]:
    return [
        *_A_LINE_BINDINGS,
        *_B_SCRIPTS,
        *_C_GEOM_DEFS,
        *_D_DEFS,
        *_E_SCRIPTS,
    ]


def build_seed_definitions() -> list[dict[str, Any]]:
    """生成全部种子定义（49 个，全部常规来源，无 runtime_key/现状镜像）。"""
    return _all_definitions()


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
        row.sort_order = int(item.get("sort_order", 0))
        row.description = item.get("description")
        row.updated_at = now
        row.updated_by = operator
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}
