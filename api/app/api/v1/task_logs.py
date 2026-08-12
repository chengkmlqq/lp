from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.database import get_db
from ...core.dependencies import (
    CurrentUser,
    require_any_permission,
    require_enabled_menu_route,
)
from ...schemas.task_log import TaskLogResponse, TaskLogUploadRequest, TaskLogUploadResponse
from ...services.legacy_authz_service import get_user_authorization, is_user_enabled
from ...services.task_log_service import (
    TaskLogNotFoundError,
    TaskLogServiceError,
    get_task_log,
    get_task_state_and_log_path,
    list_task_logs,
    read_task_log_messages,
    upload_task_log,
)
from ...services.user_service import get_user_by_id
from ...services.ws_ticket_service import ws_ticket_service

router = APIRouter(prefix="/admin/task-logs", tags=["admin-task-logs"], dependencies=[Depends(require_enabled_menu_route)])

# SSE 端点使用 EventSource（无法携带 Authorization header），必须脱离 router 级
# require_enabled_menu_route（内部强制 get_current_user）依赖，否则任何请求都会在
# 进入端点前被 401 Not authenticated 拦截。ticket + 用户权限校验在端点内完成。
sse_router = APIRouter(prefix="/admin/task-logs", tags=["admin-task-logs"])


@router.post("/upload", response_model=TaskLogUploadResponse)
def upload_log(
    request: TaskLogUploadRequest,
    _: CurrentUser = Depends(require_any_permission("celery.manage")),
) -> TaskLogUploadResponse:
    """
    Upload task execution log to MinIO storage.
    Logs are stored in the fixed path: logs/{task_id}.log
    """
    try:
        log_path, uploaded_at = upload_task_log(request.task_id, request.log_content)
        return TaskLogUploadResponse(
            task_id=request.task_id,
            log_path=log_path,
            uploaded_at=uploaded_at,
        )
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}", response_model=TaskLogResponse)
def get_log(
    task_id: str,
    log_date: datetime | None = Query(default=None, description="Date of the log (legacy fallback)"),
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> TaskLogResponse:
    """
    Retrieve task execution log from MinIO.
    Prefers the log_path persisted on celery_task_history.log_path; falls back to
    the fixed path logs/{task_id}.log, then the legacy date-based path.
    """
    _, persisted_log_path = get_task_state_and_log_path(task_id)
    try:
        log_content, log_path = get_task_log(
            task_id,
            log_date=log_date,
            log_path=persisted_log_path,
        )
        return TaskLogResponse(
            task_id=task_id,
            log_content=log_content,
            log_path=log_path,
            exists=True,
        )
    except TaskLogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{task_id}/list", response_model=list[str])
def list_logs(
    task_id: str,
    _: CurrentUser = Depends(require_any_permission("celery.read", "celery.manage")),
) -> list[str]:
    """
    List all available logs for a task across all dates.
    Returns list of log paths, sorted by most recent first.
    """
    try:
        return list_task_logs(task_id)
    except TaskLogServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@sse_router.get("/{task_id}/sse")
async def stream_log(
    task_id: str,
    request: Request,
    ticket: str = Query(...),
    last_event_id: str | None = Query(default=None, description="Front-end rebuilt connection resume cursor"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    SSE 流式读取任务执行日志（实时 + 断线补偿）。

    认证：复用一次性 ws ticket（EventSource 无法自定义 Authorization header）。
    权限：celery.read / celery.manage。

    断线续读游标：EventSource 原生自动重连会带 ``Last-Event-ID`` request header；
    前端重建连接（LP-295 换新 ticket）无法复用该 header，因此在 URL 上显式携带
    ``lastEventId`` 查询参数。该参数优先于 header，兼容两种来源。
    协议：
      - 日志行：`id: <stream-id>` + `data: {"line": "..."}`（id 即重连游标）
      - 结束：`event: done`
      - 心跳：每 15 秒 `: ping`
    """
    user_id = ws_ticket_service.consume(ticket)
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid_ws_ticket")

    user = get_user_by_id(db, user_id)
    if not user or not is_user_enabled(user.status):
        raise HTTPException(status_code=403, detail="user_not_allowed")

    authz = get_user_authorization(db, user.id)
    permission_codes = authz.permission_codes
    if "admin" not in authz.role_codes and not (
        "celery.read" in permission_codes or "celery.manage" in permission_codes
    ):
        raise HTTPException(status_code=403, detail="missing_permission")

    settings = get_settings()
    heartbeat_seconds = settings.task_log_sse_heartbeat_seconds

    state, persisted_log_path = get_task_state_and_log_path(task_id)
    # 任务已结束：直接推全量（优先 log_path / 固定路径），然后 done
    finished = state in ("SUCCESS", "FAILURE", "REVOKED", "REJECTED")

    headers = {
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
        "Content-Type": "text/event-stream",
        "Connection": "keep-alive",
    }

    async def event_generator():
        if finished:
            try:
                log_content, _path = get_task_log(task_id, log_path=persisted_log_path)
            except (TaskLogNotFoundError, TaskLogServiceError):
                # 任务已完成但日志未持久化（MinIO 不可用）
                yield f"event: error\ndata: {json.dumps({'message': '任务已完成，但日志未持久化（MinIO 不可用）'})}\n\n"
                yield "event: done\ndata: {}\n\n"
                return
            yield f"data: {json.dumps({'lines': log_content})}\n\n"
            yield "event: done\ndata: {}\n\n"
            return

        # 运行中：XREAD 增量续读
        #   初始 last_id="0"：从流开头读，把任务开始以来已 flush 的日志一次性补上，
        #     再进入实时续读（比 "$" 只收新消息体验好，弹窗打开即可看到已滚动日志）。
        #   断线重连（含前端重建连接）：优先取前端显式传回的 last_event_id 查询参数，
        #     否则回落到 EventSource 自动携带的 Last-Event-ID header，据此续读，断线日志一条不丢。
        last_id = last_event_id or request.headers.get("last-event-id") or "0"
        while True:
            if await request.is_disconnected():
                return
            messages = read_task_log_messages(task_id, last_id=last_id, block_ms=1000)
            for msg in messages:
                last_id = msg["id"]
                if msg["field"] == "__end__":
                    # 收到结束标记，再等一轮把末尾行也读出来
                    continue
                if msg["line"] is None:
                    continue
                yield f"id: {last_id}\ndata: {json.dumps({'line': msg['line']})}\n\n"
            # 检查一次最终状态：若刚结束则补推全量 + done
            current_state, current_path = get_task_state_and_log_path(task_id)
            if current_state in ("SUCCESS", "FAILURE", "REVOKED", "REJECTED"):
                try:
                    log_content, _path = get_task_log(task_id, log_path=current_path)
                except (TaskLogNotFoundError, TaskLogServiceError):
                    log_content = ""
                yield f"data: {json.dumps({'lines': log_content})}\n\n"
                yield "event: done\ndata: {}\n\n"
                return
            yield f": ping\n\n"
            await asyncio.sleep(heartbeat_seconds)

    return StreamingResponse(event_generator(), headers=headers)
