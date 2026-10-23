from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class PipelineRun(Base):
    """一次流水线运行。thread_id 是 MariaDB 与 PostgreSQL checkpointer 之间唯一的关联键。"""

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_project_created", "project_id", "created_at"),
        Index("ix_pipeline_runs_requirement", "requirement_id"),
        Index("ix_pipeline_runs_status", "status"),
        {**MYSQL_TABLE_ARGS, "comment": "流水线运行"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    requirement_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    requirement_version_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    thread_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, unique=True)
    # queued / running / waiting_approval / succeeded / failed / cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_checkpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seq: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False, default=0)
    review_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_review_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    model_overrides_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    config_snapshot_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciled_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class StageRun(Base):
    """阶段执行记录：一个 stage 每次重跑一条（attempt 递增）。"""

    __tablename__ = "stage_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "stage", "attempt", name="uq_stage_runs_run_stage_attempt"),
        {**MYSQL_TABLE_ARGS, "comment": "阶段执行记录"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # running / succeeded / failed / waiting_approval / cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)


class Artifact(Base):
    """阶段产物：每次保存/人工编辑追加一行版本。"""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "stage", "version", name="uq_artifacts_run_stage_version"),
        {**MYSQL_TABLE_ARGS, "comment": "阶段产物"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # markdown / diff / json / log / test_report
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    summary: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    edited_by_human: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)


class StageApproval(Base):
    """人工审批记录（通过 / 改后通过 / 驳回）。"""

    __tablename__ = "stage_approvals"
    __table_args__ = (
        Index("ix_stage_approvals_run_stage", "run_id", "stage"),
        {**MYSQL_TABLE_ARGS, "comment": "阶段审批"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    artifact_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    # approved / approved_with_edit / rejected / aborted
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    feedback: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True, default="local")
    decided_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)


class CodeWorkspace(Base):
    """编码沙箱工作区：每次 run 一个 clone + 独立分支，路径只在本机有效。"""

    __tablename__ = "code_workspaces"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt", name="uq_code_workspaces_run_attempt"),
        {**MYSQL_TABLE_ARGS, "comment": "编码沙箱工作区"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # worktree（默认） / docker（后续）
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="worktree")
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    workspace_path: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    base_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    spec_json: Mapped[str | None] = mapped_column(LONGTEXT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    cleaned_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=3), nullable=True)
