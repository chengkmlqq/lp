from __future__ import annotations

import os
import unittest
from contextlib import ExitStack
from io import BytesIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.core.security import hash_password
from api.app.models.audit_log import AuditLog
from api.app.models.file_storage import FileStorageBackend, FileStorageMount
from api.app.models.user import User
from api.app.schemas.admin import MenuCreateRequest, MenuUpdateRequest, RoleCreateRequest, RoleUpdateRequest
from api.app.schemas.auth import LoginRequest
from api.app.schemas.file_storage import (
    FileCreateDirectoryRequest,
    FileDeleteRequest,
    FileMoveRequest,
    FileRenameRequest,
)
from api.app.schemas.system_param import SystemParamCreateRequest, SystemParamUpdateRequest
from api.app.schemas.user import UserCreateRequest, UserPasswordResetRequest, UserRoleUpdateRequest, UserUpdateRequest
from api.app.services import auth_service, file_service, legacy_admin_rbac_service, system_param_service, user_service
from api.app.services.legacy_authz_service import UserAuthorization


class AuditLogCoverageTest(unittest.TestCase):
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
        self.tempdir = TemporaryDirectory()
        self.session_local_patcher = patch("api.app.core.database.SessionLocal", self.SessionLocal)
        self.session_local_patcher.start()

    def tearDown(self) -> None:
        self.session_local_patcher.stop()
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.tempdir.cleanup()

    def test_auth_login_failure_writes_audit_log(self) -> None:
        user = self._create_user(user_id="alice", username="alice", password="correct-pass")

        with self.assertRaises(HTTPException) as exc_info:
            auth_service.login_user(
                self.session,
                LoginRequest(user_id=user.id, password="wrong-pass"),
                user_agent="pytest",
                ip_address="127.0.0.1",
            )

        self.assertEqual(exc_info.exception.status_code, 401)
        log = self._latest_log("auth.login_failed")
        self.assertEqual(log.user_id, user.id)
        self.assertIn(f"attempted_user_id={user.id}", log.detail or "")
        self.assertIn("reason=invalid_credentials", log.detail or "")

    def test_user_and_system_param_actions_write_audit_logs(self) -> None:
        actor = self._create_user(user_id="admin", username="admin", password="admin-pass")
        created = user_service.create_user(
            self.session,
            UserCreateRequest(
                user_id="bob",
                email="bob@example.com",
                username="bobby",
                password="initial-pass",
            ),
            actor_user_id=actor.id,
        )
        self.assertIsNotNone(created)

        updated = user_service.update_user(
            self.session,
            "bob",
            UserUpdateRequest(username="robert", status="disabled"),
            actor_user_id=actor.id,
        )
        self.assertIsNotNone(updated)

        reset = user_service.reset_user_password(
            self.session,
            "bob",
            UserPasswordResetRequest(new_password="updated-pass"),
            actor_user_id=actor.id,
        )
        self.assertIsNotNone(reset)

        created_param = system_param_service.create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="site_name",
                param_name="Site Name",
                param_value="fquiz",
                description="visible name",
            ),
            actor_user_id=actor.id,
        )
        self.assertIsNotNone(created_param)

        updated_param = system_param_service.update_system_param(
            self.session,
            created_param.id,
            SystemParamUpdateRequest(status="disabled", description="changed description"),
            actor_user_id=actor.id,
        )
        self.assertIsNotNone(updated_param)

        self.assertTrue(
            system_param_service.delete_system_param(
                self.session,
                created_param.id,
                actor_user_id=actor.id,
            )
        )
        self.assertTrue(user_service.delete_user(self.session, "bob", actor_user_id=actor.id))

        actions = self._logged_actions()
        self.assertIn("user.create", actions)
        self.assertIn("user.update", actions)
        self.assertIn("user.password.reset", actions)
        self.assertIn("user.delete", actions)
        self.assertIn("system_param.create", actions)
        self.assertIn("system_param.update", actions)
        self.assertIn("system_param.delete", actions)

        user_update_log = self._latest_log("user.update")
        self.assertIn("changed_fields=status,username", user_update_log.detail or "")
        self.assertIn("status_transition=ENABLED->DISABLED", user_update_log.detail or "")

        param_update_log = self._latest_log("system_param.update")
        self.assertIn("param_key=site_name", param_update_log.detail or "")
        self.assertIn("changed_fields=description,status", param_update_log.detail or "")

    def test_legacy_role_menu_and_user_role_actions_write_audit_logs(self) -> None:
        actor = self._create_user(user_id="admin", username="admin", password="admin-pass")
        target = self._create_user(user_id="carol", username="carol", password="carol-pass")
        self._create_legacy_rbac_tables()
        self.session.execute(
            text(
                """
                INSERT INTO user_role (id, name, descr, state, create_date, update_date)
                VALUES
                    ('editor', 'Editor', 'Editor', 'ENABLED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        self.session.commit()

        with patch(
            "api.app.services.user_service.get_user_authorization",
            return_value=UserAuthorization(role_codes={"editor"}, permission_codes=set()),
        ):
            updated_user = user_service.set_user_roles(
                self.session,
                target.id,
                UserRoleUpdateRequest(role_codes=["editor"]),
                actor_user_id=actor.id,
            )
        self.assertIsNotNone(updated_user)

        with ExitStack() as stack:
            stack.enter_context(
                patch("api.app.services.legacy_admin_rbac_service._legacy_role_table_exists", return_value=True)
            )
            stack.enter_context(
                patch("api.app.services.legacy_admin_rbac_service._legacy_menu_table_exists", return_value=True)
            )
            stack.enter_context(
                patch("api.app.services.legacy_admin_rbac_service._legacy_user_role_relation_exists", return_value=True)
            )

            first_menu = legacy_admin_rbac_service.create_menu(
                self.session,
                MenuCreateRequest(
                    code="custom.audit.menu",
                    name="Custom Audit Menu",
                    path="/admin/custom-audit",
                    icon="Audit",
                    sort_order=10,
                ),
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(first_menu)

            second_menu = legacy_admin_rbac_service.create_menu(
                self.session,
                MenuCreateRequest(
                    code="custom.audit.archive",
                    name="Custom Audit Archive",
                    path="/admin/custom-archive",
                    icon="Archive",
                    sort_order=20,
                ),
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(second_menu)

            updated_menu = legacy_admin_rbac_service.update_menu(
                self.session,
                first_menu.id,
                MenuUpdateRequest(name="Custom Audit Menu 2", status="disabled"),
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(updated_menu)

            created_role = legacy_admin_rbac_service.create_role(
                self.session,
                RoleCreateRequest(code="auditor", name="Auditor", menu_ids=[]),
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(created_role)

            updated_role = legacy_admin_rbac_service.update_role(
                self.session,
                created_role.id,
                RoleUpdateRequest(name="Auditor Updated"),
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(updated_role)

            replaced_role = legacy_admin_rbac_service.replace_role_menus(
                self.session,
                created_role.id,
                [first_menu.id, second_menu.id],
                actor_user_id=actor.id,
            )
            self.assertIsNotNone(replaced_role)

            self.assertTrue(
                legacy_admin_rbac_service.delete_role(
                    self.session,
                    created_role.id,
                    actor_user_id=actor.id,
                )
            )
            self.assertTrue(
                legacy_admin_rbac_service.delete_menu(
                    self.session,
                    second_menu.id,
                    actor_user_id=actor.id,
                )
            )

        actions = self._logged_actions()
        self.assertIn("user.roles.replace", actions)
        self.assertIn("menu.create", actions)
        self.assertIn("menu.update", actions)
        self.assertIn("menu.delete", actions)
        self.assertIn("role.create", actions)
        self.assertIn("role.update", actions)
        self.assertIn("role.menus.replace", actions)
        self.assertIn("role.delete", actions)

        role_replace_log = self._latest_log("role.menus.replace")
        self.assertIn("role_code=auditor", role_replace_log.detail or "")
        self.assertIn("menu_ids=", role_replace_log.detail or "")

    def test_file_actions_write_audit_logs(self) -> None:
        actor = self._create_user(user_id="admin", username="admin", password="admin-pass")
        mount = self._create_vfs_mount()

        file_service.create_directory(
            self.session,
            FileCreateDirectoryRequest(mount_code=mount.code, parent_path="/", name="docs"),
            actor=actor,
        )
        file_service.create_directory(
            self.session,
            FileCreateDirectoryRequest(mount_code=mount.code, parent_path="/", name="archive"),
            actor=actor,
        )
        uploaded = file_service.upload_file_to_path(
            self.session,
            mount_code=mount.code,
            parent_path="/",
            file=SimpleNamespace(
                filename="guide.txt",
                file=BytesIO(b"audit coverage"),
                content_type="text/plain",
            ),
            actor=actor,
        )
        self.assertEqual(uploaded.path, "/guide.txt")

        renamed = file_service.rename_file_path(
            self.session,
            FileRenameRequest(
                mount_code=mount.code,
                path="/guide.txt",
                is_dir=False,
                new_name="guide-v2.txt",
            ),
            actor=actor,
        )
        self.assertEqual(renamed.target_path, "/guide-v2.txt")

        moved = file_service.move_file_path(
            self.session,
            FileMoveRequest(
                mount_code=mount.code,
                path="/guide-v2.txt",
                is_dir=False,
                target_parent_path="/archive",
            ),
            actor=actor,
        )
        self.assertEqual(moved.target_path, "/archive/guide-v2.txt")

        filename, content, content_type = file_service.download_file_from_path(
            self.session,
            mount_code=mount.code,
            path="/archive/guide-v2.txt",
            actor=actor,
        )
        self.assertEqual(filename, "guide-v2.txt")
        self.assertEqual(content, b"audit coverage")
        self.assertEqual(content_type, "text/plain")

        zip_name, zip_content, zip_content_type = file_service.download_directory_as_zip(
            self.session,
            mount_code=mount.code,
            path="/archive",
            actor=actor,
        )
        self.assertEqual(zip_name, "archive.zip")
        self.assertEqual(zip_content_type, "application/zip")
        self.assertGreater(len(zip_content), 0)

        deleted = file_service.delete_file_path(
            self.session,
            FileDeleteRequest(
                mount_code=mount.code,
                path="/archive/guide-v2.txt",
                is_dir=False,
                recursive=False,
            ),
            actor=actor,
        )
        self.assertEqual(deleted.path, "/archive/guide-v2.txt")

        actions = self._logged_actions()
        self.assertIn("file.mkdir", actions)
        self.assertIn("file.upload", actions)
        self.assertIn("file.rename", actions)
        self.assertIn("file.move", actions)
        self.assertIn("file.download", actions)
        self.assertIn("file.download_zip", actions)
        self.assertIn("file.delete", actions)

        download_log = self._latest_log("file.download")
        self.assertIn("mount_code=main", download_log.detail or "")
        self.assertIn("path=/archive/guide-v2.txt", download_log.detail or "")

    def _create_user(
        self,
        *,
        user_id: str,
        username: str,
        password: str,
        status: str = "ENABLED",
    ) -> User:
        user = User(
            id=user_id,
            email=f"{user_id}@example.com",
            username=username,
            password_hash=hash_password(password),
            status=status,
        )
        self.session.add(user)
        self.session.commit()
        return user

    def _create_vfs_mount(self) -> FileStorageMount:
        backend = FileStorageBackend(
            code="local",
            name="Local",
            driver_type="VFS",
            status="enabled",
            is_default=True,
            config_json={"root_dir": self.tempdir.name},
        )
        mount = FileStorageMount(
            code="main",
            name="Main",
            backend=backend,
            mount_path="/",
            root_path="/",
            is_enabled=True,
        )
        self.session.add(mount)
        self.session.commit()
        return mount

    def _create_legacy_rbac_tables(self) -> None:
        self.session.execute(
            text(
                """
                CREATE TABLE user_role (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    descr TEXT,
                    state TEXT,
                    create_date DATETIME,
                    update_date DATETIME
                )
                """
            )
        )
        self.session.execute(
            text(
                """
                CREATE TABLE user_role_rela (
                    rela_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    role_id TEXT
                )
                """
            )
        )
        self.session.execute(
            text(
                """
                CREATE TABLE menu (
                    menu_id TEXT PRIMARY KEY,
                    menu_name TEXT,
                    menu_label TEXT,
                    menu_type TEXT,
                    parent_id TEXT,
                    url TEXT,
                    menu_icon TEXT,
                    seq INTEGER,
                    state TEXT,
                    menu_descr TEXT,
                    create_date DATETIME,
                    update_date DATETIME
                )
                """
            )
        )
        self.session.execute(
            text(
                """
                CREATE TABLE role_menu_rela (
                    rela_id TEXT PRIMARY KEY,
                    role_id TEXT,
                    menu_id TEXT
                )
                """
            )
        )
        self.session.commit()

    def _latest_log(self, action: str) -> AuditLog:
        log = self.session.scalars(
            select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())
        ).first()
        self.assertIsNotNone(log, f"expected audit log for {action}")
        return log

    def _logged_actions(self) -> set[str]:
        return {log.action for log in self.session.scalars(select(AuditLog)).all()}


if __name__ == "__main__":
    unittest.main()
