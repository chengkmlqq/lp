import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .core.config import get_settings
from .core.database import SessionLocal, init_db
from .core.exception_handlers import global_exception_handler
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


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.api_name,
        "version": settings.api_version,
    }

app.add_exception_handler(Exception, global_exception_handler)

app.include_router(api_router)
