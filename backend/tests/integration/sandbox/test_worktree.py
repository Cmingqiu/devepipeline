"""worktree 沙箱集成测试：用本机临时 git 仓库，不依赖网络与 Docker。"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from app.core.exceptions import SemanticError
from app.sandbox.worktree import cleanup_workspace, prepare_workspace


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={"GIT_TERMINAL_PROMPT": "0", "PATH": __import__("os").environ.get("PATH", "")},
    )


@pytest.fixture
def seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "seed"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    (repo / "test_sample.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    return repo


async def test_prepare_write_run_and_diff(seed_repo: Path) -> None:
    run_id = uuid.uuid4().int % 900_000_000 + 100_000
    try:
        workspace = await prepare_workspace(
            run_id=run_id,
            repo_url=str(seed_repo),
            base_branch="main",
            branch=f"devpipeline/run-{run_id}",
        )
        assert (workspace.root / "README.md").exists()
        assert workspace.base_sha

        workspace.write_file("src/feature.py", "def add(a, b):\n    return a + b\n")
        assert "feature.py" in workspace.list_files("src")
        assert "src/" in workspace.list_files(".")
        assert "return a + b" in workspace.read_file("src/feature.py")

        status = await workspace.run("git status --short")
        assert status.ok
        assert "src/" in status.stdout

        pytest_result = await workspace.run("python -m pytest -q")
        assert pytest_result.ok, pytest_result.stderr

        diff = await workspace.diff()
        assert "diff --git" in diff
        assert "feature.py" in diff

        # 路径越界必须拒绝
        with pytest.raises(SemanticError):
            workspace.read_file("../outside.txt")
        with pytest.raises(SemanticError):
            workspace.write_file("../../escape.txt", "x")
    finally:
        cleanup_workspace(run_id)


async def test_reuse_existing_workspace(seed_repo: Path) -> None:
    run_id = uuid.uuid4().int % 900_000_000 + 100_000
    try:
        first = await prepare_workspace(
            run_id=run_id, repo_url=str(seed_repo), base_branch="main", branch=f"devpipeline/run-{run_id}"
        )
        first.write_file("keep.txt", "keep\n")
        second = await prepare_workspace(
            run_id=run_id, repo_url=str(seed_repo), base_branch="main", branch=f"devpipeline/run-{run_id}"
        )
        # 审批后继续执行不应把已有改动冲掉
        assert (second.root / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    finally:
        cleanup_workspace(run_id)


async def test_bad_repo_raises(tmp_path: Path) -> None:
    run_id = uuid.uuid4().int % 900_000_000 + 100_000
    with pytest.raises(SemanticError):
        await prepare_workspace(
            run_id=run_id,
            repo_url=str(tmp_path / "does-not-exist"),
            base_branch="main",
            branch="devpipeline/run-x",
        )
    shutil.rmtree(tmp_path / "workspaces", ignore_errors=True)
    cleanup_workspace(run_id)
