"""EGM 原生引擎（app.services.egm_native）测试。

黄金样本来自 exe 目录里 C# 运行留下的 `<NN>_param_main_{cic,Ic,result}.txt`
（或「部署 exe 重跑」的新鲜输出）——原生实现必须与其 `%f`（6 位小数）逐位一致。

注意：单次计算量 = 电流档 350 × 入射角 179 × 圆数，纯 numpy 约 25~80s，故黄金用例只保留 2 个。
"""
from __future__ import annotations

import pytest

from app.services import egm_native


# 66kV 单回（egm1，5 圆）：ATP 资产目录 66/66egm 里 C# 运行留下的 00 号塔样本
CIC_66_00 = [-3.0, 3.0, -5.0, 3.0, 5.0, 25.0, 25.0, 17.99, 20.99, 17.99]
IC_66_00 = [2.85, 0.0, 31.0, 2.6, 2.0, 2.0, 1.0]
EXPECT_66_00 = "1.859840 1.859808 0.007757 0.000000 0.007648"

# 110kV 双回（egm2，8 圆）：110/110egm 25 号塔样本
CIC_110_25 = [-2.85, 2.85, -3.6, 3.6, -4.35, 4.35, -3.6, 3.6,
              33.5, 33.5, 29.2, 29.2, 24.9, 24.9, 21.0, 21.0]
IC_110_25 = [8.25951095296441, -6.21355706886269, 27.782, 3.19, 4.0, 4.0, 0.85]
EXPECT_110_25 = "1.951064 2.272742 0.015834 0.116930 0.009224 0.088817 0.000000 0.000252"


def _fmt(values) -> str:
    return " ".join("%f" % v for v in values)


def test_golden_66kv_single_circuit() -> None:
    """66kV 单回 vs exe 输出逐位一致。"""
    got = egm_native.run_egm(CIC_66_00, IC_66_00, voltage=66, egm_type=1)
    assert _fmt(got) == EXPECT_66_00


def test_golden_110kv_double_circuit() -> None:
    """110kV 双回（带地面倾角）vs exe 输出逐位一致。"""
    got = egm_native.run_egm(CIC_110_25, IC_110_25, voltage=110, egm_type=2)
    assert _fmt(got) == EXPECT_110_25


def test_unverified_combo_raises_not_silently_falls_back() -> None:
    """未对拍验证的组合必须明确抛错（禁止静默降级/静默出错）。"""
    for voltage, egm_type in ((800, 1), (1000, 1), (750, 2), (110, 3)):
        with pytest.raises(egm_native.EgmNotImplemented) as exc:
            egm_native.run_egm(CIC_66_00, IC_66_00, voltage=voltage, egm_type=egm_type)
        assert "LP_EGM_ENGINE" in str(exc.value)


def test_cic_too_short_raises() -> None:
    """几何参数不足时必须抛错。"""
    with pytest.raises(ValueError):
        egm_native.run_egm([1.0, 2.0, 3.0], IC_66_00, voltage=66, egm_type=1)


def test_ic_too_short_raises() -> None:
    with pytest.raises(ValueError):
        egm_native.run_egm(CIC_66_00, [2.85, 0.0, 31.0], voltage=66, egm_type=1)


def test_supported_table_matches_verified_flag() -> None:
    """supported() 只对 verified 组合为真。"""
    assert egm_native.supported(500, 2) is True
    assert egm_native.supported(110, 3) is False
    assert egm_native.supported(1000, 1) is False
