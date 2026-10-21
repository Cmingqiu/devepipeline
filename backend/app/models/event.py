from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import MYSQL_TABLE_ARGS, Base, utcnow


class RunEvent(Base):
    """运行事件：SSE 回放的唯一数据源。seq 由 Redis INCR 生成，跨进程单调。"""

    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_run_events_run_seq"),
        Index("ix_run_events_run_type", "run_id", "type"),
        {**MYSQL_TABLE_ARGS, "comment": "运行事件时间线"},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    seq: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    # run_started / stage_started / llm_token / usage / artifact_saved / stage_finished /
    # interrupt / decision / progress / error / run_finished
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(LONGTEXT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=3), nullable=False, default=utcnow)
