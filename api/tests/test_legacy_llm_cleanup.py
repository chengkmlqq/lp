from __future__ import annotations

import importlib.util
import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from api.app import models  # noqa: F401
from api.app.core.config import Settings
from api.app.core.database import Base
from api.app.services import admin_service, legacy_admin_rbac_service, legacy_authz_service


class LegacyLlmCleanupTest(unittest.TestCase):
    def test_llm_registry_tables_removed_from_metadata(self) -> None:
        removed_tables = {
            "llm_models",
            "model_route_rules",
            "model_api_keys",
            "model_health_checks",
            "model_test_runs",
            "model_usage_logs",
        }

        self.assertNotIn("model_registry", models.__all__)
        self.assertTrue(removed_tables.isdisjoint(Base.metadata.tables))

    def test_llm_config_fields_removed(self) -> None:
        removed_fields = {
            "llm_provider_api_keys",
            "llm_request_timeout_seconds",
            "chat_context_message_limit",
            "chat_default_system_prompt",
        }

        self.assertTrue(removed_fields.isdisjoint(Settings.model_fields))

    def test_legacy_menu_filters_no_longer_reference_chat_and_models(self) -> None:
        for codes in (
            admin_service.REMOVED_MENU_CODES,
            legacy_admin_rbac_service.REMOVED_MENU_CODES,
            legacy_authz_service.DISABLED_MENU_CODES,
        ):
            self.assertNotIn("admin.chat", codes)
            self.assertNotIn("admin.models", codes)

    def test_calendar_service_module_removed(self) -> None:
        self.assertIsNone(importlib.util.find_spec("api.app.services.calendar_event_service"))


if __name__ == "__main__":
    unittest.main()
