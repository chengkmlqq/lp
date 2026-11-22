"""风电场计算（LP-35）：预检、GBK 解析、风险/建议规则重算。"""

from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from app.services import wind_farm_calc as calc
from app.services import wind_farm_calc_service as service


def _p0abc(nx: int, ny: int) -> bytes:
    header = struct.pack(">6H", 11934, 11934 + nx, 2523, 2523 + ny, nx, ny)
    return header + b"\x00\x00" * (nx * ny)


def _files(n: int = 2, nx: int = 3, ny: int = 4, s: float = 1.0) -> dict[str, bytes]:
    file1 = f"{n}\n{s}\n119.34\n25.23\n{nx}\n{ny}\n".encode()
    file2 = "".join(
        "\t".join(["119", "20", "24", "25", "13", "48", "10", "80", "40", "1", "1"]) + "\n"
        for _ in range(n)
    ).encode()
    file3 = "".join(f"{i + 1}\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n" for i in range(n)).encode()
    file4 = "".join("5.5\n" for _ in range(n)).encode()
    return {
        "file_1.txt": file1,
        "file_2.txt": file2,
        "file_3.txt": file3,
        "file_4.txt": file4,
        "P0.abc": _p0abc(nx, ny),
    }


def _gbk_out(*rows: tuple[int, str, str, str, str]) -> bytes:
    lines = [f"{seq}\t{lon}\t{lat}\t{v}\t{risk}\t{suggestion}" for seq, lon, lat, v, risk, suggestion in rows]
    return ("\n".join(lines) + "\n").encode("gbk")


# ---------------------------------------------------------------------------
# file_1 解析
# ---------------------------------------------------------------------------
def test_parse_file1_reads_six_parameters() -> None:
    params = calc.parse_file1(b"50\n1.25\n119.34\n25.23\n100\n80\n")
    assert params.n == 50
    assert params.s == 1.25
    assert params.start_lon == 119.34
    assert params.start_lat == 25.23
    assert (params.nx, params.ny) == (100, 80)


def test_parse_file1_rejects_missing_lines() -> None:
    with pytest.raises(calc.WindFarmCalcError):
        calc.parse_file1(b"1\n2\n3\n")


# ---------------------------------------------------------------------------
# 预检
# ---------------------------------------------------------------------------
def test_preflight_accepts_valid_files() -> None:
    report = calc.preflight(_files(n=3))
    assert report.ok is True, report.errors
    assert report.params is not None
    assert report.params.n == 3
    assert report.grid_rows == 3


@pytest.mark.parametrize("missing", ["file_1.txt", "file_2.txt", "file_3.txt", "file_4.txt", "P0.abc"])
def test_preflight_rejects_missing_file(missing: str) -> None:
    files = _files()
    del files[missing]
    report = calc.preflight(files)
    assert report.ok is False
    assert any(missing in err for err in report.errors)


def test_preflight_rejects_empty_file() -> None:
    files = _files()
    files["P0.abc"] = b""
    report = calc.preflight(files)
    assert report.ok is False


def test_preflight_rejects_fewer_rows_than_n() -> None:
    files = _files(n=2)
    files["file_3.txt"] = b"1\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n"  # 1 行 < N=2
    report = calc.preflight(files)
    assert report.ok is False
    assert any("file_3.txt 行数 1 少于 N=2" in err for err in report.errors)


def test_preflight_accepts_more_rows_than_n() -> None:
    """核心程序只取前 N 行：file_2/3/4 各 58 行 > N=50 应通过，多余行仅提示不阻断。"""
    n = 50
    files = _files(n=n, nx=10, ny=10)
    # 末尾 8 行放入越界的网格编号 / 回路号，验证校验只看前 N 行
    bad_3 = b"99999\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n"
    bad_2 = ("\t".join(["119", "20", "24", "25", "13", "48", "10", "80", "40", "1", "999"]) + "\n").encode()
    files["file_3.txt"] += bad_3 * 8
    files["file_2.txt"] += bad_2 * 8
    files["file_4.txt"] += b"5.5\n" * 8

    report = calc.preflight(files)
    assert report.ok is True, report.errors
    assert not report.errors
    assert report.grid_rows == n  # 进度/报告按实际参与计算的行数 N 计
    grid_check = next(c for c in report.checks if c["code"] == "file3.grid_id")
    circuit_check = next(c for c in report.checks if c["code"] == "file2.circuit")
    assert grid_check["passed"] is True
    assert circuit_check["passed"] is True

    warnings = [c for c in report.checks if c.get("level") == "warning"]
    assert {c["code"] for c in warnings} == {
        "count.extra.file_2.txt",
        "count.extra.file_3.txt",
        "count.extra.file_4.txt",
    }
    assert all(f"仅使用前 {n} 行" in c["message"] for c in warnings)


def test_preflight_rejects_grid_id_out_of_range() -> None:
    files = _files(n=2, nx=2, ny=2)
    files["file_3.txt"] = b"9\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n" * 2
    report = calc.preflight(files)
    assert report.ok is False
    assert any("网格编号" in err for err in report.errors)


def test_preflight_rejects_circuit_out_of_range() -> None:
    files = _files(n=2)
    lines = files["file_2.txt"].decode().splitlines()
    columns = lines[0].split("\t")
    columns[10] = "101"
    lines[0] = "\t".join(columns)
    files["file_2.txt"] = ("\n".join(lines) + "\n").encode()
    report = calc.preflight(files)
    assert report.ok is False
    assert any("回路号" in err for err in report.errors)


def test_preflight_rejects_p0abc_wrong_size() -> None:
    files = _files(nx=3, ny=4)
    files["P0.abc"] = files["P0.abc"][:-2]
    report = calc.preflight(files)
    assert report.ok is False
    assert any("P0.abc 字节数" in err for err in report.errors)


def test_preflight_rejects_p0abc_header_grid_mismatch() -> None:
    files = _files(nx=3, ny=4)
    files["P0.abc"] = _p0abc(5, 4)  # 头部 5×4，字节数自洽但与 file_1 的 3×4 不一致
    report = calc.preflight(files)
    assert report.ok is False
    assert any("file_1" in err for err in report.errors)


def test_preflight_rejects_too_many_turbines() -> None:
    files = _files(n=101)
    report = calc.preflight(files)
    assert report.ok is False
    assert any("1–100" in err for err in report.errors)


# ---------------------------------------------------------------------------
# 风险等级与建议文案
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,s,expected",
    [
        (0.5, 1.0, 1),
        (0.51, 1.0, 2),
        (1.0, 1.0, 2),
        (1.01, 1.0, 3),
        (1.5, 1.0, 3),
        (1.51, 1.0, 4),
    ],
)
def test_classify_risk_boundaries(value: float, s: float, expected: int) -> None:
    assert calc.classify_risk(value, s) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("I", 1), ("II", 2), ("III", 3), ("IV", 4), ("3", 3), ("iv", 4), ("?", None)],
)
def test_parse_risk_level(text: str, expected: int | None) -> None:
    assert calc.parse_risk_level(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("无", 1),
        ("停运", 2),
        ("停运(集电线)", 3),
        ("停运(风电场)", 4),
        ("全场停运", 4),
        ("", 1),
    ],
)
def test_classify_suggestion(text: str, expected: int) -> None:
    assert calc.classify_suggestion(text) == expected
    assert calc.suggestion_text(expected)


# ---------------------------------------------------------------------------
# file_out.txt 解析
# ---------------------------------------------------------------------------
def test_decode_file_out_handles_gbk() -> None:
    assert "停运(集电线)" in calc.decode_file_out("停运(集电线)".encode("gbk"))


def test_parse_file_out_recomputes_risk_and_suggestion() -> None:
    raw = _gbk_out(
        (1, "119.3400", "25.2300", "0.40000", "I", "无"),
        (2, "119.3500", "25.2400", "1.20000", "III", "停运(集电线)"),
        (3, "119.3600", "25.2500", "2.00000", "IV", "停运(风电场)"),
    )
    result = calc.parse_file_out(raw, s=1.0, expected_n=3)
    assert len(result.rows) == 3
    assert result.risk_mismatch_count == 0
    assert [row.risk_level for row in result.rows] == [1, 3, 4]
    assert [row.suggestion_code for row in result.rows] == [1, 3, 4]
    assert "停运(集电线)" in result.rows[1].raw_line


def test_parse_file_out_flags_gbk_risk_mismatch() -> None:
    raw = _gbk_out((1, "119.34", "25.23", "2.0", "I", "无"))
    result = calc.parse_file_out(raw, s=1.0, expected_n=1)
    assert result.rows[0].risk_level == 4  # 后端按 V 重算
    assert result.rows[0].parsed_risk_level == 1
    assert result.risk_mismatch_count == 1


def test_parse_file_out_rejects_row_count_mismatch() -> None:
    raw = _gbk_out((1, "119.34", "25.23", "0.4", "I", "无"))
    with pytest.raises(calc.WindFarmCalcError, match="行数"):
        calc.parse_file_out(raw, s=1.0, expected_n=2)


def test_parse_file_out_rejects_bad_sequence() -> None:
    raw = _gbk_out((2, "119.34", "25.23", "0.4", "I", "无"))
    with pytest.raises(calc.WindFarmCalcError, match="序号"):
        calc.parse_file_out(raw, s=1.0, expected_n=1)


def test_count_progress_marks() -> None:
    assert calc.count_progress_marks("I = 100.00  J = 3") == 1
    assert calc.count_progress_marks("no progress here") == 0


# ---------------------------------------------------------------------------
# 引擎路径白名单（与 ATP 引擎同款规则）
# ---------------------------------------------------------------------------
def test_resolve_engine_enforces_allowed_root(tmp_path, monkeypatch) -> None:
    exe = tmp_path / "wind_farm" / "FengLiFangLei-10.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")

    fake_settings = SimpleNamespace(
        wine_allowed_root=str(tmp_path),
        wind_farm_calc_executable="wind_farm/FengLiFangLei-10.exe",
        wine_binary_path="wine",
    )
    monkeypatch.setattr(service, "get_settings", lambda: fake_settings)

    assert service.resolve_engine() == str(exe)
    assert service.resolve_engine("wind_farm/../../evil.exe") is None
    outside = tmp_path.parent / "outside.exe"
    outside.write_bytes(b"MZ")
    assert service.resolve_engine(str(outside)) is None


# ---------------------------------------------------------------------------
# 引擎预检（LP-69）：API 只看 exe，Wine 来自执行 worker 的探测缓存
# ---------------------------------------------------------------------------
def _fake_engine_settings(tmp_path) -> SimpleNamespace:  # type: ignore[no-untyped-def]
    exe = tmp_path / "wind_farm" / "FengLiFangLei-10.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_bytes(b"MZ")
    return SimpleNamespace(
        wine_allowed_root=str(tmp_path),
        wind_farm_calc_executable="wind_farm/FengLiFangLei-10.exe",
        wine_binary_path="wine",
        wind_farm_calc_queue="wind_farm_calc",
        worker_registry_ttl_seconds=90,
    )


def _probe_payload(**overrides):  # type: ignore[no-untyped-def]
    import time

    payload = {
        "available": True,
        "version": "wine-8.0.2",
        "error": None,
        "binary": "/usr/bin/wine",
        "worker": "wind-farm-calc@lp",
        "checked_at": time.time(),
    }
    payload.update(overrides)
    return payload


def test_engine_info_uses_worker_probe_cache(tmp_path, monkeypatch) -> None:
    """API 容器没有 wine 也不影响判定：只要 worker 探测到 wine 就是就绪。"""
    monkeypatch.setattr(service, "get_settings", lambda: _fake_engine_settings(tmp_path))
    monkeypatch.setattr(service, "read_wine_probe_cache", lambda: _probe_payload())
    monkeypatch.setattr(service, "_online_wind_workers", lambda db: ("wind-farm-calc@lp", False))

    def _unexpected_dispatch() -> bool:
        raise AssertionError("60s 内已有新鲜探测结果时不应再派发探测任务")

    monkeypatch.setattr(service, "_dispatch_wine_probe", _unexpected_dispatch)

    info = service.get_engine_info()
    assert info.engine_exists is True
    assert info.worker_online is True
    assert info.worker_wine_available is True
    assert info.worker_wine_version == "wine-8.0.2"
    assert info.worker_probe_pending is False
    assert info.message == "引擎文件与执行 worker 的 Wine 均已就绪"


def test_engine_info_reports_worker_offline_without_dispatching(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(service, "get_settings", lambda: _fake_engine_settings(tmp_path))
    monkeypatch.setattr(service, "read_wine_probe_cache", lambda: None)
    monkeypatch.setattr(service, "_online_wind_workers", lambda db: (None, False))

    dispatched: list[bool] = []
    monkeypatch.setattr(service, "_dispatch_wine_probe", lambda: dispatched.append(True) or True)

    info = service.get_engine_info()
    assert info.engine_exists is True
    assert info.worker_online is False
    assert info.worker_wine_available is False
    assert dispatched == []
    assert "执行 worker 离线" in (info.message or "")


def test_engine_info_marks_probe_pending(tmp_path, monkeypatch) -> None:
    """worker 在线但探测结果还没回写（worker 忙）时，不误报 wine 不可用。"""
    monkeypatch.setattr(service, "get_settings", lambda: _fake_engine_settings(tmp_path))
    monkeypatch.setattr(service, "read_wine_probe_cache", lambda: None)
    monkeypatch.setattr(service, "_online_wind_workers", lambda db: ("wind-farm-calc@lp", False))
    monkeypatch.setattr(service, "_dispatch_wine_probe", lambda: True)
    monkeypatch.setattr(service, "_wait_for_wine_probe", lambda deadline: None)

    info = service.get_engine_info()
    assert info.worker_online is True
    assert info.worker_wine_available is False
    assert info.worker_probe_pending is True
    assert "正在探测" in (info.message or "")



# ---------------------------------------------------------------------------
# 服务端到端（SQLite + 假 exe，验证调度 → 解析 → 落库 → 统计）
# ---------------------------------------------------------------------------
def test_service_run_job_end_to_end(tmp_path, monkeypatch) -> None:
    import io
    import subprocess
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models.wind_data_prep import WindDataPrepBatch
    from app.models.wind_farm_calc import WindFarmCalcJob, WindFarmCalcResult

    class FakePopen:
        """假 Wine 子进程：启动时在 cwd 写出 GBK 的 file_out.txt，随后立即退出。"""

        def __init__(self, command, cwd, stdout, stderr, env, start_new_session):  # type: ignore[no-untyped-def]
            self.pid = 424242
            self.returncode = None
            self.stdout = io.BytesIO(b"I = 1.0\nI = 2.0\n")
            Path(cwd, "file_out.txt").write_bytes(
                _gbk_out(
                    (1, "119.34", "25.23", "0.4", "I", "无"),
                    (2, "119.35", "25.24", "2.0", "IV", "停运(风电场)"),
                )
            )
            self._polled = False

        def poll(self):  # type: ignore[no-untyped-def]
            if not self._polled:
                self.returncode = 0
                self._polled = True
            return self.returncode

        def wait(self, timeout=None):  # type: ignore[no-untyped-def]
            return self.poll()

    exe = tmp_path / "wind_farm" / "FengLiFangLei-10.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    fake_settings = SimpleNamespace(
        wine_allowed_root=str(tmp_path),
        wind_farm_calc_executable="wind_farm/FengLiFangLei-10.exe",
        wind_farm_calc_queue="wind_farm_calc",
        wine_binary_path="wine",
        wind_farm_calc_exe_soft_timeout_seconds=60,
        wind_farm_calc_exe_hard_timeout_seconds=120,
    )
    store: dict[str, bytes] = {}
    monkeypatch.setattr(service, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(service, "_fetch_prep_files", lambda batch: _files(n=2))
    monkeypatch.setattr(service.minio_storage, "put_object", lambda key, data, **kw: store.__setitem__(key, data))
    monkeypatch.setattr(subprocess, "Popen", FakePopen)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(WindDataPrepBatch(id="batch-x", name="测试批次", status="completed"))
    job = WindFarmCalcJob(
        id="job-e2e", name="测试计算", prep_batch_id="batch-x",
        status="pending", stage="fetching", progress=0,
    )
    db.add(job)
    db.commit()

    result = service.run_job(db, "job-e2e", task_id="fake-task", on_progress=lambda *_: None)
    assert result["status"] == "completed"
    assert result["turbine_count"] == 2
    db.refresh(job)
    assert job.status == "completed" and job.progress == 100
    assert (job.risk_I_count, job.risk_IV_count) == (1, 1)
    assert job.farm_shutdown_count == 1
    assert job.shutdown_count == 1
    assert job.output_object_key and job.output_object_key in store
    rows = db.query(WindFarmCalcResult).filter_by(job_id="job-e2e").order_by(WindFarmCalcResult.seq.asc()).all()
    assert [r.seq for r in rows] == [1, 2]
    assert [r.risk_level for r in rows] == [1, 4]
    assert "停运(风电场)" in rows[1].raw_line


def test_probe_wine_engine_task_writes_cache(monkeypatch) -> None:
    """探测任务在 worker 内跑 `wine --version`，并把结果写回 Redis 缓存。"""
    from app.services.wine_probe import WineProbeResult
    from app.tasks import wind_farm_calc_tasks as tasks

    monkeypatch.setattr(tasks, "wine_binary_command", lambda: "/usr/bin/wine")
    monkeypatch.setattr(
        tasks,
        "probe_wine_binary",
        lambda binary, timeout_seconds=10: WineProbeResult(True, "wine-8.0.2", None),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(tasks, "write_wine_probe_cache", lambda payload: captured.update(payload))

    result = tasks.probe_wine_engine()
    assert result["available"] is True
    assert result["version"] == "wine-8.0.2"
    assert result["binary"] == "/usr/bin/wine"
    assert captured == result


def test_engine_info_falls_back_to_celery_inspect(tmp_path, monkeypatch) -> None:
    """注册表行缺队列信息时，用 Celery active_queues 确认执行 worker，避免误报离线。"""
    monkeypatch.setattr(service, "get_settings", lambda: _fake_engine_settings(tmp_path))
    monkeypatch.setattr(service, "read_wine_probe_cache", lambda: _probe_payload())
    monkeypatch.setattr(service, "_online_wind_workers", lambda db: (None, True))
    monkeypatch.setattr(
        service,
        "_celery_worker_for_queue",
        lambda queue_name: "wind-farm-calc@lp" if queue_name == "wind_farm_calc" else None,
    )

    info = service.get_engine_info()
    assert info.worker_online is True
    assert info.worker_wine_available is True


def test_worker_signals_extracts_queues_from_task_consumer() -> None:
    """Celery 5.6 的队列列表在 consumer.task_consumer.queues 上。"""
    from app.core import worker_signals

    class _TaskConsumer:
        queues = [SimpleNamespace(name="wind_farm_calc"), SimpleNamespace(name="celery")]

    sender = SimpleNamespace(consumer=SimpleNamespace(task_consumer=_TaskConsumer()))
    assert worker_signals._extract_queue_names(sender) == ["wind_farm_calc", "celery"]
