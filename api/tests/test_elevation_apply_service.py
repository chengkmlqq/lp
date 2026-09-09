from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.elevation import ElevationApplyJob, ElevationApplyJobTower, ElevationFileRecord
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
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
            TowerCircuit.__table__,
            TowerLightningResult.__table__,
            TowerAnalysis.__table__,
            ElevationFileRecord.__table__,
            ElevationApplyJob.__table__,
            ElevationApplyJobTower.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _make_record(session: Session, *, file_name: str = "record.tif") -> ElevationFileRecord:
    record = ElevationFileRecord(
        file_name=file_name,
        file_path=f"/elevation/records/ab/cd/{file_name}",
        file_format="tif",
        file_size=32,
        mount_code="default",
        status="active",
    )
    session.add(record)
    return record


def test_create_apply_job_dispatches_actor_user_id(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-001", name="回填线路", voltage_kv=220, lightning_param_json={})
        record = _make_record(session)
        session.add_all([line, record])
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
            ElevationApplyJobCreateRequest(line_id=line.id, file_record_id=record.id, mode="overwrite_all"),
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
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
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
        assert saved_job.task_id == "celery-task-file-record"
        assert response.job.file_record_id == record.id
        assert response.job.file_record_name == "record.tif"
    finally:
        session.close()


def test_execute_apply_job_uses_saved_actor_for_preparation_source(monkeypatch) -> None:
    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-APPLY-002", name="高程回填线路", voltage_kv=110, lightning_param_json={})
        record = _make_record(session)
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

        def _fake_apply_raster(db, *, line_id, elevation_source, mode, job_id=None):
            ts = db.execute(select(LineTower).where(LineTower.line_id == line_id)).scalars().all()
            for t in ts:
                t.altitude_m = 120.0
            db.commit()
            return ({"updated_tower_count": len(ts), "skipped_tower_count": 0, "missing_geo_count": 0, "unmatched_count": 0}, [])

        monkeypatch.setattr(elevation_service, "SessionLocal", testing_session)
        monkeypatch.setattr(elevation_service, "_apply_raster_to_line_towers", _fake_apply_raster)
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
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
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

        def _fake_apply_raster(db, *, line_id, elevation_source, mode, job_id=None):
            ts = db.execute(select(LineTower).where(LineTower.line_id == line_id)).scalars().all()
            for t in ts:
                t.altitude_m = 120.0
            db.commit()
            return ({"updated_tower_count": len(ts), "skipped_tower_count": 0, "missing_geo_count": 0, "unmatched_count": 0}, [])

        monkeypatch.setattr(elevation_service, "SessionLocal", testing_session)
        monkeypatch.setattr(elevation_service, "_apply_raster_to_line_towers", _fake_apply_raster)
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
            assert source["file_record_name"] == "record.tif"
            assert source["job_id"] == job.id
        finally:
            verification_session.close()
    finally:
        session.close()


def test_apply_raster_snapshots_job_tower_details(monkeypatch) -> None:
    """回填任务执行时为每个杆塔写入明细快照（updated/skipped/missing_geo/unmatched）。

    覆盖：已更新（采样命中并写值）/ 已跳过（fill_null 且已有完整值）/
    缺坐标（无经纬度）/ 未命中（采样无值）；重复执行同一任务幂等替换明细。
    """
    import contextlib

    from app.models.elevation import ElevationApplyJobTower as JobTower

    testing_session = _build_session_factory()
    session = testing_session()
    try:
        line = Line(code="L-SNAP-001", name="明细快照线路", voltage_kv=110, lightning_param_json={})
        record = _make_record(session, file_name="snapshot.tif")
        session.add_all([line, record])
        session.flush()
        session.add_all(
            [
                # 缺坐标（missing_geo）
                LineTower(line_id=line.id, seq_no=1, tower_no="M1", longitude=None, latitude=None),
                # 采样命中（updated，mode=fill_null_only 时无原值 → 回填）
                LineTower(line_id=line.id, seq_no=2, tower_no="H1", longitude=120.0, latitude=30.0),
                # 采样未命中（unmatched）
                LineTower(line_id=line.id, seq_no=3, tower_no="U1", longitude=121.0, latitude=31.0),
                # 已有完整值且 fill_null_only → 跳过（skipped）
                LineTower(line_id=line.id, seq_no=4, tower_no="S1", longitude=122.0, latitude=32.0, altitude_m=11.1, slope_1=0.5, slope_2=0.6),
            ]
        )
        session.flush()
        job = ElevationApplyJob(
            line_id=line.id,
            file_record_id=record.id,
            mode="fill_null_only",
            status="running",
            total_tower_count=4,
            create_user="tester",
            update_user="tester",
        )
        session.add(job)
        session.commit()

        # 采样器：仅 (120.0, 30.0) 命中 88.8，其余返回 None
        def _fake_sampler(lon: float, lat: float):
            if lon == 120.0 and lat == 30.0:
                return 88.8
            return None

        @contextlib.contextmanager
        def _fake_open(db, record):  # noqa: ARG001
            yield SimpleNamespace(
                rasterio=SimpleNamespace(),
                dataset=SimpleNamespace(crs=None, nodatavals=None),
            )

        monkeypatch.setattr(elevation_service, "_open_raster_dataset", _fake_open)
        monkeypatch.setattr(elevation_service, "_build_raster_sampler", lambda *args, **kwargs: _fake_sampler)
        monkeypatch.setattr(elevation_service, "_append_non_wgs84_bounds_warning", lambda *args, **kwargs: None)

        stats, _ = elevation_service._apply_raster_to_line_towers(
            session,
            line_id=line.id,
            elevation_source=record,
            mode="fill_null_only",
            job_id=job.id,
        )
        assert stats == {
            "updated_tower_count": 1,
            "skipped_tower_count": 1,
            "missing_geo_count": 1,
            "unmatched_count": 1,
        }

        details = session.execute(
            select(JobTower)
            .where(JobTower.job_id == job.id)
            .order_by(JobTower.seq_no.asc())
        ).scalars().all()
        assert len(details) == 4
        assert [item.action for item in details] == ["missing_geo", "updated", "unmatched", "skipped"]
        assert [item.seq_no for item in details] == [1, 2, 3, 4]
        assert [item.tower_no for item in details] == ["M1", "H1", "U1", "S1"]

        hit = details[1]
        assert hit.altitude_before_m is None
        assert hit.altitude_after_m == 88.8
        assert hit.longitude == 120.0 and hit.latitude == 30.0
        skip_row = details[3]
        assert skip_row.altitude_before_m == 11.1
        assert skip_row.altitude_after_m == 11.1
        assert skip_row.slope_1_before == 0.5 and skip_row.slope_1_after == 0.5
        assert skip_row.slope_2_before == 0.6 and skip_row.slope_2_after == 0.6

        # 同任务重复执行：先清旧明细再写入（行数不变，无重复）
        elevation_service._apply_raster_to_line_towers(
            session,
            line_id=line.id,
            elevation_source=record,
            mode="fill_null_only",
            job_id=job.id,
        )
        details_again = session.execute(
            select(JobTower).where(JobTower.job_id == job.id)
        ).scalars().all()
        assert len(details_again) == 4
    finally:
        session.close()
