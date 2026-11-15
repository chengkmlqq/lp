"""LP-19：同跳绕击 EGM 容错统一 + 回路几何自检 + 失败信息区分。

本文件刻意不用 parametrize / fixture（兼容桩驱动），只使用普通函数 + 手动
monkeypatch（try/finally 还原），pytest 与最小测试驱动下都能运行。
"""
from __future__ import annotations

import sys
from pathlib import Path

from app.services import fl_analysis_service as svc
from app.services import atp_egm_trip_rate as egm

# 让脚本模块（位于 lp/scripts/）可被导入，用于审计函数单测。
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from scripts.check_test_line_circuit_geometry import audit_records  # noqa: E402


# ---------------------------------------------------------------------------
# 输入构造
# ---------------------------------------------------------------------------


def _fallback_kwargs(**over):
    kw = dict(
        tower_no="T1",
        voltage_kv=110.0,
        base_tower={"circuit_geometry_json": {"I": {}, "II": {}}},
        profile={},
        tower_type="guxing",
        raoji_withstand_ka=22.0,
        counterstrike_withstand_ka=100.0,
        result={},
    )
    kw.update(over)
    return kw


def _patch_compute(fn):
    """手动替换 EGM 计算函数，返回还原回调（不依赖 pytest fixture）。"""
    orig = egm.compute_shielding_trip_rate
    egm.compute_shielding_trip_rate = fn
    return lambda: setattr(egm, "compute_shielding_trip_rate", orig)


def _geo(circuit_count: int) -> dict:
    keys = ("I", "II", "III", "IV")
    g = {}
    for idx, key in enumerate(keys):
        if idx < circuit_count:
            g[key] = {
                "phase_spacing_m": {"upper": 7.0, "middle": 10.0, "lower": 8.0},
                "phase_height_m": {"upper": 56.0, "middle": 44.0, "lower": 33.0},
            }
    return {"circuit_geometry_json": g}


# ---------------------------------------------------------------------------
# 1) 统一容错：normal / tongtiao 共用的 _compute_egm_trip_rate_with_fallback
# ---------------------------------------------------------------------------


def test_fallback_skips_on_value_error_keeps_counterstrike():
    def boom(**_kwargs):
        raise ValueError(
            "塔型 guxing 的 EGM 程序 rjtzl_egm2.exe 期望 2 回路，"
            "但塔几何实际只有 1 回路 —— 塔型与几何不一致，拒绝静默计算"
        )

    restore = _patch_compute(boom)
    try:
        result = {"counterstrike_withstand_ka": 100.0, "shielding_withstand_ka": 22.0}
        rate = svc._compute_egm_trip_rate_with_fallback(**_fallback_kwargs(result=result))
        assert rate is None
        assert "shielding_trip_rate" not in result
        assert "shielding_trip_rate_method" not in result
        # 跳过 EGM 时保留已算出的反击 / 绕击耐雷结果，不让整塔失败
        assert result["counterstrike_withstand_ka"] == 100.0
        assert result["shielding_withstand_ka"] == 22.0
    finally:
        restore()


def test_fallback_skips_on_not_implemented():
    def boom(**_kwargs):
        raise NotImplementedError("直流/特型塔 EGM 原生引擎尚未移植")

    restore = _patch_compute(boom)
    try:
        result = {}
        rate = svc._compute_egm_trip_rate_with_fallback(**_fallback_kwargs(result=result))
        assert rate is None
        assert "shielding_trip_rate" not in result
    finally:
        restore()


def test_fallback_writes_rate_on_success():
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return 0.406567, 12.0

    restore = _patch_compute(fake)
    try:
        result = {}
        rate = svc._compute_egm_trip_rate_with_fallback(**_fallback_kwargs(result=result))
        assert rate == 0.406567
        assert result["shielding_trip_rate"] == 0.406567
        assert result["shielding_trip_rate_method"] == "egm"
        assert seen["tower_type"] == "guxing"
        assert seen["raoji_withstand_ka"] == 22.0
        assert seen["voltage_kv"] == 110.0
    finally:
        restore()


# ---------------------------------------------------------------------------
# 2) 回路几何自检纯函数
# ---------------------------------------------------------------------------


def test_expected_circuits_for_tower():
    cases = [
        ("guxing", 2),
        ("guxingd", 2),
        ("s110guxing", 2),
        ("maotou", 1),
        ("sihuita", 4),
        ("塔型:sihuita500", 4),
        ("ky", None),      # 直流/特型：无回路约束
        ("unknown", None),  # 塔型不可解析：跳过校验
    ]
    for tower_type, expected in cases:
        assert egm.expected_circuits_for_tower(tower_type) == expected, tower_type


def test_circuit_geometry_mismatch():
    # 单回几何 × 鼓型塔 → 错配（正是 TEST-OLD110guxing 的根因）
    reason = egm.circuit_geometry_mismatch("guxing", _geo(1))
    assert reason is not None and "期望 2 回路" in reason and "实际只有 1 回路" in reason
    # 双回几何 × 鼓型塔 → 一致
    assert egm.circuit_geometry_mismatch("guxing", _geo(2)) is None
    # 双回 × 单回塔 → 错配；单回 × 单回塔 → 一致
    assert egm.circuit_geometry_mismatch("maotou", _geo(2)) is not None
    assert egm.circuit_geometry_mismatch("maotou", _geo(1)) is None
    # 四回塔
    assert egm.circuit_geometry_mismatch("sihuita", _geo(4)) is None
    assert egm.circuit_geometry_mismatch("sihuita", _geo(2)) is not None
    # 直流/特型与不可解析塔型不做回路校验
    assert egm.circuit_geometry_mismatch("ky", _geo(1)) is None
    assert egm.circuit_geometry_mismatch("unknown", _geo(1)) is None


def test_audit_records_filtering():
    records = [
        {"code": "TEST-OLD110guxing", "voltage_level": "110", "tower_type": "guxing",
         "status": "enabled", "base_tower": _geo(1)},
        {"code": "TEST-WEB-110-tongtiao-guxing", "voltage_level": "110", "tower_type": "guxing",
         "status": "enabled", "base_tower": _geo(2)},
        {"code": "OTHER-220", "voltage_level": "220", "tower_type": "maotou",
         "status": "enabled", "base_tower": _geo(2)},
        {"code": "NO-GEOMETRY", "voltage_level": "110", "tower_type": "guxing",
         "status": "enabled", "base_tower": {}},
    ]
    # 110 guxing 自检：只命中单回的老线路，双回线路与 220 线路/无几何记录不算错配
    findings = audit_records(records, voltage="110", tower_type="guxing")
    assert [f["code"] for f in findings] == ["TEST-OLD110guxing"]
    assert "塔型与几何不一致" in findings[0]["reason"]
    # 全量自检还应命中 220 的双回 × 单回塔错配
    all_findings = audit_records(records)
    assert {f["code"] for f in all_findings} == {"TEST-OLD110guxing", "OTHER-220"}


# ---------------------------------------------------------------------------
# 3) 全部塔失败文案：区分阶段 + 透出真实原因
# ---------------------------------------------------------------------------


def test_all_towers_failed_message():
    msg = svc._all_towers_failed_message(
        1, ["ValueError: 塔型 guxing 期望 2 回路，但塔几何实际只有 1 回路 —— 塔型与几何不一致"]
    )
    assert "全部 1 基杆塔计算失败" in msg
    assert "引擎执行失败" in msg
    assert "结果计算阶段失败" in msg
    assert "并非 ATP 模型不可运行" in msg
    assert "塔型与几何不一致" in msg  # 真实原因透出

    # 无各塔报错时仍保留两类区分，不出现空「各塔实际报错」
    msg2 = svc._all_towers_failed_message(2, None)
    assert "常见原因分两类" in msg2
    assert "各塔实际报错" not in msg2

    # 去重：同一原因重复不刷屏
    msg3 = svc._all_towers_failed_message(3, ["ValueError: 同一原因", "ValueError: 同一原因"])
    assert msg3.count("同一原因") == 1
