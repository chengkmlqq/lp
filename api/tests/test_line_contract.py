from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "app" / "schemas" / "line.py"
SERVICE_FILE = ROOT / "app" / "services" / "line_service.py"
API_FILE = ROOT / "app" / "api" / "v1" / "lines.py"


def _load_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _class_field_names(module: ast.Module, class_name: str) -> set[str]:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.add(item.target.id)
            return names
    raise AssertionError(f"class {class_name} not found")


def _function_node(module: ast.Module, function_name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"function {function_name} not found")


class LineContractTest(unittest.TestCase):
    def test_line_schemas_do_not_expose_removed_fields(self) -> None:
        module = _load_module(SCHEMA_FILE)

        for class_name in ("LineSummary", "LineCreateRequest", "LineUpdateRequest"):
            fields = _class_field_names(module, class_name)
            self.assertNotIn("tower_shape", fields)
            self.assertNotIn("status", fields)

    def test_line_list_endpoint_no_longer_accepts_status_filter(self) -> None:
        module = _load_module(API_FILE)
        function = _function_node(module, "get_line_list")
        arg_names = [arg.arg for arg in function.args.args]

        self.assertNotIn("status_filter", arg_names)

        source = ast.unparse(function)
        # status 过滤已移除；bbox 为可选过滤参数（缺省向后兼容）。
        self.assertIn("list_lines(db,", source)
        self.assertIn("bbox=parsed_bbox", source)

    def test_line_service_drops_removed_fields_from_public_contract(self) -> None:
        module = _load_module(SERVICE_FILE)
        serialize_line = _function_node(module, "serialize_line")
        serialize_source = ast.unparse(serialize_line)

        self.assertNotIn("tower_shape=", serialize_source)
        self.assertNotIn("status=", serialize_source)

        export_source = SCHEMA_FILE.read_text(encoding="utf-8")
        self.assertNotIn("tower_shape:", export_source)
        self.assertNotIn("status:", export_source)

    def test_line_tower_csv_export_header_keeps_line_tower_tower_type(self) -> None:
        """线路杆塔 CSV 导出表头保留「塔形」（映射 tower.tower_type，杆塔级合法字段）。

        表头现由常量 LINE_TOWER_CSV_HEADERS_63 / LINE_TOWER_CSV_HEADERS_EN 提供
        （导出时按 lang 选择）；中文表头须含「塔形」，英文表头须含 "Tower type"，
        且英文表头与中文表头列数一致（65 列），保证 lang=en 导出再导入对称。
        """
        service_module = _load_module(SERVICE_FILE)
        i18n_module = _load_module(ROOT / "app" / "services" / "analysis_text_i18n.py")

        zh_header = _tuple_constant_values(service_module, "LINE_TOWER_CSV_HEADERS")
        self.assertIsNotNone(zh_header)
        self.assertIn("塔形", zh_header)
        self.assertIn("原因分析", zh_header)
        self.assertIn("措施推荐", zh_header)

        en_header = _tuple_constant_values(i18n_module, "LINE_TOWER_CSV_HEADERS_EN")
        self.assertIsNotNone(en_header)
        self.assertIn("Tower type", en_header)
        self.assertIn("Cause analysis", en_header)
        self.assertIn("Mitigation recommendation", en_header)
        self.assertEqual(len(en_header), len(zh_header))


def _tuple_constant_values(module: ast.Module, name: str) -> list[str] | None:
    """取模块顶层 `NAME: tuple[str, ...] = (...)` 的字面量字符串列表（支持 `*OTHER` 展开）；找不到返回 None。"""
    cache: dict[str, list[str] | None] = {}

    def _extract(value: ast.AST, stack: frozenset[str]) -> list[str] | None:
        if not isinstance(value, (ast.Tuple, ast.List)):
            return None
        out: list[str] | None = []
        for elt in value.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                out.append(elt.value)
            elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
                sub = _resolve(elt.value.id, stack)
                if sub is None:
                    return None
                out.extend(sub)
            else:
                return None
        return out

    def _resolve(target_name: str, stack: frozenset[str]) -> list[str] | None:
        if target_name in cache:
            return cache[target_name]
        if target_name in stack:
            return None
        for node in module.body:
            target: ast.AST | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and node.value is not None:
                target, value = None, node.value
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == target_name:
                        target = t
                        break
            elif isinstance(node, ast.AnnAssign) and node.value is not None and isinstance(node.target, ast.Name):
                target, value = node.target, node.value
            if target is not None and isinstance(target, ast.Name) and target.id == target_name and value is not None:
                values = _extract(value, stack | {target_name})
                cache[target_name] = values
                return values
        cache[target_name] = None
        return None

    return _resolve(name, frozenset())


if __name__ == "__main__":
    unittest.main()
