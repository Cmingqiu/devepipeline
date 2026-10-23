from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, SemanticError
from app.core.logging import get_logger
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.db.base import utcnow
from app.models import AgentDoc, Credential, McpConfig, Project, Skill, SkillFile
from app.schemas.context import CredentialIn, McpServerIn, RepoConfigIn
from app.services import mcp_probe, storage
from app.services.skill_pack import read_skill_zip, write_skill_pack

logger = get_logger(__name__)

SKILL_ENTRY_MAX_CHARS = 4000
SKILL_TOTAL_MAX_CHARS = 12000


async def _project_or_404(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise NotFoundError("项目不存在")
    return project


# ---------------------------------------------------------------- AGENTS.md


async def get_active_agent_doc(session: AsyncSession, project_id: int) -> AgentDoc | None:
    await _project_or_404(session, project_id)
    stmt = (
        select(AgentDoc)
        .where(AgentDoc.project_id == project_id, AgentDoc.is_active.is_(True))
        .order_by(AgentDoc.version.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def upsert_agent_doc(session: AsyncSession, project_id: int, content: str) -> AgentDoc:
    await _project_or_404(session, project_id)
    current = await get_active_agent_doc(session, project_id)
    if current is not None and current.content == content:
        return current

    next_version = int(
        (
            await session.execute(
                select(func.coalesce(func.max(AgentDoc.version), 0)).where(
                    AgentDoc.project_id == project_id
                )
            )
        ).scalar_one()
    ) + 1

    await session.execute(
        AgentDoc.__table__.update()
        .where(AgentDoc.project_id == project_id)
        .values(is_active=False)
    )
    doc = AgentDoc(project_id=project_id, version=next_version, content=content, is_active=True)
    session.add(doc)
    await session.commit()
    return doc


async def list_agent_versions(session: AsyncSession, project_id: int) -> list[AgentDoc]:
    await _project_or_404(session, project_id)
    stmt = (
        select(AgentDoc)
        .where(AgentDoc.project_id == project_id)
        .order_by(AgentDoc.version.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ------------------------------------------------------------------- Skills


async def list_skills(session: AsyncSession, project_id: int) -> list[tuple[Skill, int]]:
    await _project_or_404(session, project_id)
    stmt = (
        select(Skill, func.count(SkillFile.id))
        .outerjoin(SkillFile, SkillFile.skill_id == Skill.id)
        .where(Skill.project_id == project_id)
        .group_by(Skill.id)
        .order_by(Skill.name)
    )
    return [(skill, int(count)) for skill, count in (await session.execute(stmt)).all()]


async def get_skill(session: AsyncSession, project_id: int, skill_id: int) -> Skill:
    skill = await session.get(Skill, skill_id)
    if skill is None or skill.project_id != project_id:
        raise NotFoundError("技能包不存在")
    return skill


async def get_skill_detail(
    session: AsyncSession, project_id: int, skill_id: int
) -> tuple[Skill, list[SkillFile]]:
    skill = await get_skill(session, project_id, skill_id)
    files = list(
        (
            await session.execute(
                select(SkillFile)
                .where(SkillFile.skill_id == skill.id)
                .order_by(SkillFile.path)
            )
        ).scalars().all()
    )
    return skill, files


async def upload_skill(
    session: AsyncSession, project_id: int, raw: bytes, filename: str
) -> Skill:
    await _project_or_404(session, project_id)
    pack = read_skill_zip(raw)

    existing = (
        await session.execute(
            select(Skill).where(Skill.project_id == project_id, Skill.name == pack.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # 同名技能包按「覆盖」处理：重传是最常见的迭代路径
        await session.execute(SkillFile.__table__.delete().where(SkillFile.skill_id == existing.id))
        skill = existing
        skill.description = pack.description
        skill.entry_path = pack.entry_path
        skill.manifest_json = pack.manifest
        skill.updated_at = utcnow()
    else:
        skill = Skill(
            project_id=project_id,
            name=pack.name,
            description=pack.description,
            entry_path=pack.entry_path,
            storage_dir="",
            manifest_json=pack.manifest,
        )
        session.add(skill)
    await session.flush()

    target = storage.ensure_skill_dir(project_id, skill.id)
    write_skill_pack(pack, raw, target)
    skill.storage_dir = str(target)

    for item in pack.files:
        if item.content is None:
            continue
        session.add(
            SkillFile(
                skill_id=skill.id,
                path=item.path,
                content=item.content,
                size_bytes=item.size,
                sha256=item.sha256,
            )
        )
    await session.commit()
    logger.info("skill_uploaded", extra={"skill": pack.name, "files": len(pack.files)})
    return skill


async def get_skill_file(
    session: AsyncSession, project_id: int, skill_id: int, path: str
) -> SkillFile:
    skill = await get_skill(session, project_id, skill_id)
    file = (
        await session.execute(
            select(SkillFile).where(SkillFile.skill_id == skill.id, SkillFile.path == path).limit(1)
        )
    ).scalar_one_or_none()
    if file is None:
        raise NotFoundError("技能文件不存在（或为二进制文件，只能看磁盘副本）")
    return file


async def delete_skill(session: AsyncSession, project_id: int, skill_id: int) -> None:
    skill = await get_skill(session, project_id, skill_id)
    await session.execute(SkillFile.__table__.delete().where(SkillFile.skill_id == skill.id))
    await session.delete(skill)
    await session.commit()
    storage.remove_skill_dir(project_id, skill_id)


async def skill_prompt_snapshot(session: AsyncSession, project_id: int) -> list[dict[str, str]]:
    """注入 prompt 用的技能快照：名称、描述、SKILL.md 正文（有上限）。"""
    skills = list(
        (
            await session.execute(
                select(Skill).where(Skill.project_id == project_id, Skill.enabled.is_(True)).order_by(Skill.name)
            )
        ).scalars().all()
    )
    snapshot: list[dict[str, str]] = []
    total = 0
    for skill in skills:
        entry = (
            await session.execute(
                select(SkillFile.content).where(
                    SkillFile.skill_id == skill.id, SkillFile.path == skill.entry_path
                )
            )
        ).scalar_one_or_none() or ""
        entry = entry[:SKILL_ENTRY_MAX_CHARS]
        if total + len(entry) > SKILL_TOTAL_MAX_CHARS:
            break
        total += len(entry)
        snapshot.append(
            {"name": skill.name, "description": skill.description, "entry": entry}
        )
    return snapshot


# ---------------------------------------------------------------------- MCP


def _config_payload(server: McpServerIn) -> str:
    return json.dumps(server.config, ensure_ascii=False)


async def list_mcp(session: AsyncSession, project_id: int) -> list[McpConfig]:
    await _project_or_404(session, project_id)
    stmt = select(McpConfig).where(McpConfig.project_id == project_id).order_by(McpConfig.name)
    return list((await session.execute(stmt)).scalars().all())


async def replace_mcp(
    session: AsyncSession, project_id: int, servers: list[McpServerIn]
) -> list[McpConfig]:
    """整体覆盖：按 name upsert，未出现的删除。"""
    await _project_or_404(session, project_id)
    existing = {
        row.name: row
        for row in (
            await session.execute(select(McpConfig).where(McpConfig.project_id == project_id))
        ).scalars().all()
    }
    keep: set[str] = set()
    for server in servers:
        keep.add(server.name)
        row = existing.get(server.name)
        if row is None:
            row = McpConfig(project_id=project_id, name=server.name)
            session.add(row)
        row.transport = server.transport
        row.config_json = _config_payload(server)
        row.enabled = server.enabled
        row.updated_at = utcnow()

    for name, row in existing.items():
        if name not in keep:
            await session.delete(row)
    await session.commit()
    return await list_mcp(session, project_id)


async def delete_mcp(session: AsyncSession, project_id: int, name: str) -> None:
    row = (
        await session.execute(
            select(McpConfig).where(McpConfig.project_id == project_id, McpConfig.name == name)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("MCP 配置不存在")
    await session.delete(row)
    await session.commit()


def _parse_config(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


async def test_mcp(
    session: AsyncSession, project_id: int, servers: list[McpServerIn] | None
) -> list[dict[str, Any]]:
    if servers is None:
        rows = await list_mcp(session, project_id)
        targets = [
            {
                "name": row.name,
                "transport": row.transport,
                "config": _parse_config(row.config_json),
                "row": row,
            }
            for row in rows
        ]
    else:
        targets = [
            {"name": s.name, "transport": s.transport, "config": s.config, "row": None}
            for s in servers
        ]

    results = await asyncio.gather(
        *(
            mcp_probe.probe_server(item["name"], item["transport"], item["config"])
            for item in targets
        )
    )

    payload: list[dict[str, Any]] = []
    for item, (ok, tools, error) in zip(targets, results, strict=True):
        row: McpConfig | None = item["row"]
        if row is not None:
            row.last_test_status = "ok" if ok else "failed"
            row.last_test_at = utcnow()
            row.last_test_message = (f"{len(tools)} 个工具" if ok else (error or "")[:1000])
        payload.append({"name": item["name"], "ok": ok, "tools": tools, "error": error})
    if any(item["row"] is not None for item in targets):
        await session.commit()
    return payload


# ---------------------------------------------------------------- 仓库与凭证


async def get_repo(session: AsyncSession, project_id: int) -> tuple[Project, str | None]:
    project = await _project_or_404(session, project_id)
    hint = None
    if project.credential_id:
        credential = await session.get(Credential, project.credential_id)
        hint = credential.hint if credential else None
    return project, hint


async def update_repo(session: AsyncSession, project_id: int, payload: RepoConfigIn) -> Project:
    project = await _project_or_404(session, project_id)
    if payload.credential_id is not None:
        credential = await session.get(Credential, payload.credential_id)
        if credential is None or credential.project_id not in {0, project_id}:
            raise NotFoundError("凭证不存在")
    project.repo_url = payload.repo_url
    project.repo_provider = payload.repo_provider
    project.default_branch = payload.default_branch
    project.credential_id = payload.credential_id
    await session.commit()
    return project


async def create_credential(
    session: AsyncSession, project_id: int, payload: CredentialIn
) -> Credential:
    await _project_or_404(session, project_id)
    blob, key_version = encrypt_secret(payload.secret)
    row = (
        await session.execute(
            select(Credential).where(
                Credential.project_id == project_id, Credential.name == payload.name
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = Credential(project_id=project_id, name=payload.name)
        session.add(row)
    row.kind = payload.kind
    row.encrypted_blob = blob
    row.key_version = key_version
    row.hint = mask_secret(payload.secret)
    await session.commit()
    return row


async def list_credentials(session: AsyncSession, project_id: int) -> list[Credential]:
    await _project_or_404(session, project_id)
    stmt = select(Credential).where(Credential.project_id == project_id).order_by(Credential.name)
    return list((await session.execute(stmt)).scalars().all())


async def delete_credential(session: AsyncSession, project_id: int, credential_id: int) -> None:
    row = await session.get(Credential, credential_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("凭证不存在")
    await session.delete(row)
    await session.commit()


def _authenticated_url(repo_url: str, token: str | None) -> str:
    if not token or not repo_url.startswith("https://"):
        return repo_url
    scheme, rest = repo_url.split("://", 1)
    return f"{scheme}://x-access-token:{token}@{rest}"


async def test_repo(session: AsyncSession, project_id: int) -> tuple[bool, str]:
    project = await _project_or_404(session, project_id)
    if not project.repo_url:
        raise SemanticError("还没有配置仓库地址")

    token: str | None = None
    if project.credential_id:
        credential = await session.get(Credential, project.credential_id)
        if credential is not None:
            token = decrypt_secret(credential.encrypted_blob, credential.key_version)

    url = _authenticated_url(project.repo_url, token)

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "ls-remote", "--heads", url],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    try:
        result = await asyncio.to_thread(_run)
    except FileNotFoundError:
        raise SemanticError("本机没有 git 命令") from None
    except subprocess.TimeoutExpired:
        return False, "连接超时（20s）"

    if result.returncode == 0:
        count = len([line for line in result.stdout.splitlines() if line.strip()])
        return True, f"连接成功，{count} 个分支"
    message = (result.stderr or result.stdout or "").strip().splitlines()
    # 不要把带 token 的 URL 回显给前端
    detail = (message[-1] if message else "未知错误").replace(url, "<repo>")
    return False, detail[:500]


__all__ = [
    "create_credential",
    "delete_credential",
    "delete_mcp",
    "delete_skill",
    "get_active_agent_doc",
    "get_repo",
    "get_skill",
    "get_skill_detail",
    "get_skill_file",
    "list_agent_versions",
    "list_credentials",
    "list_mcp",
    "list_skills",
    "replace_mcp",
    "skill_prompt_snapshot",
    "test_mcp",
    "test_repo",
    "update_repo",
    "upload_skill",
    "upsert_agent_doc",
]
