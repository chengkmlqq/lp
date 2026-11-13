"""ATP 测试线路（单塔基准）服务测试（离线，不需要 wine / ATP 引擎）。

覆盖：
1. 装配器 parity —— 真实杆塔与测试线路两条路径输出**字段集完全一致**（防口径漂移）
2. 几何硬约束校验 —— 缺避雷线中距 / 四回几何重合 / 档距越界 / 绝缘子按毫米误填
3. 三级解析 —— 模型级绑定 → 几何维 → 降级 → 无命中
4. 快照 —— 稳定（同输入同 hash）、编辑后变化、执行期优先用冻结快照
5. 派生 —— 干跑返回逐字段来源；关键几何缺失时给 blockers
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAssetVersion, AtpAssetRun
from app.models.atp_test_line import AtpTestLine, AtpTestLineCircuit
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.tower_model import TowerModel
from app.services import atp_line_snapshot as snapshot_asm
from app.services import atp_test_line_service as service
from app.schemas.atp_test_line import (
    AtpTestLineCircuitPayload,
    AtpTestLineCreateRequest,
    AtpTestLineDeriveRequest,
    AtpTestLineUpdateRequest,
)
from app.services.atp_test_line_service import (
    SRC_BUILTIN,
    SRC_TEMPLATE,
    assemble_payload_from_test_line,
    create_test_line,
    derive_test_line,
    resolve_test_line,
    update_test_line,
    validate_draft,
)


def _build_sessionmaker():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            DimensionType.__table__,
            DimensionItem.__table__,
            TowerModel.__table__,
            AtpAssetVersion.__table__,
            AtpAssetRun.__table__,
            AtpTestLine.__table__,
            AtpTestLineCircuit.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session() -> Session:
    maker = _build_sessionmaker()
    db = maker()
    try:
        yield db
    finally:
        db.close()


# ───────────────────────── 夹具 ─────────────────────────


def _fake_tower() -> SimpleNamespace:
    """最小可用的「真实杆塔」替身（字段与 LineTower/TowerProfile 同构）。"""
    return SimpleNamespace(
        id="tower-1",
        line_id="line-1",
        seq_no=12,
        tower_no="N12",
        tower_model="guxing-450",
        tower_type="guxing",
        longitude=110.1,
        latitude=30.2,
        altitude_m=320.0,
        terrain="山地",
        ground_resistance_ohm=7.5,
        lightning_density=2.4,
        span_small_m=320.0,
        span_large_m=460.0,
        slope_1=8.0,
        slope_2=6.0,
        risk_level="low",
        raw_extra_json={"source": "import"},
        circuits=[
            SimpleNamespace(
                circuit_no=1,
                spacing_upper_m=12.0,
                spacing_middle_m=12.0,
                spacing_lower_m=12.0,
                height_upper_m=60.0,
                height_middle_m=48.0,
                height_lower_m=36.0,
            ),
            SimpleNamespace(
                circuit_no=2,
                spacing_upper_m=14.0,
                spacing_middle_m=13.0,
                spacing_lower_m=12.0,
                height_upper_m=58.0,
                height_middle_m=46.0,
                height_lower_m=34.0,
            ),
        ],
        lightning_result=None,
        analysis=None,
        profile=SimpleNamespace(
            phase_sequence_1="ABC",
            phase_sequence_2="ACB",
            phase_sequence_3=None,
            phase_sequence_4=None,
            arrester_a="1",
            arrester_b="0",
            arrester_c="",
            protection_angle_left_deg=-14.0,
            protection_angle_right_deg=-14.0,
            shield_wire_height_m=73.0,
            insulator_length_m=4450.0,
            call_height_m=45.0,
            angle_deg=5.0,
            current_a=31.0,
            current_b=None,
            structure_kind="直线",
            stroke_mode="fanji",
            current_type="1",
            current_head_time_us=2.6,
            current_tail_time_us=50.0,
            extra_profile_json={
                "lightning_wire": {"left_mid_distance_m": 9.6, "right_mid_distance_m": 9.6}
            },
        ),
    )


def _fake_line() -> SimpleNamespace:
    return SimpleNamespace(
        name="500kV 测试线",
        voltage_kv=500,
        phase_sequence_json={"I": "ABC"},
        arrester_install_json={"A": True},
        lightning_param_json={"density": 2.4},
    )


def _test_line_entity() -> AtpTestLine:
    """未持久化的测试线路实体（属性与 _fake_tower 同值，用于 parity 断言）。"""
    row = AtpTestLine(
        id="tl-1",
        code="TL-500-guxing-with",
        name="500kV 测试线",
        description="",
        status="enabled",
        voltage_level="500",
        tower_type="guxing",
        shield_wire="with",
        circuit_count=2,
        span_small_m=320.0,
        span_large_m=460.0,
        ground_resistance_ohm=7.5,
        lightning_density=2.4,
        altitude_m=320.0,
        terrain="山地",
        slope_1=8.0,
        slope_2=6.0,
        tower_no="N12",
        tower_model="guxing-450",
        call_height_m=45.0,
        insulator_length_m=4.45,
        shield_wire_height_m=73.0,
        shield_wire_left_mid_m=9.6,
        shield_wire_right_mid_m=9.6,
        protection_angle_left_deg=-14.0,
        protection_angle_right_deg=-14.0,
        angle_deg=5.0,
        phase_sequence_1="ABC",
        phase_sequence_2="ACB",
        arrester_a="1",
        arrester_b="0",
        arrester_c="",
        current_ka=31.0,
        current_type="1",
        current_head_time_us=2.6,
        current_tail_time_us=50.0,
        structure_kind="直线",
        source_kind="manual",
    )
    row.circuits = [
        AtpTestLineCircuit(
            id="c1",
            test_line_id="tl-1",
            circuit_no=1,
            spacing_upper_m=12.0,
            spacing_middle_m=12.0,
            spacing_lower_m=12.0,
            height_upper_m=60.0,
            height_middle_m=48.0,
            height_lower_m=36.0,
        ),
        AtpTestLineCircuit(
            id="c2",
            test_line_id="tl-1",
            circuit_no=2,
            spacing_upper_m=14.0,
            spacing_middle_m=13.0,
            spacing_lower_m=12.0,
            height_upper_m=58.0,
            height_middle_m=46.0,
            height_lower_m=34.0,
        ),
    ]
    return row


def _create_asset(session: Session, *, code: str = "ATP-500-GUXING", **overrides: Any) -> AtpAssetVersion:
    fields: dict[str, Any] = {
        "code": code,
        "name": "500kV 鼓型 反击 M123",
        "description": "",
        "status": "enabled",
        "voltage_level": "500",
        "tower_type": "guxing",
        "scene_type": "fanji",
        "arrester_config": "M123",
        "shield_wire": "with",
        "is_active": True,
    }
    fields.update(overrides)
    asset = AtpAssetVersion(**fields)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _circuits_payload() -> list[AtpTestLineCircuitPayload]:
    return [
        AtpTestLineCircuitPayload(
            circuit_no=1,
            spacing_upper_m=12.0,
            spacing_middle_m=12.0,
            spacing_lower_m=12.0,
            height_upper_m=60.0,
            height_middle_m=48.0,
            height_lower_m=36.0,
        ),
        AtpTestLineCircuitPayload(
            circuit_no=2,
            spacing_upper_m=14.0,
            spacing_middle_m=13.0,
            spacing_lower_m=12.0,
            height_upper_m=58.0,
            height_middle_m=46.0,
            height_lower_m=34.0,
        ),
    ]


# ───────────────────── 1. 装配器 parity（核心）─────────────────────


def test_assembler_field_sets_identical_between_tower_and_test_line() -> None:
    """两条路径输出的**字段集必须完全一致**——否则基准与生产线结果不可比。"""
    tower_bt, tower_pf = snapshot_asm.assemble_from_line_tower(_fake_tower(), _fake_line())
    line_bt, line_pf = snapshot_asm.assemble_from_test_line(_test_line_entity())

    assert set(tower_bt) == set(line_bt)
    assert set(tower_pf) == set(line_pf)


def test_assembler_geometry_and_lightning_wire_merge() -> None:
    """避雷线中距必须并进 geometry_layers_json（LP-570 口径），且相几何逐回路独立。"""
    _, profile = snapshot_asm.assemble_from_test_line(_test_line_entity())
    geometry = profile["geometry_layers_json"]
    assert geometry["lightning_wire"]["left_mid_distance_m"] == pytest.approx(9.6)
    assert geometry["I"]["phase_spacing_m"]["upper"] == pytest.approx(12.0)
    assert geometry["II"]["phase_spacing_m"]["upper"] == pytest.approx(14.0)

    _, tower_profile = snapshot_asm.assemble_from_line_tower(_fake_tower(), _fake_line())
    assert tower_profile["geometry_layers_json"] == geometry


def test_assembler_insulator_unit_is_metre_for_test_line() -> None:
    """测试线路按米存；真实杆塔按毫米存 —— 两者都要能被下游「>100 视为 mm」正确换算。"""
    _, line_pf = snapshot_asm.assemble_from_test_line(_test_line_entity())
    _, tower_pf = snapshot_asm.assemble_from_line_tower(_fake_tower(), _fake_line())
    assert line_pf["insulator_length_m"] == pytest.approx(4.45)
    assert tower_pf["insulator_length_m"] == pytest.approx(4450.0)


# ───────────────────── 2. 几何硬约束校验 ─────────────────────


def _draft(**overrides: Any) -> dict[str, Any]:
    base = {
        "voltage_level": "500",
        "tower_type": "guxing",
        "shield_wire": "with",
        "circuit_count": 2,
        "span_small_m": 320.0,
        "span_large_m": 460.0,
        "insulator_length_m": 4.45,
        "shield_wire_left_mid_m": 9.6,
        "shield_wire_right_mid_m": 9.6,
    }
    base.update(overrides)
    return base


def test_validate_passes_for_complete_draft() -> None:
    blockers, _warnings = validate_draft(_draft(), _circuits_payload())
    assert blockers == []


def test_validate_blocks_missing_shield_wire_mid() -> None:
    blockers, _ = validate_draft(
        _draft(shield_wire_left_mid_m=None), _circuits_payload()
    )
    assert any(item["field"] == "shield_wire_left_mid_m" for item in blockers)


def test_validate_allows_missing_shield_wire_mid_when_without() -> None:
    blockers, _ = validate_draft(
        _draft(shield_wire="without", shield_wire_left_mid_m=None, shield_wire_right_mid_m=None),
        _circuits_payload(),
    )
    assert not any("shield_wire_left_mid_m" in item["field"] for item in blockers)


def test_validate_blocks_identical_circuit_geometry() -> None:
    """四回几何重合 → LCC 判定导体重合、不产 .pch。"""
    first = _circuits_payload()[0]
    duplicated = [first, first.model_copy(update={"circuit_no": 2})]
    blockers, _ = validate_draft(_draft(), duplicated)
    assert any("导体重合" in item["reason"] for item in blockers)


def test_validate_blocks_millimetre_insulator() -> None:
    blockers, _ = validate_draft(_draft(insulator_length_m=4450.0), _circuits_payload())
    assert any(item["field"] == "insulator_length_m" for item in blockers)


def test_validate_blocks_span_out_of_range() -> None:
    blockers, _ = validate_draft(_draft(span_small_m=5000.0), _circuits_payload())
    assert any(item["field"] == "span_small_m" for item in blockers)


def test_validate_requires_voltage_and_tower_type() -> None:
    blockers, _ = validate_draft(_draft(voltage_level="", tower_type=""), _circuits_payload())
    fields = {item["field"] for item in blockers}
    assert {"voltage_level", "tower_type"} <= fields


# ───────────────────── 3. 创建 / 快照 ─────────────────────


def _create_payload(**overrides: Any) -> AtpTestLineCreateRequest:
    data: dict[str, Any] = {
        "code": "TL-500-guxing-with",
        "name": "500kV 鼓型 单塔基准",
        "voltage_level": "500",
        "tower_type": "guxing",
        "shield_wire": "with",
        "circuit_count": 2,
        "span_small_m": 320.0,
        "span_large_m": 460.0,
        "ground_resistance_ohm": 7.5,
        "lightning_density": 2.4,
        "call_height_m": 45.0,
        "insulator_length_m": 4.45,
        "shield_wire_height_m": 73.0,
        "shield_wire_left_mid_m": 9.6,
        "shield_wire_right_mid_m": 9.6,
        "protection_angle_left_deg": -14.0,
        "protection_angle_right_deg": -14.0,
        "current_ka": 31.0,
        "circuits": _circuits_payload(),
    }
    data.update(overrides)
    return AtpTestLineCreateRequest(**data)


def test_create_builds_frozen_snapshot(session: Session) -> None:
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    assert detail["snapshot_hash"]
    assert detail["snapshot_json"]["assembler"] == "atp_line_snapshot/1"
    # 回路数由几何推导
    assert detail["circuit_count"] == 2
    # 快照里带未消费字段标注（地形/倾角当前不参与几何）
    assert "base_tower.slope_1" in detail["snapshot_json"]["not_consumed"]


def test_snapshot_hash_is_stable_and_changes_after_edit(session: Session) -> None:
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    original_hash = detail["snapshot_hash"]

    # 同一条记录重复重算 → 指纹必须完全一致（确定性的前提）
    row = service.get_test_line_by_id(session, detail["id"])
    assert row is not None
    first = service.rebuild_snapshot(session, row)["snapshot_hash"]
    second = service.rebuild_snapshot(session, row)["snapshot_hash"]
    session.rollback()
    assert first == second == original_hash

    updated = update_test_line(
        session,
        test_line_id=detail["id"],
        payload=AtpTestLineUpdateRequest(call_height_m=48.0),
        actor_user_id="tester",
    )
    assert updated["snapshot_hash"] != original_hash  # 改几何 → 指纹变


def test_create_rejects_duplicate_geometry_group(session: Session) -> None:
    create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    with pytest.raises(Exception) as excinfo:
        create_test_line(
            session, payload=_create_payload(code="TL-dup"), actor_user_id="tester"
        )
    assert "409" in str(excinfo.value) or "已存在同一几何维组" in str(excinfo.value)


def test_create_rejects_blockers(session: Session) -> None:
    with pytest.raises(Exception) as excinfo:
        create_test_line(
            session,
            payload=_create_payload(shield_wire_left_mid_m=None),
            actor_user_id="tester",
        )
    assert "几何校验未通过" in str(excinfo.value)


def test_asset_binding_allows_same_geometry_group(session: Session) -> None:
    """模型级专用样本与共享基准可以同几何维共存（唯一键含 asset_id）。"""
    asset = _create_asset(session)
    create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    special = create_test_line(
        session,
        payload=_create_payload(code="TL-500-guxing-special", asset_id=asset.id),
        actor_user_id="tester",
    )
    assert special["asset_id"] == asset.id


# ───────────────────── 4. 三级解析 ─────────────────────


def test_resolve_prefers_model_binding(session: Session) -> None:
    asset = _create_asset(session)
    shared = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    special = create_test_line(
        session,
        payload=_create_payload(code="TL-special", asset_id=asset.id),
        actor_user_id="tester",
    )
    asset.test_line_id = special["id"]
    session.commit()

    row, matched_by = resolve_test_line(session, asset=asset)
    assert matched_by == "bound"
    assert row is not None and row.id == special["id"]
    assert shared["id"] != special["id"]


def test_resolve_falls_back_to_geometry_group(session: Session) -> None:
    asset = _create_asset(session)
    shared = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    row, matched_by = resolve_test_line(session, asset=asset)
    assert matched_by == "geometry"
    assert row is not None and row.id == shared["id"]


def test_resolve_degrades_to_voltage_tower_when_unique(session: Session) -> None:
    """没有 with 避雷线基准、但同电压+塔型只有一条 without → 降级并标记 degraded。"""
    asset = _create_asset(session, shield_wire="with")
    create_test_line(
        session,
        payload=_create_payload(
            code="TL-500-guxing-without",
            shield_wire="without",
            shield_wire_left_mid_m=None,
            shield_wire_right_mid_m=None,
        ),
        actor_user_id="tester",
    )
    row, matched_by = resolve_test_line(session, asset=asset)
    assert matched_by == "degraded"
    assert row is not None and row.shield_wire == "without"


def test_resolve_returns_none_without_match(session: Session) -> None:
    asset = _create_asset(session, voltage_level="220", tower_type="maotou")
    row, matched_by = resolve_test_line(session, asset=asset)
    assert row is None
    assert matched_by == "none"


def test_resolve_rejects_disabled_test_line(session: Session) -> None:
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    update_test_line(
        session,
        test_line_id=detail["id"],
        payload=AtpTestLineUpdateRequest(status="disabled"),
        actor_user_id="tester",
    )
    with pytest.raises(Exception) as excinfo:
        resolve_test_line(session, test_line_id=detail["id"])
    assert "已停用" in str(excinfo.value)


def test_resolve_skips_disabled_when_matching_geometry(session: Session) -> None:
    asset = _create_asset(session)
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    update_test_line(
        session,
        test_line_id=detail["id"],
        payload=AtpTestLineUpdateRequest(status="disabled"),
        actor_user_id="tester",
    )
    row, matched_by = resolve_test_line(session, asset=asset)
    assert row is None and matched_by == "none"


# ───────────────────── 5. 执行期装配 ─────────────────────


def test_execute_uses_frozen_snapshot_not_live_row(session: Session) -> None:
    """冻结快照的意义：表被改了，历史用例仍按「生成时那套参数」跑。"""
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    row = service.get_test_line_by_id(session, detail["id"])
    assert row is not None

    original_bt, original_pf = assemble_payload_from_test_line(row)
    # 直接改内存里的行（模拟绕过快照重算的漂移）
    row.call_height_m = 99.0
    base_tower, profile = assemble_payload_from_test_line(row)
    assert profile["call_height_m"] == original_pf["call_height_m"] == pytest.approx(45.0)
    assert base_tower == original_bt


def test_preview_reports_geometry_and_hash(session: Session) -> None:
    detail = create_test_line(session, payload=_create_payload(), actor_user_id="tester")
    preview = service.preview_test_line(session, detail["id"])
    assert preview["snapshot_hash"] == detail["snapshot_hash"]
    assert preview["base_tower"]["circuit_geometry_json"]["I"]["phase_spacing_m"]["upper"] == pytest.approx(12.0)
    assert preview["blockers"] == []


# ───────────────────── 6. 派生（dry-run）─────────────────────


def test_derive_fills_dimensions_and_marks_sources(session: Session) -> None:
    asset = _create_asset(session)
    result = derive_test_line(session, AtpTestLineDeriveRequest(asset_id=asset.id))
    draft = result["draft"]
    assert draft["voltage_level"] == "500"
    assert draft["tower_type"] == "guxing"
    assert draft["shield_wire"] == "with"
    # 至少要有回路几何（来自参数模板或内置兜底），否则无法生成 .dat
    assert draft["circuits"]
    # 每个填过的字段都有来源标注
    assert result["sources"]
    for field in ("insulator_length_m", "call_height_m", "shield_wire_height_m"):
        if draft.get(field) is not None:
            assert field in result["sources"]


def test_derive_marks_builtin_fallback_as_warning(session: Session) -> None:
    """内置兜底值必须显式告警（不允许把量级估计当成工程实测值）。"""
    asset = _create_asset(session)
    result = derive_test_line(session, AtpTestLineDeriveRequest(asset_id=asset.id))
    builtin_fields = [f for f, s in result["sources"].items() if s == SRC_BUILTIN]
    if builtin_fields:
        assert any("兜底" in item["reason"] for item in result["warnings"])


def test_derive_flags_template_sourced_values(session: Session) -> None:
    asset = _create_asset(session)
    result = derive_test_line(session, AtpTestLineDeriveRequest(asset_id=asset.id))
    template_fields = [f for f, s in result["sources"].items() if s == SRC_TEMPLATE]
    if template_fields:
        assert any("参数模板默认值" in item["reason"] for item in result["warnings"])


def test_derive_does_not_persist(session: Session) -> None:
    asset = _create_asset(session)
    derive_test_line(session, AtpTestLineDeriveRequest(asset_id=asset.id))
    assert service.list_test_lines(session)["total"] == 0


def test_derive_missing_asset_is_404(session: Session) -> None:
    with pytest.raises(Exception) as excinfo:
        derive_test_line(session, AtpTestLineDeriveRequest(asset_id="not-exists"))
    assert "ATP 资产不存在" in str(excinfo.value)


def test_derive_with_unknown_voltage_has_blocker(session: Session) -> None:
    """没有任何来源能给出回路几何时，必须给 blocker（不能生成跑不通的基准）。"""
    result = derive_test_line(
        session,
        AtpTestLineDeriveRequest(voltage_level="9999", tower_type="unknown-tower"),
    )
    assert result["blockers"]


# ─────────────────────── 菜单守卫：测试线路页与 ATP 菜单共存 ───────────────────────


def test_menu_paths_accept_test_line_menu_or_atp_models_menu() -> None:
    """``/api/v1/atp/test-lines`` 必须同时接受「测试线路管理」和「ATP模型管理」菜单。

    否则只给用户测试线路菜单时，接口会被 require_enabled_menu_route 拦成 403。
    """
    from app.core.dependencies import _menu_paths_for_api_path

    assert _menu_paths_for_api_path("/api/v1/atp/test-lines") == (
        "/admin/atp-models",
        "/admin/atp-test-lines",
    )
    # 其余 ATP 接口不应获得测试线路菜单的旁路
    assert _menu_paths_for_api_path("/api/v1/atp/assets") == ("/admin/atp-models",)


def test_menu_paths_strip_colon_action_suffix() -> None:
    """AIP 风格冒号动作（``test-lines:derive``）不能被当成更短的 ``/api/v1/atp`` 前缀。"""
    from app.core.dependencies import _menu_paths_for_api_path

    assert _menu_paths_for_api_path("/api/v1/atp/test-lines:derive") == (
        "/admin/atp-models",
        "/admin/atp-test-lines",
    )
    assert _menu_paths_for_api_path("/api/v1/atp/test-lines/abc123/preview") == (
        "/admin/atp-models",
        "/admin/atp-test-lines",
    )
