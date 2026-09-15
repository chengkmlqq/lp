"""EGM 几何注入文件（param_main_cic.txt）对齐 C# 的测试。

C# 权威实现：`ComputeLightningProtection.cs:3054-3140` 的 `switch (rjEGM_Type)`：
  case 1（单回 egm1）10 个值 / case 2（双回 egm2）16 个值 / case 3（四回 egm3）28 个值。
文件按「前 n_circle 个值=各圆 x，后 n_circle 个值=各圆 y」组织（exe 只读 2×n_circle 个）。
"""
from __future__ import annotations

import pytest

from app.services.atp_egm_trip_rate import build_cic


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
    return {"circuit_geometry_json": geo}


def _profile(structure_kind: str = "直线") -> dict:
    return {"structure_kind": structure_kind, "insulator_length_m": 8390.0,
            "extra_profile_json": {"lightning_wire": {
                "left_mid_distance_m": -12.4, "right_mid_distance_m": 12.4, "height_m": 68.0}}}


def _vals(text: str) -> list[float]:
    return [float(t) for t in text.split()]


def test_single_circuit_10_values() -> None:
    """单回 egm1：10 个值；直线塔相高减绝缘子串长。"""
    vals = _vals(build_cic(base_tower=_tower(1), profile=_profile("直线"), egm_type=1))
    assert vals == [-12.4, 12.4, -7.0, 10.1, 8.3, 68.0, 68.0, 56.0 - 8.39, 44.2 - 8.39, 33.0 - 8.39]


def test_single_circuit_tension_tower_keeps_height() -> None:
    """耐张塔（C#: 非「直线」不减绝缘子串长）。"""
    vals = _vals(build_cic(base_tower=_tower(1), profile=_profile("耐张"), egm_type=1))
    assert vals[7:] == [56.0, 44.2, 33.0]


def test_double_circuit_16_values_pairs() -> None:
    """双回 egm2：16 个值；相中距按「上/中/下」成对（左负右正），高度成对。"""
    vals = _vals(build_cic(base_tower=_tower(2), profile=_profile("直线"), egm_type=2))
    assert len(vals) == 16
    assert vals == [-12.4, 12.4, -7.0, 7.0, -10.1, 10.1, -8.3, 8.3,
                    68.0, 68.0,
                    56.0 - 8.39, 56.0 - 8.39, 44.2 - 8.39, 44.2 - 8.39, 33.0 - 8.39, 33.0 - 8.39]


def test_four_circuit_28_values_grouped_by_circuit() -> None:
    """四回 egm3：28 个值；相中距按「回路」分组（I/III 取负、II/IV 取正），高度一律减绝缘子串长。"""
    vals = _vals(build_cic(base_tower=_tower(4), profile=_profile("耐张"), egm_type=3))
    assert len(vals) == 28
    xs = [-12.4, 12.4,
          -7.0, -10.1, -8.3, 8.0, 11.1, 9.3,
          -9.0, -12.1, -10.3, 10.0, 13.1, 11.3]
    off = 8.39
    hs = [68.0, 68.0,
          56.0 - off, 44.2 - off, 33.0 - off,
          57.0 - off, 45.2 - off, 34.0 - off,
          58.0 - off, 46.2 - off, 35.0 - off,
          59.0 - off, 47.2 - off, 36.0 - off]
    assert vals == xs + hs


def test_four_circuit_requires_all_four_circuits() -> None:
    """四回塔几何不全时明确抛错（不静默写少值 → 否则 exe 会拿 0 补位算出垃圾）。"""
    with pytest.raises(ValueError) as exc:
        build_cic(base_tower=_tower(2), profile=_profile(), egm_type=3)
    assert "四回路" in str(exc.value) or "4 个回路" in str(exc.value)


def test_unknown_egm_type_raises() -> None:
    for egm_type in (4, 5, 6):
        with pytest.raises(ValueError):
            build_cic(base_tower=_tower(2), profile=_profile(), egm_type=egm_type)
