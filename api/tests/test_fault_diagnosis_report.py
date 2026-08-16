from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.models.fault_analysis import FaultAnalysis
from app.models.user import User
from app.services import fault_analysis_service
from app.services import fault_diagnosis_service


def _build_sessionmaker(tmp_path: Path) -> sessionmaker:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


class _SettingsShim:
    def __init__(self, vfs_root: str, ledger_csv: str, compiled_dir: str) -> None:
        self.file_vfs_root = vfs_root
        self.fault_diag_ledger_csv = ledger_csv
        self.fault_diag_matlab_compiled_dir = compiled_dir


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    SessionLocal = _build_sessionmaker(tmp_path)
    session = SessionLocal()
    settings = get_settings()
    shim = _SettingsShim(
        str(tmp_path / "vfs"),
        settings.fault_diag_ledger_csv,
        settings.fault_diag_matlab_compiled_dir,
    )
    monkeypatch.setattr(fault_diagnosis_service, "get_settings", lambda: shim)
    monkeypatch.setattr(fault_analysis_service, "get_settings", lambda: shim)
    stored: dict[str, bytes] = {}

    def fake_put_object(key: str, data: bytes, content_type: str | None = None) -> str:
        stored[key] = data
        return key

    monkeypatch.setattr(fault_diagnosis_service, "put_object", fake_put_object)
    session._test_minio_objects = stored
    yield session
    session.close()


def _sample_analysis(session: Session) -> FaultAnalysis:
    user = User(id="u1", username="tester", status="enabled", password_hash="x")
    session.add(user)
    item = FaultAnalysis(
        id="fa-report",
        title="报告测试",
        station="某站",
        line_name="某线路",
        fault_time="2023-01-01 10:00:00",
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
        status="pending",
        result_json={},
        upload_files={},
    )
    session.add(item)
    session.commit()
    return item


def test_generate_report_docx_after_diagnosis(db_session: Session, tmp_path: Path):
    item = _sample_analysis(db_session)

    fault_diagnosis_service.run_fault_diagnosis(db_session, item.id)
    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, item.id)
    assert updated.status == "completed"

    output = fault_diagnosis_service.generate_report_docx(db_session, item.id)
    assert isinstance(output, Path)
    assert output.is_file()
    assert output.name == "report.docx"
    # 文件落盘在 VFS 的 fault_analysis/{id} 目录下
    assert str(tmp_path / "vfs" / "fault_analysis" / item.id / "report.docx") == str(output)
    db_session.expire_all()
    updated = db_session.get(FaultAnalysis, item.id)
    assert updated.result_json["artifacts"]["report_docx"] == "fault-analysis/fa-report/Output/report.docx"
    assert db_session._test_minio_objects["fault-analysis/fa-report/Output/report.docx"]


def test_generate_report_docx_requires_diagnosis(db_session: Session):
    _sample_analysis(db_session)
    with pytest.raises(ValueError):
        fault_diagnosis_service.generate_report_docx(db_session, "fa-report")


def test_generate_report_docx_missing_analysis(db_session: Session):
    with pytest.raises(ValueError):
        fault_diagnosis_service.generate_report_docx(db_session, "fa-不存在")
