from __future__ import annotations

import csv
import io
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.line import LineCreateRequest
from app.services import line_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[Line.__table__, LineTower.__table__, TowerProfile.__table__])
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return testing_session()


def test_create_line_generates_code_automatically(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(line_service, "uuid4", lambda: SimpleNamespace(hex="abc123fedcba"))

        created = line_service.create_line(
            session,
            LineCreateRequest(name="示例线路", voltage_kv=500),
            actor_user_id="tester",
        )

        expected_code = f"PL-{line_service.utcnow().strftime('%Y%m%d')}-ABC123"
        saved = line_service.get_line_by_id(session, created.id)

        assert created.code == expected_code
        assert saved is not None
        assert saved.code == expected_code
        assert saved.name == "示例线路"
    finally:
        session.close()


def test_generate_line_code_skips_existing_code(monkeypatch) -> None:
    session = _build_session()
    try:
        existing_code = f"PL-{line_service.utcnow().strftime('%Y%m%d')}-ABC123"
        session.add(
            Line(
                code=existing_code,
                name="已有线路",
                status="enabled",
            )
        )
        session.commit()

        codes = iter(
            [
                SimpleNamespace(hex="abc123000000"),
                SimpleNamespace(hex="def456000000"),
            ]
        )
        monkeypatch.setattr(line_service, "uuid4", lambda: next(codes))

        generated = line_service._generate_line_code(session)

        assert generated == f"PL-{line_service.utcnow().strftime('%Y%m%d')}-DEF456"
    finally:
        session.close()


def test_delete_line_cascades_to_towers_and_profiles(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(
            code="PL-DELETE-001",
            name="待删除线路",
            status="enabled",
        )
        session.add(line)
        session.flush()

        tower = LineTower(
            line_id=line.id,
            seq_no=1,
            tower_no="T-001",
            tower_model="ZM-001",
            tower_type="直线塔",
        )
        session.add(tower)
        session.flush()

        session.add(
            TowerProfile(
                tower_id=tower.id,
                structure_kind="直线塔",
            )
        )
        session.commit()

        deleted = line_service.delete_line(session, line.id)

        assert deleted is True
        assert line_service.get_line_by_id(session, line.id) is None
        assert session.execute(select(LineTower).where(LineTower.line_id == line.id)).scalar_one_or_none() is None
        assert session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one_or_none() is None
    finally:
        session.close()


def test_export_line_towers_to_csv_includes_legacy_professional_columns() -> None:
    session = _build_session()
    try:
        line = Line(
            code="PL-LEGACY-001",
            name="遗留导出线路",
            voltage_kv=220,
            phase_sequence_json={"I": "ABC", "II": "BCA", "III": "CAB", "IV": "CBA"},
            arrester_install_json={"A": "否", "B": "否", "C": "否"},
            lightning_param_json={"电角度": 12.5, "雷电流幅值a": 28.0, "雷电流幅值b": 2.2},
            status="enabled",
        )
        session.add(line)
        session.flush()

        tower = LineTower(
            line_id=line.id,
            seq_no=1,
            tower_no="N001",
            tower_model="ZM-001",
            tower_type="直线塔",
            longitude=120.123456,
            latitude=30.654321,
            altitude_m=950.0,
            terrain="山区",
            ground_resistance_ohm=12.5,
            lightning_density=3.6,
            span_small_m=210.0,
            span_large_m=260.0,
            slope_1=1.5,
            slope_2=2.5,
            risk_level="高",
            circuit_geometry_json={
                "I": {
                    "phase_spacing_m": {"upper": 4.4, "middle": 3.3, "lower": 2.2},
                    "phase_height_m": {"upper": 30.0, "middle": 28.0, "lower": 26.0},
                },
                "III": {
                    "phase_spacing_m": {"upper": 9.1, "middle": 8.2, "lower": 7.3},
                    "phase_height_m": {"upper": 35.0, "middle": 34.0, "lower": 33.0},
                },
                "lightning_wire": {
                    "left_mid_distance_m": 7.7,
                    "right_mid_distance_m": 8.8,
                    "height_m": 39.0,
                },
                "insulator_length_mm": 4000.0,
                "tower_height_m": 38.0,
            },
            lightning_result_json={
                "counterstroke_withstand_ka": 45.0,
                "counterstroke_trip_rate": 0.6,
                "shielding_withstand_ka": 52.0,
                "shielding_trip_rate": 0.3,
                "risk_level": "高",
            },
        )
        session.add(tower)
        session.flush()

        session.add(
            TowerProfile(
                tower_id=tower.id,
                phase_sequence_1="ACB",
                phase_sequence_2="BAC",
                arrester_a="是",
                arrester_b="否",
                arrester_c="是",
                protection_angle_left_deg=8.8,
                protection_angle_right_deg=9.9,
                shield_wire_height_m=41.0,
                insulator_length_m=4200.0,
                call_height_m=40.5,
                angle_deg=18.0,
                current_a=31.0,
                current_b=2.6,
                structure_kind="耐张杆塔",
                stroke_mode="反击",
                geometry_layers_json={
                    "I": {
                        "phase_spacing_m": {"upper": 5.1, "middle": 4.2, "lower": 3.3},
                        "phase_height_m": {"upper": 31.0, "middle": 29.0, "lower": 27.0},
                    },
                    "II": {
                        "phase_spacing_m": {"upper": 6.1, "middle": 5.2, "lower": 4.3},
                        "phase_height_m": {"upper": 32.0, "middle": 30.0, "lower": 28.0},
                    },
                },
            )
        )
        session.commit()

        filename, content = line_service.export_line_towers_to_csv(session, line=line)

        assert filename.startswith("PL-LEGACY-001_towers_")

        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        assert len(rows) == 1

        row = rows[0]
        assert row["序号"] == "1"
        assert row["塔形"] == "直线塔"
        assert row["I回相序"] == "ACB"
        assert row["II回相序"] == "BAC"
        assert row["III回相序"] == "CAB"
        assert row["A相是否安装避雷器"] == "是"
        assert row["左避雷中距m"] == "8.8"
        assert row["右避雷中距m"] == "9.9"
        assert row["避雷线高度m"] == "41"
        assert row["绝缘子串长度mm"] == "4200"
        assert row["杆塔呼高m"] == "40.5"
        assert row["I回上相中距m"] == "5.1"
        assert row["III回上相中距m"] == "9.1"
        assert row["电角度"] == "18"
        assert row["雷电流幅值a"] == "31"
        assert row["直线或耐张杆塔"] == "耐张杆塔"
        assert row["绕击反击"] == "反击"
        assert row["反击耐雷水平kA"] == "45"
        assert row["绕击跳闸率(次/100km.a)"] == "0.3"
        assert row["雷击风险等级"] == "高"
        assert row["几何参数JSON"].startswith("{")
        assert row["雷电参数JSON"].startswith("{")
        assert row["额外字段JSON"] == "{}"
    finally:
        session.close()
