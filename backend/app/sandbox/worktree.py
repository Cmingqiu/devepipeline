"""git worktree 沙箱（Windows 本机可用；Docker 模式留到后续）。

隔离手段：每个 run 一个独立 clone 目录 + 独立分支；命令只能在该目录内执行。
"""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from app.core.config import BACKEND_DIR, get_settings
from app.core.exceptions import SemanticError
from app.core.logging import get_logger
from app.sandbox.commands import CommandResult, run_command

logger = get_logger(__name__)

MAX_FILE_READ = 20_000
MAX_FILE_WRITE = 200_000
MAX_LIST = 200


def workspaces_root() -> Path:
    root = Path(get_settings().workspaces_dir)
    if not root.is_absolute():
        root = BACKEND_DIR / root
    return root


def _authenticated_url(repo_url: str, token: str | None) -> str:
    if not token or not repo_url.startswith("https://"):
        return repo_url
    scheme, rest = repo_url.split("://", 1)
    return f"{scheme}://x-access-token:{quote(token, safe='')}@{rest}"


def _redact(text: str, token: str | None) -> str:
    """git 报错会把带 token 的 URL 原样回显，落进产物/命令记录前必须替换掉。"""
    if not token or not text:
        return text
    return text.replace(token, "***").replace(quote(token, safe=""), "***")


@dataclass
class Workspace:
    run_id: int
    root: Path
    branch: str
    base_branch: str
    repo_url: str
    base_sha: str | None = None
    command_log: list[CommandResult] = field(default_factory=list)

    # ------------------------------------------------------------ 文件操作
    def _resolve(self, relative: str) -> Path:
        target = (self.root / (relative or ".")).resolve()
        root = self.root.resolve()
        if target != root and root not in target.parents:
            raise SemanticError(f"路径越界：{relative}")
        return target

    def list_files(self, path: str = ".") -> str:
        target = self._resolve(path)
        if not target.exists():
            return f"路径不存在：{path}"
        if target.is_file():
            return f"{path} (文件, {target.stat().st_size} bytes)"
        entries: list[str] = []
        for item in sorted(target.iterdir())[:MAX_LIST]:
            if item.name == ".git":
                continue
            suffix = "/" if item.is_dir() else ""
            entries.append(f"{item.relative_to(self.root).as_posix()}{suffix}")
        return "\n".join(entries) or "(空目录)"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise SemanticError(f"文件不存在：{path}")
        data = target.read_bytes()
        if len(data) > MAX_FILE_READ:
            raise SemanticError(f"文件过大（>{MAX_FILE_READ} bytes），请分段读取")
        return data.decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str) -> str:
        if len(content) > MAX_FILE_WRITE:
            raise SemanticError(f"单次写入超过 {MAX_FILE_WRITE} 字符上限")
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已写入 {path}（{len(content)} 字符）"

    async def run(self, command: str, timeout: int = 120) -> CommandResult:
        result = await run_command(self.root, command, timeout=timeout)
        self.command_log.append(result)
        return result

    async def diff(self) -> str:
        await self._git("add", "-A")
        result = await run_command(self.root, "git diff --cached --stat")
        body = await run_command(self.root, "git diff --cached")
        if not body.stdout.strip():
            return "(没有改动)"
        return f"{result.stdout.strip()}\n\n{body.stdout}"

    async def has_changes(self) -> bool:
        result = await self._git("status", "--porcelain")
        return bool(result.stdout.strip())

    async def head(self) -> str | None:
        result = await self._git("rev-parse", "HEAD")
        return result.stdout.strip() or None

    async def commit(self, message: str) -> str | None:
        """提交全部改动并返回新 HEAD；没有可提交内容时返回 None。

        commit message 带空格/中文，必须走 argv 直传：`run_command` 会做 shlex 拆分，
        未加引号的 message 会被拆成多条 pathspec（实测 git 报 pathspec did not match）。
        """
        await self._git("add", "-A")
        commit = await _run_git(
            [
                "git",
                "-c",
                "user.name=devpipeline",
                "-c",
                "user.email=devpipeline@local",
                "commit",
                "-m",
                message,
            ],
            cwd=self.root,
        )
        if not commit.ok:
            return None
        result = await self._git("rev-parse", "HEAD")
        return result.stdout.strip() or None

    async def push(self, token: str | None = None) -> CommandResult:
        """推送当前分支；命令行里带 token，所以记录与输出都要脱敏。"""
        url = _authenticated_url(self.repo_url, token)
        result = await run_command(
            self.root,
            f"git push {url} {self.branch}:{self.branch}",
            timeout=180,
            display_command=f"git push origin {self.branch}",
        )
        result.stdout = _redact(result.stdout, token)
        result.stderr = _redact(result.stderr, token)
        self.command_log.append(result)
        return result

    async def _git(self, *args: str) -> CommandResult:
        result = await run_command(self.root, " ".join(["git", *args]))
        if not result.ok and "commit" not in args:
            logger.warning(
                "sandbox_git_failed",
                extra={"run_id": self.run_id, "git_args": list(args), "stderr": result.stderr[:200]},
            )
        return result

    def command_log_summary(self, limit: int = 20) -> str:
        return "\n".join(item.summary() for item in self.command_log[-limit:])


async def prepare_workspace(
    *,
    run_id: int,
    repo_url: str,
    base_branch: str,
    branch: str,
    token: str | None = None,
) -> Workspace:
    root = workspaces_root() / f"run-{run_id}"
    url = _authenticated_url(repo_url, token)

    if (root / ".git").exists():
        # 恢复执行（审批后继续）复用同一目录；但半年前/中断留下的坏目录要重建
        head = await _run_git(["git", "rev-parse", "--verify", "HEAD"], cwd=root)
        if head.ok:
            return Workspace(
                run_id=run_id,
                root=root,
                branch=branch,
                base_branch=base_branch,
                repo_url=repo_url,
            )
        shutil.rmtree(root, ignore_errors=True)

    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)

    clone = await _run_git(
        ["git", "clone", "--branch", base_branch, url, str(root)],
        cwd=root.parent,
    )
    if not clone.ok:
        raise SemanticError(f"克隆仓库失败：{clone.stderr[-400:] or clone.stdout[-400:]}")

    checkout = await _run_git(["git", "checkout", "-b", branch], cwd=root)
    if not checkout.ok:
        raise SemanticError(f"创建分支失败：{checkout.stderr[-400:]}")

    head = await _run_git(["git", "rev-parse", "HEAD"], cwd=root)
    logger.info("workspace_prepared", extra={"run_id": run_id, "root": str(root)})
    return Workspace(
        run_id=run_id,
        root=root,
        branch=branch,
        base_branch=base_branch,
        repo_url=repo_url,
        base_sha=head.stdout.strip() or None,
    )


async def _run_git(argv: list[str], *, cwd: Path, timeout: int = 120) -> CommandResult:
    """git 走线程里的 subprocess（selector loop 不支持 create_subprocess_exec）。"""
    import subprocess
    import time

    started = time.monotonic()

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    try:
        result = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=" ".join(argv),
            returncode=-1,
            stdout="",
            stderr=f"git 超时（>{timeout}s）",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    return CommandResult(
        command=" ".join(argv),
        returncode=result.returncode,
        stdout=(result.stdout or b"").decode("utf-8", errors="replace")[:8000],
        stderr=(result.stderr or b"").decode("utf-8", errors="replace")[:8000],
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def cleanup_workspace(run_id: int) -> None:
    root = workspaces_root() / f"run-{run_id}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


__all__ = ["Workspace", "cleanup_workspace", "prepare_workspace", "workspaces_root"]
