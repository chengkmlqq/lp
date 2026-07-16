"""Test login lockout functionality."""
from __future__ import annotations

import os
import unittest
from datetime import timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app.core.database import Base
from api.app.models.base import utcnow
from api.app.models.user import User
from api.app.schemas.auth import LoginRequest
from api.app.services.auth_service import login_user
from api.app.core.security import hash_password


class LoginLockoutTestCase(unittest.TestCase):
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

    def test_login_lockout_after_5_failed_attempts(self) -> None:
        """Test that account is locked after 5 failed login attempts."""
        db = self.SessionLocal()
        try:
            # Create test user
            test_user = User(
                id="test_lockout_user",
                email="lockout@test.com",
                username="lockout_user",
                password_hash=hash_password("correct_password"),
                status="ENABLED",
                failed_login_attempts=0,
            )
            db.add(test_user)
            db.commit()

            # Attempt login 5 times with wrong password
            for i in range(5):
                with self.assertRaises(HTTPException) as exc_context:
                    login_user(
                        db,
                        LoginRequest(user_id="test_lockout_user", password="wrong_password"),
                        user_agent=None,
                        ip_address=None,
                    )

                # First 4 attempts should return 401
                if i < 4:
                    self.assertEqual(exc_context.exception.status_code, 401)
                # 5th attempt should lock account and return 403
                else:
                    self.assertEqual(exc_context.exception.status_code, 403)
                    self.assertIn("locked", exc_context.exception.detail.lower())

            # Verify user is locked
            db.refresh(test_user)
            self.assertEqual(test_user.failed_login_attempts, 5)
            self.assertIsNotNone(test_user.failed_login_locked_until)
            self.assertGreater(test_user.failed_login_locked_until, utcnow())

            # Attempt login with correct password should still fail due to lock
            with self.assertRaises(HTTPException) as exc_context:
                login_user(
                    db,
                    LoginRequest(user_id="test_lockout_user", password="correct_password"),
                    user_agent=None,
                    ip_address=None,
                )
            self.assertEqual(exc_context.exception.status_code, 403)
            self.assertIn("locked", exc_context.exception.detail.lower())

        finally:
            db.close()

    def test_login_success_resets_failed_attempts(self) -> None:
        """Test that successful login resets failed login attempts."""
        db = self.SessionLocal()
        try:
            # Create test user with some failed attempts
            test_user = User(
                id="test_reset_user",
                email="reset@test.com",
                username="reset_user",
                password_hash=hash_password("correct_password"),
                status="ENABLED",
                failed_login_attempts=3,
            )
            db.add(test_user)
            db.commit()

            # Successful login should reset counter
            result = login_user(
                db,
                LoginRequest(user_id="test_reset_user", password="correct_password"),
                user_agent=None,
                ip_address=None,
            )

            self.assertEqual(result.user.id, "test_reset_user")

            # Verify failed attempts are reset
            db.refresh(test_user)
            self.assertEqual(test_user.failed_login_attempts, 0)
            self.assertIsNone(test_user.failed_login_locked_until)

        finally:
            db.close()

    def test_login_after_lock_expires(self) -> None:
        """Test that user can login after lock period expires."""
        db = self.SessionLocal()
        try:
            # Create test user locked in the past
            past_time = utcnow() - timedelta(minutes=1)
            test_user = User(
                id="test_expired_lock_user",
                email="expired@test.com",
                username="expired_user",
                password_hash=hash_password("correct_password"),
                status="ENABLED",
                failed_login_attempts=5,
                failed_login_locked_until=past_time,
            )
            db.add(test_user)
            db.commit()

            # Login should succeed since lock has expired
            result = login_user(
                db,
                LoginRequest(user_id="test_expired_lock_user", password="correct_password"),
                user_agent=None,
                ip_address=None,
            )

            self.assertEqual(result.user.id, "test_expired_lock_user")

            # Verify failed attempts are reset
            db.refresh(test_user)
            self.assertEqual(test_user.failed_login_attempts, 0)
            self.assertIsNone(test_user.failed_login_locked_until)

        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
