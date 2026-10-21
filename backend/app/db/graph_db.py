"""LangGraph checkpointer：PostgreSQL + psycopg 连接池。

为什么用连接池而不是 pipeline 模式：
`AsyncPostgresSaver.__init__` 对 `AsyncConnectionPool + pipe` 会直接 raise
（`Pipeline should be used only with a single AsyncConnection`）。连接池换来断线自动重连与
并发安全，代价是每次 checkpoint 多几次往返（远程 VPS 上约几十毫秒，可接受）。

注意：`get_checkpointer()` 可能被启动兜底与执行器同时调用（实测会建出两个池并泄漏 worker 任务），
所以必须加锁做单例初始化。
"""

from __future__ import annotations

import asyncio

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_pool: AsyncConnectionPool | None = None
_saver = None
_lock = asyncio.Lock()


async def get_checkpointer():
    """进程内单例 AsyncPostgresSaver；首次调用时建池并执行 setup()（建 checkpoint 表）。"""
    global _pool, _saver
    if _saver is not None:
        return _saver

    async with _lock:
        if _saver is not None:
            return _saver

        # 延迟导入，避免仅跑 M1 测试时也加载 langgraph
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        settings = get_settings()
        pool = AsyncConnectionPool(
            conninfo=settings.postgres_dsn,
            open=False,
            min_size=1,
            max_size=settings.postgres_pool_size,
            timeout=settings.postgres_connect_timeout,
            # saver 需要 dict row + autocommit + prepare_threshold=0（与 from_conn_string 一致）
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        )
        try:
            await pool.open()
            await pool.wait(timeout=settings.postgres_connect_timeout)
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
        except Exception:
            await pool.close()
            raise

        _pool, _saver = pool, saver
        logger.info("checkpointer_ready", extra={"db": settings.postgres_db})
        return _saver


async def close_checkpointer() -> None:
    global _pool, _saver
    async with _lock:
        if _pool is not None:
            await _pool.close()
        _pool = None
        _saver = None
