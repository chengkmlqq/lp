"""ATP 参数注册表 · 计算脚本沙箱（受限 Python 子集求值）。

与 ``atp_param_dsl`` 同设计哲学（AST 白名单，防注入），但支持**多语句**：
- 语句：赋值 ``name = expr``、表达式语句（末行）、注释；
- 表达式：常量 / 变量 / 四则与幂 / 一元 / 比较 / 布尔 / 三元 / 白名单函数调用；
- **禁止**：import、属性访问、下标、循环、推导式、lambda、函数定义、任意调用。

安全边界：
- AST 白名单静态校验（``validate_script``，保存时即可拦截）；
- 语句数上限 + 脚本长度上限（防病态输入）；
- 无 IO / 无网络 / 无任意调用 —— 纯数学计算。

求值语义：
- 输入变量 = 注册表已解析的依赖参数值 + build_context 上下文（``variables``）；
- 未显式 ``result`` 变量时取最后一个表达式语句的值；
- None 感知：任一操作数为 None → 结果 None（与 DSL 一致）；
- 任一步骤抛错（除零等）→ 结果 None 并在 ``errors`` 中记录（供页面/接口显式报错）。

运行期说明：注册表 script 定义（11K0/14XXSS 基线）**执行仍走 atp_work_atp_slots.py**
（固定列写入路径），本模块服务于「页面试算 / 新增计算参数 / 注册表驱动解析」。
"""

from __future__ import annotations

import ast
import math
from typing import Any, Mapping

_MAX_STATEMENTS = 200
_MAX_SCRIPT_LEN = 8000


class ScriptError(ValueError):
    """脚本非法（语法/白名单/长度超限）。"""


_ALLOWED_CALLS: dict[str, Any] = {
    "abs": abs,
    "sqrt": math.sqrt,
    "min": min,
    "max": max,
    "round": round,
    "clamp": lambda value, low: low if value < low else value,
    "hypot": math.hypot,
    "log": math.log,
    "pow": math.pow,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "radians": math.radians,
    "degrees": math.degrees,
    "floor": math.floor,
    "ceil": math.ceil,
}

# 电压分档（与 atp_work_atp_slots._voltage_profile 一致）：(避雷线弧垂 m, 导线弧垂 m)
_VOLTAGE_SAG = {
    35: (1.1, 1.8),
    66: (1.1, 1.8),
    110: (2.8, 5.3),
    220: (7.0, 12.0),
}
_VOLTAGE_SAG_HIGH = (9.5, 12.0)


def _v_arc(voltage: Any) -> float | None:
    if voltage is None:
        return None
    try:
        v = int(float(voltage))
    except (TypeError, ValueError):
        return None
    return (_VOLTAGE_SAG.get(v) or _VOLTAGE_SAG_HIGH)[0]


def _v_darc(voltage: Any) -> float | None:
    if voltage is None:
        return None
    try:
        v = int(float(voltage))
    except (TypeError, ValueError):
        return None
    return (_VOLTAGE_SAG.get(v) or _VOLTAGE_SAG_HIGH)[1]


# 电压分档函数 v()（与 DSL 同语义：<=35/66/110/220/330/500/750/else）
def _v_band(voltage: Any, series: list[Any]) -> Any:
    if voltage is None or not series:
        return None
    try:
        v = float(voltage)
    except (TypeError, ValueError):
        return None
    if v <= 35:
        return series[0]
    if v <= 66:
        return series[1]
    if v <= 110:
        return series[2]
    if v <= 220:
        return series[3]
    if v <= 330:
        return series[4]
    if v <= 500:
        return series[5]
    if v <= 750:
        return series[6]
    return series[7]


_SCRIPT_CALLS: dict[str, Any] = {
    **_ALLOWED_CALLS,
    "v": _v_band,
    "v_arc": _v_arc,
    "v_darc": _v_darc,
}

_SAFE_NODE_TYPES = (
    ast.Expression,
    ast.Module,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Compare,
    ast.IfExp,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Store,
)


def validate_script(script: str) -> None:
    """静态校验：语法 + 白名单 + 语句数/长度上限。失败抛 ScriptError。"""
    if not isinstance(script, str) or not script.strip():
        raise ScriptError("脚本为空")
    if len(script) > _MAX_SCRIPT_LEN:
        raise ScriptError(f"脚本过长（>{_MAX_SCRIPT_LEN} 字符）")
    try:
        tree = ast.parse(script, mode="exec")
    except SyntaxError as exc:  # pragma: no cover - 透出原因
        raise ScriptError(f"语法错误：{exc.msg}") from exc
    stmt_count = sum(1 for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Expr)))
    if stmt_count > _MAX_STATEMENTS:
        raise ScriptError(f"语句过多（>{_MAX_STATEMENTS} 条）")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SCRIPT_CALLS:
                raise ScriptError(f"只允许调用白名单函数：{', '.join(sorted(_SCRIPT_CALLS))}")
            if node.keywords:
                raise ScriptError("函数不接受关键字参数")
        if not isinstance(node, _SAFE_NODE_TYPES):
            raise ScriptError(f"不允许的语法：{type(node).__name__}")


def collect_names(script: str) -> set[str]:
    """取出脚本引用的变量名（不含赋值目标，用于依赖校验）。"""
    tree = ast.parse(script, mode="exec")
    assigned: set[str] = set()
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name):
                    assigned.add(target.id)
        elif isinstance(node, ast.Name):
            if node.id not in _SCRIPT_CALLS:
                referenced.add(node.id)
    return referenced - assigned


def _truthy(value: Any) -> bool:
    return bool(value)


def _compare(op: ast.cmpop, left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    raise ScriptError(f"不支持的比较符：{type(op).__name__}")


def _call(name: str, args: list[Any], voltage: Any) -> Any:
    fn = _SCRIPT_CALLS.get(name)
    if fn is None:
        raise ScriptError(f"未实现的函数：{name}")
    if any(a is None for a in args):
        # None 感知：任一参数 None → None
        return None
    if name == "v":
        if len(args) != 8:
            raise ScriptError("v() 需要 8 个电压分档参数")
        return _v_band(voltage, args)
    if name == "clamp":
        if len(args) != 2:
            raise ScriptError("clamp(x, lo) 需要 2 个参数")
        value, low = args
        return low if value < low else value
    return fn(*args)


def _eval(node: ast.AST, variables: Mapping[str, Any], voltage: Any) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables, voltage)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ScriptError(f"未知变量：{node.id}")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, variables, voltage)
        if isinstance(node.op, ast.Not):
            return not _truthy(operand)
        if operand is None:
            return None
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, variables, voltage)
        right = _eval(node.right, variables, voltage)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ScriptError(f"不支持的运算符：{type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables, voltage)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, variables, voltage)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not _truthy(_eval(value, variables, voltage)):
                    return False
            return True
        for value in node.values:
            if _truthy(_eval(value, variables, voltage)):
                return True
        return False
    if isinstance(node, ast.IfExp):
        return (
            _eval(node.body, variables, voltage)
            if _truthy(_eval(node.test, variables, voltage))
            else _eval(node.orelse, variables, voltage)
        )
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ScriptError("非函数调用")
        args = [_eval(a, variables, voltage) for a in node.args]
        return _call(node.func.id, args, voltage)
    raise ScriptError(f"不支持的表达式节点：{type(node).__name__}")


def evaluate_script(
    script: str,
    variables: Mapping[str, Any],
    *,
    voltage_var: str = "voltage",
) -> tuple[Any, list[str]]:
    """沙箱求值脚本。返回 (结果, 错误列表)；结果 None 且 errors 非空 = 计算失败。"""
    errors: list[str] = []
    try:
        validate_script(script)
        tree = ast.parse(script, mode="exec")
    except ScriptError as exc:
        return None, [str(exc)]

    scope: dict[str, Any] = dict(variables)
    voltage = scope.get(voltage_var)
    last_value: Any = None
    try:
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = _eval(node.value, scope, voltage)
                for target in targets:
                    if isinstance(target, ast.Name):
                        scope[target.id] = value
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    scope[node.target.id] = _eval(node.value, scope, voltage) if node.value else None
            elif isinstance(node, ast.Expr):
                last_value = _eval(node.value, scope, voltage)
            # 其它语句类型已被 validate_script 拦截
    except ScriptError as exc:
        return None, [str(exc)]
    except (ArithmeticError, ValueError, TypeError) as exc:
        return None, [f"计算失败：{exc}"]

    if "result" in scope:
        return scope["result"], errors
    return last_value, errors


__all__ = [
    "ScriptError",
    "collect_names",
    "evaluate_script",
    "validate_script",
]
