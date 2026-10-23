from __future__ import annotations

import asyncio
import time

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Artifact, PipelineRun, RunEvent
from app.schemas.run import ApprovalIn, ForkIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg

_SEQ = {"n": 0}


def _install_model(monkeypatch, *, slow_stage: str | None = None) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)

    class _Model:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            if slow_stage == self.stage:
                await asyncio.sleep(0.8)
            _SEQ["n"] += 1
            yield AIMessageChunk(
                content=f"# {self.stage} 产物 #{_SEQ['n']}\n",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )


@pytest.fixture
def fake_model(monkeypatch):
    _install_model(monkeypatch)


@pytest.fixture
def slow_analysis_model(monkeypatch):
    _install_model(monkeypatch, slow_stage="analysis")


@pytest.fixture
def captured_enqueue(monkeypatch):
    """resume / fork 里的入队改为记录，测试自己决定何时执行。"""
    calls: list[tuple[int, dict]] = []

    async def _enqueue(run_id: int, **kwargs):
        calls.append((run_id, kwargs))
        return "test"

    monkeypatch.setattr("app.services.run_service.dispatcher.enqueue_run", _enqueue)
    return calls


async def _approve(run_id: int) -> None:
    async with get_session_factory()() as session:
        await run_service.decide(session, run_id, ApprovalIn(decision="approved"), enqueue=False)
    await execute_run(run_id, resume_payload={"decision": "approved"})


async def _create(requirement_id: int) -> PipelineRun:
    async with get_session_factory()() as session:
        return await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)


async def _events(run_id: int) -> list[tuple[str, str]]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            )
        ).scalars().all()
    return [(row.type, row.payload) for row in rows]


async def _wait_status(run_id: int, expected: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with get_session_factory()() as session:
            current = await session.scalar(
                select(PipelineRun.status).where(PipelineRun.id == run_id)
            )
        if current == expected:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} 没在 {timeout}s 内进入 {expected}")


async def test_pause_stops_at_node_boundary_then_resume(
    project_factory, slow_analysis_model, captured_enqueue
):
    _project_id, requirement_id = await project_factory(name="暂停项目")
    run = await _create(requirement_id)

    task = asyncio.create_task(execute_run(run.id))
    # 等执行器真正进入 running（模型还在 sleep），再暂停；否则暂停会落在 queued 分支
    await _wait_status(run.id, "running")
    async with get_session_factory()() as session:
        paused = await run_service.pause_run(session, run.id)
    assert paused.status == "paused"
    await task

    async with get_session_factory()() as session:
        stored = await session.get(PipelineRun, run.id)
    events = await _events(run.id)
    assert stored.status == "paused"
    assert stored.last_checkpoint_id, "暂停时要落最后一个 checkpoint"
    assert "run_paused" in [item[0] for item in events]
    # 节点边界停下：不会越过去执行 gate
    assert stored.current_stage != "design"

    async with get_session_factory()() as session:
        resumed = await run_service.resume_run(session, run.id)
    assert resumed.status == "running"
    assert captured_enqueue, "resume 必须重新入队"
    await execute_run(run.id, continue_run=True)

    async with get_session_factory()() as session:
        stored = await session.get(PipelineRun, run.id)
    assert stored.status == "waiting_approval"
    assert stored.current_stage == "analysis"


async def test_pause_queued_emits_stop_event(project_factory):
    _project_id, requirement_id = await project_factory(name="排队暂停项目")
    run = await _create(requirement_id)

    async with get_session_factory()() as session:
        paused = await run_service.pause_run(session, run.id)
    assert paused.status == "paused"
    events = await _events(run.id)
    paused_events = [payload for name, payload in events if name == "run_paused"]
    assert len(paused_events) == 1
    assert '"paused"' in paused_events[0]


async def test_fork_from_design_checkpoint(project_factory, fake_model, captured_enqueue):
    _project_id, requirement_id = await project_factory(name="fork 项目")
    run = await _create(requirement_id)

    await execute_run(run.id)  # analysis 门
    await _approve(run.id)  # design 门
    async with get_session_factory()() as session:
        parent = await session.get(PipelineRun, run.id)
    assert parent.status == "waiting_approval"
    assert parent.current_stage == "design"

    states = await run_service.list_states(parent, limit=50)
    design_state = next(item for item in states if item["stage"] == "design")

    async with get_session_factory()() as session:
        forked = await run_service.fork_run(
            session,
            parent.id,
            ForkIn(checkpoint_id=design_state["checkpoint_id"], from_stage="design"),
        )
    assert forked.id != parent.id
    assert forked.thread_id != parent.thread_id
    assert forked.current_stage == "design"
    assert forked.status == "queued"
    assert forked.requirement_version_id == parent.requirement_version_id

    # 入队参数带源 thread / checkpoint / 起始阶段
    assert captured_enqueue and captured_enqueue[0][0] == forked.id
    fork_payload = captured_enqueue[0][1]["fork_payload"]
    assert fork_payload["source_run_id"] == parent.id
    assert fork_payload["source_thread_id"] == parent.thread_id
    assert fork_payload["checkpoint_id"] == design_state["checkpoint_id"]
    assert fork_payload["from_stage"] == "design"

    # 前序阶段产物已复制，from_stage 及之后没有
    async with get_session_factory()() as session:
        copied = (
            await session.execute(select(Artifact).where(Artifact.run_id == forked.id))
        ).scalars().all()
        parent_design = (
            await session.execute(
                select(Artifact).where(
                    Artifact.run_id == parent.id, Artifact.stage == "design"
                )
            )
        ).scalars().all()
    assert [item.stage for item in copied] == ["analysis"]
    parent_design_content = parent_design[-1].content

    await execute_run(forked.id, fork_payload=fork_payload)

    async with get_session_factory()() as session:
        stored = await session.get(PipelineRun, forked.id)
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.run_id == forked.id))
        ).scalars().all()
        still_parent = await session.get(PipelineRun, parent.id)
    events = await _events(forked.id)

    # 新 run 从 design 重跑，停在 design 门
    assert stored.status == "waiting_approval"
    assert stored.current_stage == "design"
    assert "forked" in [item[0] for item in events]
    design_artifacts = [item for item in artifacts if item.stage == "design"]
    assert design_artifacts and design_artifacts[-1].content != parent_design_content
    # 父 run 不受影响
    assert still_parent.status == "waiting_approval"
    assert still_parent.current_stage == "design"


async def test_pause_and_resume_conflicts(project_factory, fake_model):
    from app.core.exceptions import ConflictError

    _project_id, requirement_id = await project_factory(name="冲突项目")
    run = await _create(requirement_id)

    # queued 状态不能 resume
    async with get_session_factory()() as session:
        with pytest.raises(ConflictError):
            await run_service.resume_run(session, run.id)

    await execute_run(run.id)  # analysis 门
    # 等待审批时不能 pause
    async with get_session_factory()() as session:
        with pytest.raises(ConflictError):
            await run_service.pause_run(session, run.id)
