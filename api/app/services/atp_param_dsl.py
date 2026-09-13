"""ATP 参数模板表达式 DSL（安全求值 + 静态校验）。

设计约束（与现有 compute_csharp_atp_params 逐字节等价，见 scripts/atp_param_golden_test.py）：
- **AST 白名单**：只允许 常量 / 变量名 / 白名单函数 / 四则与幂运算 / 比较 / 布尔 / 条件表达式；
  禁止属性访问、下标、lambda、推导式、任意调用（防注入）。
- **None 感知**：任一操作数为 None → 结果为 None（等价现有 `x if x is not None else None`），
  最终格式化为 "1."（等价现有 fmt(None)）。
- **电压分档函数 v(a35,a66,a110,a220,a330,a500,a750,a1000)**：按 voltage 取档，
  语义与现有 vadj(series) 的 `voltage <= 档位` 完全一致。
- **槽位引用**：表达式中可直接引用已计算槽位名（如 RELE04），取的是**未格式化的原始值**
  （与现有代码用 rel01/h4 等中间变量再运算一致，避免舍入后再运算导致差异）。
"""

from __future__ import annotations

import ast
import math
from typing import Any, Mapping


class DslError(ValueError):
    """表达式非法（语法/白名单/变量未知）。"""


_ALLOWED_CALLS = {"abs", "sqrt", "min", "max", "round", "clamp", "v"}

_SAFE_NODE_TYPES = (
    ast.Expression,
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
)


def parse_expression(expr: str) -> ast.Expression:
    """解析表达式并做白名单校验；失败抛 DslError。"""
    if not isinstance(expr, str) or not expr.strip():
        raise DslError("表达式为空")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:  # pragma: no cover - 直接透出原因
        raise DslError(f"语法错误：{exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODE_TYPES):
            raise DslError(f"不允许的语法：{type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_CALLS:
                raise DslError("只允许调用白名单函数：" + "/".join(sorted(_ALLOWED_CALLS)))
            if node.keywords:
                raise DslError("函数不接受关键字参数")
    return tree


def collect_names(expr: str) -> set[str]:
    """取出表达式里引用的变量名（用于校验未知变量）。"""
    tree = parse_expression(expr)
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id not in _ALLOWED_CALLS}


def validate_expression(expr: str, allowed_vars: set[str] | None = None) -> None:
    """静态校验：语法 + 白名单 + （可选）变量名已知。"""
    names = collect_names(expr)
    if allowed_vars is not None:
        unknown = sorted(n for n in names if n not in allowed_vars)
        if unknown:
            raise DslError("未知变量：" + ", ".join(unknown))


# --------------------------------------------------------------------------------------
# 求值
# --------------------------------------------------------------------------------------

def _band(voltage: Any, series: list[Any]) -> Any:
    """电压分档（语义同现有 vadj）：<=35 / <=66 / <=110 / <=220 / <=330 / <=500 / <=750 / else。"""
    if voltage is None:
        return None
    v = float(voltage)
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


def _call(name: str, args: list[Any], voltage: Any) -> Any:
    if name == "v":
        if len(args) != 8:
            raise DslError("v() 需要 8 个电压分档参数")
        return _band(voltage, args)
    if name == "clamp":
        if len(args) != 2:
            raise DslError("clamp(x, lo) 需要 2 个参数")
        value, low = args
        if value is None or low is None:
            return None
        return low if value < low else value
    if any(a is None for a in args):
        # None 感知：任一参数 None → None（与现有代码的显式判空等价）
        return None
    if name == "abs":
        return abs(args[0])
    if name == "sqrt":
        return math.sqrt(args[0])
    if name == "min":
        return min(args)
    if name == "max":
        return max(args)
    if name == "round":
        return round(args[0], int(args[1])) if len(args) > 1 else round(args[0])
    raise DslError(f"未实现的函数：{name}")


def _eval(node: ast.AST, variables: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise DslError(f"未知变量：{node.id}")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, variables)
        if isinstance(node.op, ast.Not):
            return not _truthy(operand)
        if operand is None:
            return None
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.BinOp):
        left = _eval(node.left, variables)
        right = _eval(node.right, variables)
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
        raise DslError(f"不支持的运算符：{type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, variables)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for value in node.values:
                if not _truthy(_eval(value, variables)):
                    return False
            return True
        for value in node.values:
            if _truthy(_eval(value, variables)):
                return True
        return False
    if isinstance(node, ast.IfExp):
        return _eval(node.body, variables) if _truthy(_eval(node.test, variables)) else _eval(node.orelse, variables)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise DslError("非函数调用")
        args = [_eval(a, variables) for a in node.args]
        return _call(node.func.id, args, variables.get("voltage"))
    raise DslError(f"不支持的表达式节点：{type(node).__name__}")


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
    raise DslError(f"不支持的比较符：{type(op).__name__}")


def evaluate(expr: str, variables: Mapping[str, Any], *, tree: ast.Expression | None = None) -> Any:
    """求值表达式（None 感知）。variables 含源变量与已算槽位原始值。"""
    parsed = tree if tree is not None else parse_expression(expr)
    return _eval(parsed, variables)


# --------------------------------------------------------------------------------------
# 格式化（与现有 fmt 逐字节等价）
# --------------------------------------------------------------------------------------

def format_value(value: Any, digits: int = 2) -> str:
    """对齐 C# FeatureSetOfATP.SetFeatureValue（MyConst.cs:455-505）：

    ① `_value.ToString("F" + 精度)`；
    ② 去掉尾随的 '0'（但保留小数点，如 30.00 → "30."、34.10 → "34.1"）；
    ③ 精度为 0 时补 "."（F0 → "30."）；
    ④ None → "1."（原行为，保证 ATP 数值必带小数点）。

    ⚠️ 舍入必须用「四舍五入（half-away-from-zero）」：C# 的 `ToString("F2")` 是四舍五入，
    而 Python 的 f-string 格式化按 IEEE 二进制真值截断（51.555 的 double 实为 51.5549999…
    → 得 51.55）。实测差异：REHC 51.56(C#) vs 51.55(旧实现)。改用 Decimal(repr) + ROUND_HALF_UP。
    """
    if value is None:
        return "1."
    try:
        digits = max(0, int(digits))
    except (TypeError, ValueError):
        digits = 2
    try:
        from decimal import ROUND_HALF_UP, Decimal  # noqa: PLC0415

        # repr → 最短往返字符串，避免把二进制噪声带进舍入；quantize 后按 C# 的 F2 语义输出
        dec = Decimal(repr(float(value))).quantize(
            Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP
        )
        text = f"{dec:.{digits}f}"
    except (TypeError, ValueError, ArithmeticError):
        return "1."
    # ② 去尾随零：只删小数点后的零，且至少保留小数点本身
    if "." in text:
        text = text.rstrip("0")
        if text.endswith("."):
            return text
        return text
    # ③ 无小数点（digits=0 或 .rstrip 无零可删）→ 补 "."
    return text + "."
