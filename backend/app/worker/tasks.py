"""arq 任务函数：每个任务一个事件出口（Redis 广播 + MariaDB 落库）。"""

from __future__ import annotations

from typing import Any

from app.services.events import EventLogger
from app.services.run_executor import execute_run


async def run_pipeline(ctx: dict[str, Any], run_id: int, continue_run: bool = False) -> None:
    await execute_run(
        run_id,
        continue_run=continue_run,
        event_logger=EventLogger(run_id, publish=True),
    )


async def resume_pipeline(
    ctx: dict[str, Any], run_id: int, resume_payload: dict[str, Any] | None = None
) -> None:
    await execute_run(
        run_id,
        resume_payload=resume_payload,
        event_logger=EventLogger(run_id, publish=True),
    )


__all__ = ["resume_pipeline", "run_pipeline"]
