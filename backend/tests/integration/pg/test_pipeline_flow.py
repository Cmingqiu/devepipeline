from __future__ import annotations

import pytest

from app.db.session import get_session_factory
from app.models import Artifact, PipelineRun, StageApproval, StageRun
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg


async def _reload(run_id: int) -> PipelineRun:
    async with get_session_factory()() as session:
        run = await session.get(PipelineRun, run_id)
        assert run is not None
        return run


async def _count(model, **filters) -> int:
    from sqlalchemy import func, select

    async with get_session_factory()() as session:
        stmt = select(func.count()).select_from(model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(model, key) == value)
        return int((await session.execute(stmt)).scalar_one())


async def _approve(run_id: int, **kwargs) -> None:
    async with get_session_factory()() as session:
        payload = ApprovalIn(decision=kwargs.pop("decision", "approved"), **kwargs)
        await run_service.decide(session, run_id, payload, enqueue=False)
    await execute_run(run_id, resume_payload=payload.model_dump(exclude_none=True))


async def test_full_pipeline_stops_at_every_gate_then_succeeds(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    await execute_run(run.id)
    run = await _reload(run.id)
    assert run.status == "waiting_approval"
    assert run.current_stage == "analysis"
    assert await _count(Artifact, run_id=run.id) == 1

    for expected_stage in ("design", "coding", "review"):
        await _approve(run.id)
        run = await _reload(run.id)
        assert run.status == "waiting_approval", run
        assert run.current_stage == expected_stage

    await _approve(run.id)
    run = await _reload(run.id)
    assert run.status == "succeeded"
    assert run.finished_at is not None

    assert await _count(StageRun, run_id=run.id) == 4
    assert await _count(Artifact, run_id=run.id) == 4
    assert await _count(StageApproval, run_id=run.id) == 4
    assert fake_llm == ["analysis", "design", "coding", "review"]

    async with get_session_factory()() as session:
        stage_runs = (
            await session.execute(StageRun.__table__.select().where(StageRun.run_id == run.id))
        ).all()
    assert all(row.status == "succeeded" for row in stage_runs)
    assert all(row.prompt_tokens == 11 and row.completion_tokens == 7 for row in stage_runs)


async def test_reject_analysis_reruns_same_stage_with_feedback(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)

    await _approve(run.id, decision="rejected", feedback="补上验收标准与边界条件")

    run = await _reload(run.id)
    assert run.status == "waiting_approval"
    assert run.current_stage == "analysis"
    assert fake_llm == ["analysis", "analysis"]
    assert await _count(StageRun, run_id=run.id, stage="analysis") == 2
    assert await _count(Artifact, run_id=run.id, stage="analysis") == 2

    # 第二次的 attempt 是 2
    from sqlalchemy import select

    async with get_session_factory()() as session:
        attempts = sorted(
            (
                await session.execute(
                    select(StageRun.attempt).where(StageRun.run_id == run.id, StageRun.stage == "analysis")
                )
            ).scalars()
        )
    assert attempts == [1, 2]


async def test_approve_with_edit_replaces_artifact_and_feeds_next_stage(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)

    edited = "# analysis 产物\n\n人工改过的正文\n"
    await _approve(run.id, decision="approved_with_edit", edited_content=edited)

    from sqlalchemy import select

    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(Artifact)
                .where(Artifact.run_id == run.id, Artifact.stage == "analysis")
                .order_by(Artifact.version)
            )
        ).scalars().all()
    assert [row.version for row in rows] == [1, 2]
    assert rows[-1].edited_by_human is True
    assert rows[-1].content == edited

    # 下游拿到的是人工版本：设计节点 prompt 里应包含它
    from app.services.run_executor import get_graph, graph_config

    graph = await get_graph()
    snapshot = await graph.aget_state(graph_config(await _reload(run.id)))
    assert snapshot.values["analysis_doc"] == edited
    assert snapshot.values["gate_decisions"]["analysis"]["decision"] == "approved_with_edit"


async def test_review_reject_loops_back_and_terminates_after_max_rounds(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(
            session, requirement_id, RunCreate(max_review_rounds=2), enqueue=False
        )

    await execute_run(run.id)  # analysis gate
    await _approve(run.id)  # -> design gate
    await _approve(run.id)  # -> coding gate
    await _approve(run.id)  # -> review gate

    run = await _reload(run.id)
    assert run.current_stage == "review"

    # 第 1、2 次驳回：回到编码；改完再通过编码门，回到评审
    for round_no in (1, 2):
        await _approve(run.id, decision="rejected", feedback=f"补充错误处理（第 {round_no} 轮）")
        run = await _reload(run.id)
        assert run.status == "waiting_approval"
        assert run.current_stage == "coding"

        await _approve(run.id)  # 编码通过 -> 回到评审门
        run = await _reload(run.id)
        assert run.status == "waiting_approval"
        assert run.current_stage == "review"

    # 第 3 次驳回：超过 max_review_rounds=2，终止为 failed
    await _approve(run.id, decision="rejected", feedback="还是不行")
    run = await _reload(run.id)
    assert run.status == "failed"
    assert run.error_code == "review_round_exceeded"
    assert run.review_round == 3
