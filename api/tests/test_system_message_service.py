from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.system_message import SystemMessage
from app.schemas.system_message import SystemMessageCreateRequest
from app.services.system_message_service import (
    create_system_message,
    delete_system_message,
    list_user_messages,
)


def test_delete_system_message_removes_existing_message() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        message = create_system_message(
            db,
            SystemMessageCreateRequest(
                title="系统通知",
                content="测试内容",
                message_type="info",
            ),
        )

        deleted = delete_system_message(db, message.id)

        assert deleted is True
        assert db.scalar(select(SystemMessage).where(SystemMessage.id == message.id)) is None


def test_delete_system_message_returns_false_when_missing() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        deleted = delete_system_message(db, "missing-message-id")

        assert deleted is False


def test_list_user_messages_filters_items_and_total_by_type() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        info_message = create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知",
                content="测试内容",
                message_type="info",
            ),
        )
        create_system_message(
            db,
            SystemMessageCreateRequest(
                title="警告",
                content="测试内容",
                message_type="warning",
            ),
        )

        messages, total, unread_count = list_user_messages(
            db,
            user_id="user-1",
            message_type="info",
        )

        assert [message.id for message in messages] == [info_message.id]
        assert total == 1
        assert unread_count == 2


def test_list_user_messages_filters_by_read_status_read() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        msg1 = create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知1",
                content="测试内容",
                message_type="info",
            ),
        )
        msg2 = create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知2",
                content="测试内容",
                message_type="warning",
            ),
        )
        # Mark msg1 as read
        from datetime import datetime
        from sqlalchemy import update
        db.execute(
            update(SystemMessage)
            .where(SystemMessage.id == msg1.id)
            .values(is_read=True, read_at=datetime.utcnow())
        )
        db.commit()

        messages, total, _ = list_user_messages(
            db,
            user_id="user-1",
            read_status="read",
        )

        assert [m.id for m in messages] == [msg1.id]
        assert total == 1


def test_list_user_messages_filters_by_read_status_unread() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知1",
                content="测试内容",
                message_type="info",
            ),
        )

        messages, total, _ = list_user_messages(
            db,
            user_id="user-1",
            read_status="unread",
        )

        assert len(messages) == 1
        assert total == 1


def test_list_user_messages_read_status_none_returns_all() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[SystemMessage.__table__])

    with Session(engine) as db:
        create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知1",
                content="测试内容",
                message_type="info",
            ),
        )
        create_system_message(
            db,
            SystemMessageCreateRequest(
                title="通知2",
                content="测试内容",
                message_type="warning",
            ),
        )

        messages, total, _ = list_user_messages(
            db,
            user_id="user-1",
            read_status=None,
        )

        assert len(messages) == 2
        assert total == 2
