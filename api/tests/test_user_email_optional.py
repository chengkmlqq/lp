"""
Test that user.email field is optional (nullable).

This test verifies the fix for FL-193 where email field had a NOT NULL
constraint that conflicted with the optional email field in the frontend.
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
from api.app.core.security import hash_password
from api.app.models.user import User
from api.app.schemas.user import UserCreateRequest
from api.app.services import user_service


class UserEmailOptionalTest(unittest.TestCase):
    """Test that users can be created without an email address."""

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

    def test_create_user_without_email(self) -> None:
        """Test creating a user with email=None should succeed."""
        user = user_service.create_user(
            self.session,
            UserCreateRequest(
                user_id="test_user_1",
                email=None,
                username="TestUser1",
                password="password123",
            ),
            actor_user_id="system",
        )

        self.assertIsNotNone(user)
        self.assertEqual(user.id, "test_user_1")
        self.assertEqual(user.username, "TestUser1")
        self.assertEqual(user.email, "")  # API returns empty string for None

    def test_create_user_with_email(self) -> None:
        """Test creating a user with email should still work."""
        user = user_service.create_user(
            self.session,
            UserCreateRequest(
                user_id="test_user_2",
                email="test2@example.com",
                username="TestUser2",
                password="password123",
            ),
            actor_user_id="system",
        )

        self.assertIsNotNone(user)
        self.assertEqual(user.id, "test_user_2")
        self.assertEqual(user.username, "TestUser2")
        self.assertEqual(user.email, "test2@example.com")

    def test_create_user_directly_without_email(self) -> None:
        """Test creating a User model directly without email."""
        user = User(
            id="direct_user",
            email=None,
            username="DirectUser",
            password_hash=hash_password("password123"),
            status="ENABLED",
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)

        self.assertEqual(user.id, "direct_user")
        self.assertEqual(user.username, "DirectUser")
        self.assertIsNone(user.email)


if __name__ == "__main__":
    unittest.main()
