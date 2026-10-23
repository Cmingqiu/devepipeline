from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class AgentDoc(Base):
    """AGENTS.md 版本：每项目只有一条 is_active=1，注入编码/设计阶段的系统提示。"""

    __tablename__ = "agent_docs"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_agent_docs_project_version"),
        Index("ix_agent_docs_project_active", "project_id", "is_active"),
        {**MYSQL_TABLE_ARGS, "comment": "项目规范文档（AGENTS.md）版本"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, default="local")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)


class Skill(Base):
    """技能包：zip 解压后的元数据 + 文件树索引。"""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_skills_project_name"),
        {**MYSQL_TABLE_ARGS, "comment": "技能包"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    entry_path: Mapped[str] = mapped_column(String(255), nullable=False, default="SKILL.md")
    storage_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class SkillFile(Base):
    """技能包里的文本文件（便于在线预览与按需读取）；二进制只落磁盘。"""

    __tablename__ = "skill_files"
    __table_args__ = (
        UniqueConstraint("skill_id", "path", name="uq_skill_files_skill_path"),
        {**MYSQL_TABLE_ARGS, "comment": "技能包文件"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)


class McpConfig(Base):
    """MCP server 配置；凭证在 config_json 里用 `$CRED:<id>` 占位，运行时解密注入。"""

    __tablename__ = "mcp_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_mcp_configs_project_name"),
        {**MYSQL_TABLE_ARGS, "comment": "MCP server 配置"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    transport: Mapped[str] = mapped_column(String(24), nullable=False, default="stdio")
    config_json: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    last_test_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class Credential(Base):
    """加密凭证：Fernet 密文入库，接口只回 hint（末 4 位）。"""

    __tablename__ = "credentials"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_credentials_project_name"),
        {**MYSQL_TABLE_ARGS, "comment": "加密凭证"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    # 0 表示全局（如 LLM key），避免唯一键里出现 NULL
    project_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, default=0, server_default="0"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="git_token")
    encrypted_blob: Mapped[bytes] = mapped_column(nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    hint: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
