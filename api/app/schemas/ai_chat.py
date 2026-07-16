from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .user import UserPublic


class AiChatMessageSummary(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    tool_calls: dict | None = None
    tool_call_id: str | None = None
    created_at: datetime


class AiChatConversationSummary(BaseModel):
    id: int
    title: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    user: UserPublic | None = None
    message_count: int = 0


class AiChatConversationDetail(BaseModel):
    id: int
    title: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    user: UserPublic | None = None
    messages: list[AiChatMessageSummary] = []


class AiChatConversationListResponse(BaseModel):
    items: list[AiChatConversationSummary]
    total: int


class AiChatConversationCreateRequest(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=256)


class AiChatConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=256)


class AiChatMessageSendRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class AiChatMessageResponse(BaseModel):
    message: AiChatMessageSummary
    reply: AiChatMessageSummary
