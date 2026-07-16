import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, get_current_user, require_enabled_menu_route
from ...schemas.ai_chat import (
    AiChatConversationCreateRequest,
    AiChatConversationDetail,
    AiChatConversationListResponse,
    AiChatConversationSummary,
    AiChatConversationUpdateRequest,
    AiChatMessageResponse,
    AiChatMessageSendRequest,
)
from ...services.ai_chat_service import (
    create_conversation,
    delete_conversation,
    get_conversation_by_id,
    list_conversations,
    send_message,
    serialize_conversation_detail,
    stream_message,
    update_conversation,
)

router = APIRouter(
    prefix="/ai-chat",
    tags=["ai-chat"],
    dependencies=[Depends(require_enabled_menu_route)],
)


@router.get("/conversations", response_model=AiChatConversationListResponse)
def get_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiChatConversationListResponse:
    return list_conversations(db, user_id=current_user.user.id, limit=limit, offset=offset)


@router.post("/conversations", response_model=AiChatConversationSummary)
def create_conversation_endpoint(
    payload: AiChatConversationCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiChatConversationSummary:
    return create_conversation(db, payload, user_id=current_user.user.id)


@router.get("/conversations/{conversation_id}", response_model=AiChatConversationDetail)
def get_conversation_detail(
    conversation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiChatConversationDetail:
    conv = get_conversation_by_id(db, conversation_id, user_id=current_user.user.id)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return serialize_conversation_detail(conv)


@router.patch("/conversations/{conversation_id}", response_model=AiChatConversationSummary)
def update_conversation_endpoint(
    conversation_id: int,
    payload: AiChatConversationUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiChatConversationSummary:
    updated = update_conversation(db, conversation_id, payload, user_id=current_user.user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return updated


@router.delete("/conversations/{conversation_id}")
def delete_conversation_endpoint(
    conversation_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    deleted = delete_conversation(db, conversation_id, user_id=current_user.user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"success": True}


def _encode_stream_events(events: Iterator[dict]) -> Iterator[str]:
    for event in events:
        yield json.dumps(event, ensure_ascii=False, default=str) + "\n"


@router.post("/conversations/{conversation_id}/messages")
def send_message_endpoint(
    conversation_id: int,
    payload: AiChatMessageSendRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    events = stream_message(db, conversation_id, payload.content, user_id=current_user.user.id)
    if events is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return StreamingResponse(
        _encode_stream_events(events),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/conversations/{conversation_id}/messages/sync", response_model=AiChatMessageResponse)
def send_message_sync_endpoint(
    conversation_id: int,
    payload: AiChatMessageSendRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiChatMessageResponse:
    result = send_message(db, conversation_id, payload.content, user_id=current_user.user.id)
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    user_msg, assistant_msg = result
    return AiChatMessageResponse(message=user_msg, reply=assistant_msg)
