"""验证码 API 集成测试: 获取验证码 + 登录时校验(成功/失败/过期)。"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("MINIO_ENABLED", "false")

import unittest
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app


class FakeRedis:
    """内存 redis 替身。"""

    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = value

    def get(self, key):
        v = self.store.get(key)
        return v.encode() if isinstance(v, str) else v

    def delete(self, key):
        self.store.pop(key, None)


class CaptchaApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False, expire_on_commit=False
        )
        Base.metadata.create_all(bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.fake_redis = FakeRedis()
        self.redis_patcher = mock.patch(
            "app.services.captcha_service._get_redis_client",
            return_value=self.fake_redis,
        )
        self.redis_patcher.start()

    def tearDown(self) -> None:
        if getattr(self, "captcha_patcher", None) is not None:
            self.captcha_patcher.stop()
        self.redis_patcher.stop()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _get_captcha(self):
        resp = self.client.get("/api/v1/auth/captcha")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["captcha_id"]
        assert data["image_base64"].startswith("iVBOR")
        return data

    def _real_code(self, captcha_id: str) -> str:
        return next(v for k, v in self.fake_redis.store.items() if captcha_id in k)

    def test_get_captcha_ok(self):
        data = self._get_captcha()
        assert len(data["captcha_id"]) == 32
        assert data["expires_in"] == 300

    def test_login_without_captcha_rejected(self):
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"user_id": "nobody", "password": "whatever"},
        )
        assert resp.status_code == 400
        assert "验证码" in resp.json()["detail"]

    def test_login_wrong_captcha_rejected(self):
        data = self._get_captcha()
        resp = self.client.post(
            "/api/v1/auth/login",
            json={
                "user_id": "nobody",
                "password": "whatever",
                "captcha_id": data["captcha_id"],
                "captcha_code": "ZZZZ",
            },
        )
        assert resp.status_code == 400
        assert "验证码" in resp.json()["detail"]

    def test_login_correct_captcha_reaches_auth(self):
        data = self._get_captcha()
        code = self._real_code(data["captcha_id"])
        # 验证码正确但账号不存在 -> 应走到 401 (账号校验), 而不是 400 (验证码校验)
        resp = self.client.post(
            "/api/v1/auth/login",
            json={
                "user_id": "no_such_user_xyz",
                "password": "whatever",
                "captcha_id": data["captcha_id"],
                "captcha_code": code,
            },
        )
        assert resp.status_code == 401, resp.text

    def test_sms_send_requires_captcha(self):
        # 短信开关默认关闭: 发送短信接口应报"未启用", 但图形码校验前置
        resp = self.client.post(
            "/api/v1/auth/sms-captcha/send",
            json={"captcha_id": "bad", "captcha_code": "bad", "phone": "13800138000"},
        )
        assert resp.status_code == 400
        assert "验证码" in resp.json()["detail"]

    def test_captcha_response_has_sms_enabled_flag(self):
        resp = self.client.get("/api/v1/auth/captcha")
        data = resp.json()
        assert "sms_captcha_enabled" in data
        assert data["sms_captcha_enabled"] is False

    def _disable_captcha(self):
        """monkeypatch captcha_service._get_param: auth.captcha.enabled=false 关闭图码。"""
        from app.services import captcha_service

        orig = captcha_service._get_param

        def fake_get_param(db, key):
            if key == captcha_service.CAPTCHA_ENABLED_PARAM_KEY:
                return "false"
            return orig(db, key)

        self.captcha_patcher = mock.patch.object(
            captcha_service, "_get_param", side_effect=fake_get_param
        )
        self.captcha_patcher.start()

    def test_captcha_disabled_returns_empty_and_flag(self):
        self._disable_captcha()
        data = self.client.get("/api/v1/auth/captcha").json()
        assert data["captcha_id"] == ""
        assert data["image_base64"] == ""
        assert data["expires_in"] == 0
        assert data["captcha_enabled"] is False

    def test_captcha_disabled_login_skips_captcha(self):
        self._disable_captcha()
        # 不传图码也能走到账号校验(401 而非 400 验证码), 证明图码门禁被跳过
        resp = self.client.post(
            "/api/v1/auth/login",
            json={"user_id": "no_such_user_xyz", "password": "whatever"},
        )
        assert resp.status_code == 401, resp.text

    def test_captcha_disabled_sms_send_skips_captcha_gate(self):
        self._disable_captcha()
        # 图码门禁跳过, 直接命中"短信未启用"(短信开关默认关), 而非图码错误
        resp = self.client.post(
            "/api/v1/auth/sms-captcha/send",
            json={"phone": "13800138000"},
        )
        assert resp.status_code == 400
        assert "短信" in resp.json()["detail"]
        assert "验证码" not in resp.json()["detail"]


if __name__ == "__main__":
    unittest.main()