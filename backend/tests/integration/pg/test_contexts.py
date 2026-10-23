from __future__ import annotations

import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import get_session_factory
from app.main import create_app
from app.schemas.run import RunCreate
from app.services import run_service
from app.services.run_executor import execute_run
from app.services.storage import skill_dir

pytestmark = pytest.mark.pg

SKILL_MD = """---
name: code-review
description: 按团队规范做代码评审
---

# Code Review
1. 先看接口契约。
"""


def skill_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SKILL_MD)
        archive.writestr("scripts/check.sh", "echo ok\n")
    return buffer.getvalue()


@pytest.fixture
async def api():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def test_agents_md_versions_and_active(api, project_factory):
    project_id, _ = await project_factory(name="AGENTS 项目")
    path = f"/api/v1/projects/{project_id}/agents-md"

    assert (await api.get(path)).status_code == 204

    first = await api.put(path, json={"content": "# 规范 v1\n用 pnpm。"})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1

    second = await api.put(path, json={"content": "# 规范 v2\n用 pnpm + ruff。"})
    assert second.json()["version"] == 2
    assert second.json()["is_active"] is True

    current = (await api.get(path)).json()
    assert current["version"] == 2
    assert "ruff" in current["content"]

    versions = (await api.get(f"{path}/versions")).json()
    assert [item["version"] for item in versions] == [2, 1]
    assert sum(1 for item in versions if item["is_active"]) == 1


async def test_same_content_does_not_create_new_version(api, project_factory):
    project_id, _ = await project_factory(name="AGENTS 幂等")
    path = f"/api/v1/projects/{project_id}/agents-md"
    await api.put(path, json={"content": "same"})
    again = await api.put(path, json={"content": "same"})
    assert again.json()["version"] == 1


async def test_skill_upload_preview_and_delete(api, project_factory):
    project_id, _ = await project_factory(name="Skills 项目")

    created = await api.post(
        f"/api/v1/projects/{project_id}/skills",
        files={"file": ("skill.zip", skill_zip(), "application/zip")},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    skill_id = body["id"]
    assert body["name"] == "code-review"
    assert {item["path"] for item in body["files"]} == {"SKILL.md", "scripts/check.sh"}
    assert skill_dir(project_id, skill_id).exists()

    listing = (await api.get(f"/api/v1/projects/{project_id}/skills")).json()
    assert len(listing) == 1 and listing[0]["file_count"] == 2

    file_resp = await api.get(
        f"/api/v1/projects/{project_id}/skills/{skill_id}/files/scripts/check.sh"
    )
    assert file_resp.status_code == 200
    assert file_resp.json()["content"] == "echo ok\n"

    assert (await api.delete(f"/api/v1/projects/{project_id}/skills/{skill_id}")).status_code == 204
    assert (await api.get(f"/api/v1/projects/{project_id}/skills")).json() == []
    assert not skill_dir(project_id, skill_id).exists()


async def test_skill_upload_rejects_traversal(api, project_factory):
    project_id, _ = await project_factory(name="Skills 恶意包")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", SKILL_MD)
        archive.writestr("../evil.sh", "rm -rf /")
    resp = await api.post(
        f"/api/v1/projects/{project_id}/skills",
        files={"file": ("evil.zip", buffer.getvalue(), "application/zip")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "semantic_error"
    assert (await api.get(f"/api/v1/projects/{project_id}/skills")).json() == []


async def test_mcp_config_masking_and_replace(api, project_factory):
    project_id, _ = await project_factory(name="MCP 项目")
    payload = {
        "servers": [
            {
                "name": "fs",
                "transport": "stdio",
                "config": {"command": "npx", "args": ["-y", "server-fs"], "env": {"API_TOKEN": "secret1234"}},
            },
            {"name": "web", "transport": "streamable_http", "config": {"url": "http://127.0.0.1:9/mcp"}},
        ]
    }
    saved = await api.put(f"/api/v1/projects/{project_id}/mcp", json=payload)
    assert saved.status_code == 200, saved.text
    rows = saved.json()
    assert [row["name"] for row in rows] == ["fs", "web"]
    assert rows[0]["config"]["env"]["API_TOKEN"] == "****1234"

    replaced = await api.put(
        f"/api/v1/projects/{project_id}/mcp", json={"servers": [payload["servers"][1]]}
    )
    assert [row["name"] for row in replaced.json()] == ["web"]

    bad = await api.put(
        f"/api/v1/projects/{project_id}/mcp",
        json={"servers": [{"name": "bad", "transport": "stdio", "config": {}}]},
    )
    assert bad.status_code == 422

    assert (await api.delete(f"/api/v1/projects/{project_id}/mcp/web")).status_code == 204


async def test_credentials_and_repo(api, project_factory):
    project_id, _ = await project_factory(name="凭证项目")

    created = await api.post(
        f"/api/v1/projects/{project_id}/credentials",
        json={"name": "gh", "kind": "git_token", "secret": "ghp_abcdefgh1234"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["hint"] == "****1234"
    assert "ghp_abcdefgh1234" not in created.text
    credential_id = body["id"]

    repo = await api.put(
        f"/api/v1/projects/{project_id}/repo",
        json={
            "repo_url": "https://github.com/acme/demo.git",
            "repo_provider": "github",
            "default_branch": "develop",
            "credential_id": credential_id,
        },
    )
    assert repo.status_code == 200, repo.text
    assert repo.json()["credential_hint"] == "****1234"

    fetched = (await api.get(f"/api/v1/projects/{project_id}/repo")).json()
    assert fetched["default_branch"] == "develop"
    assert fetched["credential_id"] == credential_id

    listed = (await api.get(f"/api/v1/projects/{project_id}/credentials")).json()
    assert len(listed) == 1 and listed[0]["kind"] == "git_token"


async def test_repo_test_requires_url(api, project_factory):
    project_id, _ = await project_factory(name="仓库空配置")
    resp = await api.post(f"/api/v1/projects/{project_id}/repo/test")
    assert resp.status_code == 422
    assert resp.json()["code"] == "semantic_error"


async def test_pipeline_prompt_contains_agents_md_and_skills(project_factory, captured_llm):
    project_id, requirement_id = await project_factory(name="注入项目")

    from app.db.session import get_session_factory as factory
    from app.models import AgentDoc, Skill

    async with factory()() as session:
        session.add(
            AgentDoc(project_id=project_id, version=1, content="# 团队规范\n所有接口必须幂等。", is_active=True)
        )
        skill = Skill(
            project_id=project_id,
            name="code-review",
            description="按团队规范做代码评审",
            entry_path="SKILL.md",
            storage_dir="",
        )
        session.add(skill)
        await session.flush()
        from app.models import SkillFile

        session.add(
            SkillFile(
                skill_id=skill.id,
                path="SKILL.md",
                content=SKILL_MD,
                size_bytes=len(SKILL_MD),
                sha256="0" * 64,
            )
        )
        await session.commit()

    async with get_session_factory()() as session:
        run = await run_service.create_run(session, requirement_id, RunCreate(), enqueue=False)
    await execute_run(run.id)

    prompt = captured_llm[0][1]
    assert "所有接口必须幂等" in prompt
    assert "code-review" in prompt
    assert "先看接口契约" in prompt
