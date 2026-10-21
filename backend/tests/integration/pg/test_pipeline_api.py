from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.queue import inline

pytestmark = pytest.mark.pg


@pytest.fixture
async def api():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_run_lifecycle_through_http(api, project_factory, fake_llm):
    _, requirement_id = await project_factory()

    created = await api.post(
        f"/api/v1/requirements/{requirement_id}/runs", json={"max_review_rounds": 1}
    )
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["id"]
    assert run["status"] in {"queued", "running"}
    assert run["thread_id"]

    # 后台任务跑完停在第一个审批门
    await inline.join()
    detail = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert detail["status"] == "waiting_approval"
    assert detail["current_stage"] == "analysis"
    assert detail["pending_approval"]["stage"] == "analysis"
    assert detail["pending_approval"]["artifact_id"]
    assert detail["prompt_tokens"] > 0

    pending = await api.get(f"/api/v1/runs/{run_id}/pending-approval")
    assert pending.status_code == 200
    assert pending.json()["label"] == "需求细节分析"

    artifacts = (await api.get(f"/api/v1/runs/{run_id}/artifacts")).json()
    assert artifacts["total"] == 1
    item = artifacts["items"][0]
    assert "content" not in item
    assert item["stage"] == "analysis" and item["version"] == 1

    full = (await api.get(f"/api/v1/artifacts/{item['id']}")).json()
    assert "FAKE-analysis" in full["content"]

    approved = await api.post(
        f"/api/v1/runs/{run_id}/approval", json={"decision": "approved"}
    )
    assert approved.status_code == 202, approved.text
    await inline.join()

    detail = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert detail["status"] == "waiting_approval"
    assert detail["current_stage"] == "design"
    assert detail["review_round"] == 0

    states = (await api.get(f"/api/v1/runs/{run_id}/states", params={"limit": 5})).json()
    assert len(states) >= 2
    assert all(state["checkpoint_id"] for state in states)
    assert states[0]["has_interrupt"] is True

    # 没有待审批时再提交审批 -> 409（这里仍在 design 门，先验证错误分支的形状）
    bad = await api.post(f"/api/v1/runs/{run_id}/approval", json={"decision": "rejected"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation_error"


async def test_reject_requires_feedback(api, project_factory, fake_llm):
    _, requirement_id = await project_factory()
    created = await api.post(f"/api/v1/requirements/{requirement_id}/runs", json={})
    run_id = created.json()["id"]
    await inline.join()

    resp = await api.post(f"/api/v1/runs/{run_id}/approval", json={"decision": "rejected"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "validation_error"
    assert body["trace_id"]


async def test_reconcile_does_not_flip_back_between_approve_and_resume(
    api, project_factory, fake_llm, monkeypatch
):
    """审批已落库、resume 还没消费 interrupt 的窗口里：
    读接口不能把状态倒回 waiting_approval；pending-approval 必须 204；重复审批 409。"""
    _, requirement_id = await project_factory()
    run_id = (await api.post(f"/api/v1/requirements/{requirement_id}/runs", json={})).json()["id"]
    await inline.join()

    calls: list[tuple[int, dict]] = []

    async def _noop_execute(run_id: int, **kwargs):
        calls.append((run_id, kwargs))

    monkeypatch.setattr("app.services.run_executor.execute_run", _noop_execute)

    approved = await api.post(f"/api/v1/runs/{run_id}/approval", json={"decision": "approved"})
    assert approved.status_code == 202

    detail = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert detail["status"] == "running", detail
    assert detail["current_stage"] == "analysis"

    pending = await api.get(f"/api/v1/runs/{run_id}/pending-approval")
    assert pending.status_code == 204

    again = await api.post(f"/api/v1/runs/{run_id}/approval", json={"decision": "approved"})
    assert again.status_code == 409
    assert calls and calls[0][1]["resume_payload"] == {"decision": "approved"}


async def test_cancel_at_gate_blocks_further_approval(api, project_factory, fake_llm):
    _, requirement_id = await project_factory()
    run_id = (await api.post(f"/api/v1/requirements/{requirement_id}/runs", json={})).json()["id"]
    await inline.join()

    cancelled = await api.post(f"/api/v1/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    detail = (await api.get(f"/api/v1/runs/{run_id}")).json()
    assert detail["status"] == "cancelled"  # reconcile 不能把结束态翻回来

    approval = await api.post(f"/api/v1/runs/{run_id}/approval", json={"decision": "approved"})
    assert approval.status_code == 409


async def test_run_list_and_usage(api, project_factory, fake_llm):
    project_id, requirement_id = await project_factory(name="列表项目")
    created = await api.post(f"/api/v1/requirements/{requirement_id}/runs", json={})
    run_id = created.json()["id"]
    await inline.join()

    rows = (await api.get("/api/v1/runs", params={"project_id": project_id})).json()
    assert rows["total"] == 1
    row = rows["items"][0]
    assert row["id"] == run_id
    assert row["prompt_tokens"] > 0 and row["completion_tokens"] > 0
