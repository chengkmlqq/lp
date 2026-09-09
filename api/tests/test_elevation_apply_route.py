from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.elevation import ElevationApplyJob, ElevationApplyJobTower, ElevationFileRecord
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.models.user import User
from app.services import elevation_service
from app.api.v1.elevation import router as elevation_router


def _build_app(session_factory, *, permission_codes: set[str] | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(elevation_router, prefix="/api/v1")

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    current_user = CurrentUser(
        user=User(
            id="tester",
            email="tester@example.com",
            username="tester",
            password_hash="secret",
            status="ENABLED",
        ),
        role_codes=set(),
        permission_codes=permission_codes or {"elevation.manage"},
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    return TestClient(app)


def _build_session_factory() -> sessionmaker:
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


def test_apply_line_route_wires_to_create_apply_job(monkeypatch) -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line = Line(code="L-ROUTE-001", name="路由接线线路", voltage_kv=220, lightning_param_json={})
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

        def _fake_dispatch(*, job_id: str, actor_user_id: str | None):
            dispatched["job_id"] = job_id
            dispatched["actor_user_id"] = actor_user_id
            return __import__("types").SimpleNamespace(id="celery-route-task")

        monkeypatch.setattr(elevation_service, "_dispatch_elevation_apply_task", _fake_dispatch)
        monkeypatch.setattr(elevation_service, "_publish_elevation_change", lambda *args, **kwargs: None)

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": line.id, "file_record_id": record.id, "mode": "overwrite_all"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["queued"] is True
        assert body["job"]["line_id"] == line.id
        assert body["job"]["file_record_id"] == record.id
        assert body["job"]["status"] == "pending"

        saved = session.get(ElevationApplyJob, body["job"]["id"])
        assert saved is not None
        assert saved.task_id == "celery-route-task"
        assert dispatched == {"job_id": body["job"]["id"], "actor_user_id": "tester"}
    finally:
        session.close()


def test_apply_line_route_forbidden_without_elevation_manage() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        client = _build_app(session_factory, permission_codes={"elevation.read"})
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": "missing", "mode": "fill_null_only"},
        )
        assert response.status_code == 403
    finally:
        session.close()


def test_apply_line_route_rejects_unknown_line() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add(record)
        session.commit()

        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/jobs/apply-line",
            json={"line_id": "no-such-line", "file_record_id": record.id, "mode": "fill_null_only"},
        )
        assert response.status_code == 404
    finally:
        session.close()


def test_upload_csv_rejected_with_400(monkeypatch) -> None:
    session_factory = _build_session_factory()
    try:
        client = _build_app(session_factory)
        response = client.post(
            "/api/v1/elevation/records",
            files={"file": ("record.csv", b"lon,lat,altitude_m\n120,30,100\n", "text/csv")},
            data={},
        )
        assert response.status_code == 400
        assert "不支持的文件格式" in response.json()["detail"]
    finally:
        session_factory().close()


def test_zip_with_csv_skipped_creates_no_csv_record(monkeypatch) -> None:
    import io
    import zipfile

    from app.schemas.elevation import ElevationFileRecordCreateRequest
    from app.services.elevation_file_record_service import _create_file_records_from_zip

    session_factory = _build_session_factory()
    session = session_factory()
    try:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("data.csv", "lon,lat,altitude_m\n120,30,100\n")
            archive.writestr("terrain.tif", b"fake-tif-content")
        zip_buffer.seek(0)

        # Mock the driver so the tif-in-zip storage path never actually writes
        fake_driver = type(
            "FakeDriver",
            (),
            {
                "ensure_directory": lambda self, path: None,
                "write_file": lambda self, path, content, content_type=None: None,
            },
        )()

        result = _create_file_records_from_zip(
            db=session,
            zip_content=zip_buffer.getvalue(),
            zip_filename="archive.zip",
            payload=ElevationFileRecordCreateRequest(),
            mount_code="default",
            driver=fake_driver,
            actor=User(id="tester"),
        )

        # The .tif member should be imported, the .csv member skipped
        records = session.query(ElevationFileRecord).all()
        assert len(records) == 1
        assert records[0].file_name == "terrain.tif"
        assert records[0].file_format == "tif"
        assert result.detail.startswith("ZIP 文件已解压：成功创建 1 个文件记录")
    finally:
        session.close()


def test_linked_lines_endpoint_returns_aggregated_lines() -> None:
    """一个高程文件对同一线路多次回填，linked-lines 按线路聚合取最近一次。"""
    from datetime import datetime, timezone

    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = Line(code="L-A", name="线路A", voltage_kv=220, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line_a, record])
        session.flush()

        # 第一次回填（成功、旧时间）
        session.add(ElevationApplyJob(
            line_id=line_a.id,
            file_record_id=record.id,
            mode="fill_null_only",
            status="success",
            total_tower_count=10,
            updated_tower_count=8,
            finished_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ))
        # 第二次回填（running、新时间）——聚合应取这条
        session.add(ElevationApplyJob(
            line_id=line_a.id,
            file_record_id=record.id,
            mode="overwrite_all",
            status="running",
            total_tower_count=12,
            updated_tower_count=12,
            finished_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ))
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/elevation/records/{record.id}/linked-lines")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["line_id"] == line_a.id
        assert item["line_code"] == "L-A"
        assert item["line_name"] == "线路A"
        assert item["voltage_kv"] == 220
        assert item["apply_status"] == "running"
        assert item["tower_count"] == 12
        assert item["updated_tower_count"] == 12
    finally:
        session.close()


def test_linked_lines_endpoint_404_for_missing_record() -> None:
    session_factory = _build_session_factory()
    try:
        client = _build_app(session_factory)
        response = client.get("/api/v1/elevation/records/nope/linked-lines")
        assert response.status_code == 404
    finally:
        session_factory().close()


def test_linked_lines_endpoint_empty_when_no_jobs() -> None:
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add(record)
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/elevation/records/{record.id}/linked-lines")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 0
        assert body["items"] == []
    finally:
        session.close()


def test_list_records_includes_linked_line_count() -> None:
    """列表接口每个文件返回 linked_line_count（DISTINCT line_id 子查询）。"""
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = Line(code="L-A", name="线路A", voltage_kv=110, lightning_param_json={})
        line_b = Line(code="L-B", name="线路B", voltage_kv=110, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line_a, line_b, record])
        session.flush()
        # 文件对线路A回填两次、对线路B回填一次 → DISTINCT 计数应为 2
        session.add(ElevationApplyJob(line_id=line_a.id, file_record_id=record.id, mode="fill_null_only", status="success"))
        session.add(ElevationApplyJob(line_id=line_a.id, file_record_id=record.id, mode="overwrite_all", status="success"))
        session.add(ElevationApplyJob(line_id=line_b.id, file_record_id=record.id, mode="fill_null_only", status="success"))
        session.commit()

        client = _build_app(session_factory)
        response = client.get("/api/v1/elevation/records")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["linked_line_count"] == 2
    finally:
        session.close()


def test_job_towers_endpoint_404_for_missing_job() -> None:
    session_factory = _build_session_factory()
    try:
        client = _build_app(session_factory)
        response = client.get("/api/v1/elevation/jobs/nope/towers")
        assert response.status_code == 404
        assert "回填任务不存在" in response.json()["detail"]
    finally:
        session_factory().close()


def test_job_towers_endpoint_returns_paged_rows() -> None:
    """GET /elevation/jobs/{job_id}/towers 返回该任务逐杆塔明细（分页 + 按序号排序）。"""
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line = Line(code="L-TOW-001", name="明细路由线路", voltage_kv=220, lightning_param_json={})
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
        towers = [
            LineTower(line_id=line.id, seq_no=1, tower_no="T1", longitude=120.0, latitude=30.0),
            LineTower(line_id=line.id, seq_no=2, tower_no="T2", longitude=120.1, latitude=30.1),
            LineTower(line_id=line.id, seq_no=3, tower_no="T3", longitude=None, latitude=None),
        ]
        session.add_all(towers)
        session.flush()
        job_a = ElevationApplyJob(line_id=line.id, file_record_id=record.id, mode="overwrite_all", status="success", total_tower_count=3)
        job_b = ElevationApplyJob(line_id=line.id, file_record_id=record.id, mode="fill_null_only", status="success", total_tower_count=1)
        session.add_all([job_a, job_b])
        session.flush()

        # job_a 三条明细（乱序写入，接口应按 seq_no 升序返回）
        session.add_all([
            ElevationApplyJobTower(job_id=job_a.id, tower_id=towers[2].id, tower_no="T3", seq_no=3, longitude=None, latitude=None, action="missing_geo"),
            ElevationApplyJobTower(job_id=job_a.id, tower_id=towers[0].id, tower_no="T1", seq_no=1, longitude=120.0, latitude=30.0, action="updated", altitude_before_m=None, altitude_after_m=88.8),
            ElevationApplyJobTower(job_id=job_a.id, tower_id=towers[1].id, tower_no="T2", seq_no=2, longitude=120.1, latitude=30.1, action="unmatched"),
            # job_b 的明细不应出现在 job_a 查询中
            ElevationApplyJobTower(job_id=job_b.id, tower_id=towers[0].id, tower_no="T1", seq_no=1, longitude=120.0, latitude=30.0, action="skipped"),
        ])
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/elevation/jobs/{job_a.id}/towers")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert [item["seq_no"] for item in body["items"]] == [1, 2, 3]
        assert [item["action"] for item in body["items"]] == ["updated", "unmatched", "missing_geo"]
        first = body["items"][0]
        assert first["job_id"] == job_a.id
        assert first["tower_no"] == "T1"
        assert first["altitude_before_m"] is None
        assert first["altitude_after_m"] == 88.8
        assert first["longitude"] == 120.0

        # 分页：limit=2 offset=0 → 前两条，total 不变
        response_page = client.get(f"/api/v1/elevation/jobs/{job_a.id}/towers?limit=2&offset=0")
        assert response_page.status_code == 200, response_page.text
        page_body = response_page.json()
        assert page_body["total"] == 3
        assert [item["seq_no"] for item in page_body["items"]] == [1, 2]
    finally:
        session.close()


def test_record_jobs_endpoint_filters_by_line_id() -> None:
    """GET /records/{record_id}/jobs 支持 line_id 过滤。"""
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = Line(code="L-FA", name="线路A", voltage_kv=220, lightning_param_json={})
        line_b = Line(code="L-FB", name="线路B", voltage_kv=220, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line_a, line_b, record])
        session.flush()
        session.add(ElevationApplyJob(line_id=line_a.id, file_record_id=record.id, mode="overwrite_all", status="success"))
        session.add(ElevationApplyJob(line_id=line_b.id, file_record_id=record.id, mode="overwrite_all", status="success"))
        session.commit()

        client = _build_app(session_factory)
        response = client.get(f"/api/v1/elevation/records/{record.id}/jobs?line_id={line_b.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["line_id"] == line_b.id
        assert body["items"][0]["line_code"] == "L-FB"
    finally:
        session.close()


def test_record_jobs_endpoint_keyword_filters_line_name_and_code() -> None:
    """GET /records/{record_id}/jobs?keyword=... 按线路名称/编号模糊过滤（后台查询）。"""
    session_factory = _build_session_factory()
    session = session_factory()
    try:
        line_a = Line(code="L-NAME-A", name="白水线路", voltage_kv=220, lightning_param_json={})
        line_b = Line(code="L-NAME-B", name="青山线路", voltage_kv=110, lightning_param_json={})
        record = ElevationFileRecord(
            file_name="record.tif",
            file_path="/elevation/records/ab/cd/record.tif",
            file_format="tif",
            file_size=32,
            mount_code="default",
            status="active",
        )
        session.add_all([line_a, line_b, record])
        session.flush()
        session.add(ElevationApplyJob(line_id=line_a.id, file_record_id=record.id, mode="overwrite_all", status="success"))
        session.add(ElevationApplyJob(line_id=line_b.id, file_record_id=record.id, mode="overwrite_all", status="success"))
        session.commit()

        client = _build_app(session_factory)

        # 按名称关键词
        response = client.get(f"/api/v1/elevation/records/{record.id}/jobs?keyword=白水")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["line_id"] == line_a.id

        # 按线路编号关键词
        response_code = client.get(f"/api/v1/elevation/records/{record.id}/jobs?keyword=L-NAME-B")
        assert response_code.status_code == 200, response_code.text
        assert response_code.json()["total"] == 1

        # 空关键词返回全部
        response_all = client.get(f"/api/v1/elevation/records/{record.id}/jobs?keyword=   ")
        assert response_all.status_code == 200, response_all.text
        assert response_all.json()["total"] == 2
    finally:
        session.close()
