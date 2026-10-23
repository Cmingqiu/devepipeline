"""项目级工具装配：MCP server 工具 + 技能文件读取工具。

MCP 配置里的凭证写法是 `$CRED:<credential_id>`（env/headers 里都行），加载时解密注入，
这样 DB 里不会出现明文 token。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import decrypt_secret
from app.models import Credential, McpConfig, Skill, SkillFile

logger = get_logger(__name__)

CRED_PATTERN = re.compile(r"^\$CRED:(\d+)$")
MCP_LOAD_TIMEOUT = 20.0
MAX_NAME_LEN = 64


def tool_name(server: str, name: str) -> str:
    """给 MCP 工具加 server 前缀，防止不同 server 重名；顺带清洗非法字符与长度。"""
    raw = f"{server}__{name}"
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    return cleaned[:MAX_NAME_LEN]


async def resolve_credentials(
    session: AsyncSession, project_id: int, value: Any
) -> Any:
    """递归把 `$CRED:<id>` 替换成解密后的明文；凭证必须属于本项目或全局（project_id=0）。"""
    if isinstance(value, dict):
        return {
            key: await resolve_credentials(session, project_id, item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [await resolve_credentials(session, project_id, item) for item in value]
    if isinstance(value, str):
        match = CRED_PATTERN.match(value.strip())
        if not match:
            return value
        credential = await session.get(Credential, int(match.group(1)))
        if credential is None or credential.project_id not in {0, project_id}:
            raise ValueError(f"凭证 {match.group(1)} 不存在或不属于本项目")
        return decrypt_secret(credential.encrypted_blob, credential.key_version)
    return value


async def _skill_tool(session: AsyncSession, project_id: int):
    """按需读取技能包里的文件（SKILL.md 正文已注入 prompt，这里用于看脚本/参考资料）。"""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class ReadSkillArgs(BaseModel):
        skill: str = Field(description="技能包名称")
        path: str = Field(description="技能包内相对路径，例如 scripts/check.sh")

    async def _read(skill: str, path: str) -> str:
        row = (
            await session.execute(
                select(SkillFile)
                .join(Skill, Skill.id == SkillFile.skill_id)
                .where(
                    Skill.project_id == project_id,
                    Skill.name == skill,
                    SkillFile.path == path,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return f"未找到技能文件：{skill}/{path}（二进制文件无法读取）"
        return row.content[:8000]

    async def _read_tool(skill: str, path: str) -> str:
        return await _read(skill, path)

    return StructuredTool.from_function(
        coroutine=_read_tool,
        name="read_skill_file",
        description="读取项目技能包内的文本文件（技能名 + 相对路径）。",
        args_schema=ReadSkillArgs,
    )


async def build_mcp_tools(
    session: AsyncSession, project_id: int
) -> tuple[list[Any], list[dict[str, Any]]]:
    """按项目配置加载 MCP 工具；单个 server 失败只记录诊断，不影响其它。"""
    rows = list(
        (
            await session.execute(
                select(McpConfig).where(
                    McpConfig.project_id == project_id, McpConfig.enabled.is_(True)
                )
            )
        ).scalars().all()
    )
    connections: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for row in rows:
        try:
            config = json.loads(row.config_json or "{}")
            config = await resolve_credentials(session, project_id, config)
        except Exception as exc:  # noqa: BLE001  凭证/JSON 坏了就跳过这个 server
            diagnostics.append({"server": row.name, "ok": False, "error": str(exc)[:300]})
            continue

        if row.transport == "stdio":
            if not config.get("command"):
                diagnostics.append({"server": row.name, "ok": False, "error": "缺少 command"})
                continue
            connections[row.name] = {
                "transport": "stdio",
                "command": config["command"],
                "args": list(config.get("args") or []),
                "env": {str(k): str(v) for k, v in (config.get("env") or {}).items()},
            }
        else:
            if not config.get("url"):
                diagnostics.append({"server": row.name, "ok": False, "error": "缺少 url"})
                continue
            connections[row.name] = {
                "transport": "streamable_http",
                "url": config["url"],
                "headers": {str(k): str(v) for k, v in (config.get("headers") or {}).items()},
            }

    if not connections:
        return [], diagnostics

    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient(connections)
        tools: list[Any] = []
        for server in connections:
            try:
                server_tools = await asyncio.wait_for(
                    client.get_tools(server_name=server), timeout=MCP_LOAD_TIMEOUT
                )
                for item in server_tools:
                    item.name = tool_name(server, item.name)
                tools.extend(server_tools)
                diagnostics.append({"server": server, "ok": True, "tools": len(server_tools)})
            except TimeoutError:
                diagnostics.append({"server": server, "ok": False, "error": "加载超时"})
            except Exception as exc:  # noqa: BLE001  单 server 失败隔离
                diagnostics.append(
                    {"server": server, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
                )
        return tools, diagnostics
    except Exception as exc:
        logger.exception("mcp_tools_init_failed")
        return [], [*diagnostics, {"server": "*", "ok": False, "error": str(exc)[:300]}]


async def load_project_tools(
    session: AsyncSession, project_id: int
) -> tuple[list[Any], list[dict[str, Any]]]:
    tools, diagnostics = await build_mcp_tools(session, project_id)

    has_skill = (
        await session.execute(
            select(Skill.id).where(Skill.project_id == project_id, Skill.enabled.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if has_skill is not None:
        tools.append(await _skill_tool(session, project_id))

    if diagnostics:
        logger.info(
            "project_tools_loaded",
            extra={"project_id": project_id, "tools": len(tools), "diagnostics": diagnostics},
        )
    return tools, diagnostics


def tools_enabled() -> bool:
    return get_settings().tools_enabled


__all__ = [
    "build_mcp_tools",
    "load_project_tools",
    "resolve_credentials",
    "tool_name",
    "tools_enabled",
]
