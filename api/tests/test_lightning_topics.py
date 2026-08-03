from __future__ import annotations

from app.services.topic_registry import TOPIC_RULES, validate_topic_subscription


def _validate(topic: str, *, roles: set[str] | None = None, permissions: set[str] | None = None):
    return validate_topic_subscription(
        topic,
        role_codes=roles or set(),
        permission_codes=permissions or set(),
    )


def test_lightning_topics_registered() -> None:
    assert "admin.lightning-distribution" in TOPIC_RULES
    assert "admin.lightning-amplitude" in TOPIC_RULES


def test_lightning_topics_permissions() -> None:
    for topic in ("admin.lightning-distribution", "admin.lightning-amplitude"):
        # lightning.read 允许订阅
        ok, reason = _validate(topic, permissions={"lightning.read"})
        assert ok is True
        assert reason is None
        # lightning.manage 允许订阅
        ok, _ = _validate(topic, permissions={"lightning.manage"})
        assert ok is True
        # 无权限 → 拒绝
        ok, reason = _validate(topic, permissions={"other.read"})
        assert ok is False
        assert reason == "missing_permission"
        # admin 角色直接放行
        ok, reason = _validate(topic, roles={"admin"})
        assert ok is True
        assert reason is None
