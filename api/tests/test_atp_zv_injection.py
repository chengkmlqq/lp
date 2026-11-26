"""ZV 改造四变量（波速 / 三段塔材波阻抗）逐塔注入的渲染与 dT 联动。

锁定三条不变量：
1. 未注入时**不覆写**模型里烤死的 ZRE/VRE 字面量（guxing 的 255000000. 等存量值不变）；
2. 注入后渲染出的 $PARAMETER 使用注入值；
3. dT 自适应基于**注入后的**波速重算最短行程时间（t=L/v），不沿用模型默认 2.5E8。
"""

from __future__ import annotations

import os

os.environ.setdefault("ATP_MAPPING_MODE", "code")

import pytest  # noqa: E402

from app.services.atp_deltat_adapter import adapt_deltat  # noqa: E402
from app.services.atp_zv_params import extract_zv_params, resolve_zv_params  # noqa: E402
from app.services.fl_analysis_external import (  # noqa: E402
    _zv_injection_snapshot,
    override_numeric_current_params,
    render_csharp_equality_template,
)

_DT_FEATURE = "C  dT  >< Tmax >"


def _template(params: dict[str, str]) -> str:
    block = "\n".join(f"{name}={value}" for name, value in params.items())
    return (
        "BEGIN NEW DATA CASE\n"
        f"{_DT_FEATURE}< Xopt >< Copt >< Epsiln\n"
        "   5.E-9   2.E-5     50.     50.\n"
        "$PARAMETER\n"
        f"{block}\n"
        "BLANK\n"
        "/BRANCH\n"
        "BLANK BRANCH\n"
    )


def _base_profile() -> tuple[dict, dict]:
    base_tower = {
        "tower_type": "s66shangzi",
        "line_voltage_kv": 66,
        "ground_resistance_ohm": 12.5,
        "circuit_geometry_json": {"tower_height_m": 42.0},
    }
    profile = {
        "tower_kind": "shangzi",
        "shield_wire_height_m": 43.5,
        "insulator_length_m": 5945,
        "call_height_m": 42.0,
        "current_a": 25.0,
        "current_type": 1,
        "geometry_layers_json": {
            "I": {
                "phase_height_m": {"upper": 65.5, "middle": 53.0, "lower": 42.0},
                "phase_spacing_m": {"upper": 12.0, "middle": 12.0, "lower": 12.0},
            },
        },
    }
    return base_tower, profile


def _param_value(text: str, name: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


def test_zv_defaults_and_injection_extraction() -> None:
    assert resolve_zv_params({}) == {
        "wave_speed_m_s": 2.5e8,
        "z_1": 150.0,
        "z_2": 200.0,
        "z_3": 1350.0,
    }
    assert extract_zv_params({}) == {
        "wave_speed_m_s": None,
        "z_1": None,
        "z_2": None,
        "z_3": None,
    }
    # 非正数 / 非数值按未注入处理
    assert extract_zv_params(
        {"extra_profile_json": {"zv_params": {"wave_speed_m_s": 0, "z_1": "abc", "z_2": 220}}}
    ) == {"wave_speed_m_s": None, "z_1": None, "z_2": 220.0, "z_3": None}


def test_not_injected_keeps_model_literals() -> None:
    """未注入：保留模型自带字面量（含 guxing 的 255000000.）。"""
    template = _template(
        {"ZRE01_": "150.", "ZRE02_": "200.", "ZRE03_": "1350.", "VRE___": "255000000."}
    )
    base_tower, profile = _base_profile()
    rendered, _notes = override_numeric_current_params(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert _param_value(rendered, "ZRE01_") == "150."
    assert _param_value(rendered, "ZRE02_") == "200."
    assert _param_value(rendered, "ZRE03_") == "1350."
    assert _param_value(rendered, "VRE___") == "255000000."


def test_injected_values_override_model_literals() -> None:
    template = _template(
        {"ZRE01_": "150.", "ZRE02_": "200.", "ZRE03_": "1350.", "VRE___": "250000000."}
    )
    base_tower, profile = _base_profile()
    profile["extra_profile_json"] = {
        "zv_params": {"wave_speed_m_s": 2.4e8, "z_1": 160.5, "z_2": 210.0, "z_3": 1400.0}
    }
    rendered, _notes = override_numeric_current_params(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert _param_value(rendered, "ZRE01_") == "160.5"
    assert _param_value(rendered, "ZRE02_") == "210."
    assert _param_value(rendered, "ZRE03_") == "1400."
    assert _param_value(rendered, "VRE___") == "240000000."


def test_partial_injection_only_overrides_injected_keys() -> None:
    template = _template(
        {"ZRE01_": "150.", "ZRE02_": "200.", "ZRE03_": "1350.", "VRE___": "255000000."}
    )
    base_tower, profile = _base_profile()
    profile["extra_profile_json"] = {"zv_params": {"z_2": 222.0}}
    rendered, _notes = override_numeric_current_params(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert _param_value(rendered, "ZRE01_") == "150."
    assert _param_value(rendered, "ZRE02_") == "222."
    assert _param_value(rendered, "VRE___") == "255000000."


def test_equality_template_only_writes_injected_zv() -> None:
    """等号占位模板里 ZV 别名行：未注入保持原样，注入后写注入值。"""
    template = (
        "$PARAMETER\r\n"
        "ZRE01_ =ZRE01I\r\n"
        "ZRE01I =150.\r\n"
        "VRE___ =VREI\r\n"
        "VREI =255000000.\r\n"
        "BLANK\r\n"
    )
    base_tower, profile = _base_profile()
    untouched = render_csharp_equality_template(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert "ZRE01_ =ZRE01I" in untouched
    assert "VRE___ =VREI" in untouched

    profile["extra_profile_json"] = {"zv_params": {"z_1": 160.5, "wave_speed_m_s": 2.4e8}}
    rendered = render_csharp_equality_template(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert "ZRE01_=160.5" in rendered
    assert "VRE___=240000000." in rendered


def test_deltat_uses_injected_wave_speed() -> None:
    """渲染→dT 全链路：0.95m 支路，注入 2.4E8 后 dT 按 t=L/v 重算（而非模型默认 2.5E8）。"""
    template = (
        "BEGIN NEW DATA CASE\n"
        f"{_DT_FEATURE}< Xopt >< Copt >< Epsiln\n"
        "   5.E-9   2.E-5     50.     50.\n"
        "$PARAMETER\n"
        "ZRE02_=200.\nVRE___=250000000.\nRELEN2=0.95\n"
        "BLANK\n"
        "/BRANCH\n"
        "-1XX0005XX0120                  ZRE02_VRE___RELEN2 1 0\n"
        "BLANK BRANCH\n"
    )
    base_tower, profile = _base_profile()

    baseline = adapt_deltat(template)
    assert baseline.t_min == pytest.approx(3.8e-9, rel=1e-6)

    profile["extra_profile_json"] = {"zv_params": {"wave_speed_m_s": 2.4e8}}
    rendered, _notes = override_numeric_current_params(
        template, base_tower=base_tower, profile=profile, execution_options={}
    )
    assert _param_value(rendered, "VRE___") == "240000000."
    injected = adapt_deltat(rendered)
    assert injected.t_min == pytest.approx(0.95 / 2.4e8, rel=1e-6)
    assert injected.new_dt == pytest.approx(0.95 / 2.4e8 / 2.0, rel=1e-6)
    assert injected.new_dt > baseline.new_dt


def test_zv_injection_snapshot_records_source() -> None:
    base_tower, profile = _base_profile()
    snapshot = _zv_injection_snapshot(profile)
    assert snapshot["source"] == "default"
    assert snapshot["slots"]["VRE___"] == 2.5e8

    profile["extra_profile_json"] = {"zv_params": {"z_1": 151.0}}
    snapshot = _zv_injection_snapshot(profile)
    assert snapshot["source"] == "injected"
    assert snapshot["injected"] == {"z_1": 151.0}
    assert snapshot["slots"]["ZRE01_"] == 151.0
    assert snapshot["slots"]["ZRE02_"] == 200.0
