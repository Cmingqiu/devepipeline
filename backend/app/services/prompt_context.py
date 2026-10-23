"""M4：把 AGENTS.md 与技能包快照注入每次 run 的 state。

一次 run 冻结上下文（与需求正文同理）：运行中改配置只影响下一次 run，
checkpoint 回溯时行为可复现。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDoc
from app.services.context_service import skill_prompt_snapshot


async def load_prompt_context(session: AsyncSession, project_id: int) -> dict[str, Any]:
    """返回可直接并进 state 的 `agents_md` 与 `skill_index`。"""
    agents_md = (
        await session.execute(
            select(AgentDoc.content)
            .where(AgentDoc.project_id == project_id, AgentDoc.is_active.is_(True))
            .order_by(AgentDoc.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or ""

    skills = await skill_prompt_snapshot(session, project_id)
    return {"agents_md": agents_md, "skill_index": skills}


__all__ = ["load_prompt_context"]
