from __future__ import annotations

import asyncio
import sys
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import get_session_factory

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _cleanup_project(project_id: int) -> None:
    """按无外键的顺序手工清理；顺带把 PG 里的 checkpoint 线程删掉。"""
    factory = get_session_factory()
    thread_ids: list[str] = []
    async with factory() as session:
        rows = (
            await session.execute(
                text("select thread_id from pipeline_runs where project_id = :pid"),
                {"pid": project_id},
            )
        ).all()
        thread_ids = [row[0] for row in rows]
        for sql in (
            "delete a from artifacts a join pipeline_runs r on a.run_id = r.id where r.project_id = :pid",
            "delete s from stage_runs s join pipeline_runs r on s.run_id = r.id where r.project_id = :pid",
            "delete p from stage_approvals p join pipeline_runs r on p.run_id = r.id where r.project_id = :pid",
            "delete e from run_events e join pipeline_runs r on e.run_id = r.id where r.project_id = :pid",
            "delete from pipeline_runs where project_id = :pid",
            (
                "delete from requirement_versions where requirement_id in "
                "(select id from requirements where project_id = :pid)"
            ),
            "delete from requirements where project_id = :pid",
            "delete from projects where id = :pid",
        ):
            await session.execute(text(sql), {"pid": project_id})
        await session.commit()

    if thread_ids:
        try:
            from app.db.graph_db import get_checkpointer

            saver = await get_checkpointer()
            for thread_id in thread_ids:
                await saver.adelete_thread(thread_id)
        except Exception:  # noqa: BLE001, S110  清理失败不影响测试结论
            pass


@pytest.fixture
async def project_factory():
    """建一个可跑的 项目+需求+版本（真实提交，执行器用独立连接才能看见）。"""
    created: list[tuple[int, int]] = []

    async def _make(name: str = "流水线测试", content: str = "# 需求\n\n支持手机号验证码登录。") -> tuple[int, int]:
        from app.models import Project, Requirement, RequirementVersion

        async with get_session_factory()() as session:
            project = Project(name=name, slug=f"t-{uuid4().hex[:8]}", status="active")
            session.add(project)
            await session.flush()

            requirement = Requirement(project_id=project.id, title="登录改造", current_version_no=1)
            session.add(requirement)
            await session.flush()

            session.add(
                RequirementVersion(
                    requirement_id=requirement.id,
                    version_no=1,
                    content=content,
                    source="editor",
                )
            )
            await session.commit()
            created.append((project.id, requirement.id))
            return project.id, requirement.id

    yield _make

    for project_id, _ in created:
        await _cleanup_project(project_id)
        try:
            import shutil

            from app.services.storage import storage_root

            target = storage_root() / "skills" / str(project_id)
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        except Exception:  # noqa: BLE001, S110  清理失败不影响测试结论
            pass


@pytest.fixture
def fake_llm(monkeypatch):
    """不联网：每个节点返回固定文本 + usage，并记录调用顺序。"""
    from langchain_core.messages import AIMessage

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)
    calls: list[str] = []

    class _FakeModel:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        async def ainvoke(self, messages):
            calls.append(self.stage)
            return AIMessage(
                content=f"# {self.stage} 产物\n\nFAKE-{self.stage}-{len(calls)}\n",
                usage_metadata={
                    "input_tokens": 11,
                    "output_tokens": 7,
                    "total_tokens": 18,
                },
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _FakeModel(stage), raising=True
    )
    return calls


@pytest.fixture
def captured_llm(monkeypatch):
    """同 fake_llm，但额外记录每个阶段收到的完整 prompt（用于断言 AGENTS.md / 技能注入）。"""
    from langchain_core.messages import AIMessage

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)
    captured: list[tuple[str, str]] = []

    class _FakeModel:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        async def ainvoke(self, messages):
            text = "\n".join(str(getattr(message, "content", "")) for message in messages)
            captured.append((self.stage, text))
            return AIMessage(
                content=f"# {self.stage} 产物\n",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _FakeModel(stage), raising=True
    )
    return captured
