from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class Requirement(Base):
    """需求。与 Project / RequirementVersion 的关系全部走显式查询（不建外键、不声明 relationship）。"""

    __tablename__ = "requirements"
    __table_args__ = (
        Index("ix_requirements_project_created", "project_id", "created_at"),
        Index("ix_requirements_status", "status"),
        {**MYSQL_TABLE_ARGS, "comment": "需求"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    current_version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # draft / queued / running / waiting_approval / done / failed / cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", server_default="draft")
    latest_run_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )


class RequirementVersion(Base):
    __tablename__ = "requirement_versions"
    __table_args__ = (
        UniqueConstraint("requirement_id", "version_no", name="uq_requirement_versions_req_version"),
        {**MYSQL_TABLE_ARGS, "comment": "需求版本（正文 Markdown）"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    requirement_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    # editor / upload / ai
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="editor")
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True, default="local")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
