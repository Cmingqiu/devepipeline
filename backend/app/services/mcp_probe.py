"""MCP 连通性探测：用 langchain-mcp-adapters 起会话、列工具。"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

PROBE_TIMEOUT = 15.0
SENSITIVE_KEYS = ("token", "secret", "key", "password", "authorization")


async def probe_server(name: str, transport: str, config: dict[str, Any]) -> tuple[bool, list[str], str | None]:
    """返回 (ok, tool_names, error)。单个 server 失败不影响其它。"""

    connection: dict[str, Any] = {"transport": transport}
    if transport == "stdio":
        connection.update(
            {
                "command": config.get("command"),
                "args": list(config.get("args") or []),
                "env": {str(k): str(v) for k, v in (config.get("env") or {}).items()},
            }
        )
    else:
        connection.update(
            {
                "url": config.get("url"),
                "headers": {str(k): str(v) for k, v in (config.get("headers") or {}).items()},
            }
        )

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({name: connection})
        tools = await asyncio.wait_for(client.get_tools(server_name=name), timeout=PROBE_TIMEOUT)
        return True, [tool.name for tool in tools], None
    except TimeoutError:
        return False, [], f"连接超时（{int(PROBE_TIMEOUT)}s）"
    except Exception as exc:  # noqa: BLE001  探测失败要变成结构化结果，不能抛到接口层
        logger.warning("mcp_probe_failed", extra={"server": name, "error": str(exc)[:200]})
        return False, [], f"{type(exc).__name__}: {exc}"[:500]


def mask_config(value: Any) -> Any:
    """输出给前端时把敏感值替换成 ****（按 key 名判断，递归）。"""
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in SENSITIVE_KEYS) and isinstance(item, str):
                masked[key] = "****" if len(item) <= 4 else f"****{item[-4:]}"
            else:
                masked[key] = mask_config(item)
        return masked
    if isinstance(value, list):
        return [mask_config(item) for item in value]
    return value
