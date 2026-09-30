import logging
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..models.system_message import SystemMessage
from ..schemas.system_message import SystemMessageCreateRequest, SystemMessageType

if TYPE_CHECKING:
    from ..schemas.system_message import SystemMessagePublic

logger = logging.getLogger(__name__)


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


def notify_task_done(
    *,
    user_id: str | None,
    task_type: str,
    task_name: str,
    status: str = "success",
    detail: str | None = None,
) -> SystemMessage | None:
    """计类任务完成通知（2026-09-30）。

    单独事务：独立开 session 落库 + 推送，与宿主任务状态写入互不影响
    （宿主事务失败回滚时，通知已独立发出——按产品需求「成功失败都发」，
    通知失败也不影响任务本身）。

    status 传 'success' 表示成功；其它值（failed/error/cancelled 等）按失败文案。
    """
    from ..core.database import SessionLocal

    if not user_id:
        return None
    title = f"{task_type}任务{'已完成' if status == 'success' else '未完成'}"
    content = (
        f"「{task_name}」已成功完成。"
        if status == "success"
        else f"「{task_name}」执行{status}。{detail or ''}"
    )
    try:
        db = SessionLocal()
        try:
            message = SystemMessage(
                title=title,
                content=content.strip(),
                message_type="task_done",
                target_user_id=user_id,
            )
            db.add(message)
            db.commit()
            db.refresh(message)
        finally:
            db.close()
    except Exception:  # 通知失败不阻断任务本身
        logger.warning("任务完成通知落库失败: user=%s task=%s", user_id, task_name, exc_info=True)
        return None

    # WebSocket 实时推送（目标用户所有连接）——用独立线程跑 async,
    # 兼容 celery worker 无事件循环的场景；推送失败不影响通知落库。
    def _push() -> None:
        try:
            import asyncio
            import uuid
            from .push_service import publish_to_user
            from ..models.base import utcnow
            from ..schemas.ws import WsEventEnvelope, WsEventMeta

            async def _run() -> None:
                event = WsEventEnvelope(
                    id=f"evt_{uuid.uuid4().hex}",
                    topic="user.messages",
                    name="message.created",
                    timestamp=utcnow(),
                    payload={"message_id": str(message.id), "message_type": message.message_type},
                    meta=WsEventMeta(dedupe_key=f"msg:{message.id}", requires_refetch=["/api/v1/system-messages/me"]),
                )
                await publish_to_user(user_id, event)

            asyncio.run(_run())
        except Exception:
            logger.warning("任务完成通知 WS 推送失败: user=%s", user_id, exc_info=True)

    import threading

    threading.Thread(target=_push, daemon=True).start()
    return message


def list_user_messages(
    db: Session,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    read_status: Literal["read", "unread"] | None = None,
    message_type: SystemMessageType | None = None,
) -> tuple[list[SystemMessage], int, int]:
    """获取用户的系统消息列表"""
    base_conditions = [
        (SystemMessage.target_user_id == user_id) | (SystemMessage.target_user_id.is_(None)),
    ]

    if read_status == "read":
        base_conditions.append(SystemMessage.is_read == True)
    elif read_status == "unread":
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
