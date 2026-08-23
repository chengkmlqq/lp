from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRelease, AtpAssetRun
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.fl_analysis import (
    FlAnalysisJob,
    FlAnalysisRun,
    FlAnalysisTowerResult,
    FlAnalysisTowerSnapshot,
)
from app.models.line import Line
from app.models.line_tower import LineTower
from app.models.tower_analysis import TowerAnalysis
from app.models.tower_circuit import TowerCircuit
from app.models.tower_lightning_result import TowerLightningResult
from app.models.tower_profile import TowerProfile
from app.schemas.fl_analysis import FlAnalysisJobCreateRequest
from app.services import fl_analysis_external, fl_analysis_service

ATP_TEMPLATE_SCRIPT = """import json
result = {"counterstrike_withstand_ka": 12.0, "risk_grade": 3, "score": 91, "summary_text": "ATP执行完成"}
with open("result.json", "w", encoding="utf-8") as f:
    json.dump(result, f)
"""

WAVEFORM_OPTIONS = {
    "current_waveform": "double_slope",
    "flashover_method": "intersection",
    "altitude_correction": "formula1",
    "induced_voltage_formula": "formula2",
    "head_time_min_us": 2.4,
    "head_time_max_us": 2.6,
    "head_time_step_us": 0.2,
    "tail_time_min_us": 45.0,
    "tail_time_max_us": 50.0,
    "tail_time_step_us": 5.0,
}


def _build_sessionmaker():
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
            FlAnalysisJob.__table__,
            FlAnalysisRun.__table__,
            FlAnalysisTowerSnapshot.__table__,
            FlAnalysisTowerResult.__table__,
            FileStorageBackend.__table__,
            FileStorageMount.__table__,
            FileIndexEntry.__table__,
            AtpAsset.__table__,
            AtpAssetRelease.__table__,
            AtpAssetRun.__table__,
        ],
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def _seed_vfs_mount(session: Session, *, root_dir: Path) -> None:
    backend = FileStorageBackend(
        code="main",
        name="Main VFS",
        driver_type="VFS",
        status="enabled",
        is_default=True,
        config_json={"root_dir": str(root_dir)},
    )
    session.add(backend)
    session.flush()
    session.add(
        FileStorageMount(
            code="main",
            name="Main Mount",
            backend_id=backend.id,
            mount_path="/",
            root_path="/",
            is_enabled=True,
        )
    )
    session.commit()


def _seed_line_and_towers(session: Session) -> Line:
    line = Line(
        code="L-001",
        name="示例线路",
        voltage_kv=220,
        lightning_param_json={"雷电流幅值a": 31.0, "雷电流幅值b": 2.6},
    )
    session.add(line)
    session.flush()

    tower = LineTower(
        line_id=line.id,
        seq_no=1,
        tower_no="N1",
        tower_model="220-TEST-ZX",
        tower_type="直线",
        altitude_m=1680.0,
        ground_resistance_ohm=12.0,
        lightning_density=3.2,
        span_large_m=260.0,
        slope_1=3.0,
        slope_2=1.5,
    )
    session.add(tower)
    session.flush()

    session.add(
        TowerCircuit(
            tower_id=tower.id,
            circuit_no=1,
            phase_sequence="ABC",
            spacing_upper_m=9.0,
            spacing_middle_m=4.5,
            spacing_lower_m=8.5,
            height_upper_m=29.0,
            height_middle_m=31.0,
            height_lower_m=25.0,
        )
    )
    session.flush()

    session.add(
        TowerProfile(
            tower_id=tower.id,
            structure_kind="直线",
            arrester_a="是",
            arrester_b="否",
            arrester_c="是",
            shield_wire_height_m=41.0,
            insulator_length_m=4200.0,
            current_a=31.0,
            current_b=2.6,
            current_type="Heidler",
            current_head_time_us=2.6,
            current_tail_time_us=50.0,
        )
    )
    session.flush()
    return line


def _seed_release(
    session: Session,
    *,
    tmp_path: Path,
    code: str,
    manifest_json: dict[str, object] | None = None,
    entry_file: str = "work.atp",
    template: str | None = None,
) -> tuple[AtpAsset, AtpAssetRelease]:
    if template is not None:
        asset_root = tmp_path / "vfs" / "atp-assets" / code
        asset_root.mkdir(parents=True, exist_ok=True)
        with (asset_root / entry_file).open("w", encoding="utf-8", newline="") as handle:
            handle.write(template)

    asset = AtpAsset(
        code=code,
        name=f"资产 {code}",
        description="",
        status="enabled",
        voltage_level="110",
        tower_type="ganzi",
        scene_type="fanji",
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        latest_release_no=1,
        active_release_no=1,
    )
    session.add(asset)
    session.flush()

    release = AtpAssetRelease(
        asset_id=asset.id,
        release_no=1,
        status="released",
        voltage_level="110",
        tower_type="ganzi",
        scene_type="fanji",
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        entry_file=entry_file,
        manifest_json=manifest_json or {},
        content_hash="x",
        is_active=True,
    )
    session.add(release)
    session.flush()
    return asset, release


def test_render_atp_template_supports_binding_formats_and_defaults() -> None:
    rendered = fl_analysis_external.render_atp_template(
        "R={{GROUND_RES}}\nHEAD={{profile.current_head_time_us|F1|6|2.6}}\nNAME={{snapshot.tower_no}}",
        context={
            "snapshot": {"tower_no": "N-01"},
            "base_tower": {"ground_resistance_ohm": 12.34},
            "profile": {},
        },
        parameter_bindings={
            "GROUND_RES": {
                "path": "base_tower.ground_resistance_ohm",
                "format": "F1",
                "width": 6,
            }
        },
    )

    assert "R=  12.3" in rendered
    assert "HEAD=   2.6" in rendered
    assert "NAME=N-01" in rendered


def test_resolve_external_job_uses_manifest_atp_text(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset, release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-manifest-asset",
            manifest_json={
                "atp_text": "R={{profile.current_head_time_us}}",
                "fl_analysis": {"result_file": "result.json"},
            },
        )
        session.commit()

        resolved = fl_analysis_external.resolve_external_waveform_job(
            session,
            external_adapter="atp",
            adapter_config_json={"model_id": asset.id, "release_id": release.id},
        )

        assert resolved.adapter == "atp"
        assert resolved.asset.code == "fl-manifest-asset"
        assert resolved.release.release_no == 1
        assert resolved.atp_text == "R={{profile.current_head_time_us}}"
        assert resolved.contract["result_file"] == "result.json"
    finally:
        session.close()


def test_resolve_external_job_falls_back_to_storage_entry_file(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset, release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-storage-asset",
            manifest_json={"fl_analysis": {"result_file": "result.json"}},
            entry_file="work.atp",
            template=ATP_TEMPLATE_SCRIPT,
        )
        session.commit()

        resolved = fl_analysis_external.resolve_external_waveform_job(
            session,
            external_adapter="wine",
            adapter_config_json={"model_id": asset.id, "release_id": release.id},
        )

        assert resolved.adapter == "wine"
        assert resolved.asset.code == "fl-storage-asset"
        assert resolved.atp_text == ATP_TEMPLATE_SCRIPT
    finally:
        session.close()


def test_resolve_external_job_missing_template_reports_asset_code_and_release(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset, release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-missing-template",
            manifest_json={},
        )
        session.commit()

        with pytest.raises(RuntimeError, match="ATP 资产版本缺少可执行模板: fl-missing-template v1"):
            fl_analysis_external.resolve_external_waveform_job(
                session,
                external_adapter="atp",
                adapter_config_json={"model_id": asset.id, "release_id": release.id},
            )
    finally:
        session.close()


def test_resolve_external_job_asset_root_missing_template(tmp_path) -> None:
    """Asset-root mode: no files in the asset tree reports a clear error."""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = AtpAsset(
            code="fl-asset-empty",
            name="资产 fl-asset-empty",
            description="",
            status="enabled",
            storage_mount_code="main",
            storage_root_path="/atp-assets/fl-asset-empty",
            latest_release_no=0,
            active_release_no=None,
        )
        session.add(asset)
        session.commit()

        with pytest.raises(RuntimeError, match="ATP 资产缺少可执行模板文件: fl-asset-empty"):
            fl_analysis_external.resolve_external_waveform_job(
                session,
                external_adapter="atp",
                adapter_config_json={"model_id": asset.id},
            )
    finally:
        session.close()


def test_create_job_with_selected_model_stores_external_adapter(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        line = _seed_line_and_towers(session)
        asset, _release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-create-asset",
            manifest_json={"fl_analysis": {"result_file": "result.json"}},
            template=ATP_TEMPLATE_SCRIPT,
        )
        session.commit()

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="普通计算-ATP",
                job_type="normal",
                external_adapter="atp",
                adapter_config_json={"model_id": asset.id},
                execution_options_json=WAVEFORM_OPTIONS,
            ),
            actor=SimpleNamespace(id="tester"),
        )

        assert created.job.external_adapter == "atp"
        assert created.job.adapter_config_json == {"model_id": asset.id}
    finally:
        session.close()


def test_create_job_missing_template_returns_400_with_asset_info(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        line = _seed_line_and_towers(session)
        asset, release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-create-missing",
            manifest_json={},
        )
        session.commit()

        with pytest.raises(HTTPException) as exc_info:
            fl_analysis_service.create_job(
                session,
                FlAnalysisJobCreateRequest(
                    line_id=line.id,
                    job_name="普通计算-ATP",
                    job_type="normal",
                    external_adapter="atp",
                    adapter_config_json={"model_id": asset.id, "release_id": release.id},
                    execution_options_json=WAVEFORM_OPTIONS,
                ),
                actor=SimpleNamespace(id="tester"),
            )
        assert exc_info.value.status_code == 400
        assert "fl-create-missing v1" in str(exc_info.value.detail)
    finally:
        session.close()


def test_create_job_without_model_uses_placeholder_adapter(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        line = _seed_line_and_towers(session)
        session.commit()

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="规则近似计算",
                job_type="normal",
                external_adapter="placeholder",
                execution_options_json=WAVEFORM_OPTIONS,
            ),
            actor=SimpleNamespace(id="tester"),
        )

        assert created.job.external_adapter == "placeholder"
    finally:
        session.close()


def test_execute_job_runs_external_adapter_and_backfills_results(tmp_path, monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        line = _seed_line_and_towers(session)
        asset, _release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-execute-asset",
            manifest_json={"fl_analysis": {"result_file": "result.json"}},
            template=ATP_TEMPLATE_SCRIPT,
        )
        session.commit()

        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(fl_analysis_external, "_resolve_engine_workdir", lambda: tmp_path)
        monkeypatch.setattr(fl_analysis_external, "_resolve_native_engine_executable", lambda: (sys.executable, None))

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="普通计算-ATP",
                job_type="normal",
                external_adapter="atp",
                adapter_config_json={"model_id": asset.id},
                execution_options_json=WAVEFORM_OPTIONS,
            ),
            actor=SimpleNamespace(id="tester"),
        )
        session.close()

        fl_analysis_service.execute_job(created.job.id)

        verify_session: Session = testing_session()
        try:
            saved_job = fl_analysis_service.get_job_by_id(verify_session, created.job.id)
            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_job.result_summary_json["adapter_status"] == "executed"
            assert saved_job.result_summary_json["external_model_code"] == "fl-execute-asset"
            assert saved_job.result_summary_json["external_version_no"] == 1

            result_row = verify_session.execute(
                select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == created.job.id)
            ).scalar_one()
            assert result_row.risk_level == "high"
            assert result_row.summary_text == "ATP执行完成"
            assert result_row.result_json["counterstrike_withstand_ka"] == 12.0
            assert result_row.result_json["external_execution"]["adapter"] == "atp"
            assert result_row.result_json["external_execution"]["asset_code"] == "fl-execute-asset"

            saved_run = verify_session.execute(
                select(FlAnalysisRun).where(FlAnalysisRun.job_id == created.job.id)
            ).scalar_one()
            assert saved_run.status == "success"
            assert saved_run.runner_kind == "atp"
            assert saved_run.engine_command is not None
            assert saved_run.working_dir is not None
        finally:
            verify_session.close()
    finally:
        session.close()


ASSET_ROOT_TEMPLATE_SCRIPT = """import json
result = {"counterstrike_withstand_ka": 12.0, "risk_grade": 3, "score": 91, "summary_text": "ATP执行完成"}
with open("work.lis", "w", encoding="utf-8") as f:
    json.dump(result, f)
"""


def _seed_asset_without_release(
    session: Session,
    *,
    tmp_path: Path,
    code: str,
    template: str,
) -> AtpAsset:
    """Seed an asset with files but NO release records (the new asset-root mode).

    The template script must write its result to ``work.lis`` because the
    asset-root resolver auto-detects ``work.lis`` as the result file.
    """
    asset_root = tmp_path / "vfs" / "atp-assets" / code
    asset_root.mkdir(parents=True, exist_ok=True)
    (asset_root / "work.atp").write_text(template, encoding="utf-8")
    (asset_root / "work.lis").write_text("placeholder result", encoding="utf-8")

    asset = AtpAsset(
        code=code,
        name=f"资产 {code}",
        description="",
        status="enabled",
        voltage_level="110",
        tower_type="ganzi",
        scene_type="fanji",
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        latest_release_no=0,
        active_release_no=None,
    )
    session.add(asset)
    session.flush()
    return asset


def test_resolve_external_job_asset_root_mode_without_release(tmp_path) -> None:
    """A model without any release resolves directly from the asset file tree."""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _seed_asset_without_release(
            session,
            tmp_path=tmp_path,
            code="fl-asset-root",
            template=ASSET_ROOT_TEMPLATE_SCRIPT,
        )
        session.commit()

        resolved = fl_analysis_external.resolve_external_waveform_job(
            session,
            external_adapter="atp",
            adapter_config_json={"model_id": asset.id},
        )

        assert resolved.asset_root_mode is True
        assert resolved.release is None
        assert resolved.entry_file == "work.atp"
        assert resolved.result_file == "work.lis"
        assert resolved.storage_mount_code == "main"
        assert resolved.storage_root_path == f"/atp-assets/fl-asset-root"
        assert resolved.atp_text == ASSET_ROOT_TEMPLATE_SCRIPT
        assert resolved.contract.get("result_file") is None
    finally:
        session.close()


def test_resolve_external_job_explicit_release_still_works(tmp_path) -> None:
    """Explicit release_id/version_id keeps using the release record (backward compat)."""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset, release = _seed_release(
            session,
            tmp_path=tmp_path,
            code="fl-explicit-release",
            manifest_json={"atp_text": "R={{profile.current_head_time_us}}"},
            template=ATP_TEMPLATE_SCRIPT,
        )
        session.commit()

        resolved = fl_analysis_external.resolve_external_waveform_job(
            session,
            external_adapter="atp",
            adapter_config_json={"model_id": asset.id, "release_id": release.id},
        )

        assert resolved.asset_root_mode is False
        assert resolved.release is not None
        assert resolved.release.release_no == 1
        assert resolved.atp_text == "R={{profile.current_head_time_us}}"
    finally:
        session.close()


def test_execute_job_asset_root_mode_no_release(tmp_path, monkeypatch) -> None:
    """End-to-end job run against an asset without any release record."""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        line = _seed_line_and_towers(session)
        asset = _seed_asset_without_release(
            session,
            tmp_path=tmp_path,
            code="fl-asset-root-exec",
            template=ASSET_ROOT_TEMPLATE_SCRIPT,
        )
        session.commit()

        monkeypatch.setattr(fl_analysis_service, "SessionLocal", testing_session)
        monkeypatch.setattr(fl_analysis_service, "_publish_change", lambda *args, **kwargs: None)
        monkeypatch.setattr(fl_analysis_external, "_resolve_engine_workdir", lambda: tmp_path)
        monkeypatch.setattr(fl_analysis_external, "_resolve_native_engine_executable", lambda: (sys.executable, None))

        created = fl_analysis_service.create_job(
            session,
            FlAnalysisJobCreateRequest(
                line_id=line.id,
                job_name="普通计算-资产级ATP",
                job_type="normal",
                external_adapter="atp",
                adapter_config_json={"model_id": asset.id},
                execution_options_json=WAVEFORM_OPTIONS,
            ),
            actor=SimpleNamespace(id="tester"),
        )
        session.close()

        fl_analysis_service.execute_job(created.job.id)

        verify_session: Session = testing_session()
        try:
            saved_job = fl_analysis_service.get_job_by_id(verify_session, created.job.id)
            assert saved_job is not None
            assert saved_job.status == "success"
            assert saved_job.result_summary_json["adapter_status"] == "executed"
            assert saved_job.result_summary_json["external_model_code"] == "fl-asset-root-exec"
            assert saved_job.result_summary_json["external_version_no"] is None

            result_row = verify_session.execute(
                select(FlAnalysisTowerResult).where(FlAnalysisTowerResult.job_id == created.job.id)
            ).scalar_one()
            external_execution = result_row.result_json["external_execution"]
            assert external_execution["asset_code"] == "fl-asset-root-exec"
            assert external_execution["release_id"] is None
            assert external_execution["release_no"] is None
            assert external_execution["entry_file"] == "work.atp"
            assert external_execution["storage_root_path"] == f"/atp-assets/fl-asset-root-exec"
            assert result_row.result_json["counterstrike_withstand_ka"] == 12.0
        finally:
            verify_session.close()
    finally:
        session.close()
