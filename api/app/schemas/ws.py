from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class WsTicketResponse(BaseModel):
    ticket: str
    expires_in: int


class WsRejectedTopic(BaseModel):
    topic: str
    reason: str


class WsEventMeta(BaseModel):
    dedupe_key: str | None = None
    requires_refetch: list[str] = Field(default_factory=list)
    priority: Literal["low", "normal", "high"] = "normal"


class WsEventEnvelope(BaseModel):
    id: str
    topic: str
    name: str
    version: int = 1
    timestamp: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: WsEventMeta | None = None
