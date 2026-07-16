from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ElevationFileRecordServiceImportTests(unittest.TestCase):
    def test_elevation_service_imports_reference_defined_symbols(self) -> None:
        service_path = Path("api/app/services/elevation_file_record_service.py")
        elevation_service_path = Path("api/app/services/elevation_service.py")

        service_tree = ast.parse(service_path.read_text(encoding="utf-8"))
        elevation_service_tree = ast.parse(elevation_service_path.read_text(encoding="utf-8"))

        imported_names = {
            alias.name
            for node in service_tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "elevation_service"
            for alias in node.names
        }
        defined_names = {
            node.name
            for node in elevation_service_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        defined_names.update(
            target.id
            for node in elevation_service_tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        )
        defined_names.update(
            node.target.id
            for node in elevation_service_tree.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        )
        defined_names.update(
            alias.asname or alias.name.split(".")[0]
            for node in elevation_service_tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        defined_names.update(
            alias.asname or alias.name
            for node in elevation_service_tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        )

        self.assertLessEqual(imported_names, defined_names)


if __name__ == "__main__":
    unittest.main()
