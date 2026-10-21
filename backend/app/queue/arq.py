from __future__ import annotations

import asyncio

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

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
                default_queue_name="devpipeline",
            )
            logger.info("arq_pool_ready")
        return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def enqueue_run(
    run_id: int, *, resume_payload: dict | None = None, continue_run: bool = False
) -> str:
    """把一次执行/恢复丢给 arq worker，返回 job id。"""
    pool = await get_arq_pool()
    if resume_payload is not None:
        job = await pool.enqueue_job("resume_pipeline", run_id, resume_payload)
    else:
        job = await pool.enqueue_job("run_pipeline", run_id, continue_run)
    if job is None:
        raise RuntimeError(f"arq 拒绝入队 run={run_id}（job id 冲突）")
    return job.job_id
