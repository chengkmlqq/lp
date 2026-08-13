from __future__ import annotations

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SYSTEM_PARAM_ENCRYPTION_KEY", "0123456789abcdef0123456789abcdef")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.core.param_encryption import MASK, decrypt_value, encrypt_value, is_encrypted_value
from api.app.models.system_param import SystemParam
from api.app.schemas.system_param import SystemParamCreateRequest, SystemParamUpdateRequest
from api.app.services.system_param_service import (
    create_system_param,
    get_system_param_decrypted,
    get_system_params_runtime,
    list_system_params,
    serialize_system_param,
    update_system_param,
)


class ParamEncryptionModuleTest(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self) -> None:
        encrypted = encrypt_value("sk-secret-key-123")
        self.assertTrue(is_encrypted_value(encrypted))
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertEqual(decrypt_value(encrypted), "sk-secret-key-123")

    def test_encrypt_empty_value_stays_empty(self) -> None:
        self.assertEqual(encrypt_value(""), "")
        self.assertFalse(is_encrypted_value(""))

    def test_decrypt_non_ciphertext_returns_none(self) -> None:
        self.assertIsNone(decrypt_value("plain-value"))
        self.assertIsNone(decrypt_value(""))


class SystemParamEncryptionServiceTest(unittest.TestCase):
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

    def test_create_encrypted_param_stores_ciphertext_and_masks_serialization(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.api_key",
                param_name="Test Key",
                param_value="super-secret",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        self.assertIsNotNone(created)
        assert created is not None
        self.assertTrue(created.is_encrypted)
        self.assertTrue(created.has_value)
        self.assertEqual(created.param_value, MASK)

        stored = get_system_param_decrypted(self.session, "test.api_key")
        self.assertEqual(stored, "super-secret")

        # 数据库中绝不存明文
        raw = self.session.get(SystemParam, created.id)
        assert raw is not None
        self.assertNotEqual(raw.param_value, "super-secret")
        self.assertTrue(raw.param_value.startswith("enc:v1:"))

    def test_create_plaintext_param_stays_plaintext(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.plain",
                param_name="Plain",
                param_value="hello",
                is_encrypted=False,
            ),
            actor_user_id="admin",
        )
        assert created is not None
        self.assertFalse(created.is_encrypted)
        self.assertEqual(created.param_value, "hello")
        self.assertEqual(get_system_param_decrypted(self.session, "test.plain"), "hello")

    def test_update_encrypted_param_keeps_ciphertext_on_placeholder(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.api_key",
                param_name="Test Key",
                param_value="secret-1",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        assert created is not None
        raw_before = self.session.get(SystemParam, created.id)
        assert raw_before is not None
        stored_before = raw_before.param_value

        # 传空值 / 掩码占位值都不覆盖原密文
        for placeholder in ("", MASK):
            updated = update_system_param(
                self.session,
                created.id,
                SystemParamUpdateRequest(param_value=placeholder, is_encrypted=True),
                actor_user_id="admin",
            )
            assert updated is not None
            raw_after = self.session.get(SystemParam, created.id)
            assert raw_after is not None
            self.assertEqual(raw_after.param_value, stored_before)
            self.assertEqual(get_system_param_decrypted(self.session, "test.api_key"), "secret-1")

    def test_update_encrypted_param_with_new_value_replaces_ciphertext(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.api_key",
                param_name="Test Key",
                param_value="secret-1",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        assert created is not None

        updated = update_system_param(
            self.session,
            created.id,
            SystemParamUpdateRequest(param_value="secret-2", is_encrypted=True),
            actor_user_id="admin",
        )
        assert updated is not None
        self.assertEqual(get_system_param_decrypted(self.session, "test.api_key"), "secret-2")

    def test_toggle_off_encryption_decrypts_existing_value(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.api_key",
                param_name="Test Key",
                param_value="secret-1",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        assert created is not None

        updated = update_system_param(
            self.session,
            created.id,
            SystemParamUpdateRequest(is_encrypted=False),
            actor_user_id="admin",
        )
        assert updated is not None
        self.assertFalse(updated.is_encrypted)
        self.assertEqual(updated.param_value, "secret-1")
        raw = self.session.get(SystemParam, created.id)
        assert raw is not None
        self.assertEqual(raw.param_value, "secret-1")

    def test_toggle_on_encryption_encrypts_existing_plaintext(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.plain",
                param_name="Plain",
                param_value="hello",
                is_encrypted=False,
            ),
            actor_user_id="admin",
        )
        assert created is not None

        updated = update_system_param(
            self.session,
            created.id,
            SystemParamUpdateRequest(is_encrypted=True),
            actor_user_id="admin",
        )
        assert updated is not None
        self.assertTrue(updated.is_encrypted)
        raw = self.session.get(SystemParam, created.id)
        assert raw is not None
        self.assertTrue(raw.param_value.startswith("enc:v1:"))
        self.assertEqual(get_system_param_decrypted(self.session, "test.plain"), "hello")

    def test_keyword_search_ignores_encrypted_param_value(self) -> None:
        self.session.add(
            SystemParam(
                param_key="test.api_key",
                param_name="API Key Param",
                param_value=encrypt_value("needle-in-cipher"),
                is_encrypted=True,
                status="enabled",
            )
        )
        self.session.add(
            SystemParam(
                param_key="test.plain",
                param_name="Plain Param",
                param_value="needle-in-plain",
                is_encrypted=False,
                status="enabled",
            )
        )
        self.session.commit()

        page = list_system_params(
            self.session,
            limit=50,
            offset=0,
            keyword="needle-in",
            status_filter=None,
        )
        keys = [item.param_key for item in page.items]
        self.assertIn("test.plain", keys)
        self.assertNotIn("test.api_key", keys)

        # 但按参数名/键搜索仍能命中加密参数
        page_by_name = list_system_params(
            self.session,
            limit=50,
            offset=0,
            keyword="API Key",
            status_filter=None,
        )
        self.assertIn("test.api_key", [item.param_key for item in page_by_name.items])

    def test_decrypted_getter_requires_enabled_status(self) -> None:
        created = create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.api_key",
                param_name="Test Key",
                param_value="secret-1",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        assert created is not None
        update_system_param(
            self.session,
            created.id,
            SystemParamUpdateRequest(status="disabled"),
            actor_user_id="admin",
        )
        self.assertIsNone(get_system_param_decrypted(self.session, "test.api_key"))

    def test_runtime_helper_returns_decrypted_values(self) -> None:
        create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="tianditu.tk",
                param_name="Tianditu Key",
                param_value="tk-value-abc",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="tianditu.max_level",
                param_name="Max Level",
                param_value="18",
                is_encrypted=False,
            ),
            actor_user_id="admin",
        )
        items = get_system_params_runtime(self.session, ["tianditu.tk", "tianditu.max_level", "not.exists"])
        result = {item.param_key: item.param_value for item in items}
        self.assertEqual(result, {"tianditu.tk": "tk-value-abc", "tianditu.max_level": "18"})

    def test_serialize_empty_encrypted_param_has_no_value(self) -> None:
        create_system_param(
            self.session,
            SystemParamCreateRequest(
                param_key="test.empty",
                param_name="Empty Key",
                param_value="",
                is_encrypted=True,
            ),
            actor_user_id="admin",
        )
        item = self.session.query(SystemParam).filter_by(param_key="test.empty").first()
        summary = serialize_system_param(item)
        self.assertTrue(summary.is_encrypted)
        self.assertFalse(summary.has_value)
        self.assertEqual(summary.param_value, "")


if __name__ == "__main__":
    unittest.main()
