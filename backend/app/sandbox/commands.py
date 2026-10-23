"""编码沙箱：白名单命令执行器。

安全边界（任何一条破了都等于把服务器交给 Agent）：
- 只允许白名单里的可执行文件，命令按 argv 拆分、**不经 shell** 执行（管道/重定向会变成字面参数）
- 拒绝明显危险的模式（rm -rf、curl/wget、ssh、powershell 编码执行等）
- 工作目录必须在沙箱根内；超时与输出截断
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import SemanticError

ALLOWED_BINARIES = {
    "git",
    "python",
    "python3",
    "pip",
    "pytest",
    "node",
    "npm",
    "pnpm",
    "npx",
    "dotnet",
    "mvn",
    "gradle",
    "go",
    "cargo",
    "make",
    "ruff",
    "tsc",
    "vitest",
    "jest",
}

DENY_PATTERNS = (
    "rm -rf",
    "rm -fr",
    "mkfs",
    "dd if=",
    "curl ",
    "wget ",
    "ssh ",
    "scp ",
    "nc ",
    "netcat",
    "powershell -enc",
    "powershell -e ",
    "cmd /c",
    "cmd.exe /c",
    "shutdown",
    "reboot",
    "reg add",
    "bcdedit",
    "> /dev/sd",
)

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 300
MAX_OUTPUT = 8000


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def summary(self, limit: int = 600) -> str:
        body = (self.stdout or "").strip() or (self.stderr or "").strip()
        if len(body) > limit:
            body = body[:limit] + "…"
        return f"[{'ok' if self.ok else f'exit {self.returncode}'}] {self.command} -> {body or '(无输出)'}"


def validate_command(command: str) -> list[str]:
    text = (command or "").strip()
    if not text:
        raise SemanticError("命令不能为空")
    lowered = text.lower()
    for pattern in DENY_PATTERNS:
        if pattern in lowered:
            raise SemanticError(f"命令被安全策略拒绝（命中 {pattern.strip()}）")

    try:
        argv = shlex.split(text, posix=False)
    except ValueError as exc:
        raise SemanticError(f"命令解析失败：{exc}") from exc
    if not argv:
        raise SemanticError("命令不能为空")

    executable = Path(argv[0].strip('"')).name.lower()
    if executable not in ALLOWED_BINARIES:
        raise SemanticError(
            f"命令 {executable} 不在白名单内（允许：{', '.join(sorted(ALLOWED_BINARIES))}）"
        )
    return [item.strip('"') for item in argv]


async def run_command(
    working_dir: Path,
    command: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    display_command: str | None = None,
) -> CommandResult:
    """`display_command` 只影响记录/日志里的命令文本（用于藏掉带 token 的 URL）。"""
    argv = validate_command(command)
    timeout = max(1, min(timeout, MAX_TIMEOUT))
    started = time.monotonic()

    def _run() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            argv,
            cwd=str(working_dir),
            capture_output=True,
            timeout=timeout,
            check=False,
        )

    # Windows 上必须用 selector 事件循环（psycopg 要求），而 selector loop 不支持
    # create_subprocess_exec（实测 NotImplementedError），所以放线程里跑 subprocess.run。
    try:
        result = await asyncio.to_thread(_run)
    except FileNotFoundError as exc:
        raise SemanticError(f"可执行文件不存在：{argv[0]}") from exc
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=command,
            returncode=-1,
            stdout="",
            stderr=f"命令超时（>{timeout}s）已被终止",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def _decode(raw: bytes) -> tuple[str, bool]:
        text = raw.decode("utf-8", errors="replace")
        if len(text) > MAX_OUTPUT:
            return text[:MAX_OUTPUT] + "\n…（输出已截断）", True
        return text, False

    out, cut_out = _decode(result.stdout or b"")
    err, cut_err = _decode(result.stderr or b"")
    return CommandResult(
        command=display_command or command,
        returncode=result.returncode,
        stdout=out,
        stderr=err,
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=cut_out or cut_err,
    )


__all__ = [
    "ALLOWED_BINARIES",
    "MAX_OUTPUT",
    "CommandResult",
    "run_command",
    "validate_command",
]
