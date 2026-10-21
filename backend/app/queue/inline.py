"""进程内后台任务队列（M2）。

M3 会换成 arq + Redis；调用方只依赖 `submit()`，换实现不动业务代码。
限制（已知）：任务随进程重启丢失 —— 由启动时的 reconciler 依据 checkpoint 续跑兜底。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable

from app.core.logging import get_logger

logger = get_logger(__name__)

_tasks: set[asyncio.Task] = set()


def submit(coro: Awaitable[None], *, name: str) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)

    def _on_done(finished: asyncio.Task) -> None:
        _tasks.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            logger.exception("background_task_failed", extra={"task": name})

    task.add_done_callback(_on_done)
    return task


async def join() -> None:
    """测试用：等当前所有后台任务结束（执行器内部已兜住异常，不会往外抛）。"""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def running_count() -> int:
    return len(_tasks)
