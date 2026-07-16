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
        self.assertIn("return list_lines(db, keyword=keyword)", source)

    def test_line_service_drops_removed_fields_from_public_contract(self) -> None:
        module = _load_module(SERVICE_FILE)
        serialize_line = _function_node(module, "serialize_line")
        serialize_source = ast.unparse(serialize_line)

        self.assertNotIn("tower_shape=", serialize_source)
        self.assertNotIn("status=", serialize_source)

        export_source = SCHEMA_FILE.read_text(encoding="utf-8")
        self.assertNotIn("tower_shape:", export_source)
        self.assertNotIn("status:", export_source)

    def test_line_tower_csv_export_header_excludes_tower_shape(self) -> None:
        module = _load_module(SERVICE_FILE)
        function = _function_node(module, "export_line_towers_to_csv")
        header_values: list[str] | None = None

        for node in function.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "headers":
                        if isinstance(node.value, ast.List):
                            header_values = [
                                item.value
                                for item in node.value.elts
                                if isinstance(item, ast.Constant) and isinstance(item.value, str)
                            ]
                        break
            if header_values is not None:
                break

        self.assertIsNotNone(header_values)
        self.assertNotIn("塔形", header_values)


if __name__ == "__main__":
    unittest.main()
