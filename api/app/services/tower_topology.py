from __future__ import annotations

from typing import Any, Literal

TowerTopologyKind = Literal["single", "double", "quad", "dc"]

_TOPOLOGY_KIND_ALIASES: dict[str, TowerTopologyKind] = {
    "single": "single",
    "single_circuit": "single",
    "1": "single",
    "1h": "single",
    "1hui": "single",
    "1回": "single",
    "一回": "single",
    "单回": "single",
    "double": "double",
    "double_circuit": "double",
    "2": "double",
    "2h": "double",
    "2hui": "double",
    "2回": "double",
    "二回": "double",
    "双回": "double",
    "quad": "quad",
    "four": "quad",
    "four_circuit": "quad",
    "4": "quad",
    "4h": "quad",
    "4hui": "quad",
    "4回": "quad",
    "四回": "quad",
    "dc": "dc",
    "hvdc": "dc",
    "直流": "dc",
    "zhiliu": "dc",
    "vzhiliu": "dc",
}
_TOPOLOGY_CIRCUIT_KEYS: dict[TowerTopologyKind, tuple[str, ...]] = {
    "single": ("I",),
    "double": ("I", "II"),
    "quad": ("I", "II", "III", "IV"),
    "dc": ("I",),
}
_TOPOLOGY_PHASE_KEYS: dict[TowerTopologyKind, tuple[str, ...]] = {
    "single": ("upper", "middle", "lower"),
    "double": ("upper", "middle", "lower"),
    "quad": ("upper", "middle", "lower"),
    "dc": ("upper", "lower"),
}
_ALL_CIRCUIT_KEYS = ("I", "II", "III", "IV")
_ALL_PHASE_KEYS = ("upper", "middle", "lower")


def parse_tower_topology_override(value: Any) -> TowerTopologyKind | None:
    text = str(value or "").strip()
    if not text:
        return None
    lowered = text.lower()
    return _TOPOLOGY_KIND_ALIASES.get(text) or _TOPOLOGY_KIND_ALIASES.get(lowered)


def infer_tower_topology(
    *,
    tower_model: Any = None,
    tower_type: Any = None,
    structure_kind: Any = None,
    geometry_topology: Any = None,
) -> TowerTopologyKind:
    override = parse_tower_topology_override(geometry_topology)
    if override is not None:
        return override

    marker = "|".join(
        [
            str(tower_model or ""),
            str(tower_type or ""),
            str(structure_kind or ""),
        ]
    ).lower()
    if (
        "直流" in marker
        or "zhiliu" in marker
        or "vzhiliu" in marker
        or marker.startswith("dc")
        or "|dc" in marker
        or "dc_" in marker
    ):
        return "dc"
    if any(token in marker for token in ("sihuita", "四回", "4回")):
        return "quad"
    if any(token in marker for token in ("guxing", "双回", "2回")):
        return "double"
    return "single"


def infer_line_kind(
    *,
    tower_model: Any = None,
    tower_type: Any = None,
    structure_kind: Any = None,
    geometry_topology: Any = None,
) -> str:
    topology = infer_tower_topology(
        tower_model=tower_model,
        tower_type=tower_type,
        structure_kind=structure_kind,
        geometry_topology=geometry_topology,
    )
    return "dc" if topology == "dc" else "ac"


def infer_structure_count(
    *,
    tower_model: Any = None,
    tower_type: Any = None,
    structure_kind: Any = None,
    geometry_topology: Any = None,
) -> int:
    topology = infer_tower_topology(
        tower_model=tower_model,
        tower_type=tower_type,
        structure_kind=structure_kind,
        geometry_topology=geometry_topology,
    )
    if topology == "double":
        return 2
    if topology == "quad":
        return 4
    return 1


def topology_circuit_keys(topology: TowerTopologyKind) -> tuple[str, ...]:
    return _TOPOLOGY_CIRCUIT_KEYS[topology]


def topology_phase_keys(topology: TowerTopologyKind) -> tuple[str, ...]:
    return _TOPOLOGY_PHASE_KEYS[topology]


class TowerGeometryValidationError(ValueError):
    pass


def normalize_profile_geometry_layers(
    geometry_layers: Any,
    *,
    tower_model: Any = None,
    tower_type: Any = None,
    structure_kind: Any = None,
    shield_wire_height_m: float | None = None,
    insulator_length_m: float | None = None,
    call_height_m: float | None = None,
) -> dict[str, Any]:
    if geometry_layers in (None, ""):
        return {}
    if not isinstance(geometry_layers, dict):
        raise TowerGeometryValidationError("回路几何需要是 JSON 对象")

    topology = infer_tower_topology(
        tower_model=tower_model,
        tower_type=tower_type,
        structure_kind=structure_kind,
        geometry_topology=geometry_layers.get("topology_kind"),
    )
    normalized = {
        key: value
        for key, value in geometry_layers.items()
        if key not in {*_ALL_CIRCUIT_KEYS, "lightning_wire", "insulator_length_mm", "tower_height_m", "topology_kind"}
    }
    normalized["topology_kind"] = topology

    has_geometry_payload = any(
        _has_meaningful_value(geometry_layers.get(key))
        for key in (*_ALL_CIRCUIT_KEYS, "lightning_wire", "insulator_length_mm", "tower_height_m")
    )
    if not has_geometry_payload:
        return normalized

    active_circuits = topology_circuit_keys(topology)
    active_phases = topology_phase_keys(topology)
    phase_labels = _phase_labels_for_topology(topology)

    for circuit_key in _ALL_CIRCUIT_KEYS:
        raw_circuit = geometry_layers.get(circuit_key)
        if circuit_key not in active_circuits:
            if _has_meaningful_value(raw_circuit):
                raise TowerGeometryValidationError(f"{circuit_key}回不适用于当前杆塔拓扑")
            continue
        if not isinstance(raw_circuit, dict):
            raise TowerGeometryValidationError(f"{circuit_key}回几何缺失")

        normalized_circuit = {
            key: value
            for key, value in raw_circuit.items()
            if key not in {"phase_spacing_m", "phase_height_m"}
        }
        spacing_raw = raw_circuit.get("phase_spacing_m")
        height_raw = raw_circuit.get("phase_height_m")
        if not isinstance(spacing_raw, dict):
            raise TowerGeometryValidationError(f"{circuit_key}回导线中距缺失")
        if not isinstance(height_raw, dict):
            raise TowerGeometryValidationError(f"{circuit_key}回导线高度缺失")

        spacing_normalized: dict[str, float | None] = {}
        height_normalized: dict[str, float | None] = {}
        for phase_key in _ALL_PHASE_KEYS:
            phase_label = phase_labels[phase_key]
            if phase_key in active_phases:
                spacing_normalized[phase_key] = _require_numeric_value(
                    spacing_raw.get(phase_key),
                    label=f"{circuit_key}回{phase_label}导线中距(m)",
                    positive_only=False,
                )
                height_normalized[phase_key] = _require_numeric_value(
                    height_raw.get(phase_key),
                    label=f"{circuit_key}回{phase_label}导线高度(m)",
                    positive_only=True,
                )
            elif _has_meaningful_value(spacing_raw.get(phase_key)) or _has_meaningful_value(height_raw.get(phase_key)):
                raise TowerGeometryValidationError(f"{circuit_key}回{phase_label}仅适用于其他杆塔拓扑")
            else:
                spacing_normalized[phase_key] = None
                height_normalized[phase_key] = None

        normalized_circuit["phase_spacing_m"] = spacing_normalized
        normalized_circuit["phase_height_m"] = height_normalized
        normalized[circuit_key] = normalized_circuit

    lightning_wire_raw = geometry_layers.get("lightning_wire") if isinstance(geometry_layers.get("lightning_wire"), dict) else {}
    left_mid_distance = _coerce_optional_numeric(lightning_wire_raw.get("left_mid_distance_m"), positive_only=False)
    right_mid_distance = _coerce_optional_numeric(lightning_wire_raw.get("right_mid_distance_m"), positive_only=False)
    if left_mid_distance is None or right_mid_distance is None:
        raise TowerGeometryValidationError("请填写左右避雷中距(m)")
    wire_height = _coerce_optional_numeric(lightning_wire_raw.get("height_m"), positive_only=True)
    if wire_height is None and shield_wire_height_m is not None:
        wire_height = round(float(shield_wire_height_m), 4)
    if wire_height is None:
        raise TowerGeometryValidationError("请填写避雷线高度(m)")
    normalized["lightning_wire"] = {
        "left_mid_distance_m": left_mid_distance,
        "right_mid_distance_m": right_mid_distance,
        "height_m": wire_height,
    }

    insulator_length_mm = _coerce_optional_numeric(geometry_layers.get("insulator_length_mm"), positive_only=True)
    if insulator_length_mm is None and insulator_length_m is not None:
        insulator_length_mm = _normalize_insulator_length_mm(float(insulator_length_m))
    if insulator_length_mm is not None:
        normalized["insulator_length_mm"] = insulator_length_mm

    tower_height_m = _coerce_optional_numeric(geometry_layers.get("tower_height_m"), positive_only=True)
    if tower_height_m is None and call_height_m is not None:
        tower_height_m = round(float(call_height_m), 4)
    if tower_height_m is not None:
        normalized["tower_height_m"] = tower_height_m

    return normalized


def _phase_labels_for_topology(topology: TowerTopologyKind) -> dict[str, str]:
    if topology == "dc":
        return {
            "upper": "左极",
            "middle": "中极",
            "lower": "右极",
        }
    return {
        "upper": "上相",
        "middle": "中相",
        "lower": "下相",
    }


def _normalize_insulator_length_mm(value: float) -> float:
    if value <= 20:
        return round(value * 1000.0, 4)
    return round(value, 4)


def _coerce_optional_numeric(value: Any, *, positive_only: bool) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TowerGeometryValidationError("几何参数需要是数值") from exc
    if positive_only:
        if parsed <= 0:
            raise TowerGeometryValidationError("几何高度必须大于 0")
    elif parsed == 0:
        raise TowerGeometryValidationError("几何中距不能为 0")
    return round(parsed, 4)


def _require_numeric_value(value: Any, *, label: str, positive_only: bool) -> float:
    if value in (None, ""):
        raise TowerGeometryValidationError(f"{label}不能为空")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise TowerGeometryValidationError(f"{label}需要是数值") from exc
    if positive_only:
        if parsed <= 0:
            raise TowerGeometryValidationError(f"{label}必须大于 0")
    elif parsed == 0:
        raise TowerGeometryValidationError(f"{label}不能为 0")
    return round(parsed, 4)


def _has_meaningful_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_meaningful_value(item) for item in value)
    return True
