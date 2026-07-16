from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.dependencies import CurrentUser, get_current_user
from ...services.legacy_authz_service import get_user_authorization, is_user_enabled
from ...services.topic_registry import get_auto_topics, validate_topic_subscription
from ...services.user_service import get_user_by_id
from ...services.ws_manager import ws_connection_manager
from ...services.ws_ticket_service import ws_ticket_service
from ...schemas.ws import WsTicketResponse

router = APIRouter(prefix="/ws", tags=["ws"])


@router.post("/ticket", response_model=WsTicketResponse)
def create_ws_ticket(
    current_user: CurrentUser = Depends(get_current_user),
) -> WsTicketResponse:
    ticket, expires_in = ws_ticket_service.issue(current_user.user.id)
    return WsTicketResponse(ticket=ticket, expires_in=expires_in)


@router.websocket("")
async def websocket_endpoint(websocket: WebSocket, db: Session = Depends(get_db)) -> None:
    ticket = websocket.query_params.get("ticket")
    user_id = ws_ticket_service.consume(ticket)
    if not user_id:
        await websocket.close(code=4401, reason="invalid_ws_ticket")
        return

    user = get_user_by_id(db, user_id)
    if not user or not is_user_enabled(user.status):
        await websocket.close(code=4403, reason="user_not_allowed")
        return

    authz = get_user_authorization(db, user.id)
    role_codes = authz.role_codes
    permission_codes = authz.permission_codes

    await websocket.accept()
    connection = await ws_connection_manager.register(
        websocket,
        user_id=user.id,
        role_codes=role_codes,
        permission_codes=permission_codes,
    )

    await websocket.send_json(
        {
            "type": "ready",
            "connection_id": connection.connection_id,
            "user_id": user.id,
            "auto_topics": sorted(get_auto_topics()),
        }
    )

    try:
        while True:
            message = await websocket.receive_json()
            message_type = message.get("type")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if message_type == "subscribe":
                topics = [topic for topic in message.get("topics", []) if isinstance(topic, str)]
                accepted: list[str] = []
                rejected: list[dict[str, str]] = []
                for topic in topics:
                    is_allowed, reason = validate_topic_subscription(
                        topic,
                        role_codes=connection.role_codes,
                        permission_codes=connection.permission_codes,
                    )
                    if is_allowed:
                        accepted.append(topic)
                    else:
                        rejected.append({"topic": topic, "reason": reason or "forbidden"})
                accepted = await ws_connection_manager.subscribe(connection.connection_id, accepted)
                await websocket.send_json(
                    {
                        "type": "subscribed",
                        "topics": accepted,
                        "rejected": rejected,
                    }
                )
                continue

            if message_type == "unsubscribe":
                topics = [topic for topic in message.get("topics", []) if isinstance(topic, str)]
                removed = await ws_connection_manager.unsubscribe(connection.connection_id, topics)
                await websocket.send_json({"type": "unsubscribed", "topics": removed})
                continue

            await websocket.send_json(
                {
                    "type": "error",
                    "code": "unsupported_message_type",
                    "message": "Unsupported ws message type",
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        await ws_connection_manager.unregister(connection.connection_id)
