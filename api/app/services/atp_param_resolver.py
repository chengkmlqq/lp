"""ATP 参数模板：配置驱动的槽位解析器（覆盖链 + 来源追踪）。

与 compute_csharp_atp_params（代码路径）逐字节等价，由 scripts/atp_param_golden_test.py 保证。

覆盖链（粗 → 细）：
    L0 全局槽位（_common.json → globals）
    规则按 (specificity, priority, name) 升序合并；specificity = 规则非空维度个数
    逐槽位合并：细层定义了即覆盖粗层，未定义则继承
    mode=replace：丢弃祖先全部槽位后再重建
    enabled=false：该槽位输出 "1."（来源标注为“本级关闭”）

维度（规则可空 = 通配）：tower_type / voltage_level / circuit_count / scene_type /
arrester_config / structure_kind
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.atp_param_dsl import (
    DslError,
    collect_names,
    evaluate,
    format_value,
    parse_expression,
    validate_expression,
)
from app.services.atp_param_registry import Definition, DefinitionError, resolve_definitions

MAPPINGS_DIR = Path(__file__).resolve().parent / "atp_param_mappings"

DIMENSION_KEYS = (
    "tower_type",
    "voltage_level",
    "circuit_count",
    "scene_type",
    "arrester_config",
    "structure_kind",
)

# 表达式可引用的源变量（与 fl_analysis_external 现有取值一致）
SOURCE_VARS = {
    "ground_r", "insul_m", "shield_h", "tower_h", "voltage",
    "current_ka", "head_ms", "tail_ms", "wave_type",
    "lw_l", "lw_r", "lw_l_eff", "lw_r_eff",
    "h_u", "h_m", "h_l", "sp_u", "sp_m", "sp_l",
    "c1_u", "c1_m", "c1_l", "c1_sp_u", "c1_sp_m", "c1_sp_l",
    "c2_u", "c2_m", "c2_l", "c2_sp_u", "c2_sp_m", "c2_sp_l",
    "c3_u", "c3_m", "c3_l", "c3_sp_u", "c3_sp_m", "c3_sp_l",
    "c4_u", "c4_m", "c4_l", "c4_sp_u", "c4_sp_m", "c4_sp_l",
}


class MappingConfigError(ValueError):
    """映射配置非法。"""


@dataclass
class Rule:
    """一条参数模板规则（DB 一行 / JSON 一个文件）。"""

    name: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    slots: dict[str, dict[str, Any]] = field(default_factory=dict)
    priority: int = 100
    mode: str = "merge"  # merge | replace
    enabled: bool = True
    fallback_to: str | None = None
    fallback_enabled: bool = True
    # 「无杆塔测试」用的默认上下文变量（如 {"h_u": 65.5, "shield_h": 73.5}）：
    # 仅在 allow_defaults=True 时生效（生产路径不受影响），只补上下文里为 None 的键。
    defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def specificity(self) -> int:
        return sum(1 for key in DIMENSION_KEYS if self.dimensions.get(key) not in (None, ""))

    @property
    def sort_key(self) -> tuple[int, int, str]:
        return (self.specificity, self.priority, self.name)


@dataclass
class MappingRules:
    """全部规则 + 全局槽位 + 塔型归一化配置 + 参数注册表。"""

    rules: dict[str, Rule] = field(default_factory=dict)  # marker -> Rule
    globals: dict[str, dict[str, Any]] = field(default_factory=dict)
    exact_canonical: list[str] = field(default_factory=list)
    marker_order: list[str] = field(default_factory=list)
    default_marker: str = "ganzi"
    voltage_rules: list[Rule] = field(default_factory=list)  # 带非 tower_type 维度的细分规则
    # 全局默认上下文变量（_common.json 顶层 defaults）—— 仅 allow_defaults=True 时生效
    defaults: dict[str, Any] = field(default_factory=dict)
    # 参数注册表（atp_param_definition）；为空 = 旧行为（只有 SOURCE_VARS 上下文）
    definitions: list[Definition] = field(default_factory=list)


@dataclass
class ResolvedParams:
    values: dict[str, str] = field(default_factory=dict)          # 槽位 -> 格式化值
    sources: dict[str, str] = field(default_factory=dict)         # 槽位 -> 来源（规则名/继承）
    chain: list[str] = field(default_factory=list)                # 命中链（粗→细）
    tower_kind: str = "ganzi"
    # ↓ 诊断（默认值/缺失上下文）—— 供「无杆塔测试」与排障使用，不改变 values 语义
    defaults_used: dict[str, str] = field(default_factory=dict)   # 槽位 -> 命中的默认值
    unresolved: dict[str, list[str]] = field(default_factory=dict)  # 槽位 -> 取不到值的源变量名
    defaults_applied: list[str] = field(default_factory=list)     # 用了模板默认值的上下文变量

    def as_dict(self) -> dict[str, str]:
        return dict(self.values)


# --------------------------------------------------------------------------------------
# 加载与校验
# --------------------------------------------------------------------------------------

def _validate_slots(rule_name: str, slots: Mapping[str, Any]) -> None:
    for slot, spec in slots.items():
        if not isinstance(spec, dict) or not any(k in spec for k in ("expr", "value", "param")):
            raise MappingConfigError(f"{rule_name}.{slot} 缺少 expr/value/param")
        if "expr" in spec:
            validate_expression(str(spec["expr"]))
        when = spec.get("when")
        if when:
            validate_expression(str(when))
        fmt = spec.get("fmt", 2)
        if not isinstance(fmt, int) or not 0 <= fmt <= 10:
            raise MappingConfigError(f"{rule_name}.{slot} 的 fmt 非法：{fmt}")
        if "default" in spec:
            # default：表达式取不到值（源变量缺失/为 None）时的兜底字面值。
            # 用于「无杆塔上下文」的测试场景；不写 default 时保持与 C# 一致的 "1." 占位。
            default = spec["default"]
            if isinstance(default, bool) or not isinstance(default, (int, float, str)):
                raise MappingConfigError(f"{rule_name}.{slot} 的 default 非法：{default!r}")


def load_mappings(mappings_dir: Path | None = None) -> MappingRules:
    """从 JSON 目录加载规则（运行时可由 DB 覆盖，见 load_mappings_from_rows）。"""
    root = mappings_dir or MAPPINGS_DIR
    if not root.exists():
        raise MappingConfigError(f"映射目录不存在：{root}")
    common_path = root / "_common.json"
    if not common_path.exists():
        raise MappingConfigError("缺少 _common.json")

    common = json.loads(common_path.read_text(encoding="utf-8"))
    rules = MappingRules(
        globals={k: dict(v) for k, v in (common.get("globals") or {}).items()},
        exact_canonical=list(common.get("exact_canonical") or []),
        marker_order=list(common.get("marker_order") or []),
        default_marker=str(common.get("default_marker") or "ganzi"),
        defaults=dict(common.get("defaults") or {}),
    )
    _validate_slots("_common.globals", rules.globals)

    for path in sorted(root.glob("*.json")):
        if path.name.startswith("_"):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        marker = str(raw.get("marker") or raw.get("tower_type") or path.stem)
        rule = Rule(
            name=str(raw.get("name") or marker),
            dimensions={k: raw.get(k) for k in DIMENSION_KEYS if raw.get(k) not in (None, "")},
            slots={k: dict(v) for k, v in (raw.get("slots") or {}).items()},
            priority=int(raw.get("priority", 100)),
            mode=str(raw.get("mode") or "merge"),
            enabled=bool(raw.get("enabled", True)),
            fallback_to=raw.get("fallback_to"),
            fallback_enabled=bool(raw.get("fallback_enabled", True)),
            defaults=dict(raw.get("defaults") or {}),
        )
        _validate_slots(rule.name, rule.slots)
        if rule.dimensions.get("tower_type") and not any(
            k != "tower_type" for k in rule.dimensions
        ):
            rules.rules[marker] = rule
        else:
            rules.voltage_rules.append(rule)
    rules.definitions = _seed_definitions()
    return rules


def _seed_definitions() -> list:
    """代码内种子定义（与 atp_param_definition_seed 同源），供 JSON 回落路径使用。"""
    from app.services.atp_param_definition_seed import build_seed_definition_objects  # noqa: PLC0415

    return build_seed_definition_objects()


def globals_from_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """把 atp_param_global 表行转成 globals 规范（与 _common.json 的 globals 同构）。"""
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        spec: dict[str, Any] = {}
        if row.get("expr"):
            spec["expr"] = row["expr"]
        if row.get("value"):
            spec["value"] = row["value"]
        if row.get("when_expr"):
            spec["when"] = row["when_expr"]
        if row.get("else_value"):
            spec["else"] = row["else_value"]
        spec["fmt"] = int(row.get("fmt", 2))
        if row.get("enabled") is False:
            spec["enabled"] = False
        out[str(row["slot"])] = spec
    return out


def load_mappings_from_rows(rows: Iterable[Mapping[str, Any]], *, common: Mapping[str, Any] | None = None) -> MappingRules:
    """从 DB 行构造规则（运行时用；行结构与 JSON 一致，slots 为 dict）。"""
    if common is None:
        common_path = MAPPINGS_DIR / "_common.json"
        common_cfg: Mapping[str, Any] = json.loads(common_path.read_text(encoding="utf-8"))
    else:
        common_cfg = common
    rules = MappingRules(
        globals={k: dict(v) for k, v in (common_cfg.get("globals") or {}).items()},
        exact_canonical=list(common_cfg.get("exact_canonical") or []),
        marker_order=list(common_cfg.get("marker_order") or []),
        default_marker=str(common_cfg.get("default_marker") or "ganzi"),
        defaults=dict(common_cfg.get("defaults") or {}),
    )
    for row in rows:
        slots = row.get("slots_json")
        if isinstance(slots, str):
            slots = json.loads(slots)
        defaults = row.get("defaults_json")
        if isinstance(defaults, str):
            defaults = json.loads(defaults)
        dims = {k: row.get(k) for k in DIMENSION_KEYS if row.get(k) not in (None, "")}
        rule = Rule(
            name=str(row.get("name") or row.get("tower_type") or "unnamed"),
            dimensions=dims,
            slots={k: dict(v) for k, v in (slots or {}).items()},
            priority=int(row.get("priority", 100)),
            mode=str(row.get("mode") or "merge"),
            enabled=bool(row.get("enabled", True)),
            fallback_to=row.get("fallback_to"),
            fallback_enabled=bool(row.get("fallback_enabled", True)),
            defaults=dict(defaults or {}),
        )
        _validate_slots(rule.name, rule.slots)
        marker = str(row.get("marker") or row.get("tower_type") or rule.name)
        if rule.dimensions.get("tower_type") and not any(k != "tower_type" for k in rule.dimensions):
            rules.rules[marker] = rule
        else:
            rules.voltage_rules.append(rule)
    return rules


# --------------------------------------------------------------------------------------
# 塔型归一化（与现有代码的 marker 顺序语义一致）
# --------------------------------------------------------------------------------------

def normalize_tower_kind(raw: Any, rules: MappingRules) -> str:
    kind = str(raw or "").strip().lower()
    if not kind:
        return rules.default_marker
    if kind in rules.exact_canonical:
        return kind
    for marker in rules.marker_order:
        if marker in kind:
            return marker
    return rules.default_marker


def _resolve_rule_for(rules: MappingRules, canonical: str, *, allow_fallback: bool) -> tuple[Rule | None, str, list[str]]:
    """返回 (规则, 生效塔型, 命中链)。fallback（如 guxing→ganzi）在此处理。"""
    chain: list[str] = []
    rule = rules.rules.get(canonical)
    if rule is None:
        # 无该塔型规则 → 回落默认塔型（等价现有代码 else 分支，如 zhiliu/vzhiliu → ganzi）
        fallback = rules.rules.get(rules.default_marker)
        if fallback is not None:
            chain.append(f"{fallback.name}（默认分支）")
            return fallback, rules.default_marker, chain
        return None, canonical, chain
    chain.append(rule.name)
    if allow_fallback and rule.fallback_to:
        fb = rules.rules.get(str(rule.fallback_to))
        if fb is not None and rule.fallback_enabled:
            chain.append(f"{fb.name}（wine 回退）")
            return fb, str(rule.fallback_to), chain
    return rule, canonical, chain


def _matching_voltage_rules(rules: MappingRules, context: Mapping[str, Any], canonical: str) -> list[Rule]:
    matched: list[Rule] = []
    for rule in rules.voltage_rules:
        dims = rule.dimensions
        if dims.get("tower_type") not in (None, canonical):
            continue
        ok = True
        for key in DIMENSION_KEYS:
            want = dims.get(key)
            if want in (None, ""):
                continue
            got = context.get(key)
            if key == "voltage_level":
                if got is None or abs(float(got) - float(want)) > 1e-6:
                    ok = False
                    break
            elif str(got) != str(want):
                ok = False
                break
        if ok:
            matched.append(rule)
    return sorted(matched, key=lambda r: r.sort_key)


# --------------------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------------------

def _collect_defaults(
    rules: MappingRules,
    base_rule: Rule | None,
    ctx: Mapping[str, Any],
    effective_kind: str,
) -> dict[str, Any]:
    """收集规则链上的默认上下文变量（全局 → 塔型 → 细分，粗→细覆盖）。"""
    out: dict[str, Any] = dict(rules.defaults or {})
    if base_rule is not None and base_rule.defaults:
        out.update(base_rule.defaults)
    for rule in _matching_voltage_rules(rules, ctx, effective_kind):
        if rule.defaults:
            out.update(rule.defaults)
    return out


def _collect_requested_params(rules: MappingRules) -> set[str]:
    """收集规则里被引用的注册表参数 code：
    - 槽位 `param` 键；- expr 里 `collect_names` 命中的注册表定义（非 SOURCE_VARS/上下文键）。
    """
    referenced: set[str] = set()
    registered = {d.code for d in rules.definitions}
    if not registered:
        return referenced
    for slot_group in (rules.globals, *(rule.slots for rule in rules.rules.values()), *(rule.slots for rule in rules.voltage_rules)):
        for spec in slot_group.values():
            if not isinstance(spec, dict):
                continue
            code = spec.get("param")
            if code and code in registered:
                referenced.add(str(code))
            for key in ("expr", "when"):
                expr = spec.get(key)
                if expr:
                    referenced.update(name for name in collect_names(str(expr)) if name in registered)
    return referenced


def resolve_params(
    context: Mapping[str, Any],
    rules: MappingRules,
    *,
    allow_fallback: bool = True,
    allow_defaults: bool = False,
) -> ResolvedParams:
    """按覆盖链解析出全部槽位值（格式化）+ 来源。

    allow_defaults=True 时（**仅「无杆塔测试」使用**）：
    把规则链上的 ``defaults``（全局 → 塔型 → 细分）合并进上下文，**只补为 None 的键**，
    并记入 ``defaults_applied``。生产路径保持 False —— 行为与改动前逐字节一致。

    参数注册表（rules.definitions）：按槽位引用惰性求值；只有被 expr/param 引用的
    定义才解析（避免未引用的失败定义破坏整条链路），失败显式抛 DefinitionError。
    """
    canonical = normalize_tower_kind(context.get("tower_type"), rules)
    ctx = dict(context)
    ctx["tower_type"] = canonical

    base_rule, effective_kind, chain = _resolve_rule_for(rules, canonical, allow_fallback=allow_fallback)
    result = ResolvedParams(chain=list(chain), tower_kind=effective_kind)

    variables: dict[str, Any] = dict(ctx)
    raw_values: dict[str, Any] = {}

    # 注册表参数：只解析被引用的（expr 引用注册表 code 或 param 键）
    if rules.definitions:
        requested = _collect_requested_params(rules)
        if requested:
            resolved_params = resolve_definitions(
                definitions=rules.definitions,
                context=ctx,
                requested=requested,
            )
            # 注册表只补 ctx 里缺失（None）的键；ctx 已有值保持原值（种子=现状镜像，零回归）
            for code in requested:
                if ctx.get(code) is None and code in resolved_params:
                    variables[code] = resolved_params[code]

    if allow_defaults:
        defaults = _collect_defaults(rules, base_rule, ctx, effective_kind)
        for key, value in defaults.items():
            if variables.get(key) is None:
                variables[key] = value
                result.defaults_applied.append(key)
        result.defaults_applied.sort()

    def apply_slots(rule: Rule | None, source_label: str, *, replace: bool) -> None:
        if replace:
            result.values.clear()
            result.sources.clear()
            raw_values.clear()
        if rule is None:
            return
        for slot, spec in rule.slots.items():
            if not bool(spec.get("enabled", True)):
                result.values[slot] = "1."
                result.sources[slot] = f"{source_label}：本级关闭"
                raw_values.pop(slot, None)
                continue
            when = spec.get("when")
            if when and not _truthy(evaluate(str(when), {**variables, **raw_values})):
                if "else" in spec:
                    result.values[slot] = str(spec["else"])
                    result.sources[slot] = f"{source_label}（else）"
                continue
            if "value" in spec:  # 字面量槽位（如波形种类开关 1./0.）
                result.values[slot] = str(spec["value"])
                result.sources[slot] = source_label
                raw_values.pop(slot, None)
                continue
            param_code = spec.get("param")
            if param_code:  # 注册表参数引用（page 参数管理定义的 code）
                code = str(param_code)
                if code not in variables:
                    raise DefinitionError(f"{slot}: 注册表参数 {code} 未解析到（未定义或被停用）")
                raw = variables[code]
                if raw is None:
                    result.values[slot] = format_value(None, int(spec.get("fmt", 2)))
                    result.unresolved[slot] = [code]
                    result.sources[slot] = f"{source_label}（注册表参数 {code} 缺值→{result.values[slot]}）"
                    raw_values[slot] = None
                    continue
                raw_values[slot] = raw
                result.values[slot] = format_value(raw, int(spec.get("fmt", 2)))
                result.sources[slot] = source_label
                continue
            expression = str(spec["expr"])
            scope = {**variables, **raw_values}
            raw = evaluate(expression, scope)
            if raw is None:
                # 取不到值：优先用 default；无 default 时保持 C# 一致的 "1." 占位（生产行为不变），
                # 但把「缺哪些源变量」记进诊断，供测试层拒绝静默计算。
                missing = sorted(
                    name for name in collect_names(expression) if scope.get(name) is None
                )
                if "default" in spec:
                    fallback = spec["default"]
                    result.values[slot] = str(fallback)
                    result.defaults_used[slot] = str(fallback)
                    result.sources[slot] = f"{source_label}（默认值）"
                    raw_values[slot] = _to_number_or_none(fallback)
                    continue
                result.values[slot] = format_value(None, int(spec.get("fmt", 2)))
                result.unresolved[slot] = missing
                result.sources[slot] = f"{source_label}（缺 {'/'.join(missing) or '上下文'}→{result.values[slot]}）"
                raw_values[slot] = None
                continue
            raw_values[slot] = raw
            result.values[slot] = format_value(raw, int(spec.get("fmt", 2)))
            result.sources[slot] = source_label

    # L0 全局
    apply_slots(Rule(name="全局参数", slots=rules.globals), "全局参数", replace=False)

    # L2 塔型默认
    if base_rule is not None:
        apply_slots(base_rule, effective_kind, replace=(base_rule.mode == "replace"))

    # L3+ 细分规则（电压/回路/场景/避雷器等），粗 → 细
    for rule in _matching_voltage_rules(rules, ctx, effective_kind):
        result.chain.append(rule.name)
        apply_slots(rule, rule.name, replace=(rule.mode == "replace"))

    return result


def _truthy(value: Any) -> bool:
    return bool(value)


def _to_number_or_none(value: Any) -> Any:
    """默认值转数值（供下游槽位引用）；转不了就原样返回（字符串默认值）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return value


# --------------------------------------------------------------------------------------
# 上下文构建（与 fl_analysis_external 现有取值逐条一致）
# --------------------------------------------------------------------------------------

def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def build_context(
    *,
    base_tower: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    execution_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """抽取源变量（与 compute_csharp_atp_params 的取值链路一致）。"""
    import math

    base = _obj(base_tower)
    prof = _obj(profile)
    options = _obj(execution_options)

    insul_mm = _f(prof.get("insulator_length_m"))
    insul_m = insul_mm / 1000.0 if (insul_mm and insul_mm > 100) else insul_mm
    shield_h = _f(prof.get("shield_wire_height_m"))

    current_ka = _f(options.get("binary_search_current_ka")) or _f(prof.get("current_a")) or 0.0

    head_raw = _f(prof.get("current_head_time_ms"))
    if head_raw is None:
        head_us = _f(prof.get("current_head_time_us"))
        # ⚠️ 2026-09-13 修复：profile 缺波头/波尾时（63 列导入格式无这两列 → 恒 None），
        # 回退到任务级执行选项（页面「波头时间/μs」= head_time_min_us）。此前恒用 2.6/50 默认，
        # 导致用户在任务里设 2/40 也无效、渲染出来的 REAA/REBB 与 C# 不一致。
        if head_us is None:
            head_us = _f(options.get("head_time_min_us"))
        head_ms = head_us if head_us is not None else 2.6
    else:
        head_ms = head_raw
    tail_raw = _f(prof.get("current_tail_time_ms"))
    if tail_raw is None:
        tail_us = _f(prof.get("current_tail_time_us"))
        if tail_us is None:
            tail_us = _f(options.get("tail_time_min_us"))
        tail_ms = tail_us if tail_us is not None else 50.0
    else:
        tail_ms = tail_raw

    ground_r = _f(base.get("ground_resistance_ohm"))

    cg = _obj(base.get("circuit_geometry_json"))
    lightning_wire = _obj(cg.get("lightning_wire"))
    mid_l = _f(lightning_wire.get("left_mid_distance_m"))
    mid_r = _f(lightning_wire.get("right_mid_distance_m"))
    if mid_l is None:
        mid_l = _f(cg.get("left_mid_distance_m"))
    if mid_r is None:
        mid_r = _f(cg.get("right_mid_distance_m"))
    profile_geometry = _obj(prof.get("geometry_layers_json"))
    profile_lw = _obj(profile_geometry.get("lightning_wire"))
    if mid_l is None:
        mid_l = _f(profile_lw.get("left_mid_distance_m"))
    if mid_r is None:
        mid_r = _f(profile_lw.get("right_mid_distance_m"))

    tower_h = _f(cg.get("tower_height_m")) or _f(prof.get("call_height_m"))

    geometry = _obj(prof.get("geometry_layers_json"))
    # ⚠️ 2026-09-20 修复：按「回路相序」把台账 A/B/C 三列重排为物理上/中/下
    # （与 fl_analysis_external.compute_csharp_atp_params 同一口径，见 atp_phase_sequence）
    from .atp_phase_sequence import permute_circuit_geometry

    geometry = permute_circuit_geometry(geometry, prof)
    layer_i = _obj(geometry.get("I"))
    ph = _obj(layer_i.get("phase_height_m"))
    spacing = _obj(layer_i.get("phase_spacing_m"))
    left_h = _f(ph.get("upper"))
    mid_h = _f(ph.get("middle"))
    right_h = _f(ph.get("lower"))
    left_spacing = _f(spacing.get("upper"))
    right_spacing = _f(spacing.get("lower"))
    mid_spacing = _f(spacing.get("middle"))

    voltage = _f(base.get("line_voltage_kv")) or 500.0

    # ganzi 分支的保护角回退（仅该分支使用）
    angle_l = _f(prof.get("protection_angle_left_deg"))
    angle_r = _f(prof.get("protection_angle_right_deg"))
    lw_l_eff = mid_l
    lw_r_eff = mid_r
    if lw_l_eff is None and angle_l is not None and shield_h:
        lw_l_eff = shield_h * math.tan(math.radians(angle_l))
    if lw_r_eff is None and angle_r is not None and shield_h:
        lw_r_eff = shield_h * math.tan(math.radians(angle_r))

    wf = int(_f(prof.get("current_type")) or 1)

    context: dict[str, Any] = {
        "ground_r": ground_r,
        "voltage_level": voltage,  # 维度匹配用（与 voltage 同值）
        "insul_m": insul_m,
        "shield_h": shield_h,
        "tower_h": tower_h,
        "voltage": voltage,
        "current_ka": current_ka,
        "head_ms": head_ms,
        "tail_ms": tail_ms,
        "wave_type": wf,
        "lw_l": mid_l,
        "lw_r": mid_r,
        "lw_l_eff": lw_l_eff,
        "lw_r_eff": lw_r_eff,
        "h_u": left_h,
        "h_m": mid_h,
        "h_l": right_h,
        "sp_u": left_spacing,
        "sp_m": mid_spacing,
        "sp_l": right_spacing,
        "tower_type": (
            options.get("tower_kind")
            or prof.get("tower_kind")
            or base.get("tower_type")
            or "ganzi"
        ),
    }
    # 四回路（sihui）：I/II/III/IV 回上中下相高与中距
    for idx, cid in enumerate(("c1", "c2", "c3", "c4")):
        layer = _obj(geometry.get(("I", "II", "III", "IV")[idx]))
        layer_ph = _obj(layer.get("phase_height_m"))
        layer_sp = _obj(layer.get("phase_spacing_m"))
        context[f"{cid}_u"] = _f(layer_ph.get("upper"))
        context[f"{cid}_m"] = _f(layer_ph.get("middle"))
        context[f"{cid}_l"] = _f(layer_ph.get("lower"))
        context[f"{cid}_sp_u"] = _f(layer_sp.get("upper"))
        context[f"{cid}_sp_m"] = _f(layer_sp.get("middle"))
        context[f"{cid}_sp_l"] = _f(layer_sp.get("lower"))
    # 回路数量（维度匹配用）：有相高数据的回路条数
    context["circuit_count"] = sum(
        1
        for cid in ("c1", "c2", "c3", "c4")
        if any(context.get(f"{cid}_{key}") is not None for key in ("u", "m", "l"))
    )
    return context


def compute_params_from_config(
    *,
    base_tower: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    execution_options: Mapping[str, Any] | None = None,
    rules: MappingRules | None = None,
    allow_fallback: bool = True,
) -> dict[str, str]:
    """配置路径的等价入口（供 golden 对照与后续切换使用）。"""
    return compute_params_detailed(
        base_tower=base_tower,
        profile=profile,
        execution_options=execution_options,
        rules=rules,
        allow_fallback=allow_fallback,
    ).as_dict()


def compute_params_detailed(
    *,
    base_tower: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    execution_options: Mapping[str, Any] | None = None,
    rules: MappingRules | None = None,
    allow_fallback: bool = True,
    allow_defaults: bool = False,
) -> ResolvedParams:
    """同 compute_params_from_config，但返回带诊断（defaults_used / unresolved / chain）的结果。

    allow_defaults=True（**仅「无杆塔测试」**）：用规则链上的 defaults 补全缺失上下文。
    """
    active = rules or load_mappings()
    context = build_context(base_tower=base_tower, profile=profile, execution_options=execution_options)
    return resolve_params(
        context, active, allow_fallback=allow_fallback, allow_defaults=allow_defaults
    )


__all__ = [
    "DIMENSION_KEYS",
    "MAPPINGS_DIR",
    "MappingConfigError",
    "MappingRules",
    "ResolvedParams",
    "Rule",
    "build_context",
    "globals_from_rows",
    "compute_params_from_config",
    "compute_params_detailed",
    "load_mappings",
    "load_mappings_from_rows",
    "normalize_tower_kind",
    "resolve_params",
    "DslError",
    "parse_expression",
]
