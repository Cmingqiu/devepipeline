from __future__ import annotations

from app.sandbox.worktree import workspaces_root
from app.services.workspace_service import _norm, _under_root


def test_under_root_accepts_child_dir():
    target = workspaces_root() / "run-123"
    assert _under_root(target) is True


def test_under_root_rejects_root_and_outside():
    assert _under_root(workspaces_root()) is False
    assert _under_root(workspaces_root().parent) is False
    assert _under_root("C:/Windows") is False
    # 相似前缀不算子目录（run-12 vs run-123）
    assert _under_root(workspaces_root().parent / "workspaces-evil" / "run-1") is False


def test_norm_makes_windows_paths_comparable():
    target = workspaces_root() / "run-9"
    assert _norm(target) == _norm(str(target).replace("/", "\\"))
