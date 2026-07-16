from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.tower_profile import TowerProfileUpsertRequest
from app.services import tower_profile_service
from app.services.tower_topology import TowerGeometryValidationError, infer_structure_count, infer_tower_topology


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Line.__table__, LineTower.__table__, TowerProfile.__table__])
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return testing_session()


def test_tower_profile_upsert_request_accepts_new_professional_fields() -> None:
    payload = TowerProfileUpsertRequest(
        structure_kind="直线杆塔",
        stroke_mode="反击",
        protection_angle_left_deg=11.5,
        protection_angle_right_deg=13.5,
        shield_wire_height_m=41.0,
        insulator_length_m=4200.0,
        call_height_m=39.5,
        angle_deg=18.0,
        current_a=31.0,
        current_b=2.6,
        current_type="Heidler",
        current_head_time_us=2.6,
        current_tail_time_us=50.0,
        geometry_layers_json={
            "I": {
                "phase_spacing_m": {"upper": 5.1, "middle": 4.2, "lower": 3.3},
                "phase_height_m": {"upper": 25.0, "middle": 22.0, "lower": 19.0},
            }
        },
        extra_profile_json={"cause_analysis": "接地电阻偏高"},
    )

    assert payload.structure_kind == "直线杆塔"
    assert payload.stroke_mode == "反击"
    assert payload.protection_angle_left_deg == 11.5
    assert payload.current_type == "Heidler"
    assert payload.geometry_layers_json["I"]["phase_spacing_m"]["upper"] == 5.1
    assert payload.extra_profile_json["cause_analysis"] == "接地电阻偏高"


def test_upsert_tower_profile_persists_professional_fields() -> None:
    session = _build_session()
    try:
        line = Line(code="PL-TP-001", name="塔参线路", status="enabled")
        session.add(line)
        session.flush()

        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N-01")
        session.add(tower)
        session.commit()

        payload = TowerProfileUpsertRequest(
            structure_kind="耐张杆塔",
            stroke_mode="反击",
            phase_sequence_1="ABC",
            arrester_a="是",
            protection_angle_left_deg=12.3,
            protection_angle_right_deg=14.6,
            shield_wire_height_m=40.2,
            insulator_length_m=4100.0,
            call_height_m=38.4,
            angle_deg=16.5,
            current_a=29.1,
            current_b=2.4,
            current_type="Heidler",
            current_head_time_us=2.7,
            current_tail_time_us=48.0,
            geometry_layers_json={
                "I": {
                    "phase_spacing_m": {"upper": 5.1, "middle": 4.0, "lower": 3.0},
                    "phase_height_m": {"upper": 29.0, "middle": 27.0, "lower": 25.0},
                },
                "lightning_wire": {"left_mid_distance_m": 5.4, "right_mid_distance_m": 5.6},
            },
            extra_profile_json={"cause_analysis": "接地电阻偏高"},
        )

        detail = tower_profile_service.upsert_tower_profile(
            session,
            tower.id,
            payload,
            actor=SimpleNamespace(id="tester"),
        )

        saved = tower_profile_service.get_tower_profile_by_tower_id(session, tower.id)

        assert detail is not None
        assert saved is not None
        assert saved.structure_kind == "耐张杆塔"
        assert saved.stroke_mode == "反击"
        assert saved.protection_angle_left_deg == 12.3
        assert saved.shield_wire_height_m == 40.2
        assert saved.current_type == "Heidler"
        assert saved.current_head_time_us == 2.7
        assert saved.extra_profile_json["cause_analysis"] == "接地电阻偏高"
        assert detail.geometry_layers_json["I"]["phase_spacing_m"]["upper"] == 5.1
        assert detail.extra_profile_json["cause_analysis"] == "接地电阻偏高"
        assert detail.geometry_layers_json["lightning_wire"]["height_m"] == 40.2
        assert detail.geometry_layers_json["insulator_length_mm"] == 4100.0
        assert detail.geometry_layers_json["tower_height_m"] == 38.4
        assert detail.geometry_layers_json["topology_kind"] == "single"
    finally:
        session.close()


def test_upsert_tower_profile_rejects_extra_circuit_for_single_topology() -> None:
    session = _build_session()
    try:
        line = Line(code="PL-TP-002", name="塔参线路", status="enabled")
        session.add(line)
        session.flush()

        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N-01", tower_model="220-TEST-ZX")
        session.add(tower)
        session.commit()

        payload = TowerProfileUpsertRequest(
            structure_kind="单回直线杆塔",
            shield_wire_height_m=38.0,
            insulator_length_m=3900.0,
            call_height_m=33.0,
            geometry_layers_json={
                "topology_kind": "single",
                "I": {
                    "phase_spacing_m": {"upper": 5.0, "middle": 4.0, "lower": 3.0},
                    "phase_height_m": {"upper": 28.0, "middle": 26.0, "lower": 24.0},
                },
                "II": {
                    "phase_spacing_m": {"upper": 5.5, "middle": 4.5, "lower": 3.5},
                    "phase_height_m": {"upper": 29.0, "middle": 27.0, "lower": 25.0},
                },
                "lightning_wire": {"left_mid_distance_m": 6.0, "right_mid_distance_m": 6.0},
            },
        )

        with pytest.raises(TowerGeometryValidationError, match="II回不适用于当前杆塔拓扑"):
            tower_profile_service.upsert_tower_profile(
                session,
                tower.id,
                payload,
                actor=SimpleNamespace(id="tester"),
            )
    finally:
        session.close()


def test_upsert_tower_profile_accepts_double_circuit_override_and_normalizes_defaults() -> None:
    session = _build_session()
    try:
        line = Line(code="PL-TP-003", name="塔参线路", status="enabled")
        session.add(line)
        session.flush()

        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N-02", tower_model="500-MC31S-DJC2-42")
        session.add(tower)
        session.commit()

        payload = TowerProfileUpsertRequest(
            structure_kind="直线杆塔",
            shield_wire_height_m=45.0,
            insulator_length_m=4.8,
            call_height_m=47.0,
            geometry_layers_json={
                "topology_kind": "double",
                "I": {
                    "phase_spacing_m": {"upper": 8.0, "middle": 6.0, "lower": 4.0},
                    "phase_height_m": {"upper": 38.0, "middle": 35.0, "lower": 32.0},
                },
                "II": {
                    "phase_spacing_m": {"upper": 9.0, "middle": 7.0, "lower": 5.0},
                    "phase_height_m": {"upper": 39.0, "middle": 36.0, "lower": 33.0},
                },
                "lightning_wire": {"left_mid_distance_m": 7.5, "right_mid_distance_m": 7.5},
            },
        )

        detail = tower_profile_service.upsert_tower_profile(
            session,
            tower.id,
            payload,
            actor=SimpleNamespace(id="tester"),
        )

        assert detail is not None
        assert infer_tower_topology(
            tower_model=tower.tower_model,
            tower_type=tower.tower_type,
            structure_kind=payload.structure_kind,
            geometry_topology=detail.geometry_layers_json["topology_kind"],
        ) == "double"
        assert infer_structure_count(
            tower_model=tower.tower_model,
            tower_type=tower.tower_type,
            structure_kind=payload.structure_kind,
            geometry_topology=detail.geometry_layers_json["topology_kind"],
        ) == 2
        assert detail.geometry_layers_json["lightning_wire"]["height_m"] == 45.0
        assert detail.geometry_layers_json["insulator_length_mm"] == 4800.0
        assert detail.geometry_layers_json["tower_height_m"] == 47.0
        assert detail.geometry_layers_json["II"]["phase_height_m"]["middle"] == 36.0
    finally:
        session.close()
