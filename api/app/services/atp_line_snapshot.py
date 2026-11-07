"""``base_tower`` / ``profile`` 装配器（两条输入路径的唯一出口）。

为什么要有这个模块
------------------
ATP 测试的输入是 ``base_tower`` + ``profile`` 两个 JSON。历史上这两份 JSON 只由
「真实线路杆塔」装配（``fl_analysis_service._build_base_tower_json`` /
``_build_profile_json``）。新增「测试线路（单塔基准）」后，如果另写一套装配逻辑，
两边字段名/单位/几何合并规则稍有差异，就会出现「同一基杆塔走测试线路跑出来的结果
和走真实杆塔不一致」——基准就失去意义了。

因此：**真实杆塔、测试线路、以及后续任何来源，都只走这里的 ``assemble_*``**，
并由 ``tests`` 断言两路径输出**字段集完全相同**（防漂移）。

单位口径（重要）
----------------
- ``insulator_length_m``：``TowerProfile`` 历史按**毫米**入库（如 4450），
  下游 ``build_context`` / ``atp_geometry_pipeline`` 按「值 > 100 视为毫米」自动 /1000。
  测试线路表按**米**存（如 5.945），同样落在「≤100」分支 → 两条路径等价。
- 其余长度字段一律米；角度一律度。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

# 地形/海拔/倾角当前在几何与仿真管线里没有消费方（见 ATP_TEST_LINE_DESIGN §8-b）。
# 装配时如实搬运，同时在快照里列出来，供 compare.json 标注 not_consumed。
NOT_CONSUMED_FIELDS: tuple[str, ...] = (
    "base_tower.altitude_m",
    "base_tower.terrain",
    "base_tower.slope_1",
    "base_tower.slope_2",
)

_CIRCUIT_KEYS = {1: "I", 2: "II", 3: "III", 4: "IV"}


# --------------------------------------------------------------------------------------
# 历史脏数据兼容：*_json 字段可能被误存为 JSON 字符串（如导入链路 json.dumps 落库），
# 装配 base_tower 时统一归一化为 dict，避免下游 raw_extra.get() 抛
# 'str' object has no attribute 'get'（对齐 fl_analysis_service._ensure_json_object，
# 此处独立定义以避免循环导入）。
# --------------------------------------------------------------------------------------


def _ensure_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


# --------------------------------------------------------------------------------------
# 几何组装（真实杆塔的 TowerCircuit 与测试线路的 AtpTestLineCircuit 字段同构，共用）
# --------------------------------------------------------------------------------------


def build_geometry_layers(circuits: Iterable[Any] | None) -> dict[str, Any]:
    """``circuits`` → ``{"I": {phase_spacing_m, phase_height_m}, "II": ...}``。

    接受任何具备 ``circuit_no`` / ``spacing_*_m`` / ``height_*_m`` 的对象
    （``TowerCircuit`` 与 ``AtpTestLineCircuit`` 同构）。
    """
    layers: dict[str, Any] = {}
    for circuit in circuits or ():
        key = _CIRCUIT_KEYS.get(int(getattr(circuit, "circuit_no", 0) or 0))
        if key is None:
            continue
        layers[key] = {
            "phase_spacing_m": {
                "upper": getattr(circuit, "spacing_upper_m", None),
                "middle": getattr(circuit, "spacing_middle_m", None),
                "lower": getattr(circuit, "spacing_lower_m", None),
            },
            "phase_height_m": {
                "upper": getattr(circuit, "height_upper_m", None),
                "middle": getattr(circuit, "height_middle_m", None),
                "lower": getattr(circuit, "height_lower_m", None),
            },
        }
    return layers


def _merge_lightning_wire(
    layers: dict[str, Any], extra_profile_json: Mapping[str, Any] | None
) -> dict[str, Any]:
    """把 ``extra_profile_json.lightning_wire``（避雷线中距/高度）并入几何层。

    LP-570 修复：此前计算链路拿不到真实避雷线中距，回填 10m 默认值。
    """
    merged = dict(layers)
    lightning_wire = (extra_profile_json or {}).get("lightning_wire")
    if isinstance(lightning_wire, dict):
        merged["lightning_wire"] = dict(lightning_wire)
    return merged


# --------------------------------------------------------------------------------------
# profile 装配
# --------------------------------------------------------------------------------------

# profile 输出的固定字段集（两路径共用；新增字段只改这里）
_PROFILE_FIELDS: tuple[str, ...] = (
    "phase_sequence_1",
    "phase_sequence_2",
    "phase_sequence_3",
    "phase_sequence_4",
    "arrester_a",
    "arrester_b",
    "arrester_c",
    "protection_angle_left_deg",
    "protection_angle_right_deg",
    "shield_wire_height_m",
    "insulator_length_m",
    "call_height_m",
    "angle_deg",
    "current_a",
    "current_b",
    "structure_kind",
    "stroke_mode",
    "current_type",
    "current_head_time_us",
    "current_tail_time_us",
)


def _assemble_profile(
    *,
    fields: Mapping[str, Any],
    extra_profile_json: Mapping[str, Any] | None,
    circuits: Iterable[Any] | None,
    with_geometry_layers: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {name: fields.get(name) for name in _PROFILE_FIELDS}
    result["extra_profile_json"] = dict(extra_profile_json or {})
    if with_geometry_layers:
        result["geometry_layers_json"] = _merge_lightning_wire(
            build_geometry_layers(circuits), extra_profile_json
        )
    return result


def build_profile_from_tower_profile(
    profile: Any, tower: Any | None = None
) -> dict[str, Any]:
    """从 ``TowerProfile`` ORM 对象装配 profile（``tower`` 给定时附带几何层）。"""
    if profile is None:
        return {}
    fields = {name: getattr(profile, name, None) for name in _PROFILE_FIELDS}
    extra = getattr(profile, "extra_profile_json", None) or {}
    result = _assemble_profile(
        fields=fields,
        extra_profile_json=extra,
        circuits=getattr(tower, "circuits", None) if tower is not None else None,
        with_geometry_layers=tower is not None,
    )
    if tower is not None:
        analysis = getattr(tower, "analysis", None)
        if analysis is not None:
            result["cause_analysis"] = getattr(analysis, "cause_analysis", None)
            result["mitigation_recommendation"] = getattr(
                analysis, "mitigation_recommendation", None
            )
    return result


def build_profile_from_test_line(test_line: Any) -> dict[str, Any]:
    """从 ``AtpTestLine`` 装配 profile。

    ``extra_profile_json`` 由避雷线中距现场构造（测试线路把它存在主表两列上），
    从而让 ``geometry_layers_json.lightning_wire`` 与真实杆塔路径同构。
    """
    fields = {name: getattr(test_line, name, None) for name in _PROFILE_FIELDS}
    # 雷电流幅值：测试线路用单列 current_ka 表达，映射到 profile 的电流源变量
    # （A 相为主；执行期 execution_options.binary_search_current_ka 优先级更高，
    #  这里的值只作为「未显式指定电流」时的默认）
    fields["current_a"] = getattr(test_line, "current_ka", None)
    left = getattr(test_line, "shield_wire_left_mid_m", None)
    right = getattr(test_line, "shield_wire_right_mid_m", None)
    extra: dict[str, Any] = {}
    if left is not None or right is not None:
        extra["lightning_wire"] = {
            "left_mid_distance_m": left,
            "right_mid_distance_m": right,
        }
    return _assemble_profile(
        fields=fields,
        extra_profile_json=extra,
        circuits=getattr(test_line, "circuits", None),
        with_geometry_layers=True,
    )


# --------------------------------------------------------------------------------------
# base_tower 装配
# --------------------------------------------------------------------------------------

_BASE_TOWER_FIELDS: tuple[str, ...] = (
    "tower_id",
    "line_id",
    "line_name",
    "line_voltage_kv",
    "line_phase_sequence_json",
    "line_arrester_install_json",
    "line_lightning_param_json",
    "seq_no",
    "tower_no",
    "tower_model",
    "tower_type",
    "longitude",
    "latitude",
    "altitude_m",
    "terrain",
    "ground_resistance_ohm",
    "lightning_density",
    "span_small_m",
    "span_large_m",
    "slope_1",
    "slope_2",
    "risk_level",
    "circuit_geometry_json",
    "lightning_result_json",
    "raw_extra_json",
)


def build_base_tower_from_line_tower(tower: Any, line: Any | None) -> dict[str, Any]:
    """从 ``LineTower`` + ``Line`` 装配 base_tower（真实杆塔路径）。"""
    lightning_result = getattr(tower, "lightning_result", None)
    return {
        "tower_id": tower.id,
        "line_id": tower.line_id,
        "line_name": line.name if line else None,
        "line_voltage_kv": line.voltage_kv if line else None,
        "line_phase_sequence_json": _ensure_json_object(line.phase_sequence_json if line else None),
        "line_arrester_install_json": _ensure_json_object(line.arrester_install_json if line else None),
        "line_lightning_param_json": _ensure_json_object(line.lightning_param_json if line else None),
        "seq_no": tower.seq_no,
        "tower_no": tower.tower_no,
        "tower_model": tower.tower_model,
        "tower_type": tower.tower_type,
        "longitude": tower.longitude,
        "latitude": tower.latitude,
        "altitude_m": tower.altitude_m,
        "terrain": tower.terrain,
        "ground_resistance_ohm": tower.ground_resistance_ohm,
        "lightning_density": tower.lightning_density,
        "span_small_m": tower.span_small_m,
        "span_large_m": tower.span_large_m,
        "slope_1": tower.slope_1,
        "slope_2": tower.slope_2,
        "risk_level": tower.risk_level,
        "circuit_geometry_json": build_geometry_layers(getattr(tower, "circuits", None)),
        "lightning_result_json": build_lightning_result_json(lightning_result),
        "raw_extra_json": _ensure_json_object(getattr(tower, "raw_extra_json", None)),
    }


def build_lightning_result_json(item: Any | None) -> dict[str, Any]:
    if item is None:
        return {}
    return {
        "counterstroke_indicator": getattr(item, "counterstroke_indicator", None),
        "counterstroke_withstand_ka": getattr(item, "counterstroke_withstand_ka", None),
        "counterstroke_trip_rate": getattr(item, "counterstroke_trip_rate", None),
        "shielding_withstand_ka": getattr(item, "shielding_withstand_ka", None),
        "shielding_trip_rate": getattr(item, "shielding_trip_rate", None),
        "angle_deg": getattr(item, "angle_deg", None),
        "current_a": getattr(item, "current_a_ka", None),
        "current_b": getattr(item, "current_b_ka", None),
        "risk_level": getattr(item, "risk_level", None),
    }


def build_base_tower_from_test_line(test_line: Any) -> dict[str, Any]:
    """从 ``AtpTestLine`` 装配 base_tower（测试线路路径）。

    输出字段集与 ``build_base_tower_from_line_tower`` **完全一致**；
    测试线路没有台账侧属性（经纬度/风险等级/雷击结果），按空值输出。
    """
    circuits = list(getattr(test_line, "circuits", None) or [])
    phase_sequence_json = {
        _CIRCUIT_KEYS[int(c.circuit_no)]: c.phase_sequence
        for c in circuits
        if int(getattr(c, "circuit_no", 0) or 0) in _CIRCUIT_KEYS and c.phase_sequence
    }
    voltage_level = getattr(test_line, "voltage_level", None)
    try:
        line_voltage_kv: int | None = int(str(voltage_level)) if voltage_level else None
    except (TypeError, ValueError):
        line_voltage_kv = None
    return {
        "tower_id": test_line.id,
        "line_id": None,
        "line_name": getattr(test_line, "name", None),
        "line_voltage_kv": line_voltage_kv,
        "line_phase_sequence_json": phase_sequence_json,
        "line_arrester_install_json": {},
        "line_lightning_param_json": {},
        "seq_no": 1,
        "tower_no": getattr(test_line, "tower_no", None) or getattr(test_line, "code", None),
        "tower_model": getattr(test_line, "tower_model", None)
        or getattr(test_line, "tower_type", None),
        "tower_type": getattr(test_line, "tower_type", None),
        "longitude": None,
        "latitude": None,
        "altitude_m": getattr(test_line, "altitude_m", None),
        "terrain": getattr(test_line, "terrain", None),
        "ground_resistance_ohm": getattr(test_line, "ground_resistance_ohm", None),
        "lightning_density": getattr(test_line, "lightning_density", None),
        "span_small_m": getattr(test_line, "span_small_m", None),
        "span_large_m": getattr(test_line, "span_large_m", None),
        "slope_1": getattr(test_line, "slope_1", None),
        "slope_2": getattr(test_line, "slope_2", None),
        "risk_level": None,
        # 避雷线中距/高度一并并入回路几何层（2026-11-07）：几何管线与测试前置校验
        # 都从 circuit_geometry_json.lightning_wire 读取，此前只写在 profile 侧，
        # 导致 base_tower 侧缺失、测试自动匹配被判「几何不完整」。
        "circuit_geometry_json": _merge_lightning_wire(
            build_geometry_layers(circuits),
            {
                "lightning_wire": {
                    "left_mid_distance_m": getattr(test_line, "shield_wire_left_mid_m", None),
                    "right_mid_distance_m": getattr(test_line, "shield_wire_right_mid_m", None),
                    "height_m": getattr(test_line, "shield_wire_height_m", None),
                }
            },
        ),
        "lightning_result_json": {},
        "raw_extra_json": {},
    }


# --------------------------------------------------------------------------------------
# 统一出口
# --------------------------------------------------------------------------------------


def assemble_from_line_tower(tower: Any, line: Any | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """真实线路杆塔 → (base_tower, profile)。"""
    return (
        build_base_tower_from_line_tower(tower, line),
        build_profile_from_tower_profile(getattr(tower, "profile", None), tower),
    )


def assemble_from_test_line(test_line: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """测试线路 → (base_tower, profile)。"""
    return (
        build_base_tower_from_test_line(test_line),
        build_profile_from_test_line(test_line),
    )


def snapshot_hash(base_tower: Mapping[str, Any] | None, profile: Mapping[str, Any] | None) -> str:
    """快照指纹：规范化 JSON 的 sha256。

    只用于「基准是否变更」判定，不参与仿真；因此**排除**运行期易变字段
    （``lightning_result_json`` 等来自上一次计算的写回值）。
    """
    volatile = {"lightning_result_json"}
    payload = {
        "base_tower": {
            k: v for k, v in (base_tower or {}).items() if k not in volatile
        },
        "profile": dict(profile or {}),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def build_snapshot(test_line: Any) -> dict[str, Any]:
    """生成落库用的冻结快照（含装配结果、指纹与未消费字段标注）。"""
    base_tower, profile = assemble_from_test_line(test_line)
    return {
        "base_tower": base_tower,
        "profile": profile,
        "snapshot_hash": snapshot_hash(base_tower, profile),
        "not_consumed": list(NOT_CONSUMED_FIELDS),
        "assembler": "atp_line_snapshot/1",
    }


__all__ = [
    "NOT_CONSUMED_FIELDS",
    "assemble_from_line_tower",
    "assemble_from_test_line",
    "build_base_tower_from_line_tower",
    "build_base_tower_from_test_line",
    "build_geometry_layers",
    "build_profile_from_test_line",
    "build_lightning_result_json",
    "build_profile_from_tower_profile",
    "build_snapshot",
    "snapshot_hash",
]
