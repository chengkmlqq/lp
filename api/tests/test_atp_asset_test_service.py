"""ATP 资产「单模型测试」服务测试（离线，不需要 wine / ATP 引擎）。

覆盖：
1. 分段归一化与依赖补齐（simulate ⇒ geometry ⇒ materialize）
2. .lib 参数级解析 / .lis 致命行识别（对拍判据的解析层）
3. create_test_run 记录请求段（dry_run，不依赖 broker）
4. execute_test_run_job 的 dry_run 全链路接线
5. compare.json 结构（与 C# harness 同 schema，可直接 diff）
"""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.atp_asset import AtpAsset, AtpAssetRun
from app.models.dimension_item import DimensionItem
from app.models.dimension_type import DimensionType
from app.models.file_storage import FileIndexEntry, FileStorageBackend, FileStorageMount
from app.models.user import User
from app.schemas.atp_asset import AtpAssetCreateRequest, AtpAssetTestRunRequest
from app.services import atp_asset_service, atp_asset_test_service
from app.services.atp_asset_test_service import (
    COMPARE_SCHEMA,
    STAGE_ORDER,
    _TestContext,
    _lis_has_halt,
    _normalize_stages,
    _parse_named_values,
)


def _build_sessionmaker():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        bind=engine,
        tables=[
            FileStorageBackend.__table__,
            FileStorageMount.__table__,
            FileIndexEntry.__table__,
            User.__table__,
            DimensionType.__table__,
            DimensionItem.__table__,
            AtpAsset.__table__,
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


def _build_zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _create_asset(session: Session, *, code: str = "ATP-TEST-001", tower_type: str = "d220maotou",
                  voltage_level: str = "220") -> AtpAsset:
    asset = atp_asset_service.create_asset(
        session,
        AtpAssetCreateRequest(code=code, name="测试资产", voltage_level=voltage_level, tower_type=tower_type),
        actor_user_id="tester",
    )
    assert asset is not None
    atp_asset_service.upload_asset_archive(
        session,
        asset_id=asset.id,
        archive_filename="model.zip",
        archive_content=_build_zip(
            {
                "work.atp": "$INCLUDE, D:\\ATP\\220\\maotou\\fanji\\M123\\long.lib, X0148A, X0148B, X0148C\n",
                "long.dat": b"DAT PLACEHOLDER",
                "tpbig.exe": b"binary",
            }
        ),
        actor_user_id="tester",
    )
    refreshed = atp_asset_service.get_asset_by_id(session, asset.id)
    assert refreshed is not None
    return refreshed


# ───────────────────────── 1. 分段归一化 ─────────────────────────


def test_normalize_stages_defaults_to_all() -> None:
    assert _normalize_stages(None) == list(STAGE_ORDER)
    assert _normalize_stages([]) == list(STAGE_ORDER)
    assert _normalize_stages(["all"]) == list(STAGE_ORDER)


def test_normalize_stages_fills_dependencies() -> None:
    # 只请求 simulate → 必须补齐 materialize + geometry（否则产物不存在）
    assert _normalize_stages(["simulate"]) == ["materialize", "geometry", "simulate"]
    assert _normalize_stages(["geometry"]) == ["materialize", "geometry"]


def test_normalize_stages_rejects_unknown() -> None:
    with pytest.raises(HTTPException) as excinfo:
        _normalize_stages(["business"])
    assert excinfo.value.status_code == 400


# ───────────────────────── 2. 判据解析层 ─────────────────────────


def test_parse_named_values_extracts_work_atp_parameters(tmp_path: Path) -> None:
    """work.atp 的 $PARAMETER 段是参数级对拍的主判据（.lib 是位置制数值列，无 NAME=VALUE）。"""
    work_atp = tmp_path / "work.atp"
    work_atp.write_text(
        "BEGIN NEW DATA CASE\n"
        "$PARAMETER\n"
        "RER001=14.\n"
        "RELENS____=2.49\n"
        "REIGAN____=871.46\n"
        "REIAMP____=-871455.4\n"
        "REBB1_____=0.00005\n"
        "11HG      REHG______                                                          1.\n"
        "$ENDPARAMETER\n",
        encoding="latin-1",
    )
    values = _parse_named_values(work_atp)
    assert values["RER001"] == pytest.approx(14.0)
    assert values["RELENS____"] == pytest.approx(2.49)
    assert values["REIGAN____"] == pytest.approx(871.46)
    assert values["REIAMP____"] == pytest.approx(-871455.4)
    assert values["REBB1_____"] == pytest.approx(0.00005)
    # 位置制卡（11HG ...）不是赋值行，不计入
    assert len(values) == 5
    assert _parse_named_values(tmp_path / "missing.atp") == {}


def test_lis_has_halt_detects_fatal_lines(tmp_path: Path) -> None:
    ok = tmp_path / "ok.lis"
    ok.write_text("Totals: 0.016\nNormal termination.\n", encoding="latin-1")
    assert _lis_has_halt(ok) == []

    bad = tmp_path / "bad.lis"
    bad.write_text("Normal line\nHalt in POCKET. JTOKEN overflows limit\n", encoding="latin-1")
    hits = _lis_has_halt(bad)
    assert len(hits) == 1 and "Halt in POCKET" in hits[0]

    killed = tmp_path / "killed.lis"
    killed.write_text("KILL-code error stop\n", encoding="latin-1")
    assert len(_lis_has_halt(killed)) == 1

    assert _lis_has_halt(tmp_path / "missing.lis") == []


# ───────────────────────── 3. create_test_run ─────────────────────────


def test_create_test_run_records_requested_stages(tmp_path, monkeypatch) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session)
        monkeypatch.setattr(
            atp_asset_test_service,
            "_dispatch_test_run_task",
            lambda **kwargs: type("T", (), {"id": "task-fake"})(),
        )

        detail = atp_asset_test_service.create_test_run(
            session,
            asset_id=asset.id,
            payload=AtpAssetTestRunRequest(stages=["simulate"], current_ka=31.0),
            actor_user_id="tester",
        )

        assert detail.status == "pending"
        assert detail.task_id == "task-fake"
        assert detail.runner_kind == "atp"
        summary = detail.result_summary_json
        assert summary["schema"] == COMPARE_SCHEMA
        assert summary["requested_stages"] == ["materialize", "geometry", "simulate"]
    finally:
        session.close()


def test_create_test_run_rejects_missing_asset(tmp_path) -> None:
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        with pytest.raises(HTTPException) as excinfo:
            atp_asset_test_service.create_test_run(
                session,
                asset_id="not-exist",
                payload=AtpAssetTestRunRequest(),
                actor_user_id="tester",
            )
        assert excinfo.value.status_code == 404
    finally:
        session.close()


# ───────────────────────── 4. dry_run 全链路接线 ─────────────────────────


def test_execute_test_run_dry_run_lists_commands(tmp_path, monkeypatch) -> None:
    from app.core import database as database_module
    from app.services.fl_analysis_external import ResolvedExternalWaveformJob

    testing_session = _build_sessionmaker()
    # execute_test_run_job 内部自己开 SessionLocal（worker 侧行为）→ 指向测试库
    monkeypatch.setattr(database_module, "SessionLocal", testing_session)
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session, code="ATP-TEST-DRY")

        run = AtpAssetRun(
            asset_id=asset.id,
            status="pending",
            engine_mode="wine",
            runner_kind="atp",
            timeout_seconds=60,
            create_user="tester",
            update_user="tester",
        )
        session.add(run)
        session.commit()

        def fake_resolve(db, **kwargs):  # noqa: ANN001, ANN003
            return ResolvedExternalWaveformJob(
                adapter="atp",
                asset=asset,
                entry_file="work.atp",
                result_file=None,
                storage_mount_code="main",
                storage_root_path="/atp-assets/ATP-TEST-DRY",
                atp_text="$INCLUDE, D:\\ATP\\220\\maotou\\fanji\\M123\\long.lib, A, B, C\n",
                timeout_seconds=60,
                extra_args=[],
                environment={},
                contract={},
                parameter_bindings={},
            )

        monkeypatch.setattr(
            "app.services.fl_analysis_external.resolve_external_waveform_job", fake_resolve
        )
        monkeypatch.setattr(
            atp_asset_test_service, "_test_run_dir", lambda run_id: tmp_path / "runs" / run_id
        )
        monkeypatch.setattr(
            atp_asset_test_service,
            "_test_engine_dir",
            lambda **kwargs: tmp_path / "engine",
        )
        monkeypatch.setattr(
            atp_asset_test_service._TestContext,
            "_build_command",
            lambda self, *, input_path, relative: [
                "wine",
                "tpbig.exe",
                "both",
                str(input_path),
                "s",
                "-r",
            ],
        )
        monkeypatch.setattr(
            atp_asset_test_service, "_write_artifact_zip", lambda **kwargs: None
        )

        atp_asset_test_service.execute_test_run_job(
            run_id=run.id,
            payload_data=AtpAssetTestRunRequest(dry_run=True).model_dump(mode="json"),
            actor_user_id="tester",
        )

        session.expire_all()
        saved = atp_asset_service.get_run_by_id(session, run.id)
        assert saved is not None
        assert saved.status == "success"
        assert saved.exit_code == 0
        assert "tpbig.exe" in (saved.engine_command or "")
        assert "work.atp" in (saved.engine_command or "")
        assert saved.result_summary_json["dry_run"] is True
        assert saved.result_summary_json["schema"] == COMPARE_SCHEMA
    finally:
        session.close()


# ───────────────────────── 5. compare.json 结构 ─────────────────────────


def test_compare_payload_is_csharp_comparable(tmp_path) -> None:
    from app.services.fl_analysis_external import ResolvedExternalWaveformJob

    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        asset = _create_asset(session, code="ATP-TEST-CMP")
        resolved = ResolvedExternalWaveformJob(
            adapter="atp",
            asset=asset,
            entry_file="work.atp",
            result_file=None,
            storage_mount_code="main",
            storage_root_path="/atp-assets/ATP-TEST-CMP",
            atp_text="ATP INPUT",
            timeout_seconds=60,
            extra_args=[],
            environment={},
            contract={},
            parameter_bindings={},
        )
        payload = AtpAssetTestRunRequest(
            tower_kind="d220maotou",
            voltage_kv=220,
            scene="fanji",
            base_tower={"line_voltage_kv": 220, "ground_resistance": 7},
            profile={"insulator_length_mm": 2491.5},
            params_raw="d220maotou|ABC|是|是|是|14|7|7|43.5|2491.5|39|8|0|8|39|39|39|325|111|0|31|2.6|12|-5|2|直线|3|1|2.6|50",
            current_ka=31.0,
        )
        ctx = _TestContext(
            db=session,
            run_id="run1234567890",
            asset=asset,
            payload=payload,
            resolved_job=resolved,
            run_dir=tmp_path / "run",
            engine_dir=tmp_path / "engine",
            shim=atp_asset_test_service._test_shim("run1234567890"),
        )
        stage_results = {
            "materialize": atp_asset_test_service._stage_result(
                "materialize", verdicts=[atp_asset_test_service._verdict("ok", True)]
            )
        }
        # 参数级对拍主判据来自渲染后的 work.atp（$PARAMETER 段）
        (tmp_path / "run").mkdir(parents=True, exist_ok=True)
        (tmp_path / "run" / "work.atp").write_text(
            "$PARAMETER\nRER001=14.\nREIGAN____=871.46\n", encoding="latin-1"
        )
        compare = ctx.build_compare_payload(stage_results)

        assert compare["schema"] == COMPARE_SCHEMA
        assert compare["side"] == "web"
        assert compare["case"]["tower_type"] == "d220maotou"
        assert compare["case"]["voltage_kv"] == 220
        assert compare["case"]["params_raw"] == payload.params_raw
        assert compare["case"]["execution_options"]["binary_search_current_ka"] == 31.0
        assert compare["env"]["solver_host"] == "wine"
        assert compare["env"]["engine_fingerprints"] == {}
        assert compare["stages"]["materialize"]["status"] == "ok"
        # 单次 ATP 的固定雷电流必须进报告（对拍口径）
        assert compare["case"]["execution_options"]["binary_search_current_ka"] == payload.current_ka
    finally:
        session.close()


# ───────────────────────── 6. 无杆塔测试（模板驱动）─────────────────────────


def _ctx_without_tower(tmp_path, session, *, tower_type: str, voltage: str, code_suffix: str = "",
                       **payload_kwargs):
    """构造一个「无杆塔」测试上下文（资产维度 + 模板默认值）。"""
    from app.services.fl_analysis_external import ResolvedExternalWaveformJob

    code = f"ATP-NOTOWER-{tower_type}{code_suffix}"
    asset = _create_asset(session, code=code, tower_type=tower_type, voltage_level=voltage)
    resolved = ResolvedExternalWaveformJob(
        adapter="atp",
        asset=asset,
        entry_file="work.atp",
        result_file=None,
        storage_mount_code="main",
        storage_root_path=f"/atp-assets/{code}",
        atp_text="$PARAMETER\nRER001=PLACEHOLDER\n",
        timeout_seconds=60,
        extra_args=[],
        environment={},
        contract={},
        parameter_bindings={},
    )
    payload = AtpAssetTestRunRequest(
        tower_kind=tower_type,
        voltage_kv=int(voltage),
        current_ka=31.0,
        **payload_kwargs,
    )
    return _TestContext(
        db=session,
        run_id="run-notower-0001",
        asset=asset,
        payload=payload,
        resolved_job=resolved,
        run_dir=tmp_path / "run",
        engine_dir=tmp_path / "engine",
        shim=atp_asset_test_service._test_shim("run-notower-0001"),
    )


def test_template_params_source_needs_no_tower(tmp_path) -> None:
    """无杆塔测试：只给资产维度（塔型/电压），参数由参数模板默认值算出。"""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        ctx = _ctx_without_tower(tmp_path, session, tower_type="maotou", voltage="220")

        assert ctx.params_source == "template"
        params = ctx.ensure_params()

        assert len(params) > 10
        assert params["RER001"] == "10."       # 接地电阻（模板默认值 ground_r=10.0）
        assert params["REIGAN____"] == "31."   # 固定雷电流 31kA
        assert params["RELENS____"] == "5.95"  # 绝缘子串长（默认 insul_m=5.945m）
        diag = ctx.param_diagnostics
        assert diag["chain"], "应记录命中的模板链"
        assert diag["defaults_applied"], "应记录用到的默认上下文变量"
        assert diag["unresolved"] == {}
    finally:
        session.close()


def test_incomplete_template_defaults_refuse_to_run(tmp_path) -> None:
    """模板默认值不完整时必须显式报错（禁止静默算无意义结果）；显式放行才继续。"""
    testing_session = _build_sessionmaker()
    session: Session = testing_session()
    try:
        _seed_vfs_mount(session, root_dir=tmp_path / "vfs")
        # sihuita（四回路）暂未提供 c1_*..c4_* 默认值
        ctx = _ctx_without_tower(tmp_path, session, tower_type="sihuita", voltage="500")

        with pytest.raises(RuntimeError) as excinfo:
            ctx.ensure_params()
        message = str(excinfo.value)
        assert "默认值不完整" in message and "allow_incomplete_defaults" in message

        # 显式放行 → 允许用不完整参数跑（结果可能无物理意义）
        allowed = _ctx_without_tower(
            tmp_path,
            session,
            tower_type="sihuita",
            voltage="500",
            code_suffix="-ALLOW",
            allow_incomplete_defaults=True,
        )
        params = allowed.ensure_params()
        assert params
        assert allowed.param_diagnostics["unresolved"], "放行也要保留未解析诊断"
    finally:
        session.close()
