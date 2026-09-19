"""ATP 参数模板：槽位 ``default`` 兜底 + 缺失上下文诊断（「无杆塔测试」的底座）。

背景：没有杆塔上下文时表达式会算出 None，原实现统一退化成 ``"1."``（对齐 C#
``FeatureSetOfATP.SetFeatureValue``，保证 ATP 数值带小数点）。这对「无杆塔测试」是**静默错误** ——
测试必须能知道「哪些槽位用了默认值 / 哪些槽位其实根本没算出来」。

因此：
- 槽位新增可选 ``default``：表达式取不到值时用它（并记入 ``defaults_used``）
- 没写 ``default`` 时**生产行为不变**（仍是 ``"1."``），但把缺的源变量记入 ``unresolved``

注意：DSL 对**完全不存在**的变量名会抛 ``DslError``；生产路径（含无杆塔场景）都由
``build_context`` 产出**全键存在、值可为 None** 的上下文，所以这里也用 ``build_context``。
"""

from __future__ import annotations

import pytest

from app.services.atp_param_resolver import (
    MappingConfigError,
    MappingRules,
    Rule,
    _validate_slots,
    build_context,
    resolve_params,
)


def _rules(*, slots: dict, globals_slots: dict | None = None) -> MappingRules:
    return MappingRules(
        rules={"maotou": Rule(name="maotou", dimensions={"tower_type": "maotou"}, slots=slots)},
        globals=globals_slots or {},
        exact_canonical=["maotou", "ganzi"],
        marker_order=["maotou", "ganzi"],
        default_marker="ganzi",
        voltage_rules=[],
    )


def _no_tower_context(**overrides) -> dict:
    """「无杆塔」上下文：所有源变量存在但为 None（= 真实的无杆塔测试场景）。"""
    context = build_context(
        base_tower={},
        profile={},
        execution_options={"tower_kind": "maotou"},
    )
    context.update(overrides)
    return context


# ─────────────────── ① default 兜底 ───────────────────


def test_slot_default_used_when_context_missing() -> None:
    rules = _rules(slots={"RELE01": {"expr": "h_u", "default": 30.0, "fmt": 2}})
    result = resolve_params(_no_tower_context(), rules)

    assert result.values["RELE01"] == "30.0"
    assert result.defaults_used["RELE01"] == "30.0"
    assert result.unresolved == {}
    assert "默认值" in result.sources["RELE01"]


def test_slot_default_feeds_downstream_slots() -> None:
    """用默认值的槽位，下游引用它时应拿到数值（而不是 None）。"""
    rules = _rules(
        slots={
            "RELE01": {"expr": "h_u", "default": 30.0},
            "RELE02": {"expr": "RELE01 * 2"},
        }
    )
    result = resolve_params(_no_tower_context(), rules)

    assert result.values["RELE01"] == "30.0"
    assert result.values["RELE02"] == "60."
    assert result.unresolved == {}


def test_context_present_ignores_default() -> None:
    rules = _rules(slots={"RELE01": {"expr": "h_u", "default": 30.0, "fmt": 2}})
    result = resolve_params(_no_tower_context(h_u=42.0), rules)

    assert result.values["RELE01"] == "42."  # 表达式优先，default 不生效
    assert result.defaults_used == {}
    assert result.unresolved == {}


# ─────────────────── ② 无 default：行为不变 + 诊断 ───────────────────


def test_slot_without_default_keeps_placeholder_and_reports_missing() -> None:
    rules = _rules(slots={"RELE01": {"expr": "h_u", "fmt": 2}})
    result = resolve_params(_no_tower_context(), rules)

    # 生产行为不变：仍是 C# 对齐的 "1." 占位
    assert result.values["RELE01"] == "1."
    # 但必须能诊断出「它其实没算出来」，缺的是哪个变量
    assert result.unresolved["RELE01"] == ["h_u"]
    assert result.defaults_used == {}
    assert "h_u" in result.sources["RELE01"]


def test_missing_report_lists_all_referenced_vars() -> None:
    rules = _rules(slots={"RELE05": {"expr": "clamp(abs(h_m - h_u), 1.5)"}})
    result = resolve_params(_no_tower_context(), rules)

    assert result.unresolved["RELE05"] == ["h_m", "h_u"]


# ─────────────────── ③ 配置校验 ───────────────────


def test_validate_slots_accepts_valid_default() -> None:
    _validate_slots("t", {"A": {"expr": "h_u", "default": 1.5}})
    _validate_slots("t", {"A": {"value": "1.", "default": "1."}})


def test_validate_slots_rejects_bad_default() -> None:
    with pytest.raises(MappingConfigError):
        _validate_slots("t", {"A": {"expr": "h_u", "default": True}})
    with pytest.raises(MappingConfigError):
        _validate_slots("t", {"A": {"expr": "h_u", "default": [1, 2]}})


def test_default_alone_is_not_a_value() -> None:
    """default 是兜底，不是取值来源 —— 槽位仍必须给 expr 或 value。"""
    with pytest.raises(MappingConfigError):
        _validate_slots("t", {"A": {"default": 1.5}})


# ─────────────────── ④ 模板默认上下文变量（无杆塔测试）───────────────────


def _rules_with_defaults(**defaults) -> MappingRules:
    return MappingRules(
        rules={
            "maotou": Rule(
                name="maotou",
                dimensions={"tower_type": "maotou"},
                slots={"RELE01": {"expr": "h_u", "fmt": 2}},
                defaults=defaults,
            )
        },
        exact_canonical=["maotou", "ganzi"],
        marker_order=["maotou", "ganzi"],
        default_marker="ganzi",
        voltage_rules=[],
    )


def test_defaults_fill_missing_context_only_when_allowed() -> None:
    rules = _rules_with_defaults(h_u=30.0)

    # 生产路径（allow_defaults 默认 False）→ 与改动前一致："1." + 诊断
    plain = resolve_params(_no_tower_context(), rules)
    assert plain.values["RELE01"] == "1."
    assert plain.unresolved["RELE01"] == ["h_u"]
    assert plain.defaults_applied == []

    # 测试路径 → 用模板默认值补全（上下文变量有了值 → 表达式正常求值 → C# 风格格式化）
    filled = resolve_params(_no_tower_context(), rules, allow_defaults=True)
    assert filled.values["RELE01"] == "30."
    assert filled.unresolved == {}
    assert filled.defaults_applied == ["h_u"]
    assert filled.defaults_used == {}  # 槽位级 default 未被用到（走的是上下文默认值）


def test_defaults_do_not_override_real_context() -> None:
    rules = _rules_with_defaults(h_u=30.0)
    result = resolve_params(_no_tower_context(h_u=42.0), rules, allow_defaults=True)

    assert result.values["RELE01"] == "42."  # 真实上下文优先
    assert result.defaults_applied == []


def test_repo_defaults_cover_pilot_tower_families() -> None:
    """真实映射数据回归：_common.json 的 defaults 能让 pilot 塔型「无杆塔」解析出完整参数。

    sihuita（四回路）暂未提供 c1_*..c4_* 默认值 → 必须仍有 unresolved（测试层据此拒绝执行）。
    """
    from app.services.atp_param_resolver import load_mappings

    rules = load_mappings()
    assert rules.defaults.get("h_u") is not None, "_common.json 应带测试默认参数集"

    for kind in ("maotou", "jiubei", "ganzi", "shangzi", "menxing", "guxing"):
        context = build_context(
            base_tower={"tower_type": kind, "line_voltage_kv": 220},
            profile={},
            execution_options={"tower_kind": kind, "line_voltage_kv": 220, "binary_search_current_ka": 31.0},
        )
        result = resolve_params(context, rules, allow_defaults=True)
        assert result.unresolved == {}, f"{kind} 应能无杆塔解析：{list(result.unresolved.items())[:3]}"
        assert result.defaults_applied, f"{kind} 应记录用到的默认上下文变量"
        assert result.values.get("RER001") == "10."
        assert result.values.get("REIGAN____") == "31."

    context = build_context(
        base_tower={"tower_type": "sihuita", "line_voltage_kv": 500},
        profile={},
        execution_options={"tower_kind": "sihuita", "line_voltage_kv": 500},
    )
    sihuita = resolve_params(context, rules, allow_defaults=True)
    assert sihuita.unresolved, "sihuita 缺四回路默认值 → 必须报告未解析槽位（禁止静默）"
