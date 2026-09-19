"""ATP 参数模板（配置化）：CRUD + 模板树 + 试算预览 + 派生。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.atp_param_template import AtpParamGlobal, AtpParamTemplate
from app.services.atp_param_config import get_rules, invalidate
from app.services.atp_param_dsl import DslError, validate_expression
from app.services.atp_param_resolver import (
    DIMENSION_KEYS,
    MAPPINGS_DIR,
    SOURCE_VARS,
    MappingRules,
    Rule,
    build_context,
    load_mappings_from_rows,
    normalize_tower_kind,
    resolve_params,
)

_SLOT_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class TemplateError(ValueError):
    """参数模板操作错误（含校验失败）。"""


# --------------------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------------------

def _allowed_vars(db: Session, slots: dict[str, Any] | None = None) -> set[str]:
    names = set(SOURCE_VARS)
    names.update({"voltage_level", "circuit_count", "tower_type", "scene_type", "arrester_config", "structure_kind"})
    for row in db.execute(select(AtpParamGlobal.slot)).fetchall():
        names.add(str(row[0]))
    for row in db.execute(select(AtpParamTemplate.slots_json)).fetchall():
        payload = row[0] or {}
        if isinstance(payload, dict):
            names.update(str(k) for k in payload)
    if slots:
        names.update(str(k) for k in slots)
    return names


def _normalize_defaults(value: Any) -> dict[str, Any]:
    """校验并归一化「测试默认上下文变量」（``{变量名: 默认值}``）。

    仅用于「无杆塔测试」：解析时补全上下文里为 None 的键（allow_defaults=True）。
    """
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise TemplateError("defaults 需要是对象（{变量名: 默认值}）")
    out: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key).strip()
        if not _SLOT_NAME_RE.match(name):
            raise TemplateError(f"defaults 变量名非法：{key}")
        if isinstance(item, bool) or not isinstance(item, (int, float, str)):
            raise TemplateError(f"defaults[{name}] 需要是数值或字符串，实际：{item!r}")
        out[name] = item
    return out


def validate_slots(db: Session, slots: dict[str, Any]) -> None:
    allowed = _allowed_vars(db, slots)
    for slot, spec in (slots or {}).items():
        if not _SLOT_NAME_RE.match(str(slot)):
            raise TemplateError(f"槽位名非法：{slot}")
        if not isinstance(spec, dict):
            raise TemplateError(f"{slot} 的定义必须是对象")
        if not spec.get("expr") and not spec.get("value"):
            raise TemplateError(f"{slot} 需要 expr 或 value")
        try:
            if spec.get("expr"):
                validate_expression(str(spec["expr"]), allowed)
            if spec.get("when"):
                validate_expression(str(spec["when"]), allowed)
        except DslError as exc:
            raise TemplateError(f"{slot}: {exc}") from exc
        fmt = spec.get("fmt", 2)
        if not isinstance(fmt, int) or not 0 <= fmt <= 10:
            raise TemplateError(f"{slot} 的 fmt 非法：{fmt}")
        if "default" in spec:
            # 表达式取不到值（无杆塔上下文）时的兜底字面值 —— 「无杆塔测试」用
            default = spec["default"]
            if isinstance(default, bool) or not isinstance(default, (int, float, str)):
                raise TemplateError(f"{slot} 的 default 非法：{default!r}")


# --------------------------------------------------------------------------------------
# 序列化
# --------------------------------------------------------------------------------------

def serialize_template(row: AtpParamTemplate, *, with_slots: bool = False) -> dict[str, Any]:
    slots = row.slots_json or {}
    payload: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "marker": row.marker,
        "tower_type": row.tower_type,
        "voltage_level": row.voltage_level,
        "circuit_count": row.circuit_count,
        "scene_type": row.scene_type,
        "arrester_config": row.arrester_config,
        "structure_kind": row.structure_kind,
        "priority": row.priority,
        "mode": row.mode,
        "enabled": row.enabled,
        "fallback_to": row.fallback_to,
        "fallback_enabled": row.fallback_enabled,
        "specificity": sum(1 for key in DIMENSION_KEYS if getattr(row, key, None) not in (None, "")),
        "defined_slots": len(slots),
        "slot_names": sorted(slots.keys()),
        "defined_defaults": len(row.defaults_json or {}),
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }
    if with_slots:
        payload["slots"] = slots
        payload["defaults"] = row.defaults_json or {}
    return payload


def list_templates(
    db: Session,
    *,
    keyword: str | None = None,
    tower_type: str | None = None,
    voltage_level: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(AtpParamTemplate).order_by(AtpParamTemplate.tower_type, AtpParamTemplate.voltage_level, AtpParamTemplate.name)
    if tower_type:
        stmt = stmt.where(AtpParamTemplate.tower_type == tower_type)
    if voltage_level:
        stmt = stmt.where(AtpParamTemplate.voltage_level == voltage_level)
    rows = list(db.execute(stmt).scalars().all())
    if keyword:
        needle = keyword.strip().lower()
        rows = [
            row
            for row in rows
            if needle in (row.name or "").lower()
            or needle in (row.tower_type or "").lower()
            or needle in (row.marker or "").lower()
            or needle in (row.scene_type or "").lower()
            or needle in (row.arrester_config or "").lower()
        ]
    return [serialize_template(row) for row in rows]


def get_template(db: Session, template_id: str) -> AtpParamTemplate:
    row = db.get(AtpParamTemplate, template_id)
    if row is None:
        raise TemplateError("参数模板不存在")
    return row


def create_template(db: Session, payload: dict[str, Any], *, operator: str | None = None) -> dict[str, Any]:
    slots = payload.get("slots") or {}
    validate_slots(db, slots)
    defaults = _normalize_defaults(payload.get("defaults"))
    now = datetime.now(timezone.utc)
    row = AtpParamTemplate(
        id=payload.get("id") or str(uuid.uuid4()),
        name=payload["name"],
        marker=payload.get("marker") or payload.get("tower_type"),
        tower_type=payload.get("tower_type"),
        voltage_level=str(payload["voltage_level"]) if payload.get("voltage_level") is not None else None,
        circuit_count=payload.get("circuit_count"),
        scene_type=payload.get("scene_type"),
        arrester_config=payload.get("arrester_config"),
        structure_kind=payload.get("structure_kind"),
        priority=int(payload.get("priority", 100)),
        mode=str(payload.get("mode") or "merge"),
        enabled=bool(payload.get("enabled", True)),
        fallback_to=payload.get("fallback_to"),
        fallback_enabled=bool(payload.get("fallback_enabled", True)),
        slots_json=slots,
        defaults_json=defaults,
        created_at=now,
        updated_at=now,
        updated_by=operator,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    invalidate()
    return serialize_template(row, with_slots=True)


def update_template(db: Session, template_id: str, payload: dict[str, Any], *, operator: str | None = None) -> dict[str, Any]:
    row = get_template(db, template_id)
    slots = payload.get("slots")
    if slots is None:
        slots = row.slots_json or {}
    validate_slots(db, slots)
    row.name = payload.get("name", row.name)
    row.marker = payload.get("marker", row.marker) or payload.get("tower_type", row.tower_type)
    row.tower_type = payload.get("tower_type", row.tower_type)
    row.voltage_level = (
        str(payload["voltage_level"]) if payload.get("voltage_level") is not None else payload.get("voltage_level", row.voltage_level)
    )
    row.circuit_count = payload.get("circuit_count", row.circuit_count)
    row.scene_type = payload.get("scene_type", row.scene_type)
    row.arrester_config = payload.get("arrester_config", row.arrester_config)
    row.structure_kind = payload.get("structure_kind", row.structure_kind)
    row.priority = int(payload.get("priority", row.priority))
    row.mode = str(payload.get("mode", row.mode))
    row.enabled = bool(payload.get("enabled", row.enabled))
    row.fallback_to = payload.get("fallback_to", row.fallback_to)
    row.fallback_enabled = bool(payload.get("fallback_enabled", row.fallback_enabled))
    row.slots_json = slots
    if "defaults" in payload:
        row.defaults_json = _normalize_defaults(payload.get("defaults"))
    row.updated_at = datetime.now(timezone.utc)
    row.updated_by = operator
    db.commit()
    db.refresh(row)
    invalidate()
    return serialize_template(row, with_slots=True)


def delete_template(db: Session, template_id: str) -> None:
    row = get_template(db, template_id)
    db.delete(row)
    db.commit()
    invalidate()


# --------------------------------------------------------------------------------------
# 模板树（覆盖关系可视化）
# --------------------------------------------------------------------------------------

def _voltage_sort_key(value: str) -> tuple[int, float]:
    if value == "*":
        return (0, 0.0)
    try:
        return (1, float(value))
    except ValueError:
        return (2, 0.0)


def build_tree(db: Session, *, keyword: str | None = None) -> dict[str, Any]:
    rules_map = get_rules(force=True)
    global_count = db.execute(select(AtpParamGlobal.slot).where(AtpParamGlobal.enabled)).fetchall()
    rows = list(db.execute(select(AtpParamTemplate)).scalars().all())

    needle = (keyword or "").strip().lower()
    if needle:
        rows = [
            row
            for row in rows
            if needle in (row.name or "").lower()
            or needle in (row.tower_type or "").lower()
            or needle in (row.voltage_level or "").lower()
            or needle in (row.scene_type or "").lower()
            or needle in (row.arrester_config or "").lower()
        ]

    # 按电压分组；组内再按塔型挂载
    groups: dict[str, list[AtpParamTemplate]] = {}
    for row in rows:
        groups.setdefault(row.voltage_level or "*", []).append(row)

    children: list[dict[str, Any]] = []
    for voltage in sorted(groups.keys(), key=_voltage_sort_key):
        group_rows = groups[voltage]
        tower_rows = [row for row in group_rows if row.tower_type]
        loose_rows = [row for row in group_rows if not row.tower_type]
        tower_children: list[dict[str, Any]] = []
        by_tower: dict[str, list[AtpParamTemplate]] = {}
        for row in tower_rows:
            by_tower.setdefault(str(row.tower_type), []).append(row)
        for tower_type, tower_group in sorted(by_tower.items()):
            base_rows = [row for row in tower_group if not _finer_dimensions(row)]
            finer_rows = [row for row in tower_group if _finer_dimensions(row)]
            base = base_rows[0] if base_rows else None
            inherited_from = None
            if base is None:
                inherited = groups.get("*") or []
                for candidate in inherited:
                    if str(candidate.tower_type) == tower_type:
                        inherited_from = candidate.name
                        break
            node = {
                "key": f"tower:{voltage}:{tower_type}",
                "label": _tower_label(tower_type),
                "node_type": "rule" if base is not None else "group",
                "dimension": "tower_type",
                "rule_id": base.id if base is not None else None,
                "has_template": base is not None,
                "defined_slots": len((base.slots_json or {})) if base is not None else 0,
                "effective_slots": (len(base.slots_json or {}) if base else 0)
                + (len(global_count)),
                "status": "own" if base is not None else "inherit",
                "inherited_from": inherited_from if base is None else None,
                "overridden_by": [row.name for row in finer_rows],
                "children": [
                    _rule_node(row, effective_slots=len(global_count) + len(row.slots_json or {}))
                    for row in sorted(finer_rows, key=lambda item: (item.priority, item.name))
                ],
            }
            tower_children.append(node)
        for row in sorted(loose_rows, key=lambda item: (item.priority, item.name)):
            tower_children.append(_rule_node(row, effective_slots=len(global_count) + len(row.slots_json or {})))
        group_node = {
            "key": f"voltage:{voltage}",
            "label": "全部电压" if voltage == "*" else f"{voltage}kV",
            "node_type": "group",
            "dimension": "voltage_level",
            "rule_id": None,
            "has_template": bool(loose_rows),
            "defined_slots": sum(len(row.slots_json or {}) for row in loose_rows),
            "effective_slots": len(global_count) + sum(len(row.slots_json or {}) for row in loose_rows),
            "status": "own" if loose_rows else "inherit",
            "inherited_from": None,
            "overridden_by": [],
            "children": tower_children,
        }
        children.append(group_node)

    root = {
        "key": "global",
        "label": "全局参数模板",
        "node_type": "global",
        "dimension": None,
        "rule_id": None,
        "has_template": bool(global_count),
        "defined_slots": len(global_count),
        "effective_slots": len(global_count),
        "status": "own",
        "inherited_from": None,
        "overridden_by": [],
        "children": children,
    }
    return {"total": len(rows), "root": root}


def _finer_dimensions(row: AtpParamTemplate) -> list[str]:
    return [
        key
        for key in DIMENSION_KEYS
        if key not in ("tower_type", "voltage_level") and getattr(row, key, None) not in (None, "")
    ]


def _tower_label(tower_type: str) -> str:
    mapping = {
        "ganzi": "干字型",
        "guxing": "鼓型",
        "jiubei": "酒杯型",
        "maotou": "猫头型",
        "menxing": "门型",
        "shangzi": "上字型",
        "sihuita": "四回路型",
    }
    return f"{mapping.get(tower_type, tower_type)}（{tower_type}）"


def _rule_node(row: AtpParamTemplate, *, effective_slots: int) -> dict[str, Any]:
    dims = [key for key in DIMENSION_KEYS if getattr(row, key, None) not in (None, "")]
    return {
        "key": f"rule:{row.id}",
        "label": row.name + ("" if row.enabled else "（停用）"),
        "node_type": "rule",
        "dimension": dims[-1] if dims else None,
        "rule_id": row.id,
        "has_template": True,
        "defined_slots": len(row.slots_json or {}),
        "effective_slots": effective_slots,
        "status": "own",
        "inherited_from": None,
        "overridden_by": [],
        "children": [],
    }


# --------------------------------------------------------------------------------------
# 试算预览
# --------------------------------------------------------------------------------------

def _synthetic_case(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """构造一次试算上下文（默认样例几何；可用请求里的维度覆盖塔型/电压）。"""
    circuits = {}
    for idx, cid in enumerate(("I", "II", "III", "IV")):
        circuits[cid] = {
            "phase_height_m": {"upper": 65.5 - idx, "middle": 53.0 - idx, "lower": 42.0 - idx},
            "phase_spacing_m": {"upper": 12.0 + idx, "middle": 12.0 + idx, "lower": 12.0 - idx},
        }
    profile = {
        "tower_kind": payload.get("tower_type") or "ganzi",
        "shield_wire_height_m": 73.5,
        "insulator_length_m": 5945,
        "call_height_m": 42.0,
        "current_type": 1,
        "current_a": 25.109,
        "geometry_layers_json": {
            **circuits,
            "lightning_wire": {"left_mid_distance_m": 12.4, "right_mid_distance_m": 12.4, "height_m": 73.5},
        },
    }
    base_tower = {
        "tower_type": payload.get("tower_type") or "ganzi",
        "line_voltage_kv": payload.get("voltage_level") or 500,
        "ground_resistance_ohm": 10.0,
        "circuit_geometry_json": {
            "lightning_wire": {"left_mid_distance_m": 12.4, "right_mid_distance_m": 12.4, "height_m": 73.5},
        },
    }
    options = {"binary_search_current_ka": payload.get("current_ka") or 146.0, "tower_kind": payload.get("tower_type")}
    return base_tower, profile, options


def resolve_preview(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    rules = get_rules(force=True)
    if rules is None:
        raise TemplateError("参数模板配置不可用")
    base_tower, profile, options = _synthetic_case(payload)
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    if payload.get("voltage_level") is not None:
        context["voltage_level"] = float(payload["voltage_level"])
        context["voltage"] = float(payload["voltage_level"])
    if payload.get("circuit_count") is not None:
        context["circuit_count"] = int(payload["circuit_count"])
    for key in ("scene_type", "arrester_config", "structure_kind"):
        if payload.get(key) is not None:
            context[key] = payload[key]
    if payload.get("tower_type"):
        context["tower_type"] = payload["tower_type"]

    resolved = resolve_params(context, rules)
    diff_slots: list[str] = []
    if payload.get("rule_id"):
        skip_names = _rule_names_for(db, payload["rule_id"])
        filtered = MappingRules(
            rules={k: v for k, v in rules.rules.items() if v.name not in skip_names},
            globals=rules.globals,
            exact_canonical=rules.exact_canonical,
            marker_order=rules.marker_order,
            default_marker=rules.default_marker,
            voltage_rules=[r for r in rules.voltage_rules if r.name not in skip_names],
        )
        baseline = resolve_params(context, filtered)
        diff_slots = sorted(
            slot
            for slot in set(resolved.values) | set(baseline.values)
            if resolved.values.get(slot) != baseline.values.get(slot)
        )
    # 来源标签：基规则（仅 tower_type 维度）在 resolve 中以「塔型标记」作为来源，
    # 细分规则以「规则名」作为来源——据此判断每个槽位是本级定义还是继承。
    focus_source: str | None = None
    if payload.get("rule_id"):
        focus_row = db.get(AtpParamTemplate, payload["rule_id"])
        if focus_row is not None:
            focus_source = (
                resolved.tower_kind
                if focus_row.tower_type and not _finer_dimensions(focus_row)
                else focus_row.name
            )
    slots = [
        {
            "slot": slot,
            "value": value,
            "source": resolved.sources.get(slot, ""),
            "inherited": focus_source is not None and resolved.sources.get(slot, "") != focus_source,
        }
        for slot, value in sorted(resolved.values.items())
    ]
    return {
        "chain": resolved.chain,
        "tower_kind": resolved.tower_kind,
        "slots": slots,
        "diff": [item for item in slots if item["slot"] in diff_slots],
        "missing_slots": [],
    }


def _rule_names_for(db: Session, rule_id: str) -> set[str]:
    row = db.get(AtpParamTemplate, rule_id)
    return {row.name} if row is not None else set()


def derive_template(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    parent = get_template(db, payload["parent_id"])
    dims = {key: getattr(parent, key, None) for key in DIMENSION_KEYS}
    for key in DIMENSION_KEYS:
        if payload.get(key) not in (None, ""):
            dims[key] = payload[key]
    preview = resolve_preview(
        db,
        {
            "tower_type": dims.get("tower_type"),
            "voltage_level": dims.get("voltage_level"),
            "circuit_count": dims.get("circuit_count"),
            "scene_type": dims.get("scene_type"),
            "arrester_config": dims.get("arrester_config"),
            "structure_kind": dims.get("structure_kind"),
        },
    )
    label = " · ".join(str(value) for value in dims.values() if value not in (None, ""))
    return {
        "suggested_name": f"{label}（细分）",
        "dimensions": {key: value for key, value in dims.items() if value not in (None, "")},
        "inherited_slots": {item["slot"]: item["value"] for item in preview["slots"]},
        "chain": preview["chain"],
        "slots": {},
    }


def meta_options(db: Session) -> dict[str, Any]:
    tower_rows = db.execute(
        text("SELECT DISTINCT tower_type FROM atp_asset WHERE tower_type IS NOT NULL ORDER BY tower_type")
    ).fetchall()
    seen: dict[str, str] = {}
    for (tower_type,) in tower_rows:
        seen.setdefault(str(tower_type), _tower_label(str(tower_type)))
    try:
        common = json.loads((MAPPINGS_DIR / "_common.json").read_text(encoding="utf-8"))
        markers = list(common.get("marker_order") or [])
    except Exception:
        markers = []
    for marker in markers:
        seen.setdefault(marker, marker)
    voltage_rows = db.execute(
        text("SELECT DISTINCT voltage_level FROM atp_asset WHERE voltage_level IS NOT NULL ORDER BY voltage_level")
    ).fetchall()
    voltages = [str(row[0]) for row in voltage_rows] or ["35", "66", "110", "220", "330", "500", "750", "1000"]
    scene_rows = db.execute(
        text("SELECT DISTINCT scene_type FROM atp_asset WHERE scene_type IS NOT NULL ORDER BY scene_type")
    ).fetchall()
    arrester_rows = db.execute(
        text("SELECT DISTINCT arrester_config FROM atp_asset WHERE arrester_config IS NOT NULL ORDER BY arrester_config")
    ).fetchall()
    slot_names = sorted(
        {str(row[0]) for row in db.execute(select(AtpParamGlobal.slot)).fetchall()}
        | {str(key) for row in db.execute(select(AtpParamTemplate.slots_json)).fetchall() if isinstance(row[0], dict) for key in (row[0] or {})}
    )
    # 「测试默认参数集」可填的上下文变量名（表达式可引用的源变量 + 维度键 + 已有槽位名）
    variable_names = sorted(
        set(SOURCE_VARS)
        | set(DIMENSION_KEYS)
        | {"voltage_level", "circuit_count"}
        | set(slot_names)
    )
    return {
        "tower_types": [{"value": key, "label": label} for key, label in sorted(seen.items())],
        "voltages": voltages,
        "scene_types": [{"value": str(row[0]), "label": str(row[0])} for row in scene_rows],
        "arrester_configs": [{"value": str(row[0]), "label": str(row[0])} for row in arrester_rows],
        "slot_names": slot_names,
        "variable_names": variable_names,
    }
