"""沙箱工作区清理：成功即清、失败留查、超期兜底。

为什么不在节点里删：目录会被后续 resume 复用（waiting_approval 阶段还在用），
只有 run 到终态且确定不再执行时删除才安全。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.base import utcnow
from app.db.session import get_session_factory
from app.models import CodeWorkspace, PipelineRun
from app.sandbox.worktree import workspaces_root

logger = get_logger(__name__)

TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
SECONDS_PER_DAY = 86400


def _norm(path: str | Path) -> str:
    """Windows 路径大小写/斜杠不敏感，比较前统一。"""
    return os.path.normcase(str(Path(path).resolve()))


def _under_root(path: str | Path) -> bool:
    """只允许删 workspaces 根目录下的路径；DB 被改坏时也不能变成任意删文件。"""
    root = workspaces_root().resolve()
    target = Path(path).resolve()
    return target != root and root in target.parents


def _remove_dir(path: Path) -> tuple[bool, str | None]:
    try:
        if path.exists():
            shutil.rmtree(path)
        return True, None
    except OSError as exc:
        return False, str(exc)[:300]


async def cleanup_run_workspaces(run_id: int, *, only_if_succeeded: bool = False) -> list[int]:
    """删除一个 run 的工作区目录并写 `cleaned_at`；返回本次清理的行 id。

    - 自动路径（only_if_succeeded=True）：只在 run 成功时执行，失败/取消保留目录排查；
    - 手动路径：只允许终态 run，运行中/等审批时删目录会把正在用的沙箱抽走。
    """
    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            raise NotFoundError("运行不存在")
        if only_if_succeeded:
            if run.status != "succeeded":
                return []
        elif run.status not in TERMINAL_STATUSES:
            raise ConflictError("运行尚未结束，不能清理沙箱工作区")

        rows = (
            (
                await session.execute(
                    select(CodeWorkspace).where(CodeWorkspace.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        pending = [row for row in rows if row.cleaned_at is None and row.workspace_path]
        removed: list[int] = []
        for row in pending:
            path = Path(row.workspace_path)
            if not _under_root(path):
                logger.warning(
                    "workspace_cleanup_refused",
                    extra={"run_id": run_id, "path": row.workspace_path},
                )
                continue
            ok, error = await asyncio.to_thread(_remove_dir, path)
            if not ok:
                logger.warning(
                    "workspace_cleanup_failed",
                    extra={"run_id": run_id, "path": row.workspace_path, "error": error},
                )
                continue
            row.cleaned_at = utcnow()
            removed.append(row.id)
        if removed:
            await session.commit()

    if removed:
        logger.info("workspace_cleaned", extra={"run_id": run_id, "count": len(removed)})
    return removed


async def purge_expired_workspaces(retention_days: int | None = None) -> dict[str, int]:
    """兜底清理：删超过保留期的工作区目录，包括库里已没有对应行的孤儿目录。

    失败/取消的 run 不会被自动清理，靠这里按时间收；返回统计供日志/测试断言。
    """
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.workspace_retention_days
    cutoff = time.time() - max(0, days) * SECONDS_PER_DAY
    root = workspaces_root()
    result = {"removed": 0, "failed": 0, "marked": 0}
    if not root.exists():
        return result

    async with get_session_factory()() as session:
        rows = (await session.execute(select(CodeWorkspace))).scalars().all()
        by_path = {_norm(row.workspace_path): row for row in rows if row.workspace_path}

    marked: list[int] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not _under_root(entry):
            continue
        try:
            fresh = entry.stat().st_mtime > cutoff
        except OSError:
            continue
        if fresh:
            continue
        row = by_path.get(_norm(entry))
        ok, error = await asyncio.to_thread(_remove_dir, entry)
        if not ok:
            result["failed"] += 1
            logger.warning(
                "workspace_purge_failed", extra={"path": str(entry), "error": error}
            )
            continue
        result["removed"] += 1
        if row is not None and row.cleaned_at is None:
            marked.append(row.id)

    if marked:
        async with get_session_factory()() as session:
            for row_id in marked:
                row = await session.get(CodeWorkspace, row_id)
                if row is not None and row.cleaned_at is None:
                    row.cleaned_at = utcnow()
            await session.commit()
        result["marked"] = len(marked)

    if result["removed"] or result["failed"]:
        logger.info("workspace_purged", extra={"days": days, **result})
    return result


__all__ = ["cleanup_run_workspaces", "purge_expired_workspaces"]
