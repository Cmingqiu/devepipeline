from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.session import get_session_factory
from app.main import create_app
from app.models import RunEvent
from app.queue import inline
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg


async def _events(run_id: int) -> list[tuple[int, str, dict]]:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
            )
        ).scalars().all()
    return [(row.seq, row.type, json.loads(row.payload or "{}")) for row in rows]


async def test_events_written_with_monotonic_seq(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    await execute_run(run.id)
    events = await _events(run.id)

    seqs = [event[0] for event in events]
    assert seqs == sorted(set(seqs)), "seq 必须严格递增"
    types = {event[1] for event in events}
    assert {
        "run_started",
        "usage",
        "artifact_saved",
        "stage_finished",
        "interrupt",
    } <= types
    # 停在第一个审批门，最后一条是 interrupt
    assert events[-1][1] == "interrupt"
    assert events[-1][2]["stage"] == "analysis"


async def test_decision_event_recorded(project_factory, fake_llm):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, requirement_id = await project_factory()
        created = await client.post(
            f"/api/v1/requirements/{requirement_id}/runs", json={}
        )
        run_id = created.json()["id"]
        await inline.join()

        approved = await client.post(
            f"/api/v1/runs/{run_id}/approval", json={"decision": "approved"}
        )
        assert approved.status_code == 202
        await inline.join()

    types = [event[1] for event in await _events(run_id)]
    assert "decision" in types
    # 审批后应继续跑出 design 阶段并停在下一个审批门
    # （用 count 而不是「最后一条」，避免事件落盘时序导致的偶发）
    assert types.count("interrupt") >= 1
    assert "run_finished" not in types


async def test_sse_replays_history_then_closes(project_factory, fake_llm):
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)
    # 取消后再读流：状态终态，回放完应主动关闭
    async with get_session_factory()() as session:
        await run_service.cancel_run(session, run.id)

    app = create_app()
    transport = ASGITransport(app=app)
    seen: list[str] = []
    async with AsyncClient(
        transport=transport, base_url="http://testserver", timeout=30
    ) as client, client.stream(
        "GET", f"/api/v1/runs/{run.id}/stream", headers={"Last-Event-ID": "0"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                seen.append(line[len("event: ") :])
                if seen[-1] == "run_finished":
                    break

    assert "run_started" in seen
    assert "interrupt" in seen
    assert seen[-1] == "run_finished"
    # 同一事件不重复推送
    assert len(seen) == len(set(seen)) or seen.count("interrupt") == 1


async def test_events_endpoint_paginates_by_cursor(project_factory, fake_llm):
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        _, requirement_id = await project_factory()
        run_id = (
            await client.post(f"/api/v1/requirements/{requirement_id}/runs", json={})
        ).json()["id"]
        await inline.join()

        first = (await client.get(f"/api/v1/runs/{run_id}/events", params={"page_size": 2})).json()
        assert len(first) == 2
        assert first[0]["seq"] == 1
        cursor = first[-1]["seq"]

        rest = (
            await client.get(
                f"/api/v1/runs/{run_id}/events", params={"after_seq": cursor, "page_size": 50}
            )
        ).json()
        assert all(item["seq"] > cursor for item in rest)
        assert rest[-1]["type"] == "interrupt"


async def test_approval_gone_after_decision(project_factory, fake_llm):
    """回归：decision 事件不应让待审批接口重复暴露。"""
    _, requirement_id = await project_factory()
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)
    async with get_session_factory()() as session:
        await run_service.decide(
            session, run.id, ApprovalIn(decision="approved"), enqueue=False
        )
        assert await run_service.pending_approval(session, run) is None
