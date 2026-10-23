from __future__ import annotations

import json

from fastapi import APIRouter, File, Response, UploadFile, status

from app.api.v1.deps import SessionDep
from app.schemas.context import (
    AgentDocDetail,
    AgentDocOut,
    AgentDocUpsert,
    CredentialIn,
    CredentialOut,
    McpConfigOut,
    McpServerIn,
    McpServersIn,
    McpTestIn,
    McpTestResult,
    RepoConfigIn,
    RepoConfigOut,
    RepoTesResult,
    SkillDetail,
    SkillFileDetail,
    SkillFileOut,
    SkillOut,
)
from app.services import context_service, mcp_probe

router = APIRouter(tags=["contexts"])


def _doc_detail(doc) -> AgentDocDetail:
    return AgentDocDetail(
        id=doc.id,
        project_id=doc.project_id,
        version=doc.version,
        is_active=doc.is_active,
        created_at=doc.created_at,
        content=doc.content,
    )


@router.get(
    "/projects/{project_id}/agents-md",
    response_model=AgentDocDetail,
    responses={204: {"description": "还没配置 AGENTS.md"}},
    summary="当前生效的 AGENTS.md",
)
async def get_agents_md(session: SessionDep, project_id: int):
    doc = await context_service.get_active_agent_doc(session, project_id)
    if doc is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return _doc_detail(doc)


@router.put("/projects/{project_id}/agents-md", response_model=AgentDocDetail, summary="保存 AGENTS.md（新版本并置为生效）")
async def put_agents_md(session: SessionDep, project_id: int, payload: AgentDocUpsert):
    doc = await context_service.upsert_agent_doc(session, project_id, payload.content)
    return _doc_detail(doc)


@router.get(
    "/projects/{project_id}/agents-md/versions",
    response_model=list[AgentDocOut],
    summary="AGENTS.md 版本列表（不含正文）",
)
async def list_agents_md_versions(session: SessionDep, project_id: int) -> list[AgentDocOut]:
    docs = await context_service.list_agent_versions(session, project_id)
    return [
        AgentDocOut(
            id=doc.id,
            project_id=doc.project_id,
            version=doc.version,
            is_active=doc.is_active,
            created_at=doc.created_at,
        )
        for doc in docs
    ]


def _skill_out(skill, file_count: int) -> SkillOut:
    return SkillOut(
        id=skill.id,
        project_id=skill.project_id,
        name=skill.name,
        description=skill.description,
        entry_path=skill.entry_path,
        enabled=skill.enabled,
        file_count=file_count,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


@router.get("/projects/{project_id}/skills", response_model=list[SkillOut], summary="技能包列表")
async def list_skills(session: SessionDep, project_id: int) -> list[SkillOut]:
    rows = await context_service.list_skills(session, project_id)
    return [_skill_out(skill, count) for skill, count in rows]


@router.post(
    "/projects/{project_id}/skills",
    response_model=SkillDetail,
    status_code=status.HTTP_201_CREATED,
    summary="上传技能包 zip（含 SKILL.md，同名覆盖）",
)
async def upload_skill(
    session: SessionDep, project_id: int, file: UploadFile = File(..., description="技能包 zip")  # noqa: B008
) -> SkillDetail:
    raw = await file.read(get_settings_max_bytes() + 1)
    skill = await context_service.upload_skill(session, project_id, raw, file.filename or "skill.zip")
    _, files = await context_service.get_skill_detail(session, project_id, skill.id)
    return SkillDetail(
        **_skill_out(skill, len(files)).model_dump(),
        files=[
            SkillFileOut(
                path=item.path, size_bytes=item.size_bytes, sha256=item.sha256, is_text=True
            )
            for item in files
        ],
    )


def get_settings_max_bytes() -> int:
    from app.core.config import get_settings

    return get_settings().skill_zip_max_mb * 1024 * 1024


@router.get("/projects/{project_id}/skills/{skill_id}", response_model=SkillDetail, summary="技能包详情（文件树）")
async def get_skill(session: SessionDep, project_id: int, skill_id: int) -> SkillDetail:
    skill, files = await context_service.get_skill_detail(session, project_id, skill_id)
    return SkillDetail(
        **_skill_out(skill, len(files)).model_dump(),
        files=[
            SkillFileOut(
                path=item.path, size_bytes=item.size_bytes, sha256=item.sha256, is_text=True
            )
            for item in files
        ],
    )


@router.get(
    "/projects/{project_id}/skills/{skill_id}/files/{path:path}",
    response_model=SkillFileDetail,
    summary="技能包单个文本文件",
)
async def get_skill_file(session: SessionDep, project_id: int, skill_id: int, path: str) -> SkillFileDetail:
    item = await context_service.get_skill_file(session, project_id, skill_id, path)
    return SkillFileDetail(
        path=item.path,
        size_bytes=item.size_bytes,
        sha256=item.sha256,
        is_text=True,
        content=item.content,
    )


@router.delete(
    "/projects/{project_id}/skills/{skill_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除技能包（含磁盘目录）",
)
async def delete_skill(session: SessionDep, project_id: int, skill_id: int) -> None:
    await context_service.delete_skill(session, project_id, skill_id)


def _mcp_out(row) -> McpConfigOut:
    return McpConfigOut(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        transport=row.transport,
        config=mcp_probe.mask_config(json.loads(row.config_json or "{}")),
        enabled=row.enabled,
        last_test_status=row.last_test_status,
        last_test_at=row.last_test_at,
        last_test_message=row.last_test_message,
    )


@router.get("/projects/{project_id}/mcp", response_model=list[McpConfigOut], summary="MCP server 列表（敏感值已掩码）")
async def list_mcp(session: SessionDep, project_id: int) -> list[McpConfigOut]:
    return [_mcp_out(row) for row in await context_service.list_mcp(session, project_id)]


@router.put(
    "/projects/{project_id}/mcp",
    response_model=list[McpConfigOut],
    summary="整体覆盖 MCP 配置（按 name upsert，未出现的删除）",
)
async def put_mcp(session: SessionDep, project_id: int, payload: McpServersIn) -> list[McpConfigOut]:
    rows = await context_service.replace_mcp(session, project_id, payload.servers)
    return [_mcp_out(row) for row in rows]


@router.post(
    "/projects/{project_id}/mcp/test",
    response_model=list[McpTestResult],
    summary="MCP 连通性测试（不传 servers 则测已保存的）",
)
async def test_mcp(session: SessionDep, project_id: int, payload: McpTestIn | None = None):
    servers: list[McpServerIn] | None = payload.servers if payload else None
    results = await context_service.test_mcp(session, project_id, servers)
    return [McpTestResult(**item) for item in results]


@router.delete(
    "/projects/{project_id}/mcp/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除单个 MCP server",
)
async def delete_mcp(session: SessionDep, project_id: int, name: str) -> None:
    await context_service.delete_mcp(session, project_id, name)


@router.get("/projects/{project_id}/repo", response_model=RepoConfigOut, summary="目标仓库配置")
async def get_repo(session: SessionDep, project_id: int) -> RepoConfigOut:
    project, hint = await context_service.get_repo(session, project_id)
    return RepoConfigOut(
        repo_url=project.repo_url,
        repo_provider=project.repo_provider,
        default_branch=project.default_branch,
        credential_id=project.credential_id,
        credential_hint=hint,
    )


@router.put("/projects/{project_id}/repo", response_model=RepoConfigOut, summary="保存目标仓库配置")
async def put_repo(session: SessionDep, project_id: int, payload: RepoConfigIn) -> RepoConfigOut:
    project = await context_service.update_repo(session, project_id, payload)
    _, hint = await context_service.get_repo(session, project_id)
    return RepoConfigOut(
        repo_url=project.repo_url,
        repo_provider=project.repo_provider,
        default_branch=project.default_branch,
        credential_id=project.credential_id,
        credential_hint=hint,
    )


@router.post("/projects/{project_id}/repo/test", response_model=RepoTesResult, summary="仓库连通性测试（git ls-remote）")
async def test_repo(session: SessionDep, project_id: int) -> RepoTesResult:
    ok, message = await context_service.test_repo(session, project_id)
    return RepoTesResult(ok=ok, message=message)


@router.get(
    "/projects/{project_id}/credentials",
    response_model=list[CredentialOut],
    summary="凭证列表（只回掩码）",
)
async def list_credentials(session: SessionDep, project_id: int) -> list[CredentialOut]:
    rows = await context_service.list_credentials(session, project_id)
    return [CredentialOut.model_validate(row) for row in rows]


@router.post(
    "/projects/{project_id}/credentials",
    response_model=CredentialOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建/覆盖凭证（加密入库，响应不含明文）",
)
async def create_credential(
    session: SessionDep, project_id: int, payload: CredentialIn
) -> CredentialOut:
    row = await context_service.create_credential(session, project_id, payload)
    return CredentialOut.model_validate(row)


@router.delete(
    "/projects/{project_id}/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除凭证",
)
async def delete_credential(session: SessionDep, project_id: int, credential_id: int) -> None:
    await context_service.delete_credential(session, project_id, credential_id)


__all__ = ["router"]
