from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.api.v1.admin import router as admin_router
from app.api.v1.users import router as users_router
from app.core.database import Base, get_db
from app.core.dependencies import CurrentUser, get_current_user
from app.models.menu import Menu, RoleMenu
from app.models.rbac import Role
from app.models.user import User


class MenuRouteGuardTest(unittest.TestCase):
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
        self.session = self.SessionLocal()
        self.app = FastAPI()
        self.app.include_router(admin_router, prefix="/api/v1")
        self.app.include_router(users_router, prefix="/api/v1")

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        self.current_user = CurrentUser(
            user=User(
                id="admin",
                email="admin@example.com",
                username="admin",
                password_hash="secret",
                status="ENABLED",
            ),
            role_codes={"admin"},
            permission_codes={"user.manage", "menu.manage"},
        )
        self.app.dependency_overrides[get_db] = override_get_db
        self.app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.app.dependency_overrides.clear()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _seed_menu(self, *, status: str = "enabled", visible: bool = True) -> Menu:
        role = Role(code="admin", name="Admin")
        menu = Menu(
            code="admin.users",
            name="用户管理",
            path="/admin/users",
            type="menu",
            status=status,
            visible=visible,
            sort_order=10,
            permission_code="user.manage",
        )
        self.session.add_all([role, menu])
        self.session.flush()
        self.session.add(RoleMenu(role_id=role.id, menu_id=menu.id))
        self.session.commit()
        return menu

    def test_disabled_menu_is_hidden_from_admin_menu_tree(self) -> None:
        self._seed_menu(status="disabled")

        response = self.client.get("/api/v1/admin/me/menus")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_disabled_menu_rejects_direct_api_access(self) -> None:
        self._seed_menu(status="disabled")

        response = self.client.get("/api/v1/users")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "Menu is disabled")

    def test_enabled_menu_allows_direct_api_access_to_continue(self) -> None:
        self._seed_menu(status="enabled")

        response = self.client.get("/api/v1/users")

        self.assertNotEqual(response.status_code, 403)

    def test_hidden_menu_rejects_direct_api_access(self) -> None:
        menu = self._seed_menu(visible=False)

        response = self.client.get("/api/v1/users")

        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(self.session.scalar(select(Menu).where(Menu.id == menu.id)))


if __name__ == "__main__":
    unittest.main()
