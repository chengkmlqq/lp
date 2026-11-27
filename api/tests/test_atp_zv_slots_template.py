"""ZV 改造四变量槽位：从代码基线（_common.json globals）迁到参数模板规则。

锁定四条不变量：
1. 四槽位不再出现在 globals，而是落在一条「无维度 = 通配」的模板规则里（页面可见可改，
   且覆盖检测按 atp_param_template 计数时不再报 missing）；
2. 未注入时用槽位 ``default`` 兜底 150 / 200 / 1350 / 2.5E8；
3. 注入时取注入值（正数才生效，与 atp_zv_params 同一口径）；
4. 与代码路径（compute_csharp_atp_params）逐字节一致 —— 非 ZV 塔型行为不变。
"""

from __future__ import annotations

import os

os.environ.setdefault("ATP_MAPPING_MODE", "code")

from datetime import datetime, timezone  # noqa: E402

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.models.atp_asset import AtpAssetRun, AtpAssetVersion  # noqa: E402
from app.models.atp_param_template import AtpParamGlobal, AtpParamTemplate  # noqa: E402
from app.services.atp_asset_service import check_asset_slot_coverage  # noqa: E402
from app.services.atp_param_resolver import (  # noqa: E402
    build_context,
    compute_params_from_config,
    load_mappings,
    resolve_params,
)
from app.services.fl_analysis_external import compute_csharp_atp_params  # noqa: E402

ZV_SLOTS = ("ZRE01_", "ZRE02_", "ZRE03_", "VRE___")


def _base_profile(kind: str = "shangzi", voltage: int = 66):
    base_tower = {
        "tower_type": kind,
        "line_voltage_kv": voltage,
        "ground_resistance_ohm": 12.5,
        "circuit_geometry_json": {"tower_height_m": 42.0},
    }
    profile = {
        "tower_kind": kind,
        "shield_wire_height_m": 43.5,
        "insulator_length_m": 5945,
        "call_height_m": 42.0,
        "current_a": 25.0,
        "current_type": 1,
        "geometry_layers_json": {
            "I": {
                "phase_height_m": {"upper": 65.5, "middle": 53.0, "lower": 42.0},
                "phase_spacing_m": {"upper": 12.0, "middle": 12.0, "lower": 12.0},
            },
        },
    }
    options = {"binary_search_current_ka": 25.0, "tower_kind": kind}
    return base_tower, profile, options


# ─────────────────── ① 迁移位置：globals → 通配模板规则 ───────────────────


def test_zv_slots_moved_out_of_globals_into_wildcard_rule() -> None:
    rules = load_mappings()
    for slot in ZV_SLOTS:
        assert slot not in rules.globals, f"{slot} 不应再写在 _common.json globals"

    owners = [
        rule
        for rule in rules.voltage_rules
        if any(slot in rule.slots for slot in ZV_SLOTS)
    ]
    assert len(owners) == 1, f"应有且仅有一条模板规则承载 ZV 四槽位，实际 {len(owners)}"
    rule = owners[0]
    assert rule.dimensions == {}, "ZV 槽位对所有塔型/电压生效 → 规则必须无维度（通配）"
    assert set(rule.slots) == set(ZV_SLOTS)
    assert rule.slots["ZRE01_"]["default"] == "150."
    assert rule.slots["ZRE02_"]["default"] == "200."
    assert rule.slots["ZRE03_"]["default"] == "1350."
    assert rule.slots["VRE___"]["default"] == "250000000."


# ─────────────────── ② 未注入 → default 兜底 ───────────────────


def test_uninjected_uses_slot_defaults() -> None:
    rules = load_mappings()
    for kind, voltage in (("shangzi", 66), ("ganzi", 500), ("sihuita", 220)):
        base_tower, profile, options = _base_profile(kind, voltage)
        resolved = resolve_params(build_context(base_tower=base_tower, profile=profile, execution_options=options), rules)
        assert resolved.values["ZRE01_"] == "150."
        assert resolved.values["ZRE02_"] == "200."
        assert resolved.values["ZRE03_"] == "1350."
        assert resolved.values["VRE___"] == "250000000."
        assert set(resolved.defaults_used) >= set(ZV_SLOTS)


# ─────────────────── ③ 注入 → 取注入值 ───────────────────


def test_injected_values_win_over_defaults() -> None:
    rules = load_mappings()
    base_tower, profile, options = _base_profile()
    profile["extra_profile_json"] = {
        "zv_params": {"wave_speed_m_s": 2.4e8, "z_1": 160.5, "z_2": 210.0, "z_3": 1400.0}
    }
    resolved = resolve_params(build_context(base_tower=base_tower, profile=profile, execution_options=options), rules)
    assert resolved.values["ZRE01_"] == "160.5"
    assert resolved.values["ZRE02_"] == "210."
    assert resolved.values["ZRE03_"] == "1400."
    assert resolved.values["VRE___"] == "240000000."
    assert resolved.defaults_used == {}


def test_partial_injection_falls_back_per_slot() -> None:
    rules = load_mappings()
    base_tower, profile, options = _base_profile()
    profile["extra_profile_json"] = {"zv_params": {"z_2": 222.0}}
    resolved = resolve_params(build_context(base_tower=base_tower, profile=profile, execution_options=options), rules)
    assert resolved.values["ZRE01_"] == "150."
    assert resolved.values["ZRE02_"] == "222."
    assert resolved.values["VRE___"] == "250000000."


# ─────────────────── ④ 与代码路径逐字节一致 ───────────────────


def test_config_path_matches_code_path_for_zv_and_non_zv() -> None:
    rules = load_mappings()
    for kind, voltage in (("shangzi", 66), ("ganzi", 500), ("maotou", 1000), ("zhiliu", 500)):
        base_tower, profile, options = _base_profile(kind, voltage)
        code = compute_csharp_atp_params(base_tower=base_tower, profile=profile, execution_options=options)
        cfg = compute_params_from_config(base_tower=base_tower, profile=profile, execution_options=options, rules=rules)
        for slot in ZV_SLOTS:
            assert cfg[slot] == code[slot], f"{kind} {slot}: 代码={code[slot]} 配置={cfg[slot]}"

        profile["extra_profile_json"] = {"zv_params": {"z_1": 151.5, "wave_speed_m_s": 2.4e8}}
        code = compute_csharp_atp_params(base_tower=base_tower, profile=profile, execution_options=options)
        cfg = compute_params_from_config(base_tower=base_tower, profile=profile, execution_options=options, rules=rules)
        for slot in ZV_SLOTS:
            assert cfg[slot] == code[slot], f"{kind}(注入) {slot}: 代码={code[slot]} 配置={cfg[slot]}"


# ─────────────────── ⑤ 覆盖检测：ZV 槽位不再 missing ───────────────────


def _session_with_tables() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            AtpAssetVersion.__table__,
            AtpAssetRun.__table__,
            AtpParamTemplate.__table__,
            AtpParamGlobal.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)()


def _add_asset(db: Session, *, slots: list[str], tower_type: str | None) -> str:
    asset = AtpAssetVersion(
        id="a" * 32,
        code="zv-model-v1",
        name="ATP66-shangzi-raoji2-M123-v2",
        status="enabled",
        voltage_level="66",
        tower_type=tower_type,
        version="v1",
        is_active=True,
        is_published=False,
        shield_wire="with",
        slots_json={"work_atp": {"slots": {name: {"line": "x"} for name in slots}}},
    )
    db.add(asset)
    db.commit()
    return asset.id


def _template_row(**kwargs) -> AtpParamTemplate:
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    return AtpParamTemplate(created_at=now, updated_at=now, **kwargs)


def test_coverage_counts_zv_slots_from_template_rule() -> None:
    rules = load_mappings()
    zv_rule = next(r for r in rules.voltage_rules if any(s in r.slots for s in ZV_SLOTS))

    db = _session_with_tables()
    try:
        model_slots = ["RELE01", "RELE02", *ZV_SLOTS, "UNMAPPED_SLOT"]
        asset_id = _add_asset(db, slots=model_slots, tower_type=None)
        # 通配模板行（seed 后 atp_param_template 里的形态）：tower_type 全空 → 匹配所有资产
        db.add(
            _template_row(
                id="zv-row",
                name=zv_rule.name,
                marker="zv_tower_params",
                priority=zv_rule.priority,
                mode=zv_rule.mode,
                enabled=True,
                slots_json=zv_rule.slots,
                defaults_json={},
            )
        )
        # 塔型模板：提供 RELE01/RELE02
        db.add(
            _template_row(
                id="shangzi-row",
                name="上字型",
                marker="shangzi",
                tower_type="shangzi",
                priority=100,
                mode="merge",
                enabled=True,
                slots_json={"RELE01": {"expr": "h_u", "fmt": 2}, "RELE02": {"expr": "h_u * 1.5", "fmt": 2}},
                defaults_json={},
            )
        )
        db.commit()

        result = check_asset_slot_coverage(db, asset_id=asset_id)
        assert result["missing"] == ["UNMAPPED_SLOT"]
        for slot in ZV_SLOTS:
            assert slot in result["covered"], f"{slot} 应计入已覆盖：{result}"
            assert slot in result["template_slots"]
    finally:
        db.close()


def test_coverage_without_zv_rule_still_reports_missing() -> None:
    """反证：模板里没有 ZV 四槽位时，覆盖检测确实会报 missing（说明上面的修复来自模板数据）。"""
    db = _session_with_tables()
    try:
        asset_id = _add_asset(db, slots=list(ZV_SLOTS) + ["RELE01"], tower_type=None)
        db.add(
            _template_row(
                id="shangzi-row",
                name="上字型",
                marker="shangzi",
                tower_type="shangzi",
                priority=100,
                mode="merge",
                enabled=True,
                slots_json={"RELE01": {"expr": "h_u", "fmt": 2}},
                defaults_json={},
            )
        )
        db.commit()
        result = check_asset_slot_coverage(db, asset_id=asset_id)
        assert set(ZV_SLOTS).issubset(set(result["missing"]))
    finally:
        db.close()


# ─────────────────── ⑥ seed 落库形态（DB 路径）与 JSON 基线等价 ───────────────────


def _seed_rows_from_json() -> list[dict]:
    """按 scripts/seed_atp_templates.py 的口径把映射 JSON 变成 atp_param_template 行。"""
    import json

    from app.services.atp_param_resolver import MAPPINGS_DIR

    rows: list[dict] = []
    for path in sorted(MAPPINGS_DIR.glob("*.json")):
        if path.name == "_common.json":
            continue
        cfg = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "name": cfg.get("name") or path.stem,
                "marker": cfg.get("marker") or cfg.get("tower_type") or path.stem,
                "tower_type": cfg.get("tower_type"),
                "voltage_level": str(cfg["voltage_level"]) if cfg.get("voltage_level") is not None else None,
                "priority": int(cfg.get("priority", 100)),
                "mode": cfg.get("mode") or "merge",
                "enabled": True,
                "fallback_to": cfg.get("fallback_to"),
                "fallback_enabled": bool(cfg.get("fallback_enabled", True)),
                "slots_json": cfg.get("slots") or {},
                "defaults_json": cfg.get("defaults") or {},
            }
        )
    return rows


def test_db_seeded_rules_resolve_like_json_baseline() -> None:
    from app.services.atp_param_resolver import load_mappings_from_rows

    rules_json = load_mappings()
    rules_db = load_mappings_from_rows(_seed_rows_from_json())
    rules_db.definitions = rules_json.definitions  # 与运行时 _load_from_db 一致

    zv_owner = [r for r in rules_db.voltage_rules if any(s in r.slots for s in ZV_SLOTS)]
    assert len(zv_owner) == 1 and zv_owner[0].dimensions == {}

    for kind, voltage in (("shangzi", 66), ("ganzi", 500), ("maotou", 1000), ("menxing", 220)):
        base_tower, profile, options = _base_profile(kind, voltage)
        ctx = build_context(base_tower=base_tower, profile=profile, execution_options=options)
        from_json = resolve_params(ctx, rules_json)
        from_db = resolve_params(ctx, rules_db)
        assert from_json.values == from_db.values, f"{kind} DB 路径与 JSON 基线不一致"
        assert from_db.values["ZRE01_"] == "150."
        assert from_db.values["ZRE02_"] == "200."
        assert from_db.values["ZRE03_"] == "1350."
        assert from_db.values["VRE___"] == "250000000."
