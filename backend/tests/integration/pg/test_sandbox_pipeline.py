from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import Artifact, CodeWorkspace, PipelineRun, Project
from app.sandbox.worktree import cleanup_workspace
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run

pytestmark = pytest.mark.pg


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
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
    (repo / "test_smoke.py").write_text("def test_smoke():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


@pytest.fixture
def sandbox_model(monkeypatch):
    """coding 第一轮调用 write_file + run_command，第二轮总结。"""
    from langchain_core.messages import AIMessageChunk

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
                        },
                        {
                            "name": "sandbox_run_command",
                            "args": '{"command": "python -m pytest -q"}',
                            "id": "call_test",
                            "index": 1,
                        },
                    ],
                    usage_metadata={"input_tokens": 8, "output_tokens": 6, "total_tokens": 14},
                )
                return
            yield AIMessageChunk(
                content=f"# {self.stage} 产物\n改了 app.py，测试已跑。\n",
                usage_metadata={"input_tokens": 8, "output_tokens": 6, "total_tokens": 14},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )


async def _approve(run_id: int) -> None:
    async with get_session_factory()() as session:
        await run_service.decide(session, run_id, ApprovalIn(decision="approved"), enqueue=False)
    await execute_run(run_id, resume_payload={"decision": "approved"})


async def test_coding_edits_sandbox_and_collects_diff(project_factory, seed_repo, sandbox_model):
    project_id, requirement_id = await project_factory(name="沙箱项目")

    async with get_session_factory()() as session:
        project = await session.get(Project, project_id)
        project.repo_url = str(seed_repo)
        project.default_branch = "main"
        await session.commit()
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    try:
        await execute_run(run.id)  # analysis 门
        await _approve(run.id)  # design 门
        await _approve(run.id)  # coding：写文件 + 跑测试

        async with get_session_factory()() as session:
            workspace = (
                await session.execute(
                    select(CodeWorkspace).where(CodeWorkspace.run_id == run.id)
                )
            ).scalar_one()
            coding = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == run.id, Artifact.stage == "coding")
                )
            ).scalars().all()
            stored_run = await session.get(PipelineRun, run.id)

        assert stored_run.current_stage == "coding"
        assert stored_run.status == "waiting_approval"

        workspace_path = Path(workspace.workspace_path)
        assert workspace_path.exists()
        assert workspace.branch == f"devpipeline/run-{run.id}"
        # 文件真的被改了
        assert "ok-v2" in (workspace_path / "app.py").read_text(encoding="utf-8")

        content = coding[-1].content
        assert "## 代码改动（git diff）" in content
        assert "app.py" in content
        assert "## 命令与测试记录" in content
        assert "[ok] python -m pytest" in content
    finally:
        cleanup_workspace(run.id)
