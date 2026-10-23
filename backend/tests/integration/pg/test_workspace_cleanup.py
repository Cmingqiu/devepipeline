from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessageChunk
from sqlalchemy import select

from app.db.session import get_session_factory
from app.models import CodeWorkspace, PipelineRun, Project
from app.sandbox.worktree import cleanup_workspace, workspaces_root
from app.schemas.run import ApprovalIn, RunCreate
from app.services import run_service
from app.services.run_executor import execute_run
from app.services.workspace_service import (
    cleanup_run_workspaces,
    purge_expired_workspaces,
)

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
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


@pytest.fixture
def quiet_model(monkeypatch):
    """只返回文本、不调工具：流水线能走到 succeeded，同时沙箱目录已建。"""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_key_deepseek", "sk-test", raising=False)

    class _Model:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            yield AIMessageChunk(
                content=f"# {self.stage} 产物\n## 结论\n通过\n",
                usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            )

    monkeypatch.setattr(
        "app.agents.nodes.get_chat_model", lambda stage: _Model(stage), raising=True
    )


async def _approve(run_id: int) -> None:
    async with get_session_factory()() as session:
        await run_service.decide(session, run_id, ApprovalIn(decision="approved"), enqueue=False)
    await execute_run(run_id, resume_payload={"decision": "approved"})


async def _make_workspace(run_id: int, *, create_dir: bool = True) -> Path:
    """不跑沙箱，直接造一条 workspace 记录（目录可选创建）。"""
    root = workspaces_root() / f"run-{run_id}"
    if create_dir:
        root.mkdir(parents=True, exist_ok=True)
        (root / "app.py").write_text("ok\n", encoding="utf-8")
    async with get_session_factory()() as session:
        session.add(
            CodeWorkspace(
                run_id=run_id,
                attempt=1,
                mode="worktree",
                repo_url="https://github.com/acme/demo.git",
                workspace_path=str(root),
                branch=f"devpipeline/run-{run_id}",
            )
        )
        await session.commit()
    return root


async def test_success_cleans_workspace_automatically(project_factory, seed_repo, quiet_model):
    project_id, requirement_id = await project_factory(name="清理成功项目")
    async with get_session_factory()() as session:
        project = await session.get(Project, project_id)
        project.repo_url = str(seed_repo)
        project.default_branch = "main"
        await session.commit()
        run = await run_service.create_run(
            session, requirement_id, RunCreate(max_review_rounds=2), enqueue=False
        )

    try:
        await execute_run(run.id)  # analysis 门
        await _approve(run.id)  # design 门
        await _approve(run.id)  # coding 门
        await _approve(run.id)  # review 门
        await _approve(run.id)  # 评审通过 → succeeded
        async with get_session_factory()() as session:
            stored = await session.get(PipelineRun, run.id)
            workspace = (
                await session.execute(
                    select(CodeWorkspace).where(CodeWorkspace.run_id == run.id)
                )
            ).scalar_one()

        assert stored.status == "succeeded"
        assert workspace.cleaned_at is not None, "成功后应写清理时间"
        assert not Path(workspace.workspace_path).exists(), "目录应已删除"
    finally:
        cleanup_workspace(run.id)


async def test_failed_run_keeps_workspace(project_factory, quiet_model):
    """自动路径只清成功的 run；失败/取消保留目录排查。"""
    _project_id, requirement_id = await project_factory(name="清理失败项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
        run.status = "failed"
        await session.commit()

    root = await _make_workspace(run.id)
    try:
        removed = await cleanup_run_workspaces(run.id, only_if_succeeded=True)
        assert removed == []
        assert root.exists()
    finally:
        cleanup_workspace(run.id)


async def test_manual_cleanup_requires_terminal_status(project_factory, client):
    _project_id, requirement_id = await project_factory(name="清理进行中项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)

    response = await client.delete(f"/api/v1/runs/{run.id}/workspaces")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_manual_cleanup_api_cleans_terminal_run(project_factory, client):
    _project_id, requirement_id = await project_factory(name="清理手动项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
        run.status = "cancelled"
        await session.commit()

    root = await _make_workspace(run.id)
    assert root.exists()

    response = await client.delete(f"/api/v1/runs/{run.id}/workspaces")
    assert response.status_code == 200
    assert response.json()["removed"] == 1
    assert not root.exists()

    # 再删一次：幂等，removed=0
    again = await client.delete(f"/api/v1/runs/{run.id}/workspaces")
    assert again.status_code == 200
    assert again.json()["removed"] == 0


async def test_purge_expired_removes_old_and_orphan_dirs(project_factory):
    _project_id, requirement_id = await project_factory(name="保留期清理项目")
    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
        run.status = "failed"
        await session.commit()

    root = await _make_workspace(run.id)
    orphan = workspaces_root() / "run-99999999"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / "x.txt").write_text("orphan\n", encoding="utf-8")

    ten_days_ago = time.time() - 10 * 86400
    for path in (root, orphan):
        os.utime(path, (ten_days_ago, ten_days_ago))

    try:
        stats = await purge_expired_workspaces(retention_days=7)
        assert stats["removed"] >= 2
        assert not root.exists()
        assert not orphan.exists()

        async with get_session_factory()() as session:
            workspace = (
                await session.execute(
                    select(CodeWorkspace).where(CodeWorkspace.run_id == run.id)
                )
            ).scalar_one()
        assert workspace.cleaned_at is not None
    finally:
        cleanup_workspace(run.id)
        cleanup_workspace(99999999)

    # 新鲜目录不该被清（新起一个 run，避免 (run_id, attempt) 唯一键冲突）
    async with get_session_factory()() as session:
        fresh_run = await run_service.create_run(
            session, requirement_id, RunCreate(), enqueue=False
        )
        fresh_run.status = "failed"
        await session.commit()
    fresh = await _make_workspace(fresh_run.id)
    try:
        stats = await purge_expired_workspaces(retention_days=7)
        assert fresh.exists()
        assert stats["removed"] == 0
    finally:
        cleanup_workspace(fresh_run.id)
