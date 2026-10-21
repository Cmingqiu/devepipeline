from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import Artifact


async def list_artifacts(
    session: AsyncSession, run_id: int, *, page: int, page_size: int
) -> tuple[list[Artifact], int]:
    total = (
        await session.execute(
            select(func.count()).select_from(Artifact).where(Artifact.run_id == run_id)
        )
    ).scalar_one()
    stmt = (
        select(Artifact)
        .where(Artifact.run_id == run_id)
        .order_by(Artifact.stage, Artifact.version.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return list((await session.execute(stmt)).scalars().all()), int(total)


async def get_artifact(session: AsyncSession, artifact_id: int) -> Artifact:
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise NotFoundError("产物不存在")
    return artifact


async def edit_artifact(session: AsyncSession, artifact_id: int, content: str) -> Artifact:
    """人工编辑不改原行，追加 version+1 并标记 edited_by_human（历史可追溯）。"""
    artifact = await get_artifact(session, artifact_id)
    next_version = (
        await session.execute(
            select(func.coalesce(func.max(Artifact.version), 0)).where(
                Artifact.run_id == artifact.run_id, Artifact.stage == artifact.stage
            )
        )
    ).scalar_one() + 1

    edited = Artifact(
        run_id=artifact.run_id,
        stage=artifact.stage,
        version=int(next_version),
        kind=artifact.kind,
        content=content,
        summary=" ".join(content.split())[:300],
        edited_by_human=True,
    )
    session.add(edited)
    await session.commit()
    return edited


async def artifact_version_count(session: AsyncSession, run_id: int, stage: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Artifact)
                .where(Artifact.run_id == run_id, Artifact.stage == stage)
            )
        ).scalar_one()
    )


__all__ = ["artifact_version_count", "edit_artifact", "get_artifact", "list_artifacts"]
