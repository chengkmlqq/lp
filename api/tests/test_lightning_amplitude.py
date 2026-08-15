from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.lightning_amplitude import LightningAmplitude
from app.models.line_amplitude_backfill import LineAmplitudeBackfill
from app.services import lightning_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[LightningAmplitude.__table__, LineAmplitudeBackfill.__table__],
    )
    testing_session = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return testing_session()


def _add_amplitude(
    session: Session,
    *,
    event_id: str | None = "LC-TEST-1",
    source_file_name: str = "wave.csv",
    source_object_key: str = "lightning/amplitude/source/abc_wave.csv",
    status: str = "completed",
) -> LightningAmplitude:
    amp = LightningAmplitude(
        event_id=event_id,
        source_file_name=source_file_name,
        source_object_key=source_object_key,
        status=status,
        progress=100 if status == "completed" else 0,
        sample_count=3,
        peak_abs_current_ka=10.5,
        peak_current_ka=10.5,
        polarity="positive",
    )
    session.add(amp)
    session.flush()
    return amp


def test_serialize_amplitude_record() -> None:
    session = _build_session()
    try:
        amp = _add_amplitude(session, status="completed")
        session.commit()

        record = lightning_service._serialize_amplitude(amp)

        assert record.id == amp.id
        assert record.event_id == "LC-TEST-1"
        assert record.source_file_name == "wave.csv"
        assert record.source_object_key == "lightning/amplitude/source/abc_wave.csv"
        assert record.status == "completed"
        assert record.sample_count == 3
        assert record.peak_abs_current_ka == 10.5
        assert record.polarity == "positive"
    finally:
        session.close()


def test_list_amplitudes_filters_by_keyword_and_status() -> None:
    session = _build_session()
    try:
        _add_amplitude(session, event_id="LC-A", source_file_name="alpha.csv", status="completed")
        _add_amplitude(session, event_id="LC-B", source_file_name="beta.csv", status="failed")
        session.commit()

        result = lightning_service.list_lightning_amplitudes(session, keyword="alpha", limit=50, offset=0)
        assert result.total == 1
        assert result.items[0].source_file_name == "alpha.csv"

        result = lightning_service.list_lightning_amplitudes(session, status_filter="failed", limit=50, offset=0)
        assert result.total == 1
        assert result.items[0].event_id == "LC-B"
    finally:
        session.close()


def test_get_lightning_amplitude_status(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        amp = _add_amplitude(session, status="processing", source_object_key="lightning/amplitude/source/x.csv")
        session.commit()

        status = lightning_service.get_lightning_amplitude_status(session, amp.id)
        assert status.amplitude_id == amp.id
        assert status.status == "processing"
        assert status.record is not None
        assert status.record.progress == 0
    finally:
        session.close()


def test_delete_amplitude_removes_record(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        from app.services import minio_storage
        monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)

        amp = _add_amplitude(session, event_id="LC-DEL")
        session.commit()

        result = lightning_service.delete_lightning_amplitude(session, amp.id)
        assert result == {"success": True}
        remaining = session.execute(
            select(LightningAmplitude).where(LightningAmplitude.id == amp.id)
        ).scalar_one_or_none()
        assert remaining is None
    finally:
        session.close()


def test_delete_missing_amplitude_returns_success_false() -> None:
    session = _build_session()
    try:
        result = lightning_service.delete_lightning_amplitude(session, "nonexistent")
        assert result == {"success": False}
    finally:
        session.close()


def test_peak_exceedance_uses_completed_amplitudes(monkeypatch) -> None:
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        _add_amplitude(session, source_file_name="a.csv", status="completed", source_object_key="k1", event_id="LC-E1")
        amp2 = _add_amplitude(session, source_file_name="b.csv", status="completed", source_object_key="k2", event_id="LC-E2")
        amp2.peak_abs_current_ka = 20.0
        _add_amplitude(session, source_file_name="c.csv", status="failed", source_object_key="k3", event_id="LC-E3")
        session.commit()

        result = lightning_service.get_peak_exceedance_curve(session, region_id=None, polarity=None, wave_shape=None, is_synthetic=None, thresholds_ka=[15.0])
        assert result.total_events == 2
        assert result.thresholds[0].threshold_ka == 15.0
        assert result.thresholds[0].exceedance_count == 1  # only 20.0 >= 15
    finally:
        session.close()


def test_build_amplitude_source_key() -> None:
    from app.services import minio_storage
    key = minio_storage.build_amplitude_source_key("wave.csv")
    assert key.startswith("lightning/amplitude/source/")
    assert key.endswith("wave.csv")
    assert minio_storage.AMPLITUDE_SOURCE_PREFIX == "lightning/amplitude/source/"


def test_extract_wave_features_basic() -> None:
    currents = [0.0, 5.0, 10.0, 8.0, 3.0, 0.0]
    time_axis = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    features = lightning_service._extract_wave_features(currents, time_axis, 1.0)
    assert features.peak_abs_current_ka == 10.0
    assert features.polarity == "positive"
    assert features.stroke_count >= 1


# ---------------------------------------------------------------------------
# import_lightning_amplitude_job 任务测试（eager 模式 + mock MinIO/SessionLocal）
# ---------------------------------------------------------------------------
def _run_amplitude_job(session, monkeypatch, content: bytes, *, amplitude_id: str) -> dict:
    from app.tasks import lightning_tasks
    from app.services import minio_storage

    monkeypatch.setattr(lightning_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(lightning_tasks, "_upload_log", lambda *a, **k: None)
    monkeypatch.setattr(lightning_tasks, "_append_log", lambda *a, **k: None)
    monkeypatch.setattr(minio_storage, "get_object", lambda key: content)

    return lightning_tasks.import_lightning_amplitude_job.__wrapped__(
        amplitude_id=amplitude_id,
        actor_user_id="user-1",
    )


def test_import_amplitude_job_completed(monkeypatch) -> None:
    session = _build_session()
    try:
        amp = _add_amplitude(
            session,
            event_id=None,
            status="pending",
            source_object_key="lightning/amplitude/source/x.csv",
        )
        session.commit()

        content = "0\n5\n10\n8\n3\n0\n".encode("utf-8")
        result = _run_amplitude_job(session, monkeypatch, content, amplitude_id=amp.id)

        assert result["status"] == "completed"
        session.expire_all()
        saved = session.execute(
            select(LightningAmplitude).where(LightningAmplitude.id == amp.id)
        ).scalar_one()
        assert saved.status == "completed"
        assert saved.progress == 100
        assert saved.sample_count == 6
        assert saved.event_id is not None  # 任务内自动生成
        assert saved.peak_abs_current_ka == 10.0
        assert saved.polarity == "positive"
    finally:
        session.close()


def test_import_amplitude_job_insufficient_samples(monkeypatch) -> None:
    session = _build_session()
    try:
        amp = _add_amplitude(
            session,
            event_id=None,
            status="pending",
            source_object_key="lightning/amplitude/source/x.csv",
        )
        session.commit()

        content = "5\n".encode("utf-8")  # 只有一个点
        with pytest.raises(Exception):
            _run_amplitude_job(session, monkeypatch, content, amplitude_id=amp.id)

        session.expire_all()
        saved = session.execute(
            select(LightningAmplitude).where(LightningAmplitude.id == amp.id)
        ).scalar_one()
        assert saved.status == "failed"
        assert "采样点" in (saved.error_message or "")
    finally:
        session.close()


def test_import_amplitude_duplicate_event_id_rejected(monkeypatch) -> None:
    """用户显式填写重复事件编号时，应在导入时立即返回 409。"""
    session = _build_session()
    try:
        from fastapi import HTTPException
        from types import SimpleNamespace

        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        from app.services import minio_storage
        monkeypatch.setattr(minio_storage, "put_object", lambda *a, **k: "lightning/amplitude/source/x_dup.csv")
        monkeypatch.setattr(minio_storage, "build_amplitude_source_key", lambda name: "lightning/amplitude/source/x_dup.csv")

        class _FakeFile:
            filename = "dup.csv"
            def __init__(self) -> None:
                self.file = SimpleNamespace(read=lambda: b"0\n1\n2\n")

        _add_amplitude(session, event_id="LC-DUP", status="completed", source_object_key="k-dup")
        session.commit()

        with pytest.raises(HTTPException) as captured:
            lightning_service.import_lightning_amplitude_from_file(
                session,
                file=_FakeFile(),
                actor_user_id="tester",
                event_id="LC-DUP",
                event_time=None,
                sample_interval_us=1.0,
                region_id=None,
                location_tag=None,
                city=None,
                longitude=None,
                latitude=None,
                altitude_m=None,
                sensor_model=None,
                install_position=None,
                weather_level=None,
                pressure_hpa=None,
                humidity_percent=None,
                is_synthetic=False,
                notes=None,
            )

        assert captured.value.status_code == 409
    finally:
        session.close()


def test_import_amplitude_via_temp_file_id(monkeypatch) -> None:
    """通过 temp_file_id 导入：从 MinIO 临时对象读取内容并转移到正式 source_key。"""
    session = _build_session()
    try:
        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)
        from app.core.celery_app import celery_app as celery_module_app
        monkeypatch.setattr(
            celery_module_app,
            "send_task",
            lambda *args, **kwargs: SimpleNamespace(id="mock-task-123"),
        )
        from app.services import minio_storage

        temp_file_key = "lightning/tmp/user-1/abc123_test.csv"
        temp_content = b"0\n5\n10\n8\n3\n0\n"

        def mock_get_object(key: str) -> bytes:
            if key == temp_file_key:
                return temp_content
            msg = f"Object not found: {key}"
            raise minio_storage.MinioObjectNotFoundError(msg)

        monkeypatch.setattr(minio_storage, "get_object", mock_get_object)
        monkeypatch.setattr(minio_storage, "put_object", lambda key, data, content_type=None: key)
        monkeypatch.setattr(minio_storage, "delete_object", lambda key: None)
        monkeypatch.setattr(minio_storage, "build_amplitude_source_key", lambda name: f"lightning/amplitude/source/{name}")

        result = lightning_service.import_lightning_amplitude_from_file(
            session,
            file=None,
            temp_file_id=temp_file_key,
            actor_user_id="user-1",
            event_id="LC-TEMP-1",
            event_time=None,
            sample_interval_us=1.0,
            region_id=None,
            location_tag=None,
            city=None,
            longitude=None,
            latitude=None,
            altitude_m=None,
            sensor_model=None,
            install_position=None,
            weather_level=None,
            pressure_hpa=None,
            humidity_percent=None,
            is_synthetic=False,
            notes=None,
        )

        assert result.amplitude_id is not None
        assert result.status == "processing"
        assert result.task_id is not None

        amp = session.execute(
            select(LightningAmplitude).where(LightningAmplitude.id == result.amplitude_id)
        ).scalar_one()
        assert amp.source_file_name == "test.csv"
        assert amp.source_object_key == "lightning/amplitude/source/test.csv"
        assert amp.event_id == "LC-TEMP-1"
    finally:
        session.close()


def test_import_amplitude_temp_file_id_wrong_user(monkeypatch) -> None:
    """temp_file_id 不属于当前用户时返回 400。"""
    session = _build_session()
    try:
        from fastapi import HTTPException

        monkeypatch.setattr(lightning_service, "_publish_lightning_change", lambda *args, **kwargs: None)

        with pytest.raises(HTTPException) as captured:
            lightning_service.import_lightning_amplitude_from_file(
                session,
                file=None,
                temp_file_id="lightning/tmp/other-user/abc123_test.csv",
                actor_user_id="user-1",
                event_id="LC-TEMP-2",
                event_time=None,
                sample_interval_us=1.0,
                region_id=None,
                location_tag=None,
                city=None,
                longitude=None,
                latitude=None,
                altitude_m=None,
                sensor_model=None,
                install_position=None,
                weather_level=None,
                pressure_hpa=None,
                humidity_percent=None,
                is_synthetic=False,
                notes=None,
            )

        assert captured.value.status_code == 400
        assert "不属于当前用户" in str(captured.value.detail) or "无效" in str(captured.value.detail)
    finally:
        session.close()


def test_build_temp_key() -> None:
    """验证 build_temp_key 的格式和嵌入用户 ID。"""
    from app.services import minio_storage
    key = minio_storage.build_temp_key("wave.csv", "user-1")
    assert key.startswith("lightning/tmp/user-1/")
    assert key.endswith("wave.csv")
    assert len(key) > len("lightning/tmp/user-1/") + 1
