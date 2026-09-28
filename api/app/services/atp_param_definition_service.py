"""ATP 参数注册表服务：CRUD / 可绑定字段目录 / 脚本试算 / 预览解析。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.atp_param_definition import AtpParamDefinition
from app.services.atp_param_config import invalidate
from app.services.atp_param_definition_seed import build_seed_definition_objects
from app.services.atp_param_registry import (
    Definition,
    DefinitionError,
    definition_from_row,
    load_definitions,
    resolve_definitions,
    validate_definition,
)
from app.services.atp_param_script import collect_names, evaluate_script, validate_script
from app.services.atp_param_resolver import build_context


class DefinitionServiceError(ValueError):
    """参数注册表操作错误。"""


# --------------------------------------------------------------------------------------
# 序列化 / CRUD
# --------------------------------------------------------------------------------------

def serialize_definition(row: AtpParamDefinition) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "unit": row.unit,
        "data_type": row.data_type,
        "source_type": row.source_type,
        "binding_json": row.binding_json or {},
        "script_code": row.script_code,
        "deps_json": row.deps_json or [],
        "enabled": row.enabled,
        "sort_order": row.sort_order,
        "description": row.description,
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }


def _row_to_definition(row: AtpParamDefinition) -> Definition:
    return definition_from_row(
        {
            "code": row.code,
            "name": row.name,
            "unit": row.unit,
            "data_type": row.data_type,
            "source_type": row.source_type,
            "binding_json": row.binding_json,
            "script_code": row.script_code,
            "deps_json": row.deps_json,
            "enabled": row.enabled,
            "description": row.description,
        }
    )


def list_definitions(
    db: Session,
    *,
    keyword: str | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(AtpParamDefinition).order_by(
        AtpParamDefinition.sort_order, AtpParamDefinition.code
    )
    if source_type:
        stmt = stmt.where(AtpParamDefinition.source_type == source_type)
    rows = list(db.execute(stmt).scalars().all())
    if keyword:
        needle = keyword.strip().lower()
        rows = [
            row
            for row in rows
            if needle in (row.code or "").lower()
            or needle in (row.name or "").lower()
            or needle in (row.description or "").lower()
        ]
    return [serialize_definition(row) for row in rows]


def get_definition(db: Session, definition_id: str) -> AtpParamDefinition:
    row = db.get(AtpParamDefinition, definition_id)
    if row is None:
        raise DefinitionServiceError("参数不存在")
    return row


def create_definition(
    db: Session, payload: dict[str, Any], *, operator: str | None = None
) -> dict[str, Any]:
    code = str(payload["code"]).strip()
    existing = db.execute(
        select(AtpParamDefinition).where(AtpParamDefinition.code == code)
    ).scalar_one_or_none()
    if existing is not None:
        raise DefinitionServiceError(f"参数 code 已存在：{code}（请编辑该参数）")
    definition = Definition(
        code=code,
        name=str(payload.get("name") or code),
        unit=payload.get("unit"),
        data_type=str(payload.get("data_type") or "number"),
        source_type=str(payload.get("source_type") or "line_binding"),
        binding_json=dict(payload.get("binding_json") or {}),
        script_code=payload.get("script_code"),
        deps=list(payload.get("deps_json") or []),
        enabled=bool(payload.get("enabled", True)),
        sort_order=int(payload.get("sort_order", 0)),
        description=payload.get("description"),
    )
    validate_definition(definition, allowed_var_names=_context_var_names())
    now = datetime.now(timezone.utc)
    row = AtpParamDefinition(
        id=str(uuid.uuid4()),
        code=code,
        name=definition.name,
        unit=definition.unit,
        data_type=definition.data_type,
        source_type=definition.source_type,
        binding_json=definition.binding_json,
        script_code=definition.script_code,
        deps_json=definition.deps,
        enabled=definition.enabled,
        sort_order=definition.sort_order,
        description=definition.description,
        created_at=now,
        updated_at=now,
        updated_by=operator,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    invalidate()
    return serialize_definition(row)


def update_definition(
    db: Session, definition_id: str, payload: dict[str, Any], *, operator: str | None = None
) -> dict[str, Any]:
    row = get_definition(db, definition_id)
    code = str(payload.get("code", row.code)).strip()
    if code != row.code:
        dup = db.execute(
            select(AtpParamDefinition).where(
                AtpParamDefinition.code == code, AtpParamDefinition.id != row.id
            )
        ).scalar_one_or_none()
        if dup is not None:
            raise DefinitionServiceError(f"参数 code 已被占用：{code}")
    definition = Definition(
        code=code,
        name=str(payload.get("name", row.name) or code),
        unit=payload.get("unit", row.unit),
        data_type=str(payload.get("data_type", row.data_type) or "number"),
        source_type=str(payload.get("source_type", row.source_type) or "line_binding"),
        binding_json=dict(payload.get("binding_json", row.binding_json or {})),
        script_code=payload.get("script_code", row.script_code),
        deps=list(payload.get("deps_json", row.deps_json or [])),
        enabled=bool(payload.get("enabled", row.enabled)),
        sort_order=int(payload.get("sort_order", row.sort_order)),
        description=payload.get("description", row.description),
    )
    validate_definition(definition, allowed_var_names=_context_var_names())
    row.code = definition.code
    row.name = definition.name
    row.unit = definition.unit
    row.data_type = definition.data_type
    row.source_type = definition.source_type
    row.binding_json = definition.binding_json
    row.script_code = definition.script_code
    row.deps_json = definition.deps
    row.enabled = definition.enabled
    row.sort_order = definition.sort_order
    row.description = definition.description
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = operator
    db.commit()
    db.refresh(row)
    invalidate()
    return serialize_definition(row)


def delete_definition(db: Session, definition_id: str) -> None:
    row = get_definition(db, definition_id)
    # 检查是否被模板槽位引用（防误删）
    from app.models.atp_param_template import AtpParamGlobal, AtpParamTemplate

    refs = [
        str(r[0])
        for r in db.execute(select(AtpParamTemplate.slots_json)).fetchall()
        if isinstance(r[0], dict)
        for key, spec in (r[0] or {}).items()
        if isinstance(spec, dict) and spec.get("param") == row.code
    ]
    if refs:
        raise DefinitionServiceError(
            f"参数 {row.code} 被模板槽位 {','.join(sorted(refs))} 引用，请先解除引用再删除"
        )
    db.delete(row)
    db.commit()
    invalidate()


# --------------------------------------------------------------------------------------
# 可绑定字段目录（前端 line_binding 表单选择用）
# --------------------------------------------------------------------------------------

_BINDABLE_FIELDS: list[dict[str, Any]] = [
    # base_tower（power_line_tower / 快照主表）
    {"value": "ground_resistance_ohm", "label": "接地电阻", "source": "base_tower", "unit": "Ω", "note": "→ ground_r（RER001）"},
    {"value": "line_voltage_kv", "label": "线路电压", "source": "base_tower", "unit": "kV", "note": "→ voltage"},
    {"value": "tower_type", "label": "塔型", "source": "base_tower", "data_type": "string", "note": "维度匹配"},
    {"value": "circuit_geometry_json.tower_height_m", "label": "呼高（几何）", "source": "base_tower", "unit": "m", "note": "→ tower_h"},
    {"value": "circuit_geometry_json.lightning_wire.left_mid_distance_m", "label": "左避雷线中距", "source": "base_tower", "unit": "m", "note": "→ lw_l"},
    {"value": "circuit_geometry_json.lightning_wire.right_mid_distance_m", "label": "右避雷线中距", "source": "base_tower", "unit": "m", "note": "→ lw_r"},
    # profile（tower_profile）
    {"value": "insulator_length_m", "label": "绝缘子串长", "source": "profile", "unit": "mm", "note": "→ insul_m（>100 自动转米，可配 transform=mm_to_m）"},
    {"value": "shield_wire_height_m", "label": "避雷线高度", "source": "profile", "unit": "m", "note": "→ shield_h"},
    {"value": "call_height_m", "label": "呼高", "source": "profile", "unit": "m", "note": "→ tower_h（几何缺失时）"},
    {"value": "angle_deg", "label": "电角度", "source": "profile", "unit": "°", "note": "→ electric_angle"},
    {"value": "current_a", "label": "雷电流幅值 a", "source": "profile", "unit": "kA", "note": "→ current_ka 初值"},
    {"value": "current_head_time_us", "label": "波头时间", "source": "profile", "unit": "μs", "note": "→ head_ms"},
    {"value": "current_tail_time_us", "label": "波尾时间", "source": "profile", "unit": "μs", "note": "→ tail_ms"},
    {"value": "current_type", "label": "波形种类", "source": "profile", "data_type": "string", "note": "→ wave_type"},
    {"value": "geometry_layers_json.I.phase_height_m.upper", "label": "I回上相高", "source": "profile", "unit": "m", "note": "→ h_u（相序重排后）"},
    {"value": "geometry_layers_json.I.phase_height_m.middle", "label": "I回中相高", "source": "profile", "unit": "m", "note": "→ h_m"},
    {"value": "geometry_layers_json.I.phase_height_m.lower", "label": "I回下相高", "source": "profile", "unit": "m", "note": "→ h_l"},
    {"value": "geometry_layers_json.I.phase_spacing_m.upper", "label": "I回上相中距", "source": "profile", "unit": "m", "note": "→ sp_u"},
    {"value": "geometry_layers_json.I.phase_spacing_m.middle", "label": "I回中相中距", "source": "profile", "unit": "m", "note": "→ sp_m"},
    {"value": "geometry_layers_json.I.phase_spacing_m.lower", "label": "I回下相中距", "source": "profile", "unit": "m", "note": "→ sp_l"},
    {"value": "geometry_layers_json.lightning_wire.left_mid_distance_m", "label": "左避雷线中距（几何）", "source": "profile", "unit": "m", "note": "→ lw_l 回退"},
    {"value": "geometry_layers_json.lightning_wire.right_mid_distance_m", "label": "右避雷线中距（几何）", "source": "profile", "unit": "m", "note": "→ lw_r 回退"},
    # options（execution_options，任务级）
    {"value": "binary_search_current_ka", "label": "二分迭代电流", "source": "options", "unit": "kA", "note": "→ current_ka（优先）"},
    {"value": "head_time_min_us", "label": "波头时间（任务）", "source": "options", "unit": "μs", "note": "→ head_ms 回退"},
    {"value": "tail_time_min_us", "label": "波尾时间（任务）", "source": "options", "unit": "μs", "note": "→ tail_ms 回退"},
    {"value": "tower_kind", "label": "塔型（任务指定）", "source": "options", "data_type": "string", "note": "维度匹配"},
]


def field_catalog() -> dict[str, Any]:
    script_functions = sorted(
        [
            "abs", "sqrt", "min", "max", "round", "clamp", "hypot", "log", "pow",
            "exp", "sin", "cos", "tan", "radians", "degrees", "floor", "ceil",
            "v(35,66,110,220,330,500,750,1000)", "v_arc(voltage)", "v_darc(voltage)",
        ]
    )
    return {
        "fields": _BINDABLE_FIELDS,
        "transform_options": ["mm_to_m"],
        "source_options": [
            {"value": "base_tower", "label": "杆塔主表（power_line_tower）"},
            {"value": "profile", "label": "塔属性（tower_profile）"},
            {"value": "options", "label": "任务执行选项（execution_options）"},
        ],
        "script_functions": script_functions,
    }


# --------------------------------------------------------------------------------------
# 脚本试算 / 预览解析
# --------------------------------------------------------------------------------------

def _context_var_names() -> set[str]:
    """脚本可引用的上下文变量名（SOURCE_VARS + 维度键）。"""
    from app.services.atp_param_resolver import SOURCE_VARS

    return set(SOURCE_VARS) | {
        "voltage_level", "circuit_count", "tower_type", "scene_type",
        "arrester_config", "structure_kind",
        # 脚本保留域（pick 取数入口，非依赖）
        "base_tower", "profile", "options", "geometry_permuted",
    }


def test_script(payload: dict[str, Any], db: Session | None = None) -> dict[str, Any]:
    script = str(payload.get("script_code") or "").strip()
    deps = list(payload.get("deps_json") or [])
    if not script:
        raise DefinitionServiceError("脚本为空")
    try:
        validate_script(script)
    except Exception as exc:  # noqa: BLE001
        raise DefinitionServiceError(str(exc)) from exc
    base_tower = dict(payload.get("base_tower") or {})
    profile = dict(payload.get("profile") or {})
    options = dict(payload.get("execution_options") or {})
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    context["angle_deg"] = profile.get("angle_deg") if profile.get("angle_deg") is not None else context.get("angle_deg", 0.0)
    variables = dict(context)
    # 注入原始输入域（供 pick 取数，与 resolve_definitions 同口径）
    variables["base_tower"] = base_tower
    variables["profile"] = profile
    variables["options"] = options
    variables["geometry_permuted"] = context.get("geometry_permuted") or {}
    # 注册表依赖参数：先用 resolve_definitions 从样例上下文解析（用户自定义 line_binding/脚本参数）
    if db is not None and deps:
        from app.services.atp_param_registry import resolve_definitions  # noqa: PLC0415

        definitions = load_definitions(db)
        registered_deps = [dep for dep in deps if any(d.code == dep for d in definitions)]
        if registered_deps:
            try:
                resolved = resolve_definitions(
                    definitions=definitions,
                    base_tower=base_tower,
                    profile=profile,
                    execution_options=options,
                    context=context,
                    requested=registered_deps,
                )
                variables.update({k: v for k, v in resolved.items() if v is not None})
            except DefinitionError as exc:
                raise DefinitionServiceError(str(exc)) from exc
    # 显式声明的依赖若仍缺失 → 明确报错（禁静默，用户铁律）
    missing = [dep for dep in deps if variables.get(dep) is None]
    if missing:
        raise DefinitionServiceError(f"依赖参数缺失：{', '.join(missing)}（试算样例未提供该字段）")
    value, errors = evaluate_script(script, variables)
    referenced = sorted(collect_names(script))
    return {
        "ok": not errors,
        "value": value,
        "errors": errors,
        "referenced": referenced,
    }


def preview_resolve(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    definitions = load_definitions(db)
    if not definitions:
        definitions = build_seed_definition_objects()
    base_tower = dict(payload.get("base_tower") or {})
    profile = dict(payload.get("profile") or {})
    options = dict(payload.get("execution_options") or {})
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    context["angle_deg"] = profile.get("angle_deg", 0.0) or 0.0
    codes = list(payload.get("codes") or [])
    requested = codes or [d.code for d in definitions if not d.runtime_baseline]
    try:
        values = resolve_definitions(
            definitions=definitions,
            base_tower=base_tower,
            profile=profile,
            execution_options=options,
            context=context,
            requested=requested,
        )
    except DefinitionError as exc:
        raise DefinitionServiceError(str(exc)) from exc
    by_code = {d.code: d for d in definitions}
    items = []
    for code in sorted(requested):
        definition = by_code.get(code)
        if definition is None:
            continue
        items.append(
            {
                "code": code,
                "name": definition.name,
                "unit": definition.unit,
                "source_type": definition.source_type,
                "value": values.get(code),
            }
        )
    return {"items": items}


def preview_resolve_by_towers(
    db: Session,
    tower_ids: list[str],
    execution_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按真实杆塔上下文试算参数注册表（方案 1+3：批量塔，口径与执行链路一致）。

    每个塔复用快照组装口径：
      base_tower = fl_analysis_service._build_base_tower_json(tower, tower.line)
      profile    = fl_analysis_service._build_profile_json(tower.profile, tower)
    再调 preview_resolve（与样例上下文试算同一解析函数）。

    塔数据缺失/解析失败 → 该塔返回 error 字段，不整批 500（对齐「不具备条件抛错」）。
    """
    from app.models.line_tower import LineTower
    from app.services.fl_analysis_service import (  # noqa: PLC0415
        _build_base_tower_json,
        _build_profile_json,
    )

    options = dict(execution_options or {})
    results: list[dict[str, Any]] = []
    for tower_id in tower_ids:
        tower = db.get(LineTower, tower_id)
        entry: dict[str, Any] = {
            "tower_id": tower_id,
            "tower_no": tower.tower_no if tower else None,
            "tower_type": tower.tower_type if tower else None,
            "line_name": tower.line.name if tower and tower.line else None,
            "ok": False,
            "error": None,
            "items": [],
        }
        if tower is None:
            entry["error"] = "杆塔不存在"
            results.append(entry)
            continue
        try:
            base_tower = _build_base_tower_json(tower, tower.line)
            profile = _build_profile_json(tower.profile, tower)
            if not profile:
                entry["error"] = "杆塔无 profile 数据（未导入塔属性）"
                results.append(entry)
                continue
            preview = preview_resolve(
                db,
                {
                    "base_tower": base_tower,
                    "profile": profile,
                    "execution_options": options,
                    "codes": [],
                },
            )
            entry["ok"] = True
            entry["items"] = preview.get("items") or []
        except Exception as exc:  # noqa: BLE001 - 单塔失败不阻断整批
            entry["error"] = str(exc)
        results.append(entry)
    return {"results": results}


__all__ = [
    "DefinitionServiceError",
    "create_definition",
    "delete_definition",
    "field_catalog",
    "get_definition",
    "list_definitions",
    "preview_resolve",
    "preview_resolve_by_towers",
    "serialize_definition",
    "test_script",
    "update_definition",
]
