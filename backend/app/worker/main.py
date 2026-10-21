"""arq worker 入口：`conda run -n devpipeline arq app.worker.main.WorkerSettings`。"""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.graph_db import close_checkpointer, get_checkpointer
from app.db.session import dispose_engine
from app.services.events import close_redis
from app.worker.tasks import resume_pipeline, run_pipeline

logger = get_logger(__name__)


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging("INFO")
    # 提前建好 checkpointer（setup 建表），避免第一个任务才付初始化成本
    await get_checkpointer()
    logger.info("worker_startup")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    await close_redis()
    await close_checkpointer()
    await dispose_engine()
    logger.info("worker_shutdown")


class WorkerSettings:
    functions: ClassVar[list] = [run_pipeline, resume_pipeline]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    queue_name = "devpipeline"
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 2
    job_timeout = 3600
    keep_result = 600
    max_tries = 1
