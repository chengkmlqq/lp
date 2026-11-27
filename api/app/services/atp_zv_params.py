"""ZV 改造四变量（波速 / 主材、横材、斜材波阻抗）的逐塔注入解析。

背景：ZV 改造（波阻抗改造）后的 ATP 模型 `work.atp` 在 $PARAMETER 段写死了 4 个变量：
    VRE___  波速（m/s）       默认 250000000.（guxing 个别模型为 255000000.）
    ZRE01_  主材波阻抗（Ω）   默认 150.
    ZRE02_  横材波阻抗（Ω）   默认 200.
    ZRE03_  斜材波阻抗（Ω）   默认 1350.

用户希望按塔注入这些值：线路管理（CSV 导入 / 页面编辑）→
`profile.extra_profile_json.zv_params` →
参数定义（line_binding）→ 参数模板（ZRE01_/ZRE02_/ZRE03_/VRE___ 槽位）→
渲染覆盖 `work.atp` 中的字面量。

本模块是唯一的取值口径（build_context 配置路径与 compute_csharp_atp_params
代码路径共用），保证两条路径逐字节一致（scripts/atp_param_golden_test.py）。

约定：
- 未注入（缺失 / 非数值 / 非正数）→ 返回 None，由参数模板槽位的 `default` 兜底为
  150 / 200 / 1350 / 2.5E8；渲染阶段对**未注入**的变量不做数值覆写，
  保留模型自带字面量（guxing 的 255000000. 等），从而不改变存量结果。
- 注入值必须是正数（波速/波阻抗无 0 或负的物理意义），否则按未注入处理。
"""

from __future__ import annotations

from typing import Any, Mapping

# extra_profile_json.zv_params 内的键（CSV 列 / 页面表单同一口径）
ZV_WAVE_SPEED_KEY = "wave_speed_m_s"
ZV_IMPEDANCE_KEYS: tuple[str, ...] = ("z_1", "z_2", "z_3")
ZV_KEYS: tuple[str, ...] = (ZV_WAVE_SPEED_KEY, *ZV_IMPEDANCE_KEYS)

# 默认值（与 ZV 改造模型 $PARAMETER 段的字面量一致）
ZV_DEFAULTS: dict[str, float] = {
    ZV_WAVE_SPEED_KEY: 2.5e8,
    "z_1": 150.0,
    "z_2": 200.0,
    "z_3": 1350.0,
}

# 注入键 → ATP 参数名（渲染覆写与追溯用）
ZV_SLOT_BY_KEY: dict[str, str] = {
    ZV_WAVE_SPEED_KEY: "VRE___",
    "z_1": "ZRE01_",
    "z_2": "ZRE02_",
    "z_3": "ZRE03_",
}


def _positive_float(value: Any) -> float | None:
    """转正数；None / 空串 / 非数值 / <=0 → None（按未注入处理）。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def _zv_mapping(profile: Mapping[str, Any] | None) -> Mapping[str, Any]:
    prof = profile if isinstance(profile, Mapping) else {}
    extra = prof.get("extra_profile_json")
    if not isinstance(extra, Mapping):
        return {}
    zv = extra.get("zv_params")
    return zv if isinstance(zv, Mapping) else {}


def extract_zv_params(profile: Mapping[str, Any] | None) -> dict[str, float | None]:
    """读取逐塔注入值；未注入的键为 None（不做默认值回填）。"""
    raw = _zv_mapping(profile)
    return {key: _positive_float(raw.get(key)) for key in ZV_KEYS}


def injected_zv_keys(profile: Mapping[str, Any] | None) -> set[str]:
    """实际被注入（有效）的键集合。"""
    return {key for key, value in extract_zv_params(profile).items() if value is not None}


def resolve_zv_params(profile: Mapping[str, Any] | None) -> dict[str, float]:
    """读取注入值并回填默认值（150 / 200 / 1350 / 2.5E8）。"""
    extracted = extract_zv_params(profile)
    return {
        key: (extracted[key] if extracted[key] is not None else ZV_DEFAULTS[key])
        for key in ZV_KEYS
    }


def resolve_zv_slots(profile: Mapping[str, Any] | None) -> dict[str, float]:
    """ATP 参数名 → 数值（含默认回填），供 build_context / 代码路径取数。"""
    values = resolve_zv_params(profile)
    return {ZV_SLOT_BY_KEY[key]: values[key] for key in ZV_KEYS}


__all__ = [
    "ZV_DEFAULTS",
    "ZV_IMPEDANCE_KEYS",
    "ZV_KEYS",
    "ZV_SLOT_BY_KEY",
    "ZV_WAVE_SPEED_KEY",
    "extract_zv_params",
    "injected_zv_keys",
    "resolve_zv_params",
    "resolve_zv_slots",
]
