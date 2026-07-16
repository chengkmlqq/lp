from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.schemas.system_message import SystemMessagePublic


def test_system_message_public_validates_attribute_object() -> None:
    message = SimpleNamespace(
        id="message-1",
        title="系统通知",
        content="测试内容",
        message_type="info",
        target_user_id=None,
        is_read=False,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
        read_at=None,
    )

    result = SystemMessagePublic.model_validate(message)

    assert result.id == "message-1"
    assert result.title == "系统通知"
    assert result.is_read is False
