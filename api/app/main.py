import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.router import api_router
from .core.config import get_settings
from .core.database import SessionLocal, init_db
from .core.exception_handlers import global_exception_handler, localized_http_exception_handler
from .services.backend_lang import BackendLangMiddleware
from .services.ws_event_bridge import ws_event_forwarder
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    # 后台转发 Celery 任务经 Redis Stream 投递的 WS 事件到各 topic 订阅者。
    forwarder_task = asyncio.create_task(ws_event_forwarder())
    try:
        yield
    finally:
        forwarder_task.cancel()
        try:
            await forwarder_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.api_name,
    version=settings.api_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 每个 HTTP 请求的 X-Lang 写入上下文变量 → 任务发布时注入 Celery 消息头 →
# worker 在任务启动时快照语言（LP-22 后端日志/报告按发起者语言输出）。
app.add_middleware(BackendLangMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.api_name,
        "version": settings.api_version,
    }

app.add_exception_handler(Exception, global_exception_handler)
# HTTPException detail 按请求语言翻译（LP-148）；zh 逐字不变。
app.add_exception_handler(StarletteHTTPException, localized_http_exception_handler)

app.include_router(api_router)
