from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.base import utcnow
from ..models.line_tower import LineTower
from ..models.tower_analysis import TowerAnalysis
from ..models.tower_circuit import TowerCircuit
from ..models.tower_profile import TowerProfile
from ..models.user import User
from ..schemas.line import TowerCircuitSummary
from ..schemas.tower_profile import TowerProfileDetail, TowerProfileUpsertRequest


def get_tower_by_id(db: Session, tower_id: str) -> LineTower | None:
    return db.execute(select(LineTower).where(LineTower.id == tower_id)).scalar_one_or_none()


def get_tower_profile_by_tower_id(db: Session, tower_id: str) -> TowerProfile | None:
    return db.execute(select(TowerProfile).where(TowerProfile.tower_id == tower_id)).scalar_one_or_none()


def serialize_tower_profile(tower: LineTower, profile: TowerProfile | None) -> TowerProfileDetail:
    return TowerProfileDetail(
        id=profile.id if profile else None,
        tower_id=tower.id,
        line_id=tower.line_id,
        tower_no=tower.tower_no,
        seq_no=tower.seq_no,
        tower_model=tower.tower_model,
        tower_type=tower.tower_type,
        profile_exists=profile is not None,
        phase_sequence_1=profile.phase_sequence_1 if profile else None,
        phase_sequence_2=profile.phase_sequence_2 if profile else None,
        phase_sequence_3=profile.phase_sequence_3 if profile else None,
        phase_sequence_4=profile.phase_sequence_4 if profile else None,
        arrester_a=profile.arrester_a if profile else None,
        arrester_b=profile.arrester_b if profile else None,
        arrester_c=profile.arrester_c if profile else None,
        protection_angle_left_deg=profile.protection_angle_left_deg if profile else None,
        protection_angle_right_deg=profile.protection_angle_right_deg if profile else None,
        shield_wire_height_m=profile.shield_wire_height_m if profile else None,
        insulator_length_m=profile.insulator_length_m if profile else None,
        call_height_m=profile.call_height_m if profile else None,
        angle_deg=profile.angle_deg if profile else None,
        current_a=profile.current_a if profile else None,
        current_b=profile.current_b if profile else None,
        structure_kind=profile.structure_kind if profile else None,
        stroke_mode=profile.stroke_mode if profile else None,
        current_type=profile.current_type if profile else None,
        current_head_time_us=profile.current_head_time_us if profile else None,
        current_tail_time_us=profile.current_tail_time_us if profile else None,
        cause_analysis=tower.analysis.cause_analysis if tower.analysis else None,
        mitigation_recommendation=tower.analysis.mitigation_recommendation if tower.analysis else None,
        circuits=[_serialize_circuit(circuit) for circuit in tower.circuits],
        extra_profile_json=(profile.extra_profile_json or {}) if profile else {},
        create_date=profile.create_date if profile else None,
        create_user=profile.create_user if profile else None,
        update_date=profile.update_date if profile else None,
        update_user=profile.update_user if profile else None,
    )


def _serialize_circuit(circuit: TowerCircuit) -> TowerCircuitSummary:
    return TowerCircuitSummary(
        id=circuit.id,
        tower_id=circuit.tower_id,
        circuit_no=circuit.circuit_no,
        phase_sequence=circuit.phase_sequence,
        spacing_upper_m=circuit.spacing_upper_m,
        spacing_middle_m=circuit.spacing_middle_m,
        spacing_lower_m=circuit.spacing_lower_m,
        height_upper_m=circuit.height_upper_m,
        height_middle_m=circuit.height_middle_m,
        height_lower_m=circuit.height_lower_m,
    )


def get_tower_profile_detail(db: Session, tower_id: str) -> TowerProfileDetail | None:
    tower = get_tower_by_id(db, tower_id)
    if not tower:
        return None
    profile = get_tower_profile_by_tower_id(db, tower_id)
    return serialize_tower_profile(tower, profile)


def upsert_tower_profile(
    db: Session,
    tower_id: str,
    payload: TowerProfileUpsertRequest,
    *,
    actor: User,
) -> TowerProfileDetail | None:
    tower = get_tower_by_id(db, tower_id)
    if not tower:
        return None

    profile = get_tower_profile_by_tower_id(db, tower_id)
    now = utcnow()
    if profile is None:
        profile = TowerProfile(
            tower_id=tower.id,
            create_date=now,
            create_user=actor.id,
            update_date=now,
            update_user=actor.id,
        )
        db.add(profile)

    profile.phase_sequence_1 = payload.phase_sequence_1
    profile.phase_sequence_2 = payload.phase_sequence_2
    profile.phase_sequence_3 = payload.phase_sequence_3
    profile.phase_sequence_4 = payload.phase_sequence_4
    profile.arrester_a = payload.arrester_a
    profile.arrester_b = payload.arrester_b
    profile.arrester_c = payload.arrester_c
    profile.protection_angle_left_deg = payload.protection_angle_left_deg
    profile.protection_angle_right_deg = payload.protection_angle_right_deg
    profile.shield_wire_height_m = payload.shield_wire_height_m
    profile.insulator_length_m = payload.insulator_length_m
    profile.call_height_m = payload.call_height_m
    profile.angle_deg = payload.angle_deg
    profile.current_a = payload.current_a
    profile.current_b = payload.current_b
    profile.structure_kind = payload.structure_kind
    profile.stroke_mode = payload.stroke_mode
    profile.current_type = payload.current_type
    profile.current_head_time_us = payload.current_head_time_us
    profile.current_tail_time_us = payload.current_tail_time_us
    profile.extra_profile_json = payload.extra_profile_json or {}

    analysis = tower.analysis
    if analysis is None:
        analysis = TowerAnalysis(
            tower_id=tower.id,
            create_date=now,
            update_date=now,
        )
        tower.analysis = analysis
    analysis.cause_analysis = payload.cause_analysis
    analysis.mitigation_recommendation = payload.mitigation_recommendation
    analysis.update_date = now

    _upsert_circuits(db, tower=tower, circuits=payload.circuits, actor_user_id=actor.id, now=now)

    profile.update_date = now
    profile.update_user = actor.id
    db.commit()

    saved = get_tower_profile_by_tower_id(db, tower_id)
    if saved is None:
        return None
    return serialize_tower_profile(tower, saved)


def _upsert_circuits(
    db: Session,
    *,
    tower: LineTower,
    circuits: list[TowerCircuitSummary],
    actor_user_id: str,
    now: Any,
) -> None:
    existing_by_no: dict[int, TowerCircuit] = {item.circuit_no: item for item in tower.circuits}
    seen: set[int] = set()
    for raw in circuits:
        circuit_no = int(getattr(raw, "circuit_no", 0) or 0)
        if circuit_no <= 0:
            continue
        seen.add(circuit_no)
        circuit = existing_by_no.get(circuit_no)
        if circuit is None:
            circuit = TowerCircuit(
                tower_id=tower.id,
                circuit_no=circuit_no,
                create_date=now,
                update_date=now,
            )
            tower.circuits.append(circuit)
        circuit.phase_sequence = getattr(raw, "phase_sequence", None)
        circuit.spacing_upper_m = _coerce_float(getattr(raw, "spacing_upper_m", None))
        circuit.spacing_middle_m = _coerce_float(getattr(raw, "spacing_middle_m", None))
        circuit.spacing_lower_m = _coerce_float(getattr(raw, "spacing_lower_m", None))
        circuit.height_upper_m = _coerce_float(getattr(raw, "height_upper_m", None))
        circuit.height_middle_m = _coerce_float(getattr(raw, "height_middle_m", None))
        circuit.height_lower_m = _coerce_float(getattr(raw, "height_lower_m", None))
        circuit.update_date = now
    for circuit_no in list(existing_by_no):
        if circuit_no not in seen:
            tower.circuits.remove(existing_by_no[circuit_no])


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
