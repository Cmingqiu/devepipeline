"""编码 agent 的沙箱工具：列目录 / 读写文件 / 跑白名单命令 / 看 diff。"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.sandbox.worktree import Workspace

LIST_DESC = "列出沙箱工作区某个目录下的文件（相对路径）。"
READ_DESC = "读取沙箱工作区里的文本文件。"
WRITE_DESC = "写入/覆盖沙箱工作区里的文件（相对路径，内容为完整文件内容）。"
RUN_DESC = "在沙箱工作区执行白名单命令（如 pytest -q、pnpm test、git status），返回退出码与输出摘要。"
DIFF_DESC = "查看当前工作区相对基准分支的全部改动（unified diff）。"


class ListArgs(BaseModel):
    path: str = Field(default=".", description="相对目录，默认仓库根")


class PathArgs(BaseModel):
    path: str = Field(description="相对仓库根的路径")


class WriteArgs(BaseModel):
    path: str = Field(description="相对仓库根的路径")
    content: str = Field(description="完整文件内容")


class RunArgs(BaseModel):
    command: str = Field(description="要执行的命令，例如 pytest -q")
    timeout: int = Field(default=120, ge=1, le=300, description="超时秒数")


def build_sandbox_tools(workspace: Workspace) -> list[Any]:
    async def _list(path: str = ".") -> str:
        return workspace.list_files(path)

    async def _read(path: str) -> str:
        return workspace.read_file(path)

    async def _write(path: str, content: str) -> str:
        return workspace.write_file(path, content)

    async def _run(command: str, timeout: int = 120) -> str:
        result = await workspace.run(command, timeout=timeout)
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        parts = [f"exit={result.returncode}", f"duration_ms={result.duration_ms}"]
        if output:
            parts.append(f"stdout:\n{output}")
        if error:
            parts.append(f"stderr:\n{error}")
        if result.truncated:
            parts.append("（输出已截断）")
        return "\n".join(parts)

    async def _diff() -> str:
        return await workspace.diff()

    return [
        StructuredTool.from_function(
            coroutine=_list, name="sandbox_list_files", description=LIST_DESC, args_schema=ListArgs
        ),
        StructuredTool.from_function(
            coroutine=_read, name="sandbox_read_file", description=READ_DESC, args_schema=PathArgs
        ),
        StructuredTool.from_function(
            coroutine=_write, name="sandbox_write_file", description=WRITE_DESC, args_schema=WriteArgs
        ),
        StructuredTool.from_function(
            coroutine=_run, name="sandbox_run_command", description=RUN_DESC, args_schema=RunArgs
        ),
        StructuredTool.from_function(
            coroutine=_diff, name="sandbox_git_diff", description=DIFF_DESC, args_schema=BaseModel
        ),
    ]


__all__ = ["build_sandbox_tools"]
