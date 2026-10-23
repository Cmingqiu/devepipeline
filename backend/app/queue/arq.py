from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

QUEUE_NAME = "devpipeline"
HEALTH_KEY = "devpipeline:health"

_pool: ArqRedis | None = None
_lock = asyncio.Lock()


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is not None:
        return _pool
    async with _lock:
        if _pool is None:
            settings = get_settings()
            _pool = await create_pool(
                RedisSettings.from_dsn(settings.redis_url),
                default_queue_name=QUEUE_NAME,
            )
            logger.info("arq_pool_ready")
        return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def worker_healthy() -> bool:
    """worker 每 health_check_interval 刷新一次带 TTL 的心跳键；键不在 = 没有 worker 在消费。"""
    pool = await get_arq_pool()
    return bool(await pool.exists(HEALTH_KEY))


async def enqueue_run(
    run_id: int,
    *,
    resume_payload: dict | None = None,
    fork_payload: dict | None = None,
    continue_run: bool = False,
    job_id: str,
) -> str | None:
    """入队；job_id 相同视为重复投递，返回 None（不抛异常、也不重复执行）。"""
    pool = await get_arq_pool()
    if resume_payload is not None:
        job = await pool.enqueue_job(
            "resume_pipeline", run_id, resume_payload, _job_id=job_id
        )
    elif fork_payload is not None:
        job = await pool.enqueue_job(
            "fork_pipeline", run_id, fork_payload, _job_id=job_id
        )
    else:
        job = await pool.enqueue_job(
            "run_pipeline", run_id, continue_run, _job_id=job_id
        )
    return job.job_id if job is not None else None
