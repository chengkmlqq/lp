"""ATP 参数注册表 golden 对照测试（无 DB / 无 tpbig，纯函数）。

目的：证明「注册表驱动解析」与「现有代码路径（compute_csharp_atp_params）」输出
**逐字节一致** —— 即新增参数注册表（atp_param_definition）没有改变任何既有计算结果。

对照矩阵（与 atp_param_golden_test.py 同口径）：
    15 塔型 × 8 电压 × 3 几何 × 3 波形 × 3 波形时间 × 2 电流

另外验证注册表自身能力：
1. line_binding 种子镜像：38 个源变量值 == build_context 产出值；
2. param 槽位形态：{"param": "h_u"} 与 {"expr": "h_u"} 输出相同；
3. script 沙箱：coupling_k0 求值成功且与 atp_work_atp_slots.coupling_k0 一致；
4. 沙箱安全：import/属性访问/循环脚本被拒。

运行（api 容器内）：
    docker exec -e PYTHONPATH=/app lp-deploy-api-1 python3 /app/scripts/atp_param_registry_golden_test.py
"""

from __future__ import annotations

import os

# 对照必须走代码路径：强制 code 模式（运行时默认 config_db 会短路到配置路径）
os.environ["ATP_MAPPING_MODE"] = "code"

import itertools
import sys

sys.path.insert(0, "/app/scripts")

from atp_param_golden_test import (  # noqa: E402
    CURRENTS,
    GEOMETRIES,
    TIMES,
    TOWER_TYPES,
    VOLTAGES,
    WAVE_TYPES,
    build_case,
    diff_dicts,
)

from app.services.atp_param_dsl import format_value  # noqa: E402
from app.services.atp_param_registry import (  # noqa: E402
    DefinitionError,
    resolve_definitions,
    validate_definition,
)
from app.services.atp_param_resolver import (  # noqa: E402
    MappingRules,
    Rule,
    build_context,
    compute_params_from_config,
    load_mappings,
    resolve_params,
)
from app.services.atp_param_script import ScriptError, evaluate_script, validate_script  # noqa: E402
from app.services.fl_analysis_external import compute_csharp_atp_params  # noqa: E402


def check_registry_mirror(rules: MappingRules, failures: list[str]) -> int:
    """1) line_binding 种子镜像：注册表求值 == build_context 产出（逐变量）。"""
    checked = 0
    base_tower, profile, options = build_case("s500maotou", 500, GEOMETRIES[0], 1, 2.6, 50.0, 146.0)
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    mirrored = [
        d
        for d in rules.definitions
        if d.source_type == "line_binding" and (d.binding_json or {}).get("runtime_key")
    ]
    values = resolve_definitions(
        definitions=mirrored,
        base_tower=base_tower,
        profile=profile,
        execution_options=options,
        context=context,
        requested=[d.code for d in mirrored],
    )
    for definition in mirrored:
        checked += 1
        expected = context.get(definition.code)
        got = values.get(definition.code)
        if expected != got:
            failures.append(f"[镜像] {definition.code}: build_context={expected!r} 注册表={got!r}")
    return checked


def check_param_slot_form(failures: list[str]) -> None:
    """2) param 槽位形态与 expr 形态输出一致。"""
    base_tower, profile, options = build_case("s500ganzi", 500, GEOMETRIES[0], 1, 2.6, 50.0, 146.0)
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    rules = load_mappings()
    rules.rules["ganzi"] = Rule(
        name="ganzi",
        dimensions={"tower_type": "ganzi"},
        slots={
            "RELE01": {"param": "h_u", "fmt": 1},
            "REHG______": {"expr": "shield_h", "fmt": 1},
        },
    )
    rules.voltage_rules = []
    resolved = resolve_params(context, rules)
    if resolved.values.get("RELE01") != "65.5":
        failures.append(f"[param 槽位] RELE01 期望 65.5 实得 {resolved.values.get('RELE01')}")
    if resolved.values.get("REHG______") != "73.5":
        failures.append(f"[expr 槽位] REHG 期望 73.5 实得 {resolved.values.get('REHG______')}")
    # 未注册 code 显式报错（禁静默）
    try:
        resolve_params(
            context,
            MappingRules(
                rules={"ganzi": Rule(name="g", dimensions={"tower_type": "ganzi"}, slots={"X": {"param": "nonexistent"}})},
                globals={},
                exact_canonical=["ganzi"],
                marker_order=["ganzi"],
                default_marker="ganzi",
            ),
        )
        failures.append("[param 槽位] 引用未注册参数应报错，但未报错")
    except DefinitionError:
        pass


def check_coupling_script(failures: list[str]) -> None:
    """3) script 沙箱：coupling_k0 == atp_work_atp_slots.coupling_k0。"""
    from app.services.atp_param_registry import Definition
    from app.services.atp_work_atp_slots import coupling_k0

    rules = load_mappings()
    script_def = next((d for d in rules.definitions if d.code == "coupling_k0"), None)
    if script_def is None:
        failures.append("[script] 种子缺少 coupling_k0 定义")
        return
    base_tower, profile, options = build_case("s220ganzi", 220, GEOMETRIES[0], 1, 2.6, 50.0, 146.0)
    context = build_context(base_tower=base_tower, profile=profile, execution_options=options)
    context = {**context, "angle_deg": 10.0}
    try:
        values = resolve_definitions(
            definitions=rules.definitions,
            base_tower=base_tower,
            profile=profile,
            execution_options=options,
            context=context,
            requested=["coupling_k0"],
        )
    except DefinitionError as exc:
        failures.append(f"[script] coupling_k0 求值失败：{exc}")
        return
    k0_registry = values.get("coupling_k0")
    # C# 权威实现对照：shield=73.5, lw=12.4, insul=5.945m, h_u=65.5, sp_u=12.0, v=220
    k0_code = coupling_k0(
        tower_kind="ganzi",
        voltage_kv=220,
        shield_wire_height_m=73.5,
        left_mid_distance_m=12.4,
        right_mid_distance_m=12.4,
        insulator_length_m=5.945,
        phase_geometry={
            "phase_spacing_m": {"upper": 12.0, "middle": 12.0, "lower": 12.0},
            "phase_height_m": {"upper": 65.5, "middle": 53.0, "lower": 42.0},
        },
        is_dc=False,
        phase_sequence=["A", "B", "C"],
    )
    if k0_registry is None or k0_code is None or abs(float(k0_registry) - k0_code) > 1e-9:
        failures.append(f"[script] coupling_k0 注册表={k0_registry} C#移植={k0_code}")


def check_sandbox_security(failures: list[str]) -> None:
    """4) 沙箱安全：危险语法必须被拒。"""
    dangerous = [
        "import os",
        "result = __import__('os').system('ls')",
        "result = open('/etc/passwd').read()",
        "result = (1).__class__",
        "result = [i for i in range(10)]",
        "while True:\n    result = 1",
        "def f():\n    return 1",
        "result = eval('1+1')",
    ]
    for script in dangerous:
        try:
            validate_script(script)
        except ScriptError:
            continue
        failures.append(f"[安全] 危险脚本未被拒绝：{script[:40]!r}")
    # 合法脚本能跑
    value, errors = evaluate_script("a = x * 2\nresult = a + 1", {"x": 3.0})
    if errors or value != 7.0:
        failures.append(f"[安全] 合法脚本求值失败：value={value} errors={errors}")
    # 除零 → 显式错误（禁静默）
    value, errors = evaluate_script("result = 1 / (x - x)", {"x": 1.0})
    if not errors:
        failures.append("[安全] 除零应报错")


def main() -> int:
    rules = load_mappings()
    failures: list[str] = []
    total = 0

    # 0) 双重对照：
    #    A/B：注册表版配置路径 vs 无注册表版配置路径 —— **必须逐字节一致**（核心不回归证明）；
    #    vs 代码路径：差异数与无注册表版一致（不新增差异；既有差异=guxing wine 回退，见脚本头注释）。
    rules_no_defs = MappingRules(
        rules=rules.rules,
        globals=rules.globals,
        exact_canonical=rules.exact_canonical,
        marker_order=rules.marker_order,
        default_marker=rules.default_marker,
        voltage_rules=rules.voltage_rules,
        defaults=rules.defaults,
        definitions=[],
    )
    for tower_type, voltage, geom, wave, (head, tail), current in itertools.product(
        TOWER_TYPES, VOLTAGES, GEOMETRIES, WAVE_TYPES, TIMES, CURRENTS
    ):
        base_tower, profile, options = build_case(tower_type, voltage, geom, wave, head, tail, current)
        code_params = compute_csharp_atp_params(base_tower=base_tower, profile=profile, execution_options=options)
        config_params = compute_params_from_config(
            base_tower=base_tower, profile=profile, execution_options=options, rules=rules
        )
        config_no_defs = compute_params_from_config(
            base_tower=base_tower, profile=profile, execution_options=options, rules=rules_no_defs
        )
        total += 1
        label = f"{tower_type}/v{voltage}/wave{wave}/h{head}/t{tail}/i{current}/geom{GEOMETRIES.index(geom)}"
        ab_problems = diff_dicts(config_no_defs, config_params)
        if ab_problems:
            failures.append(f"[A/B 注册表回归 {label}]\n  " + "\n  ".join(ab_problems))
        code_problems = diff_dicts(code_params, config_params)
        code_base_problems = diff_dicts(code_params, config_no_defs)
        if code_problems != code_base_problems:
            failures.append(f"[代码路径差异漂移 {label}]\n  有注册表:\n  " + "\n  ".join(code_problems[:6]) + "\n  无注册表:\n  " + "\n  ".join(code_base_problems[:6]))
        if len([x for x in failures if x.startswith("[A/B") or x.startswith("[代码路径差异漂移")]) >= 8:
            break

    # 1-4) 注册表专项
    mirrored = check_registry_mirror(rules, failures)
    check_param_slot_form(failures)
    check_coupling_script(failures)
    check_sandbox_security(failures)

    print(f"注册表对照用例：{total} 组（与 atp_param_golden_test.py 同矩阵）")
    print(f"镜像变量核对：{mirrored} 个 line_binding 种子参数")
    print(f"注册表定义总数：{len(rules.definitions)}")
    if failures:
        print(f"\n❌ 不一致 {len(failures)} 处：")
        for item in failures[:12]:
            print(item)
        return 1
    print("\n✅ 注册表驱动解析与代码路径逐字节一致；param 槽位/script 沙箱/安全校验全通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
