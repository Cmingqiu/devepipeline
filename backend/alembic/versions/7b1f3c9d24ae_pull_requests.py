"""pull requests

Revision ID: 7b1f3c9d24ae
Revises: 503586198009
Create Date: 2026-10-23 17:10:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql  # noqa: F401  autogenerate 会用到 BIGINT/LONGTEXT/DATETIME

revision: str = '7b1f3c9d24ae'
down_revision: str | Sequence[str] | None = '503586198009'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('pull_requests',
    sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
    sa.Column('run_id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('repo_full_name', sa.String(length=255), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('url', sa.String(length=512), nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('base_branch', sa.String(length=255), nullable=False),
    sa.Column('head_sha', sa.String(length=40), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pull_requests')),
    sa.UniqueConstraint('run_id', 'provider', name='uq_pull_requests_run_provider'),
    comment='Pull Request',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )


def downgrade() -> None:
    op.drop_table('pull_requests')
