from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class Project(Base):
    """项目。

    本库按设计不建外键（业务层保证完整性），因此这里也不声明 ORM relationship：
    关系一律用显式查询表达，避免"无外键 → ORM 猜不出 join 条件"和异步 lazy load 的坑。
    """

    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_status", "status"),
        {**MYSQL_TABLE_ARGS, "comment": "项目"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 本期恒为 NULL，为多用户预留
    owner_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, default=utcnow, onupdate=utcnow
    )
