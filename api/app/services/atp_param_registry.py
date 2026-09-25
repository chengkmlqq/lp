"""ATP 参数注册表：定义加载 + 按需求值（注册表驱动解析）。

来源三种（与 atp_param_definition 表 source_type 对应）：
- ``line_binding``：从线路导入的杆塔属性绑定
  · 种子镜像（binding_json.runtime_key）：直接取 ``build_context`` 对应键 —— **与现状逐字节一致**；
  · 用户新增（binding_json.source/path 点路径）：从 base_tower/profile/options 抽取
    （path 支持 ``a.b.c`` 嵌套；transform=mm_to_m 时按 >100 启发式转米）。
- ``script``：沙箱求值（atp_param_script.evaluate_script），入参 = 上下文 + 已解析依赖。
- ``constant``：字面量（binding_json.value）。

设计约束（精度优先 / 不回归）：
- 种子 = 现状镜像：runtime_key 命中时取 build_context 原值，杜绝二义；
- 求值失败（脚本抛错/依赖缺值）→ 显式抛 ``DefinitionError``，禁静默 fallback（用户铁律）；
- 槽位按需解析：只解析其显式引用的 code（+ 依赖闭包），不为未引用参数冒失败风险；
- ``runtime_baseline=true`` 的定义（11K0/14XXSS 运行期基线）执行仍走 atp_work_atp_slots.py，
  注册表侧只负责页面展示与按需试算 —— 显式引用其 code 时才在沙箱里求值。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.models.atp_param_definition import AtpParamDefinition
from app.services.atp_param_script import ScriptError, collect_names, evaluate_script, validate_script

# line_binding 允许的抽取域
_BINDING_SOURCES = ("base_tower", "profile", "options")

SOURCE_TYPES = ("line_binding", "script", "constant")


class DefinitionError(ValueError):
    """参数注册表定义非法 / 求值失败。"""


@dataclass
class Definition:
    """一条注册表定义（DB 行同构）。"""

    code: str
    name: str = ""
    unit: str | None = None
    data_type: str = "number"
    source_type: str = "line_binding"  # line_binding | script | constant
    binding_json: dict[str, Any] = field(default_factory=dict)
    script_code: str | None = None
    deps: list[str] = field(default_factory=list)
    enabled: bool = True
    sort_order: int = 0
    description: str | None = None

    @property
    def runtime_baseline(self) -> bool:
        return bool((self.binding_json or {}).get("runtime_baseline"))


def definition_from_row(row: Mapping[str, Any]) -> Definition:
    return Definition(
        code=str(row["code"]),
        name=str(row.get("name") or row["code"]),
        unit=row.get("unit"),
        data_type=str(row.get("data_type") or "number"),
        source_type=str(row.get("source_type") or "line_binding"),
        binding_json=dict(row.get("binding_json") or {}),
        script_code=row.get("script_code"),
        deps=list(row.get("deps_json") or []),
        enabled=bool(row.get("enabled", True)),
        sort_order=int(row.get("sort_order", 0)),
        description=row.get("description"),
    )


def load_definitions(db_session: Any) -> list[Definition]:
    """从 DB 加载启用中的定义（按 sort_order, code 排序）。"""
    from sqlalchemy import select  # noqa: PLC0415

    rows = (
        db_session.execute(
            select(AtpParamDefinition).where(AtpParamDefinition.enabled)
        )
        .scalars()
        .all()
    )
    definitions: list[Definition] = []
    for row in rows:
        definitions.append(
            definition_from_row(
                {
                    "code": row.code,
                    "name": row.name,
                    "unit": row.unit,
                    "data_type": row.data_type,
                    "source_type": row.source_type,
                    "binding_json": row.binding_json,
                    "script_code": row.script_code,
                    "deps_json": row.deps_json,
                    "enabled": row.enabled,
                    "description": row.description,
                }
            )
        )
    return sorted(definitions, key=lambda d: d.code)


def _dotted_get(data: Mapping[str, Any], path: str) -> Any:
    """按 ``a.b.c`` 取嵌套值；任一层缺失返回 None。"""
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _extract_binding(
    *,
    base_tower: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
    options: Mapping[str, Any] | None,
    binding: Mapping[str, Any],
) -> Any:
    """抽取 line_binding 值（用户新增定义；种子镜像走 runtime_key 提前短路）。"""
    source = str(binding.get("source") or "")
    path = str(binding.get("path") or "")
    if source not in _BINDING_SOURCES or not path:
        return None
    raw: Mapping[str, Any] = {
        "base_tower": base_tower or {},
        "profile": profile or {},
        "options": options or {},
    }[source]
    value = _dotted_get(raw, path)
    if str(binding.get("transform") or "") == "mm_to_m":
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return value
        value = numeric / 1000.0 if numeric and numeric > 100 else numeric
    return value


def resolve_definitions(
    *,
    definitions: Iterable[Definition],
    base_tower: Mapping[str, Any] | None = None,
    profile: Mapping[str, Any] | None = None,
    execution_options: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    requested: Iterable[str] | None = None,
) -> dict[str, Any]:
    """按需求值注册表定义，返回 {code: value}。

    ``requested``：槽位显式引用的 code 集合；不传则求值全部「非运行期基线」定义。
    任何被求值定义失败 → DefinitionError（显式报错，禁静默）。
    """
    definitions = list(definitions)
    by_code = {d.code: d for d in definitions}
    ctx = dict(context or {})

    if requested is None:
        wanted = {d.code for d in definitions if not d.runtime_baseline}
    else:
        wanted = set(requested)
        # 依赖闭包扩展
        queue = list(wanted)
        while queue:
            code = queue.pop()
            definition = by_code.get(code)
            if definition is None:
                continue
            for dep in definition.deps:
                if dep in by_code and dep not in wanted:
                    wanted.add(dep)
                    queue.append(dep)

    resolved: dict[str, Any] = {}

    def resolve_one(definition: Definition, stack: tuple[str, ...] = ()) -> Any:
        code = definition.code
        if code in resolved:
            return resolved[code]
        if code in stack:
            raise DefinitionError(f"参数依赖成环：{' → '.join(stack + (code,))}")
        next_stack = stack + (code,)

        if definition.source_type == "constant":
            value = (definition.binding_json or {}).get("value")

        elif definition.source_type == "line_binding":
            binding = definition.binding_json or {}
            runtime_key = binding.get("runtime_key")
            if runtime_key:
                # 种子镜像：build_context 原值（与现状逐字节一致）
                value = ctx.get(str(runtime_key))
            else:
                value = _extract_binding(
                    base_tower=base_tower, profile=profile, options=execution_options, binding=binding
                )

        elif definition.source_type == "script":
            script = (definition.script_code or "").strip()
            if not script:
                raise DefinitionError(f"{code}: 脚本为空")
            # 依赖先求值（deps 可以是其它注册表参数，也可以是上下文键）
            for dep in definition.deps:
                if dep in by_code and dep not in resolved:
                    resolve_one(by_code[dep], next_stack)
            missing = [dep for dep in definition.deps if (resolved.get(dep, ctx.get(dep)) is None)]
            if missing:
                raise DefinitionError(f"{code}: 依赖参数缺失：{', '.join(missing)}")
            deps = {dep: resolved.get(dep, ctx.get(dep)) for dep in definition.deps}
            value, errors = evaluate_script(script, {**ctx, **deps})
            if errors:
                raise DefinitionError(f"{code}: 脚本求值失败：{'；'.join(errors)}")

        else:
            raise DefinitionError(f"{code}: 未知 source_type={definition.source_type}")

        resolved[code] = value
        return value

    # 确定性求值顺序（按 code 排序，避免定义顺序影响错误信息）
    for code in sorted(wanted):
        definition = by_code.get(code)
        if definition is None:
            continue
        resolve_one(definition)

    return dict(resolved)


def validate_definition(definition: Definition, allowed_var_names: set[str] | None = None) -> None:
    """保存前校验定义（code 命名字法 / 来源合法性 / 脚本合法 / 依赖声明）。"""
    code = definition.code
    if not code or not code.replace("_", "").isalnum():
        raise DefinitionError("code 只能包含字母/数字/下划线")
    if definition.source_type not in SOURCE_TYPES:
        raise DefinitionError(f"{code}: 未知 source_type={definition.source_type}")
    if definition.source_type == "script":
        try:
            validate_script(definition.script_code or "")
        except ScriptError as exc:
            raise DefinitionError(f"{code}: {exc}") from exc
        if allowed_var_names is not None:
            referenced = collect_names(definition.script_code or "")
            unknown = sorted(
                name for name in referenced if name not in set(definition.deps) and name not in allowed_var_names
            )
            if unknown:
                raise DefinitionError(f"{code}: 脚本引用了未声明依赖的变量：{', '.join(unknown)}")
    elif definition.source_type == "line_binding":
        binding = definition.binding_json or {}
        if not binding.get("runtime_key") and (
            binding.get("source") not in _BINDING_SOURCES or not binding.get("path")
        ):
            raise DefinitionError(f"{code}: line_binding 需要 source+path（或 runtime_key）")


__all__ = [
    "Definition",
    "DefinitionError",
    "SOURCE_TYPES",
    "definition_from_row",
    "load_definitions",
    "resolve_definitions",
    "validate_definition",
]
