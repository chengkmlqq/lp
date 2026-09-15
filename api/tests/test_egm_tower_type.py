"""EGM 程序选型对齐 C#（按塔型选 + 一致性校验不符即抛错）的测试。

C# 权威实现：
  * 塔型名数组 `MyParamClass.cs:121-137 mNames_GanTa`（15 种，顺序照抄）
  * 模型串后缀匹配 `MyParamClass.cs:2831-2841`（EndsWith("0"名) / "5"名 / "66"名 / ":名500" / ":名800"）
  * 塔型→程序映射 `LP/LP/bin/Debug/SettingTxtFile/tzl_model.txt`（rjEGM_Type：1 单回 / 2 双回 / 3 四回 / 4 egm4 / 5-6 直流）

规则：选程序只看塔型（C# 不看回路数）；塔型期望回路数与几何实际回路数不符即抛错。

注：本文件刻意不用 parametrize / fixture（容器镜像无 pytest，用 scripts/run_tests_min.py
的桩驱动时只支持普通函数 + pytest.raises）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import egm_native
from app.services.atp_egm_trip_rate import (
    compute_shielding_trip_rate,
    egm_type_for_tower,
    parse_tower_name,
)

# ---------------------------------------------------------------------------
# 输入构造（复用 test_atp_egm_cic.py 的风格）
# ---------------------------------------------------------------------------


def _tower(circuit_count: int) -> dict:
    geo = {}
    for idx, key in enumerate(("I", "II", "III", "IV")):
        if idx >= circuit_count:
            geo[key] = {"phase_spacing_m": {"upper": None, "middle": None, "lower": None},
                        "phase_height_m": {"upper": None, "middle": None, "lower": None}}
            continue
        geo[key] = {
            "phase_spacing_m": {"upper": 7.0 + idx, "middle": 10.1 + idx, "lower": 8.3 + idx},
            "phase_height_m": {"upper": 56.0 + idx, "middle": 44.2 + idx, "lower": 33.0 + idx},
        }
    return {"circuit_geometry_json": geo, "lightning_density": 2.8,
            "line_lightning_param_json": {"雷电流幅值a": 25.109, "雷电流幅值b": 3.62},
            "slope_1": 0.0, "slope_2": 0.0}


def _profile() -> dict:
    return {"structure_kind": "直线", "insulator_length_m": 8390.0,
            "current_a": 25.109, "current_b": 3.62,
            "extra_profile_json": {"lightning_wire": {
                "left_mid_distance_m": -12.4, "right_mid_distance_m": 12.4, "height_m": 68.0}}}


# ---------------------------------------------------------------------------
# 塔型名解析（C# 后缀规则）
# ---------------------------------------------------------------------------


def test_parse_tower_name_csharp_rules() -> None:
    cases = [
        ("s500guxing", "guxing"),     # EndsWith("0guxing")
        ("s110guxing", "guxing"),
        ("s220ganzi", "ganzi"),
        ("d500shangzi", "shangzi"),
        ("s500sihuita", "sihuita"),
        ("s500zxj", "zxj"),           # 不会被 zj/zx 抢先（精确后缀匹配）
        ("s500guxingd", "guxingd"),
        ("s66ganzi", "ganzi"),
        ("s35maotou", "maotou"),
        ("塔型:guxing500", "guxing"),  # EndsWith(":guxing500")
        ("塔型:guxing800", "guxing"),  # EndsWith(":guxing800")
    ]
    for model_string, expected in cases:
        got = parse_tower_name(model_string)
        assert got == expected, f"模型串 {model_string!r}: 期望 {expected!r}，实际 {got!r}"


def test_parse_tower_name_unknown_returns_none() -> None:
    for bad in ("直线", "", "s500unknown"):
        assert parse_tower_name(bad) is None, f"{bad!r} 应解析失败"


def test_parse_tower_name_loose_via_egm_type() -> None:
    """纯塔型名（无 C# 电压前缀）也能解析：egm_type_for_tower 内部有最长命中兜底。"""
    assert egm_type_for_tower("guxing", 2) == 2
    assert egm_type_for_tower("guxingd", 2) == 2
    assert egm_type_for_tower("ganzi", 1) == 1


# ---------------------------------------------------------------------------
# 按塔型选程序（egm_type_for_tower）
# ---------------------------------------------------------------------------


def test_egm_type_by_tower_type() -> None:
    assert egm_type_for_tower("s500guxing", 2, voltage_kv=500) == 2
    assert egm_type_for_tower("s220ganzi", 1, voltage_kv=220) == 1
    assert egm_type_for_tower("s500sihuita", 4, voltage_kv=500) == 3
    assert egm_type_for_tower("s110maotou", 1, voltage_kv=110) == 1
    assert egm_type_for_tower("s500guxingd", 2, voltage_kv=500) == 2


def test_egm_type_mismatch_raises() -> None:
    """塔型期望回路数与几何实际回路数不符 → 抛错（信息含塔型/期望/实际）。"""
    with pytest.raises(ValueError) as exc:
        egm_type_for_tower("s500guxing", 1)
    assert "期望 2 回路" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        egm_type_for_tower("s500ganzi", 2)
    assert "期望 1 回路" in str(exc.value)
    with pytest.raises(ValueError) as exc:
        egm_type_for_tower("s500sihuita", 2)
    assert "期望 4 回路" in str(exc.value)


def test_egm_type_unparseable_raises() -> None:
    """塔型解析不出来 → 抛错（C# 同样拒绝 mIndexOfGanTaName=-1 的塔），禁止按回路数猜。"""
    for bad in ("", "直线", "耐张", "s500unknown"):
        with pytest.raises(ValueError) as exc:
            egm_type_for_tower(bad, 2)
        assert "解析" in str(exc.value), f"{bad!r} 的错误信息应含「解析」：{exc.value}"


def test_egm_type_dc_not_implemented() -> None:
    """直流/特型塔型（egm4/egmDC/egm_zhiliu）→ 明确报未移植。"""
    for tower_type in ("s500zj", "s800zx", "s500zxj", "s500ky", "s500nz", "s500zhiliu", "s500vzhiliu"):
        with pytest.raises(NotImplementedError) as exc:
            egm_type_for_tower(tower_type, 2)
        assert "未移植" in str(exc.value), f"{tower_type} 的错误信息应含「未移植」：{exc.value}"


def test_egm_type_voltage_not_supported() -> None:
    """C# tzl_model 该塔型没有对应电压的 EGM 行（如 sihuita 无 330）→ 抛错。"""
    with pytest.raises(ValueError) as exc:
        egm_type_for_tower("s330sihuita", 4, voltage_kv=330)
    assert "未配置" in str(exc.value)


# ---------------------------------------------------------------------------
# 入口冒烟：compute_shielding_trip_rate 把 tower_type 变成正确的 egm_type
# ---------------------------------------------------------------------------


def test_compute_shielding_trip_rate_passes_tower_type() -> None:
    """guxing 双回 → egm_type=2 传给原生引擎；两轮分量求和 ÷2（鼓型）。"""
    seen: dict = {}
    original = egm_native.run_egm

    def fake(cic_vals, ic_vals, *, voltage, egm_type, p_chunk=8, threads=None):
        seen["egm_type"] = egm_type
        seen["voltage"] = voltage
        return [1.0] * {1: 5, 2: 8, 3: 14}[egm_type]

    egm_native.run_egm = fake
    try:
        rate, _alpha = compute_shielding_trip_rate(
            atp_root=Path("/nonexistent"),
            voltage_kv=500.0,
            base_tower=_tower(2),
            profile=_profile(),
            tower_type="s500guxing",
            raoji_withstand_ka=22.0,
            env={},
            engine="native",
        )
    finally:
        egm_native.run_egm = original
    assert seen["egm_type"] == 2
    assert seen["voltage"] == 500
    # turn1 取 [2][4][6] = 3.0；turn2 取 [3][5][7] = 3.0 → total 6.0 ÷ 2（guxing）= 3.0
    assert rate == 3.0


def test_compute_shielding_trip_rate_mismatch_raises() -> None:
    """入口处塔型与几何回路数不一致 → 任务链路会明确抛错（不静默计算）。"""
    original = egm_native.run_egm

    def fake(cic_vals, ic_vals, *, voltage, egm_type, p_chunk=8, threads=None):
        raise AssertionError("不应走到引擎")

    egm_native.run_egm = fake
    try:
        with pytest.raises(ValueError) as exc:
            compute_shielding_trip_rate(
                atp_root=Path("/nonexistent"),
                voltage_kv=500.0,
                base_tower=_tower(1),   # guxing 塔型但几何只有 1 回
                profile=_profile(),
                tower_type="s500guxing",
                raoji_withstand_ka=22.0,
                env={},
                engine="native",
            )
        assert "期望 2 回路" in str(exc.value)
    finally:
        egm_native.run_egm = original
