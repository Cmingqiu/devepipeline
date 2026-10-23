from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Artifact, RunEvent
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg


async def _approve(run_id: int, tools=None) -> None:
    async with get_session_factory()() as session:
        payload = ApprovalIn(decision="approved")
        await run_service.decide(session, run_id, payload, enqueue=False)
    await execute_run(run_id, resume_payload={"decision": "approved"}, tools=tools)


@pytest.fixture
def tool_model(monkeypatch):
    """coding 第一轮发起一次工具调用，拿到结果后第二轮输出正文。"""
    from langchain_core.messages import AIMessageChunk

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)
    seen_tools: list[list[str]] = []

    class _Model:
        def __init__(self, stage: str) -> None:
            self.stage = stage
            self.turn = 0

        def bind_tools(self, tools):
            seen_tools.append([tool.name for tool in tools])
            return self

        async def astream(self, messages):
            if self.stage == "coding" and self.turn == 0:
                self.turn += 1
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": "lookup", "args": '{"q": "x"}', "id": "call_1", "index": 0}
                    ],
                    usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
                )
                return
            yield AIMessageChunk(
                content=f"# {self.stage} 产物\n",
                usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )
    return seen_tools


@pytest.fixture
def fake_tool():
    from langchain_core.tools import StructuredTool

    def _lookup(q: str) -> str:
        """查资料。"""
        return f"TOOL-OUT:{q}"

    return StructuredTool.from_function(func=_lookup, name="lookup", description="查资料")


async def test_coding_tool_loop_emits_events(project_factory, tool_model, fake_tool):
    _, requirement_id = await project_factory(name="工具调用项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    await execute_run(run.id)  # analysis 门
    await _approve(run.id)  # design 门
    await _approve(run.id, tools=[fake_tool])  # coding 门（这里应触发工具调用）

    async with get_session_factory()() as session:
        events = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.seq)
            )
        ).scalars().all()
        coding = (
            await session.execute(
                select(Artifact).where(Artifact.run_id == run.id, Artifact.stage == "coding")
            )
        ).scalars().all()

    types = [event.type for event in events]
    assert "tool_started" in types
    assert "tool_finished" in types

    started = next(event for event in events if event.type == "tool_started")
    finished = next(event for event in events if event.type == "tool_finished")
    assert started.stage == "coding"
    assert json.loads(started.payload)["name"] == "lookup"
    finished_payload = json.loads(finished.payload)
    assert finished_payload["ok"] is True
    assert "TOOL-OUT:x" in finished_payload["result"]

    assert coding and "# coding 产物" in coding[-1].content
    # 模型确实拿到工具列表
    assert tool_model and "lookup" in tool_model[0]
