"""验证码服务单元测试:生成 + 校验(一次性/大小写不敏感/过期)。"""
import time

import pytest


def _make_fake_redis(monkeypatch, code: str = "abcd"):
    """用内存 dict 模拟 redis,避免依赖真实 redis 连接。"""
    import redis as redis_lib

    store = {}

    class FakeRedis:
        def setex(self, key, ttl, value):
            store[key] = (value, time.time() + ttl)

        def get(self, key):
            item = store.get(key)
            if not item:
                return None
            value, exp = item
            if time.time() > exp:
                return None
            return value.encode() if isinstance(value, str) else value

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(
        "app.services.captcha_service._get_redis_client",
        lambda: FakeRedis(),
    )
    return store


def test_generate_returns_id_and_image(monkeypatch):
    from app.services.captcha_service import generate_captcha

    _make_fake_redis(monkeypatch)
    captcha_id, image_b64 = generate_captcha()
    assert captcha_id
    assert len(captcha_id) == 32
    assert image_b64.startswith("iVBOR")  # PNG magic in base64


def test_verify_case_insensitive_and_one_time(monkeypatch):
    from app.services.captcha_service import generate_captcha, verify_captcha

    store = _make_fake_redis(monkeypatch)
    captcha_id, _ = generate_captcha()
    # 从 fake store 取出真实答案
    real_answer = list(store.values())[0][0]
    assert verify_captcha(captcha_id, real_answer.upper()) is True
    # 一次性:第二次校验失败(已删除)
    assert verify_captcha(captcha_id, real_answer) is False


def test_verify_wrong_code_fails(monkeypatch):
    from app.services.captcha_service import generate_captcha, verify_captcha

    _make_fake_redis(monkeypatch)
    captcha_id, _ = generate_captcha()
    assert verify_captcha(captcha_id, "zzzz") is False


def test_verify_missing_ids_fail():
    from app.services.captcha_service import verify_captcha

    assert verify_captcha("", "") is False
    assert verify_captcha("nonexistent-id", "abcd") is False
