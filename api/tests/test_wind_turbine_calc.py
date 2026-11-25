"""单风机计算（LP-36）：参数校验 / golden case / CSV 解析 / 引擎多队列路由。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import wind_turbine_calc as calc
from app.services import wind_turbine_calc_service as service


# ---------------------------------------------------------------------------
# golden case（issue LP-36 §二，逐项误差 ≤1e-9，均值 0.006840169911441951）
# ---------------------------------------------------------------------------
def test_golden_csv_parses_all_twelve_angles() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes())
    assert len(parsed.rows) == 12
    assert [r.theta_deg for r in parsed.rows] == calc.GOLDEN_ANGLES
    for row, expected in zip(parsed.rows, calc.GOLDEN_FAILURE_RATES):
        assert abs(row.failure_rate - expected) <= 1e-9


def test_golden_mean_matches_reference() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes())
    assert abs(parsed.mean_failure_rate - calc.GOLDEN_MEAN) <= 1e-9


def test_golden_min_max_and_theta() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes())
    assert abs(parsed.min_failure_rate - min(calc.GOLDEN_FAILURE_RATES)) <= 1e-9
    assert abs(parsed.max_failure_rate - max(calc.GOLDEN_FAILURE_RATES)) <= 1e-9
    assert parsed.min_failure_rate_theta == calc.GOLDEN_ANGLES[calc.GOLDEN_FAILURE_RATES.index(parsed.min_failure_rate)]
    assert parsed.max_failure_rate_theta == calc.GOLDEN_ANGLES[calc.GOLDEN_FAILURE_RATES.index(parsed.max_failure_rate)]


def test_parse_csv_restricts_single_angle_to_requested_rows() -> None:
    """单角度任务：历史引擎会返回整条 0–110° 曲线，统计口径只能取请求角度。"""
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=[0])
    assert [r.theta_deg for r in parsed.rows] == [0.0]
    assert parsed.max_failure_rate_theta == 0.0
    assert parsed.min_failure_rate_theta == 0.0
    assert abs(parsed.max_failure_rate - calc.GOLDEN_FAILURE_RATES[0]) <= 1e-12
    assert abs(parsed.mean_failure_rate - calc.GOLDEN_FAILURE_RATES[0]) <= 1e-12
    assert len(parsed.all_rows) == 12
    assert parsed.has_unrequested_rows is True


def test_parse_csv_restricts_multi_angles_to_requested_rows() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=[0, 30, 60, 90])
    assert [r.theta_deg for r in parsed.rows] == [0.0, 30.0, 60.0, 90.0]
    assert parsed.max_failure_rate_theta == 60.0
    assert abs(parsed.mean_failure_rate - sum(calc.GOLDEN_FAILURE_RATES[i] for i in (0, 3, 6, 9)) / 4) <= 1e-12
    assert parsed.has_unrequested_rows is True


def test_parse_csv_dedupes_repeated_requested_angles() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=[0, 0])
    assert [r.theta_deg for r in parsed.rows] == [0.0]


def test_parse_csv_keeps_all_rows_when_angles_match_request() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=list(calc.GOLDEN_ANGLES))
    assert len(parsed.rows) == 12
    assert parsed.has_unrequested_rows is False
    assert abs(parsed.mean_failure_rate - calc.GOLDEN_MEAN) <= 1e-9


def test_parse_csv_rejects_missing_requested_angle() -> None:
    """引擎返回的角度不含请求角度时不能猜值，直接报错暴露契约不符。"""
    with pytest.raises(calc.WindTurbineCalcError) as excinfo:
        calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=[0, 15])
    assert "15" in str(excinfo.value)


def test_single_angle_chart_renders() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes(), angle_list=[0])
    png = calc.render_chart_png(parsed)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000


def test_parse_csv_with_bom_and_whitespace() -> None:
    raw = (
        "\ufeff Theta_deg , FailureRate , FailureRate_pct \n"
        " 0 , 0.00622877556642743 , 0.622877556642743 \n"
        "10 , 0.00630627791810152 , 0.630627791810152 \n"
    ).encode("utf-8")
    parsed = calc.parse_failure_rate_csv(raw)
    assert len(parsed.rows) == 2
    assert parsed.rows[0].theta_deg == 0.0
    assert abs(parsed.rows[0].failure_rate - calc.GOLDEN_FAILURE_RATES[0]) <= 1e-12


def test_parse_csv_rejects_empty_and_bad_numbers() -> None:
    with pytest.raises(calc.WindTurbineCalcError):
        calc.parse_failure_rate_csv(b"Theta_deg,FailureRate,FailureRate_pct\n")
    with pytest.raises(calc.WindTurbineCalcError):
        calc.parse_failure_rate_csv(b"0,not-a-number,1\n")


# ---------------------------------------------------------------------------
# 参数校验（issue LP-36 §四 / §七.4）
# ---------------------------------------------------------------------------
def _valid_kwargs(**overrides: object) -> dict:
    kwargs = dict(
        hub_height=105.5,
        receptor_radii=[53.6, 63.6, 73.6, 78.6, 82.6],
        blade_length=None,
        start_current=1.0,
        angle_list=list(calc.DEFAULT_ANGLE_LIST),
    )
    kwargs.update(overrides)
    return kwargs


def test_validate_defaults_ok() -> None:
    result = calc.validate_params(**_valid_kwargs())
    assert result.ok is True, result.errors
    assert result.params is not None
    assert result.params["blade_length"] == 82.6  # 默认 max(r_list)
    assert result.params["angle_list"] == calc.DEFAULT_ANGLE_LIST


@pytest.mark.parametrize(
    "override",
    [
        {"receptor_radii": []},
        {"receptor_radii": [10.0, 5.0]},           # 非递增
        {"receptor_radii": [10.0, 90.0], "blade_length": 82.6},  # r > R
        {"hub_height": 0.0},
        {"hub_height": -1.0},
        {"start_current": 0.0},
        {"start_current": -5.0},
        {"angle_list": []},
        {"angle_list": list(range(37))},
    ],
)
def test_validate_rejects_invalid_params(override: dict) -> None:
    result = calc.validate_params(**_valid_kwargs(**override))
    assert result.ok is False
    assert result.errors


def test_build_params_json_contract() -> None:
    params = calc.validate_params(**_valid_kwargs()).params
    assert params is not None
    payload = json.loads(calc.build_params_json(params).decode("utf-8"))
    assert set(payload) == {
        "hub_height", "receptor_radii", "blade_length", "start_current", "angle_list"
    }
    assert payload["receptor_radii"] == [53.6, 63.6, 73.6, 78.6, 82.6]


def test_render_chart_returns_png() -> None:
    parsed = calc.parse_failure_rate_csv(calc.golden_csv_bytes())
    png = calc.render_chart_png(parsed)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 1000


# ---------------------------------------------------------------------------
# 引擎管理多队列（P1）：worker_queue 字段 + 动态路由
# ---------------------------------------------------------------------------
def test_create_module_sets_worker_queue(monkeypatch) -> None:
    from app.services import fault_matlab_engine_service as engine

    saved: dict = {}
    monkeypatch.setattr(engine, "_load_modules", lambda db: [])
    monkeypatch.setattr(engine, "_save_modules", lambda db, modules, **kw: saved.update(modules=modules))
    monkeypatch.setattr(engine, "_publish_event", lambda *a, **kw: None)

    module = engine.create_module(
        object(),
        {"name": "单风机计算", "slug": "wind_turbine_calc", "worker_queue": "matlab-wind"},
        actor_user_id="u1",
    )
    assert module["worker_queue"] == "matlab-wind"
    assert saved["modules"][0]["worker_queue"] == "matlab-wind"


def test_legacy_module_defaults_to_diagnostics_queue(monkeypatch) -> None:
    from app.services import fault_matlab_engine_service as engine

    saved: dict = {}
    monkeypatch.setattr(engine, "_load_modules", lambda db: [])
    monkeypatch.setattr(engine, "_save_modules", lambda db, modules, **kw: saved.update(modules=modules))
    monkeypatch.setattr(engine, "_publish_event", lambda *a, **kw: None)

    module = engine.create_module(object(), {"name": "判别"}, actor_user_id="u1")
    assert module["worker_queue"] == "matlab-diagnostics"


def test_trigger_sync_routes_by_module_queue(monkeypatch) -> None:
    from app.services import fault_matlab_engine_service as engine

    captured: dict = {}

    class FakeResult:
        id = "task-123"

    class FakeTask:
        @staticmethod
        def apply_async(args=None, queue=None):
            captured["queue"] = queue
            captured["args"] = args
            return FakeResult()

    monkeypatch.setattr(engine, "get_module", lambda db, slug: {"slug": slug, "worker_queue": "matlab-wind", "worker_deploy_path": "/app/matlab-wind"})
    monkeypatch.setattr(
        engine,
        "_load_versions",
        lambda db, slug: {"releases": [{"version_hash": "abc", "worker_deploy_path": "/app/matlab-wind"}]},
    )
    import sys

    # 必须强制覆盖（之前的测试可能已导入真实任务模块，setdefault 不会生效）
    monkeypatch.setitem(sys.modules, "app.tasks.sync_matlab_engine_task", SimpleNamespace(sync_matlab_engine_module=FakeTask))

    task_id = engine.trigger_sync_for_module(object(), "wind_turbine_calc", actor_user_id="u1")
    assert task_id == "task-123"
    assert captured["queue"] == "matlab-wind"
    assert captured["args"][1] == "abc"


def test_queue_routing_uses_diagnostics_for_legacy(monkeypatch) -> None:
    from app.services import fault_matlab_engine_service as engine

    captured: dict = {}

    class FakeResult:
        id = "task-456"

    class FakeTask:
        @staticmethod
        def apply_async(args=None, queue=None):
            captured["queue"] = queue
            return FakeResult()

    monkeypatch.setattr(engine, "get_module", lambda db, slug: {"slug": slug, "worker_queue": "matlab-diagnostics"})
    monkeypatch.setattr(
        engine,
        "_load_versions",
        lambda db, slug: {"releases": [{"version_hash": "def"}]},
    )
    import sys

    monkeypatch.setitem(sys.modules, "app.tasks.sync_matlab_engine_task", SimpleNamespace(sync_matlab_engine_module=FakeTask))

    engine.trigger_sync_for_version(object(), "waveform_diagnosis", "def", actor_user_id="u1")
    assert captured["queue"] == "matlab-diagnostics"


def test_export_type_all_uses_zip(monkeypatch) -> None:
    job = SimpleNamespace(
        id="j1",
        name="test",
        mean_failure_rate=calc.GOLDEN_MEAN,
        chart_object_key=None,
    )
    monkeypatch.setattr(service, "_get_job_or_404", lambda db, job_id: job)

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeDb:
        def execute(self, *args, **kwargs):
            return FakeResult()

    content, media, filename = service.export_results(FakeDb(), "j1", export_type="all")
    assert media == "application/zip"
    assert filename.endswith(".zip")
    assert content[:2] == b"PK"  # ZIP magic
