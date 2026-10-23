from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import UtcDatetime

McpTransport = Literal["stdio", "streamable_http"]


class AgentDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    version: int
    is_active: bool
    created_at: UtcDatetime


class AgentDocDetail(AgentDocOut):
    content: str


class AgentDocUpsert(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)


class SkillFileOut(BaseModel):
    path: str
    size_bytes: int
    sha256: str
    is_text: bool


class SkillOut(BaseModel):
    id: int
    project_id: int
    name: str
    description: str
    entry_path: str
    enabled: bool
    file_count: int = 0
    created_at: UtcDatetime
    updated_at: UtcDatetime


class SkillDetail(SkillOut):
    files: list[SkillFileOut] = Field(default_factory=list)


class SkillFileDetail(SkillFileOut):
    content: str


class McpServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    transport: McpTransport = "stdio"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("config")
    @classmethod
    def _config_required_keys(cls, value: dict[str, Any], info) -> dict[str, Any]:
        transport = (info.data or {}).get("transport", "stdio")
        if transport == "stdio" and not value.get("command"):
            raise ValueError("stdio 传输必须在 config.command 里给出启动命令")
        if transport == "streamable_http" and not value.get("url"):
            raise ValueError("streamable_http 传输必须在 config.url 里给出地址")
        return value


class McpConfigOut(BaseModel):
    id: int
    project_id: int
    name: str
    transport: str
    config: dict[str, Any]
    enabled: bool
    last_test_status: str | None = None
    last_test_at: UtcDatetime | None = None
    last_test_message: str | None = None


class McpServersIn(BaseModel):
    servers: list[McpServerIn] = Field(default_factory=list)


class McpTestIn(BaseModel):
    """不传则测试库里已保存的配置。"""

    servers: list[McpServerIn] | None = None


class McpTestResult(BaseModel):
    name: str
    ok: bool
    tools: list[str] = Field(default_factory=list)
    error: str | None = None


class RepoConfigIn(BaseModel):
    repo_url: str | None = Field(default=None, max_length=512)
    repo_provider: Literal["github", "gitlab"] | None = None
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    credential_id: int | None = None

    @field_validator("repo_url")
    @classmethod
    def _url_shape(cls, value: str | None) -> str | None:
        if value and not value.startswith(("https://", "git@")):
            raise ValueError("仓库地址必须是 https:// 或 git@ 形式")
        return value


class RepoConfigOut(BaseModel):
    repo_url: str | None = None
    repo_provider: str | None = None
    default_branch: str = "main"
    credential_id: int | None = None
    credential_hint: str | None = None


class RepoTesResult(BaseModel):
    ok: bool
    message: str


class CredentialIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["git_token", "llm_api_key", "mcp_env"] = "git_token"
    secret: str = Field(min_length=1, max_length=4096)


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    kind: str
    hint: str | None = None
    created_at: UtcDatetime
