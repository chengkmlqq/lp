from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.app import models  # noqa: F401
from api.app.core.database import Base
from api.app.models.ai_chat import AiChatConversation, AiChatMessage
from api.app.models.user import User
from api.app.services.ai_chat_service import stream_message


class AiChatStreamServiceTest(unittest.TestCase):
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
        self.session.add(
            User(
                id="user-1",
                email="user@example.com",
                username="tester",
                password_hash="hash",
                status="active",
            )
        )
        self.session.add(AiChatConversation(id=1, title="测试对话", user_id="user-1"))
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_stream_message_yields_delta_and_persists_messages(self) -> None:
        def fake_stream(_: Any, history: list[AiChatMessage]) -> list[dict[str, Any]]:
            self.assertEqual(history[-1].content, "你好")
            return [
                {"choices": [{"delta": {"content": "你"}, "finish_reason": None}]},
                {"choices": [{"delta": {"content": "好"}, "finish_reason": "stop"}]},
            ]

        with patch("api.app.services.ai_chat_service._stream_openai_api", side_effect=fake_stream):
            events = stream_message(self.session, 1, "你好", user_id="user-1")
            self.assertIsNotNone(events)
            event_list = list(events or [])

        self.assertEqual([event["type"] for event in event_list], ["message", "delta", "delta", "done"])
        self.assertEqual(event_list[1]["content"], "你")
        self.assertEqual(event_list[2]["content"], "好")
        self.assertEqual(event_list[3]["reply"]["content"], "你好")

        stored_messages = (
            self.session.query(AiChatMessage)
            .filter(AiChatMessage.conversation_id == 1)
            .order_by(AiChatMessage.id.asc())
            .all()
        )
        self.assertEqual([message.role for message in stored_messages], ["user", "assistant"])
        self.assertEqual([message.content for message in stored_messages], ["你好", "你好"])


if __name__ == "__main__":
    unittest.main()
