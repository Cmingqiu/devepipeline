from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger, set_trace_id
from app.db.session import dispose_engine

# Windows 必须用 selector 事件循环：M2 的 psycopg（LangGraph checkpointer）不支持 Proactor。
# 必须在 uvicorn 建 loop 之前设置，所以放在模块导入期。
if sys.platform == "win32":
    if not isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = get_logger(__name__)


class TraceIdMiddleware(BaseHTTPMiddleware):
    """每个请求一个 trace_id：塞进 contextvar（日志）与响应头，错误体里也带。"""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Trace-Id") or uuid4().hex
        set_trace_id(trace_id)
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("INFO")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            "api_startup",
            extra={
                "app_env": settings.app_env,
                "mariadb": f"{settings.mariadb_host}:{settings.mariadb_port}/{settings.mariadb_database}",
            },
        )
        # 启动兜底：进程内队列随重启丢失，按 checkpoint 把未完成的 run 重新挂上。
        # 依赖不可用时只记日志，不能因此起不来（前端/单测都会用到这个 app）。
        if settings.app_env != "test":
            try:
                from app.services.run_service import requeue_incomplete

                requeued = await requeue_incomplete()
                if requeued:
                    logger.info("runs_requeued", extra={"count": requeued})
            except Exception:
                logger.exception("requeue_incomplete_failed")

        yield

        try:
            from app.db.graph_db import close_checkpointer

            await close_checkpointer()
        except Exception:  # noqa: BLE001
            logger.warning("close_checkpointer_failed")
        await dispose_engine()
        logger.info("api_shutdown")

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )
    app.add_middleware(TraceIdMiddleware)

    register_exception_handlers(app)

    # 探针不带业务前缀，其余全部挂在 /api/v1
    app.include_router(health.router)
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
