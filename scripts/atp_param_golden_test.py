"""ATP 参数模板配置化 —— golden 对照测试（无 DB / 无 tpbig，纯函数）。

目的：证明「配置路径」与「现有代码路径（compute_csharp_atp_params）」输出**逐字节一致**，
      从而可安全切换到配置驱动。

运行（api 容器内）：
    docker exec -e PYTHONPATH=/app lp-deploy-api-1 python3 /app/scripts/atp_param_golden_test.py

覆盖矩阵：15 种塔型字符串 × 8 电压 × 3 组几何 × 3 波形 × 3 组波形时间 × N 电流。
"""

from __future__ import annotations

import itertools
import sys
from typing import Any

from app.services.atp_param_resolver import build_context, compute_params_from_config, load_mappings, resolve_params
from app.services.fl_analysis_external import compute_csharp_atp_params

TOWER_TYPES = [
    "s500guxing", "s500guxingd", "s500jiubei", "s500maotou", "s500ganzi",
    "s500shangzi", "s500sihuita", "s500menxing",
    "d500zhiliu", "s500vzhiliu", "s110jiubeino", "s110maotouno", "s220shangzino",
    "s35sihuitano", "unknown_tower_type",
]
VOLTAGES = [35, 66, 110, 220, 330, 500, 750, 1000]

GEOMETRIES: list[dict[str, Any]] = [
    {  # 典型对称
        "shield": 73.5, "insul_mm": 5945, "call": 42.0, "lw": 12.4,
        "h": (65.5, 53.0, 42.0), "sp": (12.0, 12.0, 12.0),
    },
    {  # 非对称
        "shield": 43.5, "insul_mm": 4450, "call": 39.0, "lw": 9.85,
        "h": (39.0, 39.0, 39.0), "sp": (11.6, 0.0, 11.6),
    },
    {  # 缺字段（走 None 分支）
        "shield": None, "insul_mm": None, "call": None, "lw": None,
        "h": (None, 30.0, None), "sp": (None, None, 8.0),
    },
]
WAVE_TYPES = [1, 2, 3]
TIMES = [(2.6, 50.0), (2.0, 40.0), (None, None)]
CURRENTS = [146.0, 0.1]


def build_case(tower_type: str, voltage: int, geom: dict[str, Any], wave: int, head: float | None, tail: float | None, current: float):
    circuits = {}
    for idx, cid in enumerate(("I", "II", "III", "IV")):
        if idx == 0:
            hu, hm, hl = geom["h"]
            su, sm, sl = geom["sp"]
        else:  # II/III/IV 用错位值，确保四回路规则真正被覆盖
            hu, hm, hl = (geom["h"][0] or 40) - idx, (geom["h"][1] or 30) - idx, (geom["h"][2] or 20) - idx
            su, sm, sl = (geom["sp"][0] or 10) + idx, (geom["sp"][1] or 6) + idx, (geom["sp"][2] or 8) - idx
        circuits[cid] = {
            "phase_height_m": {"upper": hu, "middle": hm, "lower": hl},
            "phase_spacing_m": {"upper": su, "middle": sm, "lower": sl},
        }
    profile: dict[str, Any] = {
        "tower_kind": tower_type,
        "shield_wire_height_m": geom["shield"],
        "insulator_length_m": geom["insul_mm"],
        "call_height_m": geom["call"],
        "current_type": wave,
        "current_a": 25.109,
        "protection_angle_left_deg": 10.0,
        "protection_angle_right_deg": 10.0,
        "geometry_layers_json": {
            **circuits,
            "lightning_wire": {
                "left_mid_distance_m": geom["lw"], "right_mid_distance_m": geom["lw"],
                "height_m": geom["shield"],
            },
        },
    }
    if head is not None:
        profile["current_head_time_ms"] = head
    if tail is not None:
        profile["current_tail_time_ms"] = tail
    base_tower: dict[str, Any] = {
        "tower_type": tower_type,
        "line_voltage_kv": voltage,
        "ground_resistance_ohm": 10.0,
        "circuit_geometry_json": {
            "lightning_wire": {
                "left_mid_distance_m": geom["lw"], "right_mid_distance_m": geom["lw"], "height_m": geom["shield"],
            },
        },
    }
    options = {"binary_search_current_ka": current, "tower_kind": tower_type}
    return base_tower, profile, options


def diff_dicts(a: dict[str, str], b: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for key in sorted(set(a) | set(b)):
        if key not in a:
            problems.append(f"仅配置有 {key}={b[key]}")
        elif key not in b:
            problems.append(f"仅代码有 {key}={a[key]}")
        elif a[key] != b[key]:
            problems.append(f"{key}: 代码={a[key]} 配置={b[key]}")
    return problems


def main() -> int:
    rules = load_mappings()
    total = 0
    failures: list[str] = []
    for tower_type, voltage, geom, wave, (head, tail), current in itertools.product(
        TOWER_TYPES, VOLTAGES, GEOMETRIES, WAVE_TYPES, TIMES, CURRENTS
    ):
        base_tower, profile, options = build_case(tower_type, voltage, geom, wave, head, tail, current)
        code_params = compute_csharp_atp_params(base_tower=base_tower, profile=profile, execution_options=options)
        config_params = compute_params_from_config(
            base_tower=base_tower, profile=profile, execution_options=options, rules=rules
        )
        total += 1
        problems = diff_dicts(code_params, config_params)
        if problems:
            label = f"{tower_type}/v{voltage}/wave{wave}/h{head}/t{tail}/i{current}/geom{GEOMETRIES.index(geom)}"
            failures.append(f"[{label}]\n  " + "\n  ".join(problems))
            if len(failures) >= 12:
                break

    # 鼓型公式语义检查（代码路径因 wine 回退走不到 guxing 分支，单独锚定已核对过的 C# 语义值）
    guxing_expected = {
        "RELE01": "42.0", "RELE02": "63.0", "REHG______": "67.5", "REHC1_____": "51.6",
    }
    base_tower, profile, options = build_case("s500guxing", 500, GEOMETRIES[0], 1, 2.6, 50.0, 146.0)
    resolved = resolve_params(build_context(base_tower=base_tower, profile=profile, execution_options=options), rules, allow_fallback=False)
    for slot, want in guxing_expected.items():
        got = resolved.values.get(slot)
        if got != want:
            failures.append(f"[guxing 语义] {slot}: 期望 {want} 实得 {got}")

    print(f"对照用例：{total} 组（塔型×电压×几何×波形×时间×电流）")
    print(f"配置路径覆盖链示例（maotou/1000kV）：{resolve_params(build_context(**dict(zip(('base_tower','profile','execution_options'), build_case('s500maotou', 1000, GEOMETRIES[0], 1, 2.6, 50.0, 146.0)))), rules).chain}")
    if failures:
        print(f"\n❌ 不一致 {len(failures)} 处：")
        for item in failures[:12]:
            print(item)
        return 1
    print("\n✅ 配置路径与代码路径逐字节一致（含鼓型语义锚定）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
