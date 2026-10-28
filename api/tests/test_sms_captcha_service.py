"""短信验证码服务单测(pytest 风格): 开关、发送(阿里云调用)、频率限制、校验。"""
from __future__ import annotations

from unittest import mock

import pytest


class FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, key, ttl, value):
        self.store[key] = (value, ttl)

    def get(self, key):
        item = self.store.get(key)
        return (item[0].encode() if isinstance(item[0], str) else item[0]) if item else None

    def delete(self, key):
        self.store.pop(key, None)

    def exists(self, key):
        return 1 if key in self.store else 0


FULL_PARAMS = {
    "auth.sms_captcha.enabled": "true",
    "auth.sms_captcha.access_key_id": "AKID",
    "auth.sms_captcha.access_key_secret": "SECRET",
    "auth.sms_captcha.sign_name": "LP平台",
    "auth.sms_captcha.template_code": "SMS_123",
    "auth.sms_captcha.ttl_seconds": "300",
    "auth.sms_captcha.interval_seconds": "60",
}


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(
        "app.services.sms_captcha_service._get_redis_client",
        lambda: redis,
    )
    return redis


@pytest.fixture
def params(monkeypatch):
    def _install(overrides: dict | None = None):
        merged = dict(FULL_PARAMS)
        if overrides:
            merged.update(overrides)

        def fake_get_param(db, key: str) -> str:
            return merged.get(key, "")

        monkeypatch.setattr(
            "app.services.sms_captcha_service._get_param",
            fake_get_param,
        )
        return merged

    return _install


def test_disabled_by_default(params):
    params({"auth.sms_captcha.enabled": "false"})
    from app.services.sms_captcha_service import is_sms_captcha_enabled

    assert is_sms_captcha_enabled(object()) is False


def test_enabled_when_true(params):
    params()
    from app.services.sms_captcha_service import is_sms_captcha_enabled

    assert is_sms_captcha_enabled(object()) is True


@mock.patch("app.services.sms_captcha_service._send_sms")
def test_send_ok(mock_send, params, fake_redis):
    params()
    from app.services.sms_captcha_service import send_sms_captcha

    result = send_sms_captcha(object(), "13800138000")
    assert result["interval_seconds"] == 60
    assert result["ttl_seconds"] == 300
    mock_send.assert_called_once()
    stored = fake_redis.get("lp:smscaptcha:13800138000")
    assert stored and len(stored.decode()) == 6


@mock.patch("app.services.sms_captcha_service._send_sms")
def test_interval_limit(mock_send, params, fake_redis):
    params()
    from app.services.sms_captcha_service import SmsCaptchaError, send_sms_captcha

    send_sms_captcha(object(), "13800138000")
    with pytest.raises(SmsCaptchaError):
        send_sms_captcha(object(), "13800138000")
    mock_send.assert_called_once()  # 第二次未真正发送


@mock.patch("app.services.sms_captcha_service._send_sms")
def test_verify_one_time(mock_send, params, fake_redis):
    params()
    from app.services.sms_captcha_service import send_sms_captcha, verify_sms_captcha

    send_sms_captcha(object(), "13800138000")
    code = fake_redis.get("lp:smscaptcha:13800138000").decode()
    assert verify_sms_captcha(object(), "13800138000", code) is True
    assert verify_sms_captcha(object(), "13800138000", code) is False  # 一次性


def test_verify_wrong(params):
    params()
    from app.services.sms_captcha_service import verify_sms_captcha

    assert verify_sms_captcha(object(), "13800138000", "000000") is False
    assert verify_sms_captcha(object(), "", "") is False


@mock.patch("app.services.sms_captcha_service._send_sms")
def test_send_rejects_when_disabled(mock_send, params):
    params({"auth.sms_captcha.enabled": "false"})
    from app.services.sms_captcha_service import SmsCaptchaError, send_sms_captcha

    with pytest.raises(SmsCaptchaError):
        send_sms_captcha(object(), "13800138000")
    mock_send.assert_not_called()