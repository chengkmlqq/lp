from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER_FILE = ROOT / "app" / "api" / "router.py"
SEED_FILE = ROOT / "app" / "services" / "seed_service.py"
AUTHZ_FILE = ROOT / "app" / "services" / "legacy_authz_service.py"


def _load_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class FaultRecurrenceContractTest(unittest.TestCase):
    def test_router_registers_fault_recurrence_api(self) -> None:
        source = ROUTER_FILE.read_text(encoding="utf-8")
        self.assertIn("from .v1.fault_recurrence import router as fault_recurrence_router", source)
        self.assertIn("v1_router.include_router(fault_recurrence_router)", source)

    def test_seed_defaults_include_fault_recurrence_menu(self) -> None:
        source = SEED_FILE.read_text(encoding="utf-8")
        self.assertIn('"code": "admin.fault_recurrence"', source)
        self.assertIn('"path": "/admin/fault-recurrence"', source)
        self.assertIn('"admin.fault_recurrence"', source)

    def test_legacy_authz_maps_fault_recurrence_permissions(self) -> None:
        source = AUTHZ_FILE.read_text(encoding="utf-8")
        self.assertIn('"admin.fault_recurrence"', source)
        self.assertIn('"/admin/fault-recurrence"', source)

    def test_upload_temp_endpoint_registered(self) -> None:
        source = (ROOT / "app" / "api" / "v1" / "fault_recurrence.py").read_text(encoding="utf-8")
        self.assertIn('"/upload-temp"', source)
        self.assertIn("save_temp_upload", source)
        self.assertIn("FaultRecurrenceTempUploadResponse", source)

    def test_analyze_supports_temp_file_id(self) -> None:
        source = (ROOT / "app" / "api" / "v1" / "fault_recurrence.py").read_text(encoding="utf-8")
        self.assertIn("temp_file_id: str | None = Form(default=None)", source)
        self.assertIn("resolve_temp_upload", source)


if __name__ == "__main__":
    unittest.main()
