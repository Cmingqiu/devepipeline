"""当前 run 可用的工具（进程内注册表）。

为什么不放进 state / config：工具对象带 MCP 客户端与网络句柄，不可序列化、也不该进 checkpoint。
执行器在每次执行/恢复前按项目重新加载并注册，节点只按 run_id 取。
"""

from __future__ import annotations

from typing import Any

_TOOLS: dict[int, list[Any]] = {}


def set_run_tools(run_id: int, tools: list[Any]) -> None:
    if tools:
        _TOOLS[run_id] = tools


def get_run_tools(run_id: int | None) -> list[Any]:
    if run_id is None:
        return []
    return _TOOLS.get(int(run_id), [])


def clear_run_tools(run_id: int) -> None:
    _TOOLS.pop(run_id, None)
