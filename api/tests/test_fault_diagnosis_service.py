from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.models.fault_analysis import FaultAnalysis
from app.models.user import User
from app.schemas.fault_analysis import FaultAnalysisCreateRequest
from app.services import fault_analysis_service
from app.services import fault_diagnosis_service


def _build_sessionmaker(tmp_path: Path) -> sessionmaker:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _sample_user(session: Session) -> User:
    user = User(id="u1", username="tester", status="enabled", password_hash="x")
    session.add(user)
    session.commit()
    return user


def _sample_analysis(session: Session) -> FaultAnalysis:
    item = FaultAnalysis(
        id="fa-sample",
        title="龙和线故障",
        station="广东河源500kV上寨变",
        line_name="220kV 龙和线",
        fault_time="2023-03-27 20:20:31.939",
        fault_phase="AN",
        fault_duration_ms=64,
        reclosure_status="success",
        fault_voltage_v=37.04,
        fault_current_a=1.3,
        max_zero_current_a=1.45,
        zero_compensation=0.52,
        line_length_km=89.77,
        line_angle_deg=85,
        line_impedance_ohm=28.520,
        lightning_current_ka=20.3,
        wave_distance_km=16.022,
        traveling_wave_distance_km=16.51,
        status="pending",
        result_json={},
        upload_files={},
    )
    session.add(item)
    session.commit()
    return item


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    SessionLocal = _build_sessionmaker(tmp_path)
    session = SessionLocal()
    # 将判别服务的共享卷指向临时目录，避免写入仓库 data/。
    settings = get_settings()
    shim = _SettingsShim(
        str(tmp_path / "vfs"),
        settings.fault_diag_ledger_csv,
        settings.fault_diag_matlab_compiled_dir,
    )
    monkeypatch.setattr(fault_diagnosis_service, "get_settings", lambda: shim)
    monkeypatch.setattr(fault_analysis_service, "get_settings", lambda: shim)
    yield session
    session.close()


class _SettingsShim:
    def __init__(self, vfs_root: str, ledger_csv: str, compiled_dir: str) -> None:
        self.file_vfs_root = vfs_root
        self.fault_diag_ledger_csv = ledger_csv
        self.fault_diag_matlab_compiled_dir = compiled_dir


def test_run_fault_diagnosis_completes_and_backfills(db_session: Session):
    _sample_user(db_session)
    item = _sample_analysis(db_session)

    result = fault_diagnosis_service.run_fault_diagnosis(db_session, item.id)

    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, item.id)
    assert updated.status == "completed"
    assert updated.risk_level in {"low", "medium", "high"}
    assert updated.fault_type  # 例如 "A相单相接地"
    assert updated.fault_phase == "A"
    assert updated.confidence is not None
    assert updated.confidence > 0

    assert isinstance(updated.result_json, dict)
    assert "sections" in updated.result_json
    assert updated.result_json["sections"]
    assert "diagnosis" in updated.result_json
    assert updated.result_json["diagnosis"]["ground_fault_decision"]["is_ground_fault"] is True
    assert result == updated.result_json


def test_run_fault_diagnosis_degrades_with_minimal_input(db_session: Session):
    _sample_user(db_session)
    item = FaultAnalysis(
        id="fa-minimal",
        title="最小输入",
        station="某站",
        fault_time="2023-01-01 10:00:00",
        line_name="某线路",
        fault_phase="B",
        status="pending",
        result_json={},
        upload_files={},
    )
    db_session.add(item)
    db_session.commit()

    result = fault_diagnosis_service.run_fault_diagnosis(db_session, item.id)

    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, item.id)
    # 判别系统在输入不足时不应抛异常，而是降级输出。
    assert updated.status == "completed"
    assert "sections" in updated.result_json
    assert updated.fault_type is not None


def test_run_fault_diagnosis_with_traveling_wave_file(db_session: Session, tmp_path: Path):
    _sample_user(db_session)
    # 构造一个可解析的行波 TXT（Key=Value + CurrentDataInput）。
    samples = ",".join(str(value) for value in [1.0] * 40)
    wave_dir = tmp_path / "vfs" / "fault_analysis" / "fa-wave"
    wave_dir.mkdir(parents=True)
    wave_file = wave_dir / "wave_data_file_A相_1号杆塔.txt"
    wave_file.write_text(f"SampleFrequency=1000000\nCurrentDataInput={samples}\n", encoding="utf-8")

    item = FaultAnalysis(
        id="fa-wave",
        title="行波测试",
        station="某站",
        fault_time="2023-01-01 10:00:00",
        line_name="某线路",
        fault_phase="AN",
        fault_duration_ms=64,
        fault_voltage_v=37.04,
        fault_current_a=1.3,
        max_zero_current_a=1.45,
        zero_compensation=0.52,
        line_length_km=89.77,
        line_angle_deg=85,
        line_impedance_ohm=28.520,
        status="pending",
        result_json={},
        upload_files={"traveling_wave_file": wave_file.relative_to(tmp_path / "vfs").as_posix()},
    )
    db_session.add(item)
    db_session.commit()

    result = fault_diagnosis_service.run_fault_diagnosis(db_session, item.id)

    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, item.id)
    assert updated.status == "completed"
    wave_analysis = updated.result_json["diagnosis"]["traveling_wave_analysis"]
    assert wave_analysis["phase_analyses"]  # 已解析行波相
    assert wave_analysis["status"] in {"analyzed", "needs_review"}


def test_store_upload_file_and_create_analysis(db_session: Session, tmp_path: Path):
    _sample_user(db_session)
    relative = fault_analysis_service.store_analysis_upload_file(
        "fa-upload", "wave_data_file", "a.txt", b"hello"
    )
    assert (tmp_path / "vfs" / relative).is_file()
    assert relative.endswith("a.txt")


def test_create_analysis_dispatches_and_fails_gracefully_without_broker(
    db_session: Session, monkeypatch
):
    _sample_user(db_session)
    from app.tasks import fault_diagnosis_tasks

    def _raise(*args, **kwargs):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(fault_diagnosis_tasks.run_fault_diagnosis_task, "delay", _raise)
    payload = FaultAnalysisCreateRequest(
        title="创建测试",
        station="某站",
        fault_time="2023-01-01 10:00:00",
        line_name="某线路",
        fault_phase="AN",
        line_id="l1",
    )

    user = db_session.query(User).first()
    response = fault_analysis_service.create_analysis(
        db_session, payload, actor=user, auto_diagnose=True
    )
    assert response.analysis.id
    # 队列不可用时创建仍成功，记录被标记为失败并记录原因。
    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, response.analysis.id)
    assert updated.status == "failed"
    assert "error" in updated.result_json

