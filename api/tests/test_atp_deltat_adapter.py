"""work.atp 步长（dT）自适应：$PARAMETER 变量形态的波速/长度解析。

背景（2026-11-13 定位）：ATPDraw 导出的塔模型把分布参数支路的 A/B/Leng 三个字段
整体写成 ``$PARAMETER`` 变量名且**紧贴无空格**：

    -1XX0005XX0120                  ZRE02_VRE___RELE03 1 0

原实现只在行内扫描指数形数值来认波速，遇到变量名直接 ``continue`` 且不记
``skipped`` —— 整族模板识别 0 条支路，``t_min`` 恒为空，日志还打印
「未发现分布参数支路，无需适配」，把兜底失效伪装成正常跳过。750kV/66kV/35kV
共 12 个任务因此被 ATP 引擎 ``KILL=29`` 拒跑（dT 大于最短支路波行程）。

这里锁定三条不变量：
1. 波速/长度是变量名时能回查 ``$PARAMETER`` 得到真实值；
2. 三个字段紧密粘连时按 ATP 6 列字段宽度切块；
3. 解析不出来的 ``-1`` 行必须进 ``skipped``，不许静默吞掉。
"""

from __future__ import annotations

import pytest

from app.services.atp_deltat_adapter import (
    _extract_param_values,
    _find_param_velocity,
    analyze_distributed_lines,
    adapt_deltat,
)

_DT_FEATURE = "C  dT  >< Tmax >"


def _model(branch_lines: list[str], params: dict[str, float], dt: str = "5.E-9") -> str:
    """拼一个能被 _scan_branch_section / adapt_deltat 识别的最小 work.atp。"""
    param_block = "\n".join(f"{name}={value:g}" for name, value in params.items())
    branches = "\n".join(branch_lines)
    return (
        "BEGIN NEW DATA CASE\n"
        f"{_DT_FEATURE}< Xopt >< Copt >< Epsiln\n"
        f"   {dt}   2.E-5     50.     50.\n"
        "$PARAMETER\n"
        f"{param_block}\n"
        "BLANK\n"
        "/BRANCH\n"
        f"{branches}\n"
        "BLANK BRANCH\n"
        "BLANK SWITCH\n"
    )


def test_velocity_as_param_variable_is_resolved() -> None:
    """波速写成 VRE___ 时回查 $PARAMETER，t_min 与引擎一致（0.95m / 2.5e8 = 3.8ns）。"""
    text = _model(
        ["-1XX0005XX0120                  ZRE02_VRE___RELE03 1 0"],
        {"ZRE02_": 200.0, "VRE___": 2.5e8, "RELE03": 0.95},
    )
    lines, skipped = analyze_distributed_lines(text)

    assert skipped == []
    assert len(lines) == 1
    line = lines[0]
    assert line.velocity == pytest.approx(2.5e8)
    assert line.velocity_source == "param:VRE___"
    assert line.length == pytest.approx(0.95)
    assert line.length_source == "param:RELE03"
    assert line.travel_time == pytest.approx(3.8e-9, rel=1e-6)


def test_dt_narrowed_when_template_exceeds_travel_time() -> None:
    """dT=5ns > 3.8ns → 收窄到 t_min/2=1.9ns，且 Tmax 等后续列不动。"""
    text = _model(
        ["-1XX0005XX0120                  ZRE02_VRE___RELE03 1 0"],
        {"ZRE02_": 200.0, "VRE___": 2.5e8, "RELE03": 0.95},
    )
    result = adapt_deltat(text)

    assert result.changed is True
    assert result.original_dt == pytest.approx(5e-9)
    assert result.new_dt == pytest.approx(1.9e-9)
    assert result.t_min == pytest.approx(3.8e-9, rel=1e-6)

    dt_row = result.atp_text.splitlines()[2]
    assert dt_row.split()[0] == "1.9E-9"
    assert dt_row.split()[1] == "2.E-5"          # Tmax 未被改写
    assert dt_row.split()[2:] == ["50.", "50."]


def test_dt_untouched_when_already_small_enough() -> None:
    """dT=2ns < 6ns，只收窄不放宽。"""
    text = _model(
        ["-1XX0005XX0120                  ZRE02_VRE___RELE04 1 0"],
        {"ZRE02_": 200.0, "VRE___": 2.5e8, "RELE04": 1.5},
        dt="2.E-9",
    )
    result = adapt_deltat(text)

    assert result.changed is False
    assert result.new_dt is None
    assert result.t_min == pytest.approx(6e-9, rel=1e-6)
    assert result.atp_text == text


def test_literal_velocity_still_works() -> None:
    """原有数值形态不能回归：``180. 2.5E8  .5``。"""
    text = _model(
        ["-1XX0121XX0173   200. 2.5E8    .5 1 0"],
        {},
        dt="2.E-9",
    )
    lines, skipped = analyze_distributed_lines(text)

    assert skipped == []
    assert len(lines) == 1
    assert lines[0].velocity == pytest.approx(2.5e8)
    assert lines[0].velocity_source == "literal"
    assert lines[0].length == pytest.approx(0.5)
    assert lines[0].travel_time == pytest.approx(2e-9, rel=1e-6)


def test_velocity_var_with_literal_length() -> None:
    """波速是变量、长度是数值：v_end 之后取长度仍要正确。"""
    text = _model(
        ["-1XX0120XX0119    ZRE01_VRE___   20. 1 0"],
        {"ZRE01_": 150.0, "VRE___": 2.5e8},
    )
    lines, _ = analyze_distributed_lines(text)

    assert len(lines) == 1
    assert lines[0].length == pytest.approx(20.0)
    assert lines[0].length_source == "literal"


def test_unresolvable_velocity_is_reported_not_silent() -> None:
    """认不出波速的 -1 行必须进 skipped —— 否则「未发现分布参数支路」会把 bug 藏起来。"""
    text = _model(
        ["-1XX0001XX0002                  ZRE99_XXX___RELE99 1 0"],
        {"ZRE99_": 200.0},
    )
    lines, skipped = analyze_distributed_lines(text)

    assert lines == []
    assert len(skipped) == 1
    assert "波速字段既非数值也非可解析变量" in skipped[0]

    result = adapt_deltat(text)
    assert result.changed is False
    assert any("波速字段" in note for note in result.notes)


def test_undefined_length_variable_is_reported() -> None:
    """长度变量悬空（未规范化前）时如实报错——这正是 35kV 的 t_min 虚高来源。"""
    text = _model(
        ["-1XX0220XX0204                  ZRE02_VRE___RELE16 1 0"],
        {"ZRE02_": 200.0, "VRE___": 2.5e8},          # RELE16 缺失
    )
    lines, skipped = analyze_distributed_lines(text)

    assert lines == []
    assert any("RELE16" in note for note in skipped)


def test_param_name_trailing_underscore_normalised() -> None:
    """卡片 ``VRE___``（6 列补位）与参数表 ``VRE``（未补位）要能对齐。"""
    body = "-1XX0005XX0120    ZRE01_VRE___   0.95 1 0"
    params = _extract_param_values(
        "$PARAMETER\nZRE01_=150.\nVRE=250000000.\nBLANK\n"
    )
    found = _find_param_velocity(body, 14, params)

    assert found is not None
    velocity, start, end = found
    assert velocity == pytest.approx(2.5e8)
    assert body[start:end] == "VRE___"


def test_pathological_short_branch_raises() -> None:
    """亚厘米级支路（0.4mm）判为病态几何，不能默默收窄到硬下限以下。"""
    text = _model(
        ["-1XX0005XX0120                  ZRE02_VRE___RELE03 1 0"],
        {"ZRE02_": 200.0, "VRE___": 2.5e8, "RELE03": 0.0004},
    )
    from app.services.atp_deltat_adapter import AtpDataError

    with pytest.raises(AtpDataError):
        adapt_deltat(text)
