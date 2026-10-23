"""arq 任务函数：每个任务一个事件出口（Redis 广播 + MariaDB 落库）。"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.events import EventLogger
from app.services.run_executor import execute_run

logger = get_logger(__name__)


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


async def fork_pipeline(
    ctx: dict[str, Any], run_id: int, fork_payload: dict[str, Any]
) -> None:
    await execute_run(
        run_id,
        fork_payload=fork_payload,
        event_logger=EventLogger(run_id, publish=True),
    )


async def purge_workspaces(ctx: dict[str, Any]) -> None:
    """每日兜底清理：清掉超过保留期的工作区（含失败/取消 run 的目录与孤儿目录）。"""
    from app.services.workspace_service import purge_expired_workspaces

    stats = await purge_expired_workspaces()
    logger.info("workspace_purge_cron", extra=stats)


__all__ = ["fork_pipeline", "purge_workspaces", "resume_pipeline", "run_pipeline"]
