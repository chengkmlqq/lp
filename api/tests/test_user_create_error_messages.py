"""
Test that user creation errors return specific, distinct error messages.

This test verifies the fix for FL-199 where the error message
"User id/email/username already exists or default role missing"
was too ambiguous to debug effectively.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app.core.database import Base
from api.app.schemas.user import UserCreateRequest
from api.app.services.user_service import (
    UserDuplicateError,
    create_user,
)


class UserCreateErrorMessageTest(unittest.TestCase):
    """Test that user creation returns specific error messages."""

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

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_duplicate_user_id_error_message(self) -> None:
        """Test that duplicate user_id returns specific error message."""
        create_user(
            self.session,
            UserCreateRequest(
                user_id="duplicate_test",
                email="user1@example.com",
                username="User1",
                password="password123",
            ),
            actor_user_id="system",
        )

        with self.assertRaises(UserDuplicateError) as ctx:
            create_user(
                self.session,
                UserCreateRequest(
                    user_id="duplicate_test",
                    email="user2@example.com",
                    username="User2",
                    password="password123",
                ),
                actor_user_id="system",
            )

        self.assertIn("already exists", str(ctx.exception))
        self.assertNotIn("default role", str(ctx.exception))

    def test_duplicate_username_error_message(self) -> None:
        """Test that duplicate username returns specific error message."""
        create_user(
            self.session,
            UserCreateRequest(
                user_id="user1",
                email="user1@example.com",
                username="DuplicateUsername",
                password="password123",
            ),
            actor_user_id="system",
        )

        with self.assertRaises(UserDuplicateError) as ctx:
            create_user(
                self.session,
                UserCreateRequest(
                    user_id="user2",
                    email="user2@example.com",
                    username="DuplicateUsername",
                    password="password123",
                ),
                actor_user_id="system",
            )

        self.assertIn("already exists", str(ctx.exception))
        self.assertNotIn("default role", str(ctx.exception))

    def test_duplicate_email_error_message(self) -> None:
        """Test that duplicate email returns specific error message."""
        create_user(
            self.session,
            UserCreateRequest(
                user_id="user1",
                email="duplicate@example.com",
                username="User1",
                password="password123",
            ),
            actor_user_id="system",
        )

        with self.assertRaises(UserDuplicateError) as ctx:
            create_user(
                self.session,
                UserCreateRequest(
                    user_id="user2",
                    email="duplicate@example.com",
                    username="User2",
                    password="password123",
                ),
                actor_user_id="system",
            )

        self.assertIn("already exists", str(ctx.exception))
        self.assertNotIn("default role", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
