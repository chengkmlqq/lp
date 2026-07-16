from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, get_current_user, require_enabled_menu_route, require_permission
from ...schemas.auth import MessageResponse
from ...schemas.system_message import (
    SystemMessageCreateRequest,
    SystemMessageListResponse,
    SystemMessageMarkReadRequest,
    SystemMessagePublic,
    SystemMessageType,
)
from ...services.system_message_service import (
    create_system_message,
    delete_system_message,
    get_unread_count,
    list_user_messages,
    mark_messages_as_read,
)

router = APIRouter(prefix="/system-messages", tags=["system_messages"])


@router.post(
    "",
    response_model=SystemMessagePublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_enabled_menu_route)],
)
def create_message(
    payload: SystemMessageCreateRequest,
    _: CurrentUser = Depends(require_permission("admin.system_message")),
    db: Session = Depends(get_db),
) -> SystemMessagePublic:
    """创建系统消息（需要admin.system_message权限）"""
    message = create_system_message(db, payload)
    return SystemMessagePublic.model_validate(message)


@router.get("/me", response_model=SystemMessageListResponse)
def get_my_messages(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    unread_only: bool = Query(default=False),
    message_type: SystemMessageType | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SystemMessageListResponse:
    """获取当前用户的系统消息"""
    messages, total, unread_count = list_user_messages(
        db,
        user_id=current_user.user.id,
        limit=limit,
        offset=offset,
        unread_only=unread_only,
        message_type=message_type,
    )
    return SystemMessageListResponse(
        items=[SystemMessagePublic.model_validate(m) for m in messages],
        total=total,
        unread_count=unread_count,
    )


@router.get("/me/unread-count")
def get_my_unread_count(
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """获取当前用户未读消息数量"""
    count = get_unread_count(db, current_user.user.id)
    return {"unread_count": count}


@router.post("/me/mark-read")
def mark_my_messages_read(
    payload: SystemMessageMarkReadRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """标记消息为已读"""
    affected = mark_messages_as_read(db, current_user.user.id, payload.message_ids)
    return {"affected": affected}


@router.delete("/{message_id}", response_model=MessageResponse, dependencies=[Depends(require_enabled_menu_route)])
def remove_system_message(
    message_id: str,
    _: CurrentUser = Depends(require_permission("admin.system_message")),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """删除系统消息（需要admin.system_message权限）"""
    deleted = delete_system_message(db, message_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System message not found")
    return MessageResponse(message="System message deleted")
