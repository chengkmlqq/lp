from __future__ import annotations

import ast
import unittest
from pathlib import Path


class ElevationFileRecordServiceImportTests(unittest.TestCase):
    def test_elevation_service_imports_reference_defined_symbols(self) -> None:
        # 用「文件自身位置」推导服务目录，避免依赖 pytest 的启动目录
        # （历史上该测试写死仓库根相对路径 "api/app/..."，从 api/ 目录运行时必失败）。
        service_dir = Path(__file__).resolve().parent.parent / "app" / "services"
        service_path = service_dir / "elevation_file_record_service.py"
        elevation_service_path = service_dir / "elevation_service.py"

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
