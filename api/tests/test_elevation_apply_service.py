from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.elevation import ElevationApplyJob, ElevationDataset, ElevationFileRecord
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_profile import TowerProfile
from app.schemas.elevation import ElevationApplyJobCreateRequest
from app.services import elevation_service


def _build_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Line.__table__,
            LineTower.__table__,
            TowerProfile.__table__,
            ElevationDataset.__table__,
            ElevationFileRecord.__table__,
            ElevationApplyJob.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def test_create_apply_job_dispatches_actor_user_id(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-001", name="回填线路", voltage_kv=220, lightning_param_json={})
        dataset = ElevationDataset(
            code="DEM-APPLY-001",
            name="高程数据集",
            file_format="csv",
            mount_code="default",
            dataset_dir="/elevation/datasets/DEM-APPLY-001",
            file_path="/elevation/datasets/DEM-APPLY-001/dataset.csv",
            status="active",
            usage_status="idle",
        )
        session.add_all([line, dataset])
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0))
        session.commit()

        dispatched: dict[str, str | None] = {}

        def _fake_dispatch(*, job_id: str, actor_user_id: str | None) -> SimpleNamespace:
            dispatched["job_id"] = job_id
            dispatched["actor_user_id"] = actor_user_id
            return SimpleNamespace(id="celery-task-1")

        monkeypatch.setattr(elevation_service, "_dispatch_elevation_apply_task", _fake_dispatch)
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)

        response = elevation_service.create_apply_job(
            session,
            ElevationApplyJobCreateRequest(line_id=line.id, dataset_id=dataset.id, mode="overwrite_all"),
            actor=SimpleNamespace(id="tester"),
        )

        saved_job = session.get(ElevationApplyJob, response.job.id)
        assert response.queued is True
        assert dispatched == {"job_id": response.job.id, "actor_user_id": "tester"}
        assert saved_job is not None
        assert saved_job.task_id == "celery-task-1"
        assert saved_job.create_user == "tester"
        assert saved_job.update_user == "tester"
    finally:
        session.close()


def test_create_apply_job_accepts_file_record_id(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-003", name="文件记录回填线路", voltage_kv=220, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.csv",
            file_path="/elevation/records/ab/cd/record.csv",
            file_format="csv",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line, record])
        session.flush()
        session.add(LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0))
        session.commit()

        dispatched: dict[str, str | None] = {}

        def _fake_dispatch(*, job_id: str, actor_user_id: str | None) -> SimpleNamespace:
            dispatched["job_id"] = job_id
            dispatched["actor_user_id"] = actor_user_id
            return SimpleNamespace(id="celery-task-file-record")

        monkeypatch.setattr(elevation_service, "_dispatch_elevation_apply_task", _fake_dispatch)
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)

        response = elevation_service.create_apply_job(
            session,
            ElevationApplyJobCreateRequest(line_id=line.id, file_record_id=record.id, mode="overwrite_all"),
            actor=SimpleNamespace(id="tester"),
        )

        saved_job = session.get(ElevationApplyJob, response.job.id)
        assert response.queued is True
        assert dispatched == {"job_id": response.job.id, "actor_user_id": "tester"}
        assert saved_job is not None
        assert saved_job.file_record_id == record.id
        assert saved_job.dataset_id is None
        assert saved_job.task_id == "celery-task-file-record"
        assert response.job.file_record_id == record.id
        assert response.job.file_record_name == "record.csv"
    finally:
        session.close()


def test_execute_apply_job_uses_saved_actor_for_preparation_source(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-002", name="高程回填线路", voltage_kv=110, lightning_param_json={})
        dataset = ElevationDataset(
            code="DEM-APPLY-002",
            name="高程数据集",
            file_format="csv",
            mount_code="default",
            dataset_dir="/elevation/datasets/DEM-APPLY-002",
            file_path="/elevation/datasets/DEM-APPLY-002/dataset.csv",
            status="active",
            usage_status="idle",
        )
        session.add_all([line, dataset])
        session.flush()

        meter_to_lat = 1 / 111_320.0
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="P1", longitude=120.0, latitude=30.0 + 300 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=2, tower_no="P2", longitude=120.0, latitude=30.0 + 600 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=3, tower_no="P3", longitude=120.0, latitude=30.0 + 900 * meter_to_lat),
            ]
        )
        session.flush()

        job = ElevationApplyJob(
            line_id=line.id,
            dataset_id=dataset.id,
            mode="overwrite_all",
            status="pending",
            total_tower_count=3,
            create_user="tester",
            update_user="tester",
        )
        session.add(job)
        session.commit()

        points = [
            elevation_service.ElevationSamplePoint(
                lon=120.0,
                lat=30.0 + distance_m * meter_to_lat,
                altitude_m=100.0 + distance_m * 0.12,
            )
            for distance_m in range(0, 1251, 50)
        ]

        monkeypatch.setattr(elevation_service, "SessionLocal", testing_session)
        monkeypatch.setattr(elevation_service, "_load_dataset_points", lambda *_args, **_kwargs: (points, []))
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(elevation_service, "_publish_line_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(elevation_service, "_refresh_dataset_usage_status", lambda *args, **kwargs: None)

        elevation_service.execute_apply_job(job.id)

        verification_session = testing_session()
        try:
            saved_job = verification_session.get(ElevationApplyJob, job.id)
            saved_line = verification_session.get(Line, line.id)
            towers = verification_session.execute(
                select(LineTower).where(LineTower.line_id == line.id).order_by(LineTower.seq_no.asc())
            ).scalars().all()

            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_line is not None
            assert saved_line.update_user == "tester"
            assert all(tower.altitude_m is not None for tower in towers)

            source = saved_line.lightning_param_json["preparation_sources"]["ground_slope"]
            assert source["prepared_by_user_id"] == "tester"
            assert source["dataset_id"] == dataset.id
            assert source["job_id"] == job.id
        finally:
            verification_session.close()
    finally:
        session.close()


def test_execute_apply_job_uses_file_record_source(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-004", name="文件记录高程回填线路", voltage_kv=110, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.csv",
            file_path="/elevation/records/ab/cd/record.csv",
            file_format="csv",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line, record])
        session.flush()

        meter_to_lat = 1 / 111_320.0
        session.add_all(
            [
                LineTower(line_id=line.id, seq_no=1, tower_no="P1", longitude=120.0, latitude=30.0 + 300 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=2, tower_no="P2", longitude=120.0, latitude=30.0 + 600 * meter_to_lat),
                LineTower(line_id=line.id, seq_no=3, tower_no="P3", longitude=120.0, latitude=30.0 + 900 * meter_to_lat),
            ]
        )
        session.flush()

        job = ElevationApplyJob(
            line_id=line.id,
            file_record_id=record.id,
            mode="overwrite_all",
            status="pending",
            total_tower_count=3,
            create_user="tester",
            update_user="tester",
        )
        session.add(job)
        session.commit()

        points = [
            elevation_service.ElevationSamplePoint(
                lon=120.0,
                lat=30.0 + distance_m * meter_to_lat,
                altitude_m=100.0 + distance_m * 0.12,
            )
            for distance_m in range(0, 1251, 50)
        ]

        monkeypatch.setattr(elevation_service, "SessionLocal", testing_session)
        monkeypatch.setattr(elevation_service, "_load_dataset_points", lambda *_args, **_kwargs: (points, []))
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(elevation_service, "_publish_line_change", lambda *args, **kwargs: None)

        elevation_service.execute_apply_job(job.id)

        verification_session = testing_session()
        try:
            saved_job = verification_session.get(ElevationApplyJob, job.id)
            saved_line = verification_session.get(Line, line.id)
            towers = verification_session.execute(
                select(LineTower).where(LineTower.line_id == line.id).order_by(LineTower.seq_no.asc())
            ).scalars().all()

            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_line is not None
            assert saved_line.update_user == "tester"
            assert all(tower.altitude_m is not None for tower in towers)

            source = saved_line.lightning_param_json["preparation_sources"]["ground_slope"]
            assert source["prepared_by_user_id"] == "tester"
            assert source["file_record_id"] == record.id
            assert source["file_record_name"] == "record.csv"
            assert source["dataset_id"] is None
            assert source["job_id"] == job.id
        finally:
            verification_session.close()
    finally:
        session.close()
