"""LLM 提供商与每阶段模型绑定（M4 多 provider）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class LlmProvider(Base):
    """OpenAI 兼容端点；密钥来自 credentials（credential_id）或环境变量 LLM_KEY_<NAME>。"""

    __tablename__ = "llm_providers"
    __table_args__ = (
        UniqueConstraint("name", name="uq_llm_providers_name"),
        {**MYSQL_TABLE_ARGS, "comment": "LLM 提供商"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    credential_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    extra_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class ModelBinding(Base):
    """每阶段 provider/model 绑定；project_id=0 表示 global（避免 NULL 破坏唯一键）。"""

    __tablename__ = "model_bindings"
    __table_args__ = (
        UniqueConstraint(
            "scope", "project_id", "stage", name="uq_model_bindings_scope_project_stage"
        ),
        {**MYSQL_TABLE_ARGS, "comment": "每阶段模型绑定"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    project_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True), nullable=False, default=0, server_default="0"
    )
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )
