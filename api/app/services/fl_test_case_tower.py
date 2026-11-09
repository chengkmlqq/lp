"""防雷测试集「防雷计算用例」的托管杆塔。

用例表单直接填写「编辑杆塔」表单字段 + 「防雷计算」表单字段，不再要求用户
先到线路管理里造测试线路 / 测试塔。但 fl_analysis 现有计算链路（外键、
线路准备状态门禁、tower_snapshot 装配）仍以 ``Line + LineTower`` 为载体，
因此在用例**保存时**按表单快照自动创建 / 更新一条系统托管线路 + 1 基杆塔：

- 线路 code 以 ``FLTC-`` 开头，仅作为用例的计算载体，用例表单不暴露；
- 表单里没有、但仿真必需的字段（绝缘子串、回路几何、避雷线、雷电流幅值等）
  优先取 ``TowerModel`` 模型默认值（按表单里的「模型」编码匹配），
  模型不存在时用内置兜底默认；用例也可在表单里显式覆盖这些值；
- 用例编辑后再次保存会就地刷新托管塔，因此「填什么就按什么算」，
  执行链路 ``fl_test_set_service._build_job_request`` 完全不用改。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.line import Line
from ..models.line_tower import LineTower
from ..models.tower_circuit import TowerCircuit
from ..models.tower_model import TowerModel
from ..models.tower_profile import TowerProfile

MANAGED_LINE_PREFIX = "FLTC-"

# 「编辑杆塔」表单字段（用例表单 Tab「杆塔参数」原样照搬）
TOWER_FORM_FIELDS: tuple[str, ...] = (
    "tower_no",
    "tower_type",
    "tower_model",
    "risk_level",
    "longitude",
    "latitude",
    "altitude_m",
    "ground_resistance_ohm",
    "lightning_density",
    "span_small_m",
    "span_large_m",
    "slope_1",
    "slope_2",
)

# 仿真必需、但编辑杆塔表单里没有的字段：允许用例显式覆盖
SIM_OVERRIDE_FIELDS: tuple[str, ...] = (
    "voltage_kv",
    "insulator_length_m",  # 毫米口径（>100 视为毫米，下游自动 /1000）
    "shield_wire_height_m",
    "call_height_m",
    "lightning_wire_left_mid_distance_m",
    "lightning_wire_right_mid_distance_m",
    "protection_angle_left_deg",
    "protection_angle_right_deg",
    "height_upper_m",
    "height_middle_m",
    "height_lower_m",
    "spacing_upper_m",
    "spacing_middle_m",
    "spacing_lower_m",
    "current_a",
    "current_b",
    "arrester_a",
    "arrester_b",
    "arrester_c",
)

# 模型库缺数据时的兜底默认，保证线路准备状态门禁 / 几何解析能跑通
_FALLBACK_SIM: dict[str, Any] = {
    "voltage_kv": 110,
    "insulator_length_m": 1000.0,
    "shield_wire_height_m": 30.0,
    "call_height_m": 24.0,
    "lightning_wire_left_mid_distance_m": 5.0,
    "lightning_wire_right_mid_distance_m": 5.0,
    "protection_angle_left_deg": 10.0,
    "protection_angle_right_deg": 10.0,
    "height_upper_m": 30.0,
    "height_middle_m": 24.0,
    "height_lower_m": 18.0,
    "spacing_upper_m": 6.0,
    "spacing_middle_m": 7.0,
    "spacing_lower_m": 6.0,
    "current_a": 31.0,
    "current_b": 2.6,
    "arrester_a": "否",
    "arrester_b": "否",
    "arrester_c": "否",
}

# 准备状态门禁要求这几项必须非空
_GATE_FALLBACK: dict[str, Any] = {
    "lightning_density": 2.8,
    "slope_1": 0.0,
    "slope_2": 0.0,
}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _not_blank(value: Any) -> bool:
    return value is not None and value != ""


def _model_sim(db: Session, model_code: Any) -> dict[str, Any]:
    """按表单「模型」编码读取塔模型库里的仿真默认值。"""
    code = str(model_code or "").strip()
    if not code:
        return {}
    model = db.execute(
        select(TowerModel).where(
            func.lower(TowerModel.code) == code.lower(),
            TowerModel.is_enabled.is_(True),
        )
    ).scalar_one_or_none()
    if model is None:
        return {}
    raw = model.default_raw_json or {}
    legacy = raw.get("legacy_defaults") or {}
    geometry = (raw.get("circuit_geometry_json") or {}).get("I") or {}
    spacing = geometry.get("phase_spacing_m") or {}
    height = geometry.get("phase_height_m") or {}
    arrester = legacy.get("arrester_install") or {}

    result: dict[str, Any] = {}
    pairs = (
        ("voltage_kv", legacy.get("voltage_kv")),
        ("insulator_length_m", legacy.get("insulator_length_mm")),
        ("shield_wire_height_m", legacy.get("lightning_wire_height_m")),
        ("call_height_m", legacy.get("tower_height_m")),
        ("lightning_wire_left_mid_distance_m", legacy.get("left_lightning_mid_distance_m")),
        ("lightning_wire_right_mid_distance_m", legacy.get("right_lightning_mid_distance_m")),
        ("current_a", legacy.get("current_a")),
        ("current_b", legacy.get("current_b")),
        ("height_upper_m", height.get("upper")),
        ("height_middle_m", height.get("middle")),
        ("height_lower_m", height.get("lower")),
        ("spacing_upper_m", spacing.get("upper")),
        ("spacing_middle_m", spacing.get("middle")),
        ("spacing_lower_m", spacing.get("lower")),
    )
    for key, value in pairs:
        if _not_blank(value):
            result[key] = value
    for phase in ("A", "B", "C"):
        if phase in arrester:
            result[f"arrester_{phase.lower()}"] = "是" if arrester[phase] else "否"
    return result


def _resolve_sim(db: Session, tower_params: dict[str, Any]) -> dict[str, Any]:
    """兜底默认 → 塔模型默认 → 用例表单覆盖，后者优先。"""
    sim: dict[str, Any] = dict(_FALLBACK_SIM)
    sim.update(_model_sim(db, tower_params.get("tower_model")))
    for key in SIM_OVERRIDE_FIELDS:
        if _not_blank(tower_params.get(key)):
            sim[key] = tower_params[key]
    for key in ("voltage_kv", "insulator_length_m", "shield_wire_height_m", "call_height_m",
                "height_upper_m", "height_middle_m", "height_lower_m",
                "spacing_upper_m", "spacing_middle_m", "spacing_lower_m",
                "current_a", "current_b"):
        parsed = _num(sim.get(key))
        if parsed is not None:
            sim[key] = parsed
    return sim


def _managed_line_code(case_id: str) -> str:
    return f"{MANAGED_LINE_PREFIX}{case_id[:24]}"


def is_managed_line(line: Line | None) -> bool:
    return bool(line and str(line.code or "").startswith(MANAGED_LINE_PREFIX))


def ensure_case_tower(
    db: Session,
    *,
    case_id: str,
    case_name: str,
    tower_params: dict[str, Any] | None,
    actor_user_id: str | None,
) -> tuple[str, str]:
    """创建 / 刷新用例的计算载体，返回 ``(line_id, tower_id)``。

    调用方负责 ``commit``；本函数只 ``flush``，方便与用例行同事务提交。
    """
    params = dict(tower_params or {})
    sim = _resolve_sim(db, params)
    now = utcnow()

    # ---- 线路（每用例一条，避免不同电压等级互相串数据）----
    code = _managed_line_code(case_id)
    line = db.execute(select(Line).where(Line.code == code)).scalar_one_or_none()
    if line is None:
        line = Line(code=code, name="", status="enabled", create_user=actor_user_id)
        db.add(line)
        db.flush()
    line.name = f"[测试集托管] {case_name or case_id}"[:255]
    voltage_kv = _num(sim.get("voltage_kv"))
    line.voltage_kv = int(voltage_kv) if voltage_kv is not None else 110
    line.lightning_param_json = {
        "雷电流幅值a": _num(sim.get("current_a")) or 31.0,
        "雷电流幅值b": _num(sim.get("current_b")) or 2.6,
    }
    line.arrester_install_json = {
        phase: str(sim.get(f"arrester_{phase.lower()}") or "否") in {"是", "已装", "1", "true", "True", "Y", "y"}
        for phase in ("A", "B", "C")
    }
    line.update_user = actor_user_id
    line.update_date = now

    # ---- 杆塔（1 基；「编辑杆塔」表单 13 字段逐项落库）----
    tower_no = str(params.get("tower_no") or "1").strip() or "1"
    tower = db.execute(
        select(LineTower).where(LineTower.line_id == line.id, LineTower.seq_no == 1)
    ).scalar_one_or_none()
    if tower is None:
        tower = LineTower(line_id=line.id, seq_no=1, tower_no=tower_no, create_user=actor_user_id)
        db.add(tower)
        db.flush()
    tower.tower_no = tower_no
    for field in (
        "tower_type", "tower_model", "risk_level", "longitude", "latitude", "altitude_m",
        "ground_resistance_ohm", "lightning_density", "span_small_m", "span_large_m",
        "slope_1", "slope_2",
    ):
        value = params.get(field)
        setattr(tower, field, _num(value) if field in {
            "longitude", "latitude", "altitude_m", "ground_resistance_ohm", "lightning_density",
            "span_small_m", "span_large_m", "slope_1", "slope_2",
        } else (str(value).strip() if _not_blank(value) else None))
    # 准备状态门禁：地闪密度 / 两个地面倾角必须有值（表单留空时用兜底）
    for field, fallback in _GATE_FALLBACK.items():
        if getattr(tower, field) is None:
            setattr(tower, field, fallback)
    tower.update_user = actor_user_id
    tower.update_date = now

    # ---- 仿真 profile（计算真正读取的塔参数）----
    profile = db.execute(
        select(TowerProfile).where(TowerProfile.tower_id == tower.id)
    ).scalar_one_or_none()
    if profile is None:
        profile = TowerProfile(tower_id=tower.id, create_user=actor_user_id, create_date=now)
        db.add(profile)
        db.flush()
    profile.insulator_length_m = _num(sim.get("insulator_length_m"))
    profile.shield_wire_height_m = _num(sim.get("shield_wire_height_m"))
    profile.call_height_m = _num(sim.get("call_height_m"))
    profile.protection_angle_left_deg = _num(sim.get("protection_angle_left_deg"))
    profile.protection_angle_right_deg = _num(sim.get("protection_angle_right_deg"))
    profile.current_a = _num(sim.get("current_a"))
    profile.current_b = _num(sim.get("current_b"))
    profile.arrester_a = str(sim.get("arrester_a") or "否")
    profile.arrester_b = str(sim.get("arrester_b") or "否")
    profile.arrester_c = str(sim.get("arrester_c") or "否")
    profile.structure_kind = "直线"
    profile.stroke_mode = "绕击反击"
    profile.current_type = "heidler"
    profile.current_head_time_us = 2.6
    profile.current_tail_time_us = 50.0
    profile.angle_deg = 0.0
    profile.extra_profile_json = {
        "lightning_wire": {
            "left_mid_distance_m": _num(sim.get("lightning_wire_left_mid_distance_m")),
            "right_mid_distance_m": _num(sim.get("lightning_wire_right_mid_distance_m")),
        }
    }
    profile.update_user = actor_user_id
    profile.update_date = now

    # ---- I 回几何（EGM / ATP 参数解析需要回路几何）----
    circuit = db.execute(
        select(TowerCircuit).where(TowerCircuit.tower_id == tower.id, TowerCircuit.circuit_no == 1)
    ).scalar_one_or_none()
    if circuit is None:
        circuit = TowerCircuit(tower_id=tower.id, circuit_no=1, phase_sequence="ABC")
        db.add(circuit)
        db.flush()
    circuit.spacing_upper_m = _num(sim.get("spacing_upper_m"))
    circuit.spacing_middle_m = _num(sim.get("spacing_middle_m"))
    circuit.spacing_lower_m = _num(sim.get("spacing_lower_m"))
    circuit.height_upper_m = _num(sim.get("height_upper_m"))
    circuit.height_middle_m = _num(sim.get("height_middle_m"))
    circuit.height_lower_m = _num(sim.get("height_lower_m"))
    circuit.update_date = now

    db.flush()
    return line.id, tower.id


def delete_case_tower(db: Session, *, case_id: str) -> None:
    """删用例时一并清理托管线路（杆塔/profile/回路按外键级联）。"""
    code = _managed_line_code(case_id)
    line = db.execute(select(Line).where(Line.code == code)).scalar_one_or_none()
    if line is not None:
        db.delete(line)
        db.flush()
