from __future__ import annotations

from collections.abc import Generator, Iterator
import json
import os
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models.ai_chat import AiChatConversation, AiChatMessage
from ..schemas.ai_chat import (
    AiChatConversationCreateRequest,
    AiChatConversationDetail,
    AiChatConversationListResponse,
    AiChatConversationSummary,
    AiChatConversationUpdateRequest,
    AiChatMessageSummary,
)
from ..services.system_param_service import get_system_param_by_key
from .user_service import serialize_user


def serialize_message(msg: AiChatMessage) -> AiChatMessageSummary:
    return AiChatMessageSummary(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        tool_calls=msg.tool_calls,
        tool_call_id=msg.tool_call_id,
        created_at=msg.created_at,
    )


def serialize_conversation(conv: AiChatConversation, message_count: int = 0) -> AiChatConversationSummary:
    return AiChatConversationSummary(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        user=serialize_user(conv.user) if conv.user else None,
        message_count=message_count,
    )


def serialize_conversation_detail(conv: AiChatConversation) -> AiChatConversationDetail:
    messages = sorted(conv.messages, key=lambda m: m.created_at)
    return AiChatConversationDetail(
        id=conv.id,
        title=conv.title,
        user_id=conv.user_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        user=serialize_user(conv.user) if conv.user else None,
        messages=[serialize_message(msg) for msg in messages],
    )


def list_conversations(
    db: Session,
    *,
    user_id: str,
    limit: int,
    offset: int,
) -> AiChatConversationListResponse:
    stmt = (
        select(AiChatConversation)
        .options(selectinload(AiChatConversation.user))
        .where(AiChatConversation.user_id == user_id)
    )

    total_stmt = select(func.count()).select_from(AiChatConversation).where(AiChatConversation.user_id == user_id)

    total = db.scalar(total_stmt) or 0
    items = (
        db.execute(
            stmt.order_by(AiChatConversation.updated_at.desc(), AiChatConversation.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    result_items = []
    for item in items:
        msg_count = db.scalar(
            select(func.count()).select_from(AiChatMessage).where(AiChatMessage.conversation_id == item.id)
        ) or 0
        result_items.append(serialize_conversation(item, message_count=msg_count))

    return AiChatConversationListResponse(items=result_items, total=total)


def get_conversation_by_id(db: Session, conversation_id: int, user_id: str) -> AiChatConversation | None:
    return db.execute(
        select(AiChatConversation)
        .options(
            selectinload(AiChatConversation.user),
            selectinload(AiChatConversation.messages),
        )
        .where(AiChatConversation.id == conversation_id, AiChatConversation.user_id == user_id)
    ).scalar_one_or_none()


def create_conversation(
    db: Session,
    payload: AiChatConversationCreateRequest,
    *,
    user_id: str,
) -> AiChatConversationSummary:
    conv = AiChatConversation(
        title=payload.title.strip(),
        user_id=user_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return serialize_conversation(conv, message_count=0)


def update_conversation(
    db: Session,
    conversation_id: int,
    payload: AiChatConversationUpdateRequest,
    *,
    user_id: str,
) -> AiChatConversationSummary | None:
    conv = get_conversation_by_id(db, conversation_id, user_id)
    if not conv:
        return None

    conv.title = payload.title.strip()
    db.commit()

    msg_count = db.scalar(
        select(func.count()).select_from(AiChatMessage).where(AiChatMessage.conversation_id == conv.id)
    ) or 0

    return serialize_conversation(conv, message_count=msg_count)


def delete_conversation(db: Session, conversation_id: int, *, user_id: str) -> bool:
    conv = get_conversation_by_id(db, conversation_id, user_id)
    if not conv:
        return False

    db.delete(conv)
    db.commit()
    return True


def send_message(
    db: Session,
    conversation_id: int,
    content: str,
    *,
    user_id: str,
) -> tuple[AiChatMessageSummary, AiChatMessageSummary] | None:
    conv = get_conversation_by_id(db, conversation_id, user_id)
    if not conv:
        return None

    user_message = AiChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=content.strip(),
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    history = sorted(conv.messages, key=lambda m: m.created_at)
    history.append(user_message)

    try:
        response_data = _call_openai_api(db, history)
        choice = response_data["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason")

        if finish_reason == "tool_calls" and message.get("tool_calls"):
            assistant_message_with_tool_calls = AiChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=message.get("content") or "",
                tool_calls=message["tool_calls"],
            )
            db.add(assistant_message_with_tool_calls)
            db.commit()
            db.refresh(assistant_message_with_tool_calls)
            history.append(assistant_message_with_tool_calls)

            for tool_call in message["tool_calls"]:
                function_name = tool_call["function"]["name"]
                function_args_str = tool_call["function"]["arguments"]
                tool_call_id = tool_call["id"]

                try:
                    function_args = json.loads(function_args_str)
                except json.JSONDecodeError:
                    function_args = {}

                function_result = _execute_function(db, function_name, function_args)

                tool_message = AiChatMessage(
                    conversation_id=conversation_id,
                    role="tool",
                    content=function_result,
                    tool_call_id=tool_call_id,
                )
                db.add(tool_message)
                db.commit()
                db.refresh(tool_message)
                history.append(tool_message)

            final_response_data = _call_openai_api(db, history)
            final_message = final_response_data["choices"][0]["message"]
            reply_content = final_message.get("content", "")

            assistant_message = AiChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=reply_content,
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            return serialize_message(user_message), serialize_message(assistant_message)

        else:
            reply_content = message.get("content", "")
            assistant_message = AiChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=reply_content,
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            return serialize_message(user_message), serialize_message(assistant_message)

    except Exception as e:
        reply_content = f"抱歉，AI服务暂时不可用：{str(e)}"
        assistant_message = AiChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content=reply_content,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        return serialize_message(user_message), serialize_message(assistant_message)


def stream_message(
    db: Session,
    conversation_id: int,
    content: str,
    *,
    user_id: str,
) -> Iterator[dict[str, Any]] | None:
    conv = get_conversation_by_id(db, conversation_id, user_id)
    if not conv:
        return None

    user_message = AiChatMessage(
        conversation_id=conversation_id,
        role="user",
        content=content.strip(),
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    history = sorted(conv.messages, key=lambda m: m.created_at)
    history.append(user_message)

    def event_stream() -> Iterator[dict[str, Any]]:
        yield {"type": "message", "message": serialize_message(user_message).model_dump(mode="json")}

        try:
            reply_content = yield from _stream_assistant_reply(db, conversation_id, history)
            assistant_message = AiChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=reply_content,
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            yield {"type": "done", "reply": serialize_message(assistant_message).model_dump(mode="json")}
        except Exception as e:
            reply_content = f"抱歉，AI服务暂时不可用：{str(e)}"
            assistant_message = AiChatMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=reply_content,
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)

            yield {"type": "delta", "content": reply_content}
            yield {"type": "done", "reply": serialize_message(assistant_message).model_dump(mode="json")}

    return event_stream()


def _get_function_definitions() -> list[dict[str, Any]]:
    """Define available functions that the AI can call."""
    return [
        {
            "type": "function",
            "function": {
                "name": "query_tower_models",
                "description": "查询杆塔型号列表。可以根据关键字搜索杆塔型号名称。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键字，用于匹配杆塔型号名称",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "是否只查询启用的杆塔型号",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回结果数量限制，默认10",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_lines",
                "description": "查询线路列表。可以根据关键字搜索线路名称。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键字，用于匹配线路名称",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回结果数量限制，默认10",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_users",
                "description": "查询系统用户列表。可以根据关键字搜索用户名称或邮箱。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键字，用于匹配用户名称或邮箱",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回结果数量限制，默认10",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_system_params",
                "description": "查询系统参数配置。可以根据参数键或名称搜索。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键字，用于匹配参数键或名称",
                        },
                        "category": {
                            "type": "string",
                            "description": "参数分类",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回结果数量限制，默认10",
                            "default": 10,
                        },
                    },
                    "required": [],
                },
            },
        },
    ]


def _execute_function(db: Session, function_name: str, arguments: dict[str, Any]) -> str:
    """Execute a function call and return the result as a string."""
    try:
        if function_name == "query_tower_models":
            from ..services.tower_model_service import list_tower_models

            keyword = arguments.get("keyword")
            enabled = arguments.get("enabled")
            limit = arguments.get("limit", 10)

            result = list_tower_models(
                db,
                limit=limit,
                offset=0,
                keyword=keyword,
                enabled=enabled,
            )

            if not result.items:
                return "未找到匹配的杆塔型号。"

            items_text = []
            for item in result.items:
                items_text.append(
                    f"- 型号: {item.name}, "
                    f"高度: {item.height}m, "
                    f"状态: {'启用' if item.enabled else '禁用'}"
                )

            return f"找到 {result.total} 个杆塔型号（显示前{len(result.items)}个）:\n" + "\n".join(items_text)

        elif function_name == "query_lines":
            from ..services.line_service import list_lines

            keyword = arguments.get("keyword")
            limit = arguments.get("limit", 10)

            result = list_lines(
                db,
                limit=limit,
                offset=0,
                keyword=keyword,
            )

            if not result.items:
                return "未找到匹配的线路。"

            items_text = []
            for item in result.items:
                items_text.append(
                    f"- 线路: {item.name}, "
                    f"电压等级: {item.voltage_level or '未设置'}, "
                    f"长度: {item.length or '未设置'}km"
                )

            return f"找到 {result.total} 条线路（显示前{len(result.items)}个）:\n" + "\n".join(items_text)

        elif function_name == "query_users":
            from ..services.user_service import list_users

            keyword = arguments.get("keyword")
            limit = arguments.get("limit", 10)

            result = list_users(
                db,
                limit=limit,
                offset=0,
                keyword=keyword,
            )

            if not result.items:
                return "未找到匹配的用户。"

            items_text = []
            for item in result.items:
                items_text.append(
                    f"- 用户ID: {item.id}, "
                    f"用户名: {item.username}, "
                    f"邮箱: {item.email or '未设置'}"
                )

            return f"找到 {result.total} 个用户（显示前{len(result.items)}个）:\n" + "\n".join(items_text)

        elif function_name == "query_system_params":
            from ..services.system_param_service import list_system_params

            keyword = arguments.get("keyword")
            category = arguments.get("category")
            limit = arguments.get("limit", 10)

            result = list_system_params(
                db,
                limit=limit,
                offset=0,
                keyword=keyword,
                category=category,
            )

            if not result.items:
                return "未找到匹配的系统参数。"

            items_text = []
            for item in result.items:
                items_text.append(
                    f"- 参数键: {item.param_key}, "
                    f"名称: {item.param_name}, "
                    f"值: {item.param_value or '未设置'}, "
                    f"状态: {item.status}"
                )

            return f"找到 {result.total} 个系统参数（显示前{len(result.items)}个）:\n" + "\n".join(items_text)

        else:
            return f"未知的函数: {function_name}"

    except Exception as e:
        return f"执行函数 {function_name} 时出错: {str(e)}"


def _build_openai_chat_request(
    db: Session,
    history: list[AiChatMessage],
    *,
    stream: bool = False,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    api_key_param = get_system_param_by_key(db, "ai_chat.openai_api_key")
    model_param = get_system_param_by_key(db, "ai_chat.model")
    base_url_param = get_system_param_by_key(db, "ai_chat.base_url")

    api_key = api_key_param.param_value if api_key_param and api_key_param.status == "enabled" else None
    model = model_param.param_value if model_param and model_param.status == "enabled" else "gpt-3.5-turbo"
    base_url = base_url_param.param_value if base_url_param and base_url_param.status == "enabled" else "https://api.openai.com/v1"

    if not api_key:
        api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise ValueError("AI模型配置缺失：请在系统参数中配置 ai_chat.openai_api_key")

    messages = []
    for msg in history:
        msg_dict: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
        if msg.tool_calls:
            msg_dict["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            msg_dict["tool_call_id"] = msg.tool_call_id
        messages.append(msg_dict)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": _get_function_definitions(),
    }
    if stream:
        payload["stream"] = True

    return f"{base_url}/chat/completions", headers, payload


def _call_openai_api(db: Session, history: list[AiChatMessage]) -> dict[str, Any]:
    url, headers, payload = _build_openai_chat_request(db, history)

    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            url,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    return data


def _stream_openai_api(db: Session, history: list[AiChatMessage]) -> Iterator[dict[str, Any]]:
    url, headers, payload = _build_openai_chat_request(db, history, stream=True)

    with httpx.Client(timeout=60.0) as client:
        with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                line = line.strip()
                if line.startswith(":"):
                    continue
                if line.startswith("data:"):
                    line = line.removeprefix("data:").strip()
                if not line or line == "[DONE]":
                    continue
                yield json.loads(line)


def _stream_assistant_reply(
    db: Session,
    conversation_id: int,
    history: list[AiChatMessage],
) -> Generator[dict[str, Any], None, str]:
    reply_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    finish_reason = yield from _consume_completion_stream(db, history, reply_parts, tool_calls)
    normalized_tool_calls = _normalize_tool_calls(tool_calls)
    if finish_reason == "tool_calls" and normalized_tool_calls:
        assistant_message_with_tool_calls = AiChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content="".join(reply_parts),
            tool_calls=normalized_tool_calls,
        )
        db.add(assistant_message_with_tool_calls)
        db.commit()
        db.refresh(assistant_message_with_tool_calls)
        history.append(assistant_message_with_tool_calls)

        for tool_call in normalized_tool_calls:
            function_name = tool_call["function"]["name"]
            function_args_str = tool_call["function"].get("arguments") or "{}"
            tool_call_id = tool_call["id"]

            try:
                function_args = json.loads(function_args_str)
            except json.JSONDecodeError:
                function_args = {}

            function_result = _execute_function(db, function_name, function_args)
            tool_message = AiChatMessage(
                conversation_id=conversation_id,
                role="tool",
                content=function_result,
                tool_call_id=tool_call_id,
            )
            db.add(tool_message)
            db.commit()
            db.refresh(tool_message)
            history.append(tool_message)

        reply_parts = []
        yield from _consume_completion_stream(db, history, reply_parts, [])

    return "".join(reply_parts)


def _consume_completion_stream(
    db: Session,
    history: list[AiChatMessage],
    reply_parts: list[str],
    tool_calls: list[dict[str, Any]],
) -> Generator[dict[str, Any], None, str | None]:
    finish_reason: str | None = None
    for chunk in _stream_openai_api(db, history):
        choices = chunk.get("choices") or []
        if not choices:
            continue

        choice = choices[0]
        finish_reason = choice.get("finish_reason") or finish_reason
        delta = choice.get("delta") or {}

        content_delta = delta.get("content")
        if content_delta:
            reply_parts.append(content_delta)
            yield {"type": "delta", "content": content_delta}

        for tool_call_delta in delta.get("tool_calls") or []:
            _merge_tool_call_delta(tool_calls, tool_call_delta)

    return finish_reason


def _merge_tool_call_delta(tool_calls: list[dict[str, Any]], delta: dict[str, Any]) -> None:
    index = delta.get("index")
    if not isinstance(index, int):
        index = len(tool_calls)

    while len(tool_calls) <= index:
        tool_calls.append(
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        )

    tool_call = tool_calls[index]
    if delta.get("id"):
        tool_call["id"] = delta["id"]
    if delta.get("type"):
        tool_call["type"] = delta["type"]

    function_delta = delta.get("function") or {}
    function = tool_call.setdefault("function", {"name": "", "arguments": ""})
    if function_delta.get("name"):
        function["name"] = f"{function.get('name', '')}{function_delta['name']}"
    if function_delta.get("arguments"):
        function["arguments"] = f"{function.get('arguments', '')}{function_delta['arguments']}"


def _normalize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        function = tool_call.get("function") or {}
        function_name = function.get("name")
        if not function_name:
            continue
        normalized.append(
            {
                "id": tool_call.get("id") or f"tool_call_{index}",
                "type": tool_call.get("type") or "function",
                "function": {
                    "name": function_name,
                    "arguments": function.get("arguments") or "{}",
                },
            }
        )
    return normalized
