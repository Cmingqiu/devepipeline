from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select, text

from app.db.session import get_session_factory
from app.models import Artifact, CodeWorkspace, PipelineRun, Project, PullRequest
from app.sandbox.worktree import cleanup_workspace, prepare_workspace
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.pr_service import ensure_pull_request
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


@pytest.fixture
def seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    (repo / "app.py").write_text("def health() -> str:\n    return 'ok'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


@pytest.fixture
def coding_model(monkeypatch):
    """coding 第一轮写文件，其余阶段直接给文本（与 test_sandbox_pipeline 一致）。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)

    class _Model:
        def __init__(self, stage: str) -> None:
            self.stage = stage
            self.turn = 0

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            if self.stage == "coding" and self.turn == 0:
                self.turn += 1
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "sandbox_write_file",
                            "args": '{"path": "app.py", "content": "def health() -> str:\\n    return \'ok-v2\'\\n"}',
                            "id": "call_write",
                            "index": 0,
                        }
                    ],
                    usage_metadata={"input_tokens": 8, "output_tokens": 6, "total_tokens": 14},
                )
                return
            yield AIMessageChunk(
                content=f"# {self.stage} 产物\n## 结论\n通过\n",
                usage_metadata={"input_tokens": 8, "output_tokens": 6, "total_tokens": 14},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )


@pytest.fixture
def fake_vcs(monkeypatch):
    """项目仓库是本地路径（沙箱能 clone/push），PR 客户端换成假 GitHub。"""
    from app.vcs import PullRequestInfo, RepoRef

    created: list[dict] = []

    class _FakeClient:
        async def create_pull_request(self, **kwargs):
            created.append(kwargs)
            return PullRequestInfo(
                provider="github",
                repo_full_name="acme/demo",
                number=7,
                url="https://github.com/acme/demo/pull/7",
                branch=kwargs["head"],
                base_branch=kwargs["base"],
                head_sha=None,
            )

        async def get_pull_request(self, *, owner, repo, number):  # pragma: no cover
            raise AssertionError("不该调用")

    monkeypatch.setattr(
        "app.services.pr_service.resolve_repo",
        lambda repo_url, provider=None: RepoRef(
            provider="github", host="github.com", owner="acme", repo="demo"
        ),
    )
    monkeypatch.setattr(
        "app.services.pr_service.build_vcs_client", lambda ref, token: _FakeClient()
    )
    return created


async def _approve(run_id: int) -> None:
    async with get_session_factory()() as session:
        await run_service.decide(session, run_id, ApprovalIn(decision="approved"), enqueue=False)
    await execute_run(run_id, resume_payload={"decision": "approved"})


async def test_review_creates_pull_request(project_factory, seed_repo, coding_model, fake_vcs):
    project_id, requirement_id = await project_factory(name="PR 项目")

    async with get_session_factory()() as session:
        project = await session.get(Project, project_id)
        project.repo_url = str(seed_repo)
        project.default_branch = "main"
        await session.commit()
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    try:
        await execute_run(run.id)  # analysis 门
        await _approve(run.id)  # design 门
        await _approve(run.id)  # coding：改文件
        await _approve(run.id)  # coding 审批通过 → review 阶段建 PR，停在 review 门

        branch = f"devpipeline/run-{run.id}"
        async with get_session_factory()() as session:
            pr = (
                await session.execute(select(PullRequest).where(PullRequest.run_id == run.id))
            ).scalar_one()
            workspace = (
                await session.execute(
                    select(CodeWorkspace).where(CodeWorkspace.run_id == run.id)
                )
            ).scalar_one()
            review_artifacts = (
                (
                    await session.execute(
                        select(Artifact).where(
                            Artifact.run_id == run.id, Artifact.stage == "review"
                        )
                    )
                )
                .scalars()
                .all()
            )
            stored_run = await session.get(PipelineRun, run.id)
            events = (
                await session.execute(
                    text(
                        "select type, payload from run_events "
                        "where run_id = :rid and type = 'pull_request_created'"
                    ),
                    {"rid": run.id},
                )
            ).all()

        # PR 落库 + 状态停在 review 门等人工
        assert pr.number == 7
        assert pr.url == "https://github.com/acme/demo/pull/7"
        assert pr.branch == branch
        assert pr.base_branch == "main"
        assert pr.status == "open"
        assert stored_run.status == "waiting_approval"
        assert stored_run.current_stage == "review"
        assert review_artifacts, "评审产物应已落库"

        # 沙箱里真的提交并推到了“远端”（本地仓库）
        local_head = _git(Path(workspace.workspace_path), "rev-parse", "HEAD").stdout.strip()
        assert workspace.head_sha == local_head
        assert pr.head_sha == local_head
        remote_head = _git(seed_repo, "rev-parse", branch).stdout.strip()
        assert remote_head == local_head
        assert "ok-v2" in _git(seed_repo, "show", f"{branch}:app.py").stdout

        # 事件推给了时间线，且 PR 元数据齐全
        assert len(events) == 1
        event_payload = json.loads(events[0].payload)
        assert event_payload["number"] == 7
        assert event_payload["branch"] == branch
        assert event_payload["head_sha"] == local_head

        # 建 PR 的参数：标题带需求、body 指向运行详情
        assert fake_vcs and fake_vcs[0]["head"] == branch
        assert "登录改造" in fake_vcs[0]["title"]
        assert f"# {run.id}" in fake_vcs[0]["body"]

        # 幂等：重跑评审阶段不会再插入一条 PR
        again = await prepare_workspace(
            run_id=run.id,
            repo_url=str(seed_repo),
            base_branch="main",
            branch=branch,
        )
        second = await ensure_pull_request(run.id, again)
        assert second is not None
        assert second.created is False
        assert len(fake_vcs) == 1
        async with get_session_factory()() as session:
            rows = (
                await session.execute(select(PullRequest).where(PullRequest.run_id == run.id))
            ).scalars().all()
        assert len(rows) == 1

        await _approve(run.id)  # 评审通过 → 结束
        async with get_session_factory()() as session:
            finished = await session.get(PipelineRun, run.id)
        assert finished.status == "succeeded"
    finally:
        cleanup_workspace(run.id)


async def test_no_changes_skips_pull_request(project_factory, seed_repo, monkeypatch, fake_vcs):
    """模型只输出文本、沙箱没改动时不该建空 PR。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)

    class _Model:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            yield AIMessageChunk(
                content=f"# {self.stage} 产物\n",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )

    project_id, requirement_id = await project_factory(name="无改动项目")
    async with get_session_factory()() as session:
        project = await session.get(Project, project_id)
        project.repo_url = str(seed_repo)
        project.default_branch = "main"
        await session.commit()
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    try:
        await execute_run(run.id)
        await _approve(run.id)
        await _approve(run.id)  # coding 无改动，直接进 review
        await _approve(run.id)  # 通过 coding 门 → review 阶段

        async with get_session_factory()() as session:
            rows = (
                await session.execute(select(PullRequest).where(PullRequest.run_id == run.id))
            ).scalars().all()
        assert rows == []
        assert fake_vcs == []
    finally:
        cleanup_workspace(run.id)


async def test_list_pull_requests_api(project_factory, client):
    _project_id, requirement_id = await project_factory(name="PR 接口项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
        session.add(
            PullRequest(
                run_id=run.id,
                provider="github",
                repo_full_name="acme/demo",
                number=12,
                url="https://github.com/acme/demo/pull/12",
                branch=f"devpipeline/run-{run.id}",
                base_branch="main",
                head_sha="c" * 40,
                status="open",
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/runs/{run.id}/pull-requests")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["number"] == 12
    assert body[0]["provider"] == "github"
    assert body[0]["status"] == "open"
    assert body[0]["head_sha"] == "c" * 40

    assert (await client.get("/api/v1/runs/999999/pull-requests")).status_code == 404
