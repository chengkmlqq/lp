"""LP-206: Verify TASK_NAME_LABELS stays in sync with actual Celery task registrations.

Reads the TS mapping from ``web/src/lib/celery-task-display.ts`` and asserts:

* every key in the mapping corresponds to a real registered Celery task
  (no dead/legacy mappings left behind)
* every registered task (from ``celery_app.conf.include``) has a mapping
  (no future tasks added without a label)
"""

from __future__ import annotations

import importlib
import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

# Ensure api package is importable from the repo root
import sys
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from api.app.core.celery_app import celery_app  # noqa: F401,E402

# ---------------------------------------------------------------------------
# Load all include modules so every @celery_app.task is registered.
# ---------------------------------------------------------------------------
for _mod in celery_app.conf.include:
    importlib.import_module("api." + _mod)

REGISTERED_TASKS: set[str] = {
    n for n in celery_app.tasks.keys() if n.startswith("app.tasks.")
}

# ---------------------------------------------------------------------------
# Parse TASK_NAME_LABELS keys from the TypeScript source.
# ---------------------------------------------------------------------------
_TS_PATH = Path(__file__).resolve().parent.parent.parent / "web" / "src" / "lib" / "celery-task-display.ts"
_TS_SOURCE = _TS_PATH.read_text(encoding="utf-8")
MAPPING_KEYS: set[str] = set(
    re.findall(r'"((?:app\.tasks\.)[^"]+)"\s*:', _TS_SOURCE)
)


class TaskNameRegistryConsistencyTest(unittest.TestCase):
    """Ensure TASK_NAME_LABELS ↔ celery task registry stay in sync."""

    def test_mapping_ts_file_exists(self) -> None:
        """Sanity-check that we actually found the TS source file."""
        self.assertTrue(_TS_PATH.exists(), f"TS file not found: {_TS_PATH}")

    def test_mapping_keys_non_empty(self) -> None:
        """Ensure regex actually extracted keys from the TS file."""
        self.assertGreater(len(MAPPING_KEYS), 0, "No TASK_NAME_LABELS keys extracted")

    def test_no_dead_mapping_keys(self) -> None:
        """Every key in TASK_NAME_LABELS must correspond to a registered task."""
        dead = MAPPING_KEYS - REGISTERED_TASKS
        self.assertEqual(
            dead,
            set(),
            f"Dead mapping keys (in TS but not in Celery registry): {sorted(dead)}",
        )

    def test_no_missing_mapping_keys(self) -> None:
        """Every registered Celery task must have a TASK_NAME_LABELS entry."""
        missing = REGISTERED_TASKS - MAPPING_KEYS
        self.assertEqual(
            missing,
            set(),
            f"Registered tasks missing from TASK_NAME_LABELS: {sorted(missing)}",
        )


if __name__ == "__main__":
    unittest.main()
