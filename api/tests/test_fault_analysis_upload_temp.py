from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.fault_analysis import FaultAnalysis
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.core import file_upload
from app.api.v1 import fault_analysis as fault_analysis_api
from app.services import fault_analysis_service


def _build_sessionmaker(tmp_path: Path) -> sessionmaker:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    SessionLocal = _build_sessionmaker(tmp_path)
    session = SessionLocal()
    shim = SimpleNamespace(file_vfs_root=str(tmp_path / "vfs"))
    monkeypatch.setattr(fault_analysis_service, "get_settings", lambda: shim)
    yield session
    session.close()


def _make_upload_file(filename: str, content: bytes):
    class _FakeFile:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def tell(self) -> int:
            return 0

        def seek(self, offset: int, whence: int = 0) -> int:
            return 0

    class _Upload:
        def __init__(self, name: str, data: bytes) -> None:
            self.filename = name
            self.file = _FakeFile(data)

    return _Upload(filename, content)


def _make_line(session: Session, name: str = "220kV 龙和线") -> dict:
    line = Line(code=f"code-{name}", name=name, voltage_kv=220)
    session.add(line)
    session.flush()
    tower = LineTower(
        line_id=line.id,
        seq_no=1,
        tower_no="N65",
        tower_model="ZM1",
        tower_type="直线",
        longitude=114.50476,
        latitude=23.79996,
        altitude_m=120.5,
        terrain="山地",
        ground_resistance_ohm=12.5,
        lightning_density=4.2,
        risk_level="中",
    )
    session.add(tower)
    session.flush()
    profile = TowerProfile(tower_id=tower.id, insulator_length_m=1.8)
    session.add(profile)
    lightning = TowerLightningResult(
        tower_id=tower.id,
        counterstroke_withstand_ka=85.0,
        shielding_withstand_ka=35.0,
    )
    session.add(lightning)
    session.commit()
    return {"line_id": line.id, "tower_id": tower.id, "line_name": name}


def test_store_and_resolve_temp_upload(monkeypatch) -> None:
    """temp_file_id 归属校验 + 消费后删除（通用 upload-temp 链路）。"""
    from app.services import minio_storage

    stored: dict[str, bytes] = {}

    def mock_put(key, data, content_type=None) -> str:
        stored[key] = data
        return key

    def mock_get(key):
        if key not in stored:
            raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")
        return stored[key]

    monkeypatch.setattr(minio_storage, "put_object", mock_put)
    monkeypatch.setattr(minio_storage, "get_object", mock_get)
    monkeypatch.setattr(minio_storage, "delete_object", lambda key: stored.pop(key, None))

    upload = _make_upload_file("1_录波数据.txt", b"wave-form-data")
    temp_file_id, file_name = file_upload.save_temp_upload(upload, "u1")
    assert file_name == "1_录波数据.txt"
    assert temp_file_id.startswith("lightning/tmp/u1/")
    assert temp_file_id.endswith("1_录波数据.txt")

    content, resolved_name = file_upload.resolve_temp_upload(temp_file_id, "u1")
    assert content == b"wave-form-data"
    assert resolved_name == "1_录波数据.txt"
    # 消费后临时对象已删除
    assert temp_file_id not in stored


def test_resolve_temp_upload_wrong_user(monkeypatch) -> None:
    """temp_file_id 不属于当前用户时返回 400。"""
    from fastapi import HTTPException
    from app.services import minio_storage

    monkeypatch.setattr(minio_storage, "put_object", lambda key, data, content_type=None: key)

    with pytest.raises(HTTPException) as captured:
        file_upload.resolve_temp_upload(
            "lightning/tmp/other-user/abc123_test.csv",
            "u1",
        )
    assert captured.value.status_code == 400
    assert "不属于当前用户" in str(captured.value.detail)


def test_validate_upload_bytes_rejects_bad_extension() -> None:
    """两段式提交校验：台账临时文件扩展名不在白名单时返回 400（LP-378）。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
        file_upload.validate_upload_bytes(
            "tower-data.xlsx",
            b"ledger-content",
            allowed_exts={"csv"},
        )
    assert captured.value.status_code == 400
    assert "不支持的文件格式" in str(captured.value.detail)


def test_validate_upload_bytes_rejects_oversize() -> None:
    """两段式提交校验：临时文件超过大小上限时返回 413（LP-378）。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
        file_upload.validate_upload_bytes(
            "wave.txt",
            b"x" * (2 * 1024 * 1024),
            max_mb=1,
            allowed_exts={"txt"},
        )
    assert captured.value.status_code == 413
    assert "超过限制" in str(captured.value.detail)


def test_validate_upload_bytes_accepts_valid() -> None:
    """两段式提交校验：符合扩展名与大小限制时放行（LP-378）。"""
    file_upload.validate_upload_bytes(
        "wave.txt",
        b"wave",
        max_mb=1,
        allowed_exts={"txt"},
    )


def test_assemble_ledger_rows_maps_system_data(db_session) -> None:
    """台账自动组装：系统表数据按 LEDGER_OUTPUT_FIELDS 16 列映射（LP-378）。"""
    made = _make_line(db_session)
    rows = fault_analysis_service.assemble_ledger_rows(db_session, made["line_id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["线路名称"] == "220kV 龙和线"
    assert row["电压等级"] == 220
    assert row["塔号"] == "N65"
    assert row["地形"] == "山地"
    assert row["地闪密度"] == 4.2
    assert row["海拔m"] == 120.5
    assert row["杆塔模型"] == "ZM1"
    assert row["塔形"] == "直线"
    assert row["直线或耐张杆塔"] == "直线"
    # 绝缘子串长度米转毫米
    assert row["绝缘子串长度mm"] == 1800.0
    assert row["接地电阻"] == 12.5
    assert row["反击耐雷水平kA"] == 85.0
    assert row["绕击耐雷水平kA"] == 35.0
    assert row["雷击风险等级"] == "中"
    assert row["经度"] == 114.50476
    assert row["纬度"] == 23.79996
    assert set(row.keys()) == set(fault_analysis_service.LEDGER_OUTPUT_FIELDS)


def test_assemble_ledger_rows_raises_for_missing_line(db_session) -> None:
    """台账自动组装：线路不存在时返回 404（LP-378）。"""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as captured:
        fault_analysis_service.assemble_ledger_rows(db_session, "no-such-line")
    assert captured.value.status_code == 404


def test_assemble_ledger_csv_writes_csv(db_session) -> None:
    """台账自动组装：生成判别所需 CSV 并落盘到分析目录（LP-378）。"""
    made = _make_line(db_session)
    relative, row_count = fault_analysis_service.assemble_ledger_csv(
        db_session, "fa-ledger-1", made["line_id"]
    )
    assert row_count == 1
    assert relative.endswith("auto_assembled_ledger.csv")
    path = Path(fault_analysis_service.get_settings().file_vfs_root) / relative
    text = path.read_text(encoding="utf-8-sig")
    assert "线路名称" in text
    assert "塔号" in text
    assert "绝缘子串长度mm" in text
    assert "反击耐雷水平kA" in text
    assert "N65" in text
    assert "1800.0" in text


def test_assemble_ledger_csv_raises_when_no_towers(db_session) -> None:
    """台账自动组装：线路无杆塔数据时给出明确提示（LP-378）。"""
    from fastapi import HTTPException
    from app.models.line import Line

    line = Line(code="code-empty", name="空杆塔线路", voltage_kv=220)
    db_session.add(line)
    db_session.commit()

    with pytest.raises(HTTPException) as captured:
        fault_analysis_service.assemble_ledger_csv(db_session, "fa-ledger-empty", line.id)
    assert captured.value.status_code == 400
    assert "无杆塔数据" in str(captured.value.detail)


def test_ensure_line_has_towers(db_session) -> None:
    """台账自动组装预检：线路缺失/无杆塔数据时拦截，有杆塔数据时放行（LP-378）。"""
    from fastapi import HTTPException
    from app.models.line import Line

    with pytest.raises(HTTPException) as captured:
        fault_analysis_service.ensure_line_has_towers(db_session, "no-such-line")
    assert captured.value.status_code == 404

    line = Line(code="code-empty-2", name="空杆塔线路2", voltage_kv=110)
    db_session.add(line)
    db_session.commit()
    with pytest.raises(HTTPException) as captured:
        fault_analysis_service.ensure_line_has_towers(db_session, line.id)
    assert captured.value.status_code == 400
    assert "无杆塔数据" in str(captured.value.detail)

    made = _make_line(db_session)
    fault_analysis_service.ensure_line_has_towers(db_session, made["line_id"])


def test_resolve_temp_upload_missing(monkeypatch) -> None:
    """临时文件不存在/已过期时返回 400。"""
    from fastapi import HTTPException
    from app.services import minio_storage

    def mock_get(key):
        raise minio_storage.MinioObjectNotFoundError(f"Object not found: {key}")

    monkeypatch.setattr(minio_storage, "get_object", mock_get)

    with pytest.raises(HTTPException) as captured:
        file_upload.resolve_temp_upload(
            "lightning/tmp/u1/abc_test.csv",
            "u1",
        )
    assert captured.value.status_code == 400
    assert "不存在或已过期" in str(captured.value.detail)


@pytest.mark.asyncio
async def test_auto_classified_temp_uploads_preserve_all_wave_files(monkeypatch) -> None:
    temp_files = {
        "tmp/1": (b"wave", "1 录波故障信息 雁湖线_fault_info.xlsx"),
        "tmp/2": (b"lightning", "2 雷电定位输入模板.xlsx"),
        "tmp/a": (b"A", "1号杆塔A相.txt"),
        "tmp/b": (b"B", "1号杆塔B相.txt"),
        "tmp/c": (b"C", "1号杆塔C相.txt"),
    }
    stored: list[tuple[str, str, str, bytes]] = []

    def mock_resolve(temp_file_id: str, user_id: str) -> tuple[bytes, str]:
        return temp_files[temp_file_id]

    def mock_store(analysis_id: str, field: str, file_name: str, content: bytes) -> str:
        stored.append((analysis_id, field, file_name, content))
        return f"fault_analysis/{analysis_id}/{field}_{file_name}"

    monkeypatch.setattr(fault_analysis_api, "resolve_temp_upload", mock_resolve)
    monkeypatch.setattr(fault_analysis_api, "store_analysis_upload_file", mock_store)

    upload_files = await fault_analysis_api._store_auto_classified_files(
        "fa-1",
        uploads=[],
        temp_file_ids=["tmp/1", "tmp/2", "tmp/a", "tmp/b", "tmp/c"],
        user_id="u1",
    )

    assert upload_files["wave_data_file"].endswith("1 录波故障信息 雁湖线_fault_info.xlsx")
    assert upload_files["lightning_data_file"].endswith("2 雷电定位输入模板.xlsx")
    assert upload_files["traveling_wave_file"] == [
        "fault_analysis/fa-1/traveling_wave_file_1号杆塔A相.txt",
        "fault_analysis/fa-1/traveling_wave_file_1号杆塔B相.txt",
        "fault_analysis/fa-1/traveling_wave_file_1号杆塔C相.txt",
    ]
    assert [field for _, field, _, _ in stored].count("traveling_wave_file") == 3


@pytest.mark.asyncio
async def test_auto_classified_unknown_file_fails_clearly(monkeypatch) -> None:
    monkeypatch.setattr(
        fault_analysis_api,
        "resolve_temp_upload",
        lambda temp_file_id, user_id: (b"content", "report.docx"),
    )

    with pytest.raises(HTTPException) as captured:
        await fault_analysis_api._store_auto_classified_files(
            "fa-1",
            uploads=[],
            temp_file_ids=["tmp/unknown"],
            user_id="u1",
        )
    assert captured.value.status_code == 400
    assert "无法自动识别文件类别" in str(captured.value.detail)
