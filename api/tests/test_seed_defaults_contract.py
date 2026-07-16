from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.api.router import v1_router
from api.app.api.v1.admin import router as admin_router
from api.app.core.database import Base, get_db, init_db
from api.app.core.dependencies import CurrentUser, get_current_user
from api.app.models.menu import Menu
from api.app.models.scheduled_task import ScheduledTask
from api.app.models.user import User
from api.app.services.legacy_authz_service import DEFAULT_ADMIN_PERMISSION_CODES, SYNTHETIC_LEGACY_MENU_ROWS
from api.app.services.seed_service import DEFAULT_MENUS, DEFAULT_PERMISSIONS, DEFAULT_ROLES, SeedDefaultsResult, seed_defaults
from api.app.services.topic_registry import TOPIC_RULES


DEFAULT_MENU_BY_CODE = {
    str(menu["code"]): menu
    for menu in DEFAULT_MENUS
}


class DatabaseFixtureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
        Base.metadata.create_all(bind=self.engine)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()


class InitDbContractTest(unittest.TestCase):
    def test_init_db_does_not_open_a_seed_session(self) -> None:
        with patch("api.app.core.database._ensure_user_pk_column_compatibility"), patch(
            "api.app.core.database._ensure_user_timestamp_column_compatibility"
        ), patch("api.app.core.database._ensure_user_audit_column_compatibility"), patch(
            "api.app.core.database._ensure_elevation_dataset_column_compatibility"
        ), patch("api.app.core.database._ensure_tower_model_column_compatibility"), patch(
            "api.app.core.database._ensure_tower_profile_column_compatibility"
        ), patch("api.app.core.database.Base.metadata.create_all") as create_all, patch(
            "api.app.core.database.SessionLocal"
        ) as session_local:
            init_db()

        create_all.assert_called_once()
        session_local.assert_not_called()

    def test_quiz_legacy_tables_are_not_registered(self) -> None:
        self.assertNotIn("question_bank", Base.metadata.tables)
        self.assertNotIn("hot_search_records", Base.metadata.tables)
        self.assertNotIn("hot_search_follow_topics", Base.metadata.tables)


class LegacyQuizCleanupContractTest(unittest.TestCase):
    def test_quiz_legacy_routes_and_topics_are_removed(self) -> None:
        paths = {
            getattr(route, "path", "")
            for route in v1_router.routes
        }

        self.assertFalse(any("question-bank" in path for path in paths))
        self.assertFalse(any("mdresolve" in path for path in paths))
        self.assertFalse(any("hot-search" in path for path in paths))
        self.assertNotIn("admin.question_bank", TOPIC_RULES)

    def test_quiz_legacy_permissions_are_not_seeded(self) -> None:
        self.assertNotIn("question_bank.read", DEFAULT_ADMIN_PERMISSION_CODES)
        self.assertNotIn("question_bank.manage", DEFAULT_ADMIN_PERMISSION_CODES)
        self.assertNotIn("question_bank.read", DEFAULT_PERMISSIONS)
        self.assertNotIn("question_bank.manage", DEFAULT_PERMISSIONS)
        self.assertNotIn("question_bank.read", DEFAULT_ROLES["admin"]["permissions"])
        self.assertNotIn("question_bank.manage", DEFAULT_ROLES["admin"]["permissions"])

    def test_legacy_authz_uses_standalone_atp_models_menu_url(self) -> None:
        atp_menu = next(row for row in SYNTHETIC_LEGACY_MENU_ROWS if row["menu_id"] == "admin.atp_models")

        self.assertEqual(atp_menu["url"], "/admin/atp-models")


class SeedDefaultsServiceTest(DatabaseFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session = self.SessionLocal()

    def tearDown(self) -> None:
        self.session.close()
        super().tearDown()

    def _run_seed(self, *, force: bool = False) -> SeedDefaultsResult:
        with patch(
            "api.app.services.seed_service._seed_legacy_tower_models_if_empty",
            return_value=None,
        ):
            return seed_defaults(self.session, force=force)

    def _load_menu(self, code: str) -> Menu:
        menu = self.session.scalar(select(Menu).where(Menu.code == code))
        self.assertIsNotNone(menu)
        return menu

    def test_seed_defaults_preserves_existing_menu_changes_by_default(self) -> None:
        self._run_seed()

        menu = self._load_menu("admin.menus")
        menu.name = "自定义菜单"
        menu.sort_order = 999
        self.session.commit()

        result = self._run_seed()
        self.session.expire_all()

        refreshed = self._load_menu("admin.menus")
        self.assertEqual(refreshed.name, "自定义菜单")
        self.assertEqual(refreshed.sort_order, 999)
        self.assertEqual(result.mode, "missing_only")
        self.assertFalse(result.overwrote_existing)

    def test_seed_defaults_force_restores_default_menu_fields(self) -> None:
        self._run_seed()

        menu = self._load_menu("admin.menus")
        menu.name = "自定义菜单"
        menu.sort_order = 999
        self.session.commit()

        result = self._run_seed(force=True)
        self.session.expire_all()

        refreshed = self._load_menu("admin.menus")
        default_menu = DEFAULT_MENU_BY_CODE["admin.menus"]
        self.assertEqual(refreshed.name, str(default_menu["name"]))
        self.assertEqual(refreshed.sort_order, int(default_menu["sort_order"]))
        self.assertEqual(result.mode, "force_overwrite")
        self.assertTrue(result.overwrote_existing)
        self.assertGreater(result.summary["menus"].overwritten, 0)

    def test_seed_defaults_use_standalone_atp_models_path(self) -> None:
        self._run_seed()

        menu = self._load_menu("admin.atp_models")
        default_menu = DEFAULT_MENU_BY_CODE["admin.atp_models"]

        self.assertEqual(str(default_menu["path"]), "/admin/atp-models")
        self.assertEqual(menu.path, "/admin/atp-models")

    def test_seed_defaults_include_scheduled_tasks_menu_and_default_task(self) -> None:
        self._run_seed()

        menu = self._load_menu("admin.scheduled_tasks")
        default_menu = DEFAULT_MENU_BY_CODE["admin.scheduled_tasks"]
        scheduled_task = self.session.scalar(
            select(ScheduledTask).where(ScheduledTask.task_key == "syslog.cleanup.default")
        )

        self.assertEqual(str(default_menu["path"]), "/admin/scheduled-tasks")
        self.assertEqual(menu.path, "/admin/scheduled-tasks")
        self.assertIsNotNone(scheduled_task)
        self.assertTrue(scheduled_task.enabled if scheduled_task else False)


class SeedDefaultsEndpointTest(DatabaseFixtureTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        current_user = CurrentUser(
            user=User(
                id="admin",
                email="admin@example.com",
                username="admin",
                password_hash="secret",
                status="ENABLED",
            ),
            role_codes={"admin"},
            permission_codes={"menu.manage"},
        )
        self.app.dependency_overrides[get_db] = override_get_db
        self.app.dependency_overrides[get_current_user] = lambda: current_user
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_seed_defaults_endpoint_triggers_seed_service(self) -> None:
        result = SeedDefaultsResult(force=True)
        result.summary["menus"].updated = 1
        result.summary["menus"].overwritten = 1

        with patch("api.app.api.v1.admin.seed_defaults", return_value=result) as seed_defaults_mock:
            response = self.client.post("/api/v1/admin/system/seed-defaults?force=true")

        self.assertEqual(response.status_code, 200)
        seed_defaults_mock.assert_called_once()
        self.assertTrue(seed_defaults_mock.call_args.kwargs["force"])

        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "force_overwrite")
        self.assertTrue(payload["overwrote_existing"])
        self.assertEqual(payload["summary"]["menus"]["updated"], 1)
        self.assertEqual(payload["summary"]["menus"]["overwritten"], 1)


if __name__ == "__main__":
    unittest.main()
