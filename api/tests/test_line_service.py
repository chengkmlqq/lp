from __future__ import annotations

import csv
import io
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.schemas.line import LineCreateRequest
from app.services import line_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Line.__table__,
            LineTower.__table__,
            TowerProfile.__table__,
            TowerCircuit.__table__,
            TowerLightningResult.__table__,
            TowerAnalysis.__table__,
        ],
    )
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
        )
        session.add(tower)
        session.flush()

        session.add_all(
            [
                TowerCircuit(
                    tower_id=tower.id,
                    circuit_no=1,
                    phase_sequence="ACB",
                    spacing_upper_m=5.1,
                    spacing_middle_m=4.2,
                    spacing_lower_m=3.3,
                    height_upper_m=31.0,
                    height_middle_m=29.0,
                    height_lower_m=27.0,
                ),
                TowerCircuit(
                    tower_id=tower.id,
                    circuit_no=2,
                    phase_sequence="BAC",
                    spacing_upper_m=6.1,
                    spacing_middle_m=5.2,
                    spacing_lower_m=4.3,
                    height_upper_m=32.0,
                    height_middle_m=30.0,
                    height_lower_m=28.0,
                ),
                TowerCircuit(
                    tower_id=tower.id,
                    circuit_no=3,
                    spacing_upper_m=9.1,
                    spacing_middle_m=8.2,
                    spacing_lower_m=7.3,
                    height_upper_m=35.0,
                    height_middle_m=34.0,
                    height_lower_m=33.0,
                ),
            ]
        )
        session.add(
            TowerLightningResult(
                tower_id=tower.id,
                counterstroke_withstand_ka=45.0,
                counterstroke_trip_rate=0.6,
                shielding_withstand_ka=52.0,
                shielding_trip_rate=0.3,
                risk_level="高",
            )
        )
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
            )
        )
        session.commit()

        filename, content = line_service.export_line_towers_to_csv(session, line=line)

        assert filename.startswith("PL-LEGACY-001_towers_")

        # 导出对齐 C#：UTF-8 无 BOM、固定 69 列（1-63 + 原因分析 + 措施推荐 + ZV 四变量），不含 JSON 列
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
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
        assert row["原因分析"] == ""
        assert row["措施推荐"] == ""
        header = next(csv.reader(io.StringIO(content.decode("utf-8"))))
        assert len(header) == 69
        assert header[-4:] == ["波速(m/s)", "主材波阻抗(Ω)", "横材波阻抗(Ω)", "斜材波阻抗(Ω)"]
        assert not any("JSON" in name for name in header)
    finally:
        session.close()


def test_export_line_towers_csv_round_trips_zv_params(monkeypatch) -> None:
    """LP-140：ZV 四变量导出为末尾 4 列，重新导入后值不变。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)
        line = Line(code="PL-ZV-RT", name="ZV 往返线路", voltage_kv=66, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="shangzi")
        session.add(tower)
        session.flush()
        session.add(
            TowerProfile(
                tower_id=tower.id,
                extra_profile_json={
                    "zv_params": {"wave_speed_m_s": 2.4e8, "z_1": 151.5, "z_2": 205.0, "z_3": 1360.0}
                },
            )
        )
        session.commit()

        _filename, content = line_service.export_line_towers_to_csv(session, line=line)
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
        assert len(rows) == 1
        row = rows[0]
        assert row["波速(m/s)"] == "240000000"
        assert row["主材波阻抗(Ω)"] == "151.5"
        assert row["横材波阻抗(Ω)"] == "205"
        assert row["斜材波阻抗(Ω)"] == "1360"

        # 清空后按导出内容重新导入，注入值原样带回
        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        profile.extra_profile_json = {}
        session.commit()
        line_service._upsert_tower_profile_from_legacy_row(
            session, tower=tower, row=row, actor_user_id="tester"
        )
        session.commit()
        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        assert (profile.extra_profile_json or {}).get("zv_params") == {
            "wave_speed_m_s": 240000000.0,
            "z_1": 151.5,
            "z_2": 205.0,
            "z_3": 1360.0,
        }
    finally:
        session.close()


def test_export_line_towers_uses_lightning_wire_mid_distance_and_skips_absent_circuits() -> None:
    """1 回线路导出：II/III/IV 相序留空，左/右避雷中距取 lightning_wire 真实值。

    回归：曾把「左/右避雷中距m」按 protection_angle_*_deg 优先导出（值为 0），
    再把历史遗留的 profile.phase_sequence_2/3/4（ABC）写进 II/III/IV 列，
    导入后 1 回线路被放大成 4 回、避雷线中距变成 0 → ATP KILL=78。
    """
    session = _build_session()
    try:
        line = Line(
            code="PL-FIX-001",
            name="单回导出线路",
            voltage_kv=115,
            phase_sequence_json={"I": "ABC"},
            status="enabled",
        )
        session.add(line)
        session.flush()

        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="ganzi")
        session.add(tower)
        session.flush()
        session.add(
            TowerCircuit(
                tower_id=tower.id,
                circuit_no=1,
                phase_sequence="ABC",
                spacing_upper_m=6.0,
                spacing_middle_m=5.6,
                spacing_lower_m=5.0,
                height_upper_m=30.0,
                height_middle_m=28.0,
                height_lower_m=26.0,
            )
        )
        # 历史污染：1 回线路的 profile 里 II/III/IV 相序都是 ABC，保护角是 0
        session.add(
            TowerProfile(
                tower_id=tower.id,
                phase_sequence_1="ABC",
                phase_sequence_2="ABC",
                phase_sequence_3="ABC",
                phase_sequence_4="ABC",
                protection_angle_left_deg=0.0,
                protection_angle_right_deg=0.0,
                shield_wire_height_m=20.0,
                extra_profile_json={"lightning_wire": {"left_mid_distance_m": 5.6, "right_mid_distance_m": 5.6}},
            )
        )
        session.commit()

        _, content = line_service.export_line_towers_to_csv(session, line=line)
        row = next(iter(csv.DictReader(io.StringIO(content.decode("utf-8")))))

        assert row["I回相序"] == "ABC"
        assert row["II回相序"] == ""
        assert row["III回相序"] == ""
        assert row["IV回相序"] == ""
        assert row["左避雷中距m"] == "5.6"
        assert row["右避雷中距m"] == "5.6"
    finally:
        session.close()


def test_import_legacy_row_drops_zero_mid_distance_and_keeps_protection_angle() -> None:
    """导入：中距 0 按缺失处理，且不得写进 protection_angle_*_deg，也不新建空回路。"""
    session = _build_session()
    try:
        line = Line(code="PL-FIX-002", name="单回导入线路", voltage_kv=115, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="ganzi")
        session.add(tower)
        session.flush()
        session.add(
            TowerCircuit(
                tower_id=tower.id,
                circuit_no=1,
                phase_sequence="ABC",
                spacing_upper_m=6.0,
                spacing_middle_m=5.6,
                spacing_lower_m=5.0,
                height_upper_m=30.0,
                height_middle_m=28.0,
                height_lower_m=26.0,
            )
        )
        session.add(TowerProfile(tower_id=tower.id, protection_angle_left_deg=0.0, protection_angle_right_deg=0.0))
        session.commit()

        import_row = {
            "I回相序": "ABC",
            "II回相序": "ABC",
            "III回相序": "ABC",
            "IV回相序": "ABC",
            "左避雷中距m": "0",
            "右避雷中距m": "0",
            "避雷线高度m": "20",
        }
        line_service._upsert_tower_profile_from_legacy_row(
            session, tower=tower, row=import_row, actor_user_id="tester"
        )
        line_service._upsert_tower_circuits_from_legacy_row(
            session, tower=tower, row=import_row, actor_user_id="tester"
        )
        session.commit()

        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        lightning_wire = (profile.extra_profile_json or {}).get("lightning_wire") or {}
        circuits = session.execute(select(TowerCircuit).where(TowerCircuit.tower_id == tower.id)).scalars().all()

        assert "left_mid_distance_m" not in lightning_wire
        assert "right_mid_distance_m" not in lightning_wire
        assert profile.protection_angle_left_deg == 0.0
        assert profile.protection_angle_right_deg == 0.0
        # 空回路不新建、已有回路的几何不被空值覆盖
        assert sorted(circuit.circuit_no for circuit in circuits) == [1]
        assert circuits[0].spacing_middle_m == 5.6
    finally:
        session.close()


def test_import_legacy_row_writes_real_mid_distance_to_lightning_wire() -> None:
    session = _build_session()
    try:
        line = Line(code="PL-FIX-003", name="中距导入线路", voltage_kv=115, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="ganzi")
        session.add(tower)
        session.flush()
        session.add(TowerProfile(tower_id=tower.id, protection_angle_left_deg=0.0))
        session.commit()

        line_service._upsert_tower_profile_from_legacy_row(
            session,
            tower=tower,
            row={"左避雷中距m": "5.6", "右避雷中距m": "5.7"},
            actor_user_id="tester",
        )
        session.commit()

        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        lightning_wire = (profile.extra_profile_json or {}).get("lightning_wire") or {}
        assert lightning_wire.get("left_mid_distance_m") == 5.6
        assert lightning_wire.get("right_mid_distance_m") == 5.7
        # 保护角不被中距污染
        assert profile.protection_angle_left_deg == 0.0
    finally:
        session.close()



def test_import_legacy_row_writes_zv_params_from_new_columns() -> None:
    """LP-140：CSV 新增 4 列（波速/主材、横材、斜材波阻抗）落到 extra_profile_json.zv_params。"""
    session = _build_session()
    try:
        line = Line(code="PL-FIX-ZV", name="ZV 注入线路", voltage_kv=66, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="shangzi")
        session.add(tower)
        session.flush()
        session.commit()

        line_service._upsert_tower_profile_from_legacy_row(
            session,
            tower=tower,
            row={
                "波速(m/s)": "255000000",
                "主材波阻抗(Ω)": "160.5",
                "横材波阻抗(Ω)": "",
                "斜材波阻抗(Ω)": "1400",
            },
            actor_user_id="tester",
        )
        session.commit()

        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        zv = (profile.extra_profile_json or {}).get("zv_params") or {}
        assert zv == {"wave_speed_m_s": 255000000.0, "z_1": 160.5, "z_3": 1400.0}

        # 旧版 65 列文件（无 ZV 列）重导：不清掉已有注入值
        line_service._upsert_tower_profile_from_legacy_row(
            session,
            tower=tower,
            row={"绝缘子串长度mm": "5945"},
            actor_user_id="tester",
        )
        session.commit()
        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        assert (profile.extra_profile_json or {}).get("zv_params") == zv
    finally:
        session.close()


def test_import_accepts_legacy_zv_csv_headers() -> None:
    """LP-146：存量 CSV 的旧表头「塔材波阻抗1/2/3(Ω)」重导仍能取到值。"""
    session = _build_session()
    try:
        line = Line(code="PL-FIX-ZV-OLD", name="ZV 旧表头线路", voltage_kv=66, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="shangzi")
        session.add(tower)
        session.flush()
        session.commit()

        line_service._upsert_tower_profile_from_legacy_row(
            session,
            tower=tower,
            row={
                "波速(m/s)": "240000000",
                "塔材波阻抗1(Ω)": "151.5",
                "塔材波阻抗2(Ω)": "205",
                "塔材波阻抗3(Ω)": "1360",
            },
            actor_user_id="tester",
        )
        session.commit()

        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        assert (profile.extra_profile_json or {}).get("zv_params") == {
            "wave_speed_m_s": 240000000.0,
            "z_1": 151.5,
            "z_2": 205.0,
            "z_3": 1360.0,
        }
    finally:
        session.close()


def test_remap_english_csv_header_accepts_legacy_zv_names() -> None:
    """LP-146：存量英文 CSV 的旧表头重导时映射到新中文列名。"""
    header = list(line_service.LINE_TOWER_CSV_HEADERS_EN)
    assert header[-3:] == [
        "Main material surge impedance (ohm)",
        "Cross material surge impedance (ohm)",
        "Diagonal material surge impedance (ohm)",
    ]
    header[-3:] = [
        "Tower material surge impedance 1 (ohm)",
        "Tower material surge impedance 2 (ohm)",
        "Tower material surge impedance 3 (ohm)",
    ]
    remapped = line_service._remap_english_csv_header(header)
    assert remapped[-3:] == ["主材波阻抗(Ω)", "横材波阻抗(Ω)", "斜材波阻抗(Ω)"]


def test_update_line_tower_sets_and_clears_zv_params() -> None:
    """LP-140：杆塔编辑 PATCH 可写入/清空 ZV 四变量（None → 回默认值）。"""
    session = _build_session()
    try:
        line = Line(code="PL-FIX-ZV2", name="ZV 编辑线路", voltage_kv=66, status="enabled")
        session.add(line)
        session.flush()
        tower = LineTower(line_id=line.id, seq_no=1, tower_no="N001", tower_type="shangzi")
        session.add(tower)
        session.flush()
        session.commit()

        from app.schemas.line import LineTowerUpdateRequest

        updated = line_service.update_line_tower(
            session,
            tower.id,
            LineTowerUpdateRequest(wave_speed_m_s=2.4e8, tower_z_1=151.0, tower_z_2=201.0, tower_z_3=1355.0),
            actor_user_id="tester",
        )
        assert updated is not None
        assert updated.wave_speed_m_s == 2.4e8
        assert updated.tower_z_1 == 151.0
        assert updated.tower_z_3 == 1355.0

        cleared = line_service.update_line_tower(
            session,
            tower.id,
            LineTowerUpdateRequest(wave_speed_m_s=None, tower_z_1=None, tower_z_2=None, tower_z_3=None),
            actor_user_id="tester",
        )
        assert cleared is not None
        assert cleared.wave_speed_m_s is None
        profile = session.execute(select(TowerProfile).where(TowerProfile.tower_id == tower.id)).scalar_one()
        assert (profile.extra_profile_json or {}).get("zv_params") is None
    finally:
        session.close()


def test_list_lines_returns_estimated_length_from_tower_coordinates(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(
            code="PL-EST-001",
            name="估算长度线路",
            voltage_kv=220,
            status="enabled",
        )
        session.add(line)
        session.flush()

        # 3 towers with valid coordinates + 1 tower without coordinates.
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="E001", longitude=120.0, latitude=30.0),
                LineTower(line_id=line.id, seq_no=2, tower_no="E002", longitude=120.01, latitude=30.0),
                LineTower(line_id=line.id, seq_no=3, tower_no="E003", longitude=120.02, latitude=30.0),
                LineTower(line_id=line.id, seq_no=4, tower_no="E004"),
            ]
        )
        session.commit()

        response = line_service.list_lines(session, keyword=None)
        assert response.total == 1
        item = response.items[0]
        assert item.tower_count == 4
        assert item.estimated_length_km is not None
        assert item.estimated_length_km > 0

        # Haversine distance: ~0.01 deg longitude at 30 deg latitude ≈ 0.9616 km
        # per pair, so 2 pairs should sum to roughly 1.92 km.
        assert abs(item.estimated_length_km - 2 * _expected_km_per_0_01_deg_at_30()) < 0.05
    finally:
        session.close()


def test_list_lines_estimated_length_breaks_at_invalid_coordinates(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(
            code="PL-EST-002",
            name="估算长度分段线路",
            voltage_kv=220,
            status="enabled",
        )
        session.add(line)
        session.flush()

        # Middle tower has no coordinates → route is split into 2 segments,
        # each contributing one pair of consecutive distances.
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="E011", longitude=120.0, latitude=30.0),
                LineTower(line_id=line.id, seq_no=2, tower_no="E012", longitude=120.01, latitude=30.0),
                LineTower(line_id=line.id, seq_no=3, tower_no="E013"),
                LineTower(line_id=line.id, seq_no=4, tower_no="E014", longitude=120.02, latitude=30.0),
                LineTower(line_id=line.id, seq_no=5, tower_no="E015", longitude=120.03, latitude=30.0),
            ]
        )
        session.commit()

        response = line_service.list_lines(session, keyword=None)
        item = response.items[0]
        assert item.estimated_length_km is not None
        expected = 2 * _expected_km_per_0_01_deg_at_30()
        assert abs(item.estimated_length_km - expected) < 0.05
    finally:
        session.close()


def test_list_lines_estimated_length_none_without_coordinates(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(
            code="PL-EST-003",
            name="无坐标线路",
            voltage_kv=220,
            status="enabled",
        )
        session.add(line)
        session.flush()

        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="E021"),
                LineTower(line_id=line.id, seq_no=2, tower_no="E022"),
            ]
        )
        session.commit()

        response = line_service.list_lines(session, keyword=None)
        item = response.items[0]
        assert item.tower_count == 2
        assert item.estimated_length_km is None
    finally:
        session.close()


def test_get_line_detail_summary_includes_estimated_length(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line = Line(
            code="PL-EST-004",
            name="详情估算长度线路",
            voltage_kv=220,
            status="enabled",
        )
        session.add(line)
        session.flush()

        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="E031", longitude=120.0, latitude=30.0),
                LineTower(line_id=line.id, seq_no=2, tower_no="E032", longitude=120.01, latitude=30.0),
            ]
        )
        session.commit()

        detail = line_service.get_line_detail_summary(session, line.id)
        assert detail is not None
        assert detail.id == line.id
        assert detail.tower_count == 2
        assert detail.estimated_length_km is not None
        assert detail.estimated_length_km > 0
        assert abs(detail.estimated_length_km - _expected_km_per_0_01_deg_at_30()) < 0.05
    finally:
        session.close()


def test_get_line_detail_summary_missing_line_returns_none(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)
        assert line_service.get_line_detail_summary(session, "missing-line-id") is None
    finally:
        session.close()


def _expected_km_per_0_01_deg_at_30() -> float:
    from app.services.line_service import _haversine_km

    return _haversine_km(30.0, 120.0, 30.0, 120.01)


def test_list_lines_bbox_filters_lines_with_overlapping_towers(monkeypatch) -> None:
    """bbox 过滤：仅保留杆塔经纬度与 bbox 有矩形重叠的线路（含端点）。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        inside = Line(code="PL-IN-001", name="内部线路", voltage_kv=220, status="enabled")
        boundary = Line(code="PL-BD-001", name="边界线路", voltage_kv=220, status="enabled")
        outside = Line(code="PL-OU-001", name="外部线路", voltage_kv=220, status="enabled")
        session.add_all([inside, boundary, outside])
        session.flush()

        session.add_all(
            [
                # 含端点：max(min_lat)<=min(max_lat)：30.0 落在 [30.0, 31.0] 内 → 保留
                LineTower(line_id=inside.id, seq_no=1, tower_no="I001", longitude=120.0, latitude=30.0),
                # 恰好压在 bbox 边界（经度 121.0、纬度 31.0）→ 保留
                LineTower(line_id=boundary.id, seq_no=1, tower_no="B001", longitude=121.0, latitude=31.0),
                # 超出 bbox（纬度 40）→ 排除
                LineTower(line_id=outside.id, seq_no=1, tower_no="O001", longitude=121.0, latitude=40.0),
            ]
        )
        session.commit()

        # bbox: min_lat=30.0, min_lon=120.0, max_lat=31.0, max_lon=121.0
        response = line_service.list_lines(session, keyword=None, bbox=(30.0, 120.0, 31.0, 121.0))

        codes = sorted(item.code for item in response.items)
        assert codes == ["PL-BD-001", "PL-IN-001"]
        assert response.total == 2
    finally:
        session.close()


def test_list_lines_bbox_none_returns_all_lines(monkeypatch) -> None:
    """bbox 缺省（None）时行为不变，返回全部线路（向后兼容）。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        line_a = Line(code="PL-A-001", name="线路A", status="enabled")
        line_b = Line(code="PL-B-001", name="线路B", status="enabled")
        session.add_all([line_a, line_b])
        session.flush()
        session.add_all(
            [
                LineTower(line_id=line_a.id, seq_no=1, tower_no="A001", longitude=120.0, latitude=30.0),
                LineTower(line_id=line_b.id, seq_no=1, tower_no="B001"),  # 无坐标
            ]
        )
        session.commit()

        response = line_service.list_lines(session, keyword=None)

        assert response.total == 2
        assert len(response.items) == 2
    finally:
        session.close()


def test_list_lines_bbox_ignores_towers_without_coordinates(monkeypatch) -> None:
    """无经纬度的杆塔不参与重叠判定，不会导致线路被错误保留或误伤。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        no_coord_line = Line(code="PL-NC-001", name="无坐标线路", status="enabled")
        session.add(no_coord_line)
        session.flush()
        session.add(LineTower(line_id=no_coord_line.id, seq_no=1, tower_no="N001"))
        session.commit()

        response = line_service.list_lines(session, keyword=None, bbox=(0.0, 0.0, 10.0, 10.0))

        assert response.total == 0
        assert response.items == []
    finally:
        session.close()


def test_list_lines_pagination_limits_items_and_keeps_total(monkeypatch) -> None:
    """limit/offset 分页：items 截断、total 保持全量计数（与线路管理分页一致）。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        from datetime import datetime, timezone

        fixed_date = datetime(2026, 8, 9, tzinfo=timezone.utc)
        for i in range(1, 6):
            session.add(
                Line(
                    code=f"PL-PG-{i:03d}",
                    name=f"分页线路{i}",
                    status="enabled",
                    create_date=fixed_date,
                    update_date=fixed_date,
                )
            )
        session.commit()

        # update_date 相同 → 按 code asc 排序，便于断言分页切片
        first_page = line_service.list_lines(session, keyword=None, limit=2, offset=0)
        assert first_page.total == 5
        assert len(first_page.items) == 2
        assert {item.code for item in first_page.items} == {"PL-PG-001", "PL-PG-002"}

        second_page = line_service.list_lines(session, keyword=None, limit=2, offset=2)
        assert second_page.total == 5
        assert len(second_page.items) == 2
        assert {item.code for item in second_page.items} == {"PL-PG-003", "PL-PG-004"}

        last_page = line_service.list_lines(session, keyword=None, limit=2, offset=4)
        assert last_page.total == 5
        assert len(last_page.items) == 1
        assert last_page.items[0].code == "PL-PG-005"
    finally:
        session.close()


def test_list_lines_pagination_keyword_keeps_total_scoped(monkeypatch) -> None:
    """分页 + 关键词：total 为筛选后全量，items 为当前页（按 update_date desc/code asc）。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        from datetime import datetime, timezone

        fixed_date = datetime(2026, 8, 9, tzinfo=timezone.utc)
        for i in range(1, 5):
            session.add(
                Line(
                    code=f"PL-KW-{i:03d}",
                    name=f"目标线路{i}",
                    status="enabled",
                    create_date=fixed_date,
                    update_date=fixed_date,
                )
            )
        session.add(
            Line(
                code="PL-OTHER-001",
                name="无关线路",
                status="enabled",
                create_date=fixed_date,
                update_date=fixed_date,
            )
        )
        session.commit()

        response = line_service.list_lines(session, keyword="目标", limit=2, offset=0)
        assert response.total == 4
        assert len(response.items) == 2
        assert all("目标" in item.name for item in response.items)

        response_all = line_service.list_lines(session, keyword="目标", limit=10, offset=0)
        assert response_all.total == 4
        assert len(response_all.items) == 4
    finally:
        session.close()


def test_list_lines_voltage_kv_filter_combines_with_keyword_and_pagination(monkeypatch) -> None:
    """电压等级过滤：精确匹配 voltage_kv，与 keyword/分页叠加且 total 为筛选后全量。"""
    session = _build_session()
    try:
        monkeypatch.setattr(line_service, "_publish_line_change", lambda *args, **kwargs: None)

        from datetime import datetime, timezone

        fixed_date = datetime(2026, 8, 9, tzinfo=timezone.utc)
        rows = [
            ("PL-VOL-001", "目标110线路一", 110),
            ("PL-VOL-002", "目标110线路二", 110),
            ("PL-VOL-003", "目标220线路", 220),
            ("PL-VOL-004", "无关110线路", 110),
            ("PL-VOL-005", "目标500线路", 500),
        ]
        for code, name, voltage_kv in rows:
            session.add(
                Line(
                    code=code,
                    name=name,
                    voltage_kv=voltage_kv,
                    status="enabled",
                    create_date=fixed_date,
                    update_date=fixed_date,
                )
            )
        session.commit()

        # 仅按电压等级：total 与 items 都只含 110kV
        only_voltage = line_service.list_lines(session, keyword=None, voltage_kv=110)
        assert only_voltage.total == 3
        assert {item.code for item in only_voltage.items} == {"PL-VOL-001", "PL-VOL-002", "PL-VOL-004"}

        # 电压等级 + 关键词：条件叠加，total 为筛选后全量
        combined = line_service.list_lines(session, keyword="目标", voltage_kv=110)
        assert combined.total == 2
        assert {item.code for item in combined.items} == {"PL-VOL-001", "PL-VOL-002"}

        # 叠加分页：items 截断但 total 保持筛选后全量
        page = line_service.list_lines(session, keyword="目标", voltage_kv=110, limit=1, offset=0)
        assert page.total == 2
        assert len(page.items) == 1
        assert page.items[0].code == "PL-VOL-001"

        # 未指定电压等级时不过滤（缺省向后兼容）
        without_filter = line_service.list_lines(session, keyword=None)
        assert without_filter.total == 5
    finally:
        session.close()
