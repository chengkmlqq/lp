from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models.system_message import SystemMessage
from ..schemas.system_message import SystemMessageCreateRequest, SystemMessageType

if TYPE_CHECKING:
    from ..schemas.system_message import SystemMessagePublic


def create_system_message(
    db: Session,
    payload: SystemMessageCreateRequest,
) -> SystemMessage:
    """创建系统消息"""
    message = SystemMessage(
        title=payload.title,
        content=payload.content,
        message_type=payload.message_type,
        target_user_id=payload.target_user_id,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_user_messages(
    db: Session,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool = False,
    message_type: SystemMessageType | None = None,
) -> tuple[list[SystemMessage], int, int]:
    """获取用户的系统消息列表"""
    base_conditions = [
        (SystemMessage.target_user_id == user_id) | (SystemMessage.target_user_id.is_(None)),
    ]

    if unread_only:
        base_conditions.append(SystemMessage.is_read == False)

    if message_type:
        base_conditions.append(SystemMessage.message_type == message_type)

    query = select(SystemMessage).where(*base_conditions)

    # 获取总数
    total_query = select(func.count()).select_from(SystemMessage).where(*base_conditions)
    total = db.scalar(total_query)

    # 获取未读数
    unread_query = select(func.count()).select_from(SystemMessage).where(
        (SystemMessage.target_user_id == user_id) | (SystemMessage.target_user_id.is_(None)),
        SystemMessage.is_read == False,
    )
    unread_count = db.scalar(unread_query)

    # 按创建时间倒序
    query = query.order_by(SystemMessage.created_at.desc())
    query = query.limit(limit).offset(offset)

    messages = list(db.scalars(query).all())

    return messages, total or 0, unread_count or 0


def mark_messages_as_read(
    db: Session,
    user_id: str,
    message_ids: list[str],
) -> int:
    """标记消息为已读"""
    stmt = (
        update(SystemMessage)
        .where(
            SystemMessage.id.in_(message_ids),
            (SystemMessage.target_user_id == user_id) | (SystemMessage.target_user_id.is_(None)),
            SystemMessage.is_read == False,
        )
        .values(is_read=True, read_at=datetime.utcnow())
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def delete_system_message(db: Session, message_id: str) -> bool:
    """删除系统消息"""
    stmt = delete(SystemMessage).where(SystemMessage.id == message_id)
    result = db.execute(stmt)
    db.commit()
    return (result.rowcount or 0) > 0


def get_unread_count(db: Session, user_id: str) -> int:
    """获取用户未读消息数量"""
    query = select(func.count()).select_from(SystemMessage).where(
        (SystemMessage.target_user_id == user_id) | (SystemMessage.target_user_id.is_(None)),
        SystemMessage.is_read == False,
    )
    count = db.scalar(query)
    return count or 0
