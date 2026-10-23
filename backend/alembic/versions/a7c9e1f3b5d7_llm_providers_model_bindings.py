"""llm providers and model bindings

Revision ID: a7c9e1f3b5d7
Revises: 7b1f3c9d24ae
Create Date: 2026-10-23 21:55:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql  # noqa: F401  autogenerate 会用到 BIGINT/LONGTEXT/DATETIME

revision: str = 'a7c9e1f3b5d7'
down_revision: str | Sequence[str] | None = '7b1f3c9d24ae'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('llm_providers',
    sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('endpoint', sa.String(length=512), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('credential_id', mysql.BIGINT(unsigned=True), nullable=True),
    sa.Column('extra_json', mysql.LONGTEXT(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_providers')),
    sa.UniqueConstraint('name', name='uq_llm_providers_name'),
    comment='LLM 提供商',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )

    op.create_table('model_bindings',
    sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
    sa.Column('scope', sa.String(length=16), nullable=False),
    sa.Column('project_id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('stage', sa.String(length=24), nullable=False),
    sa.Column('provider_id', mysql.BIGINT(unsigned=True), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('params_json', mysql.LONGTEXT(), nullable=True),
    sa.Column('created_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.Column('updated_at', mysql.DATETIME(fsp=3), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_bindings')),
    sa.UniqueConstraint(
        'scope', 'project_id', 'stage', name='uq_model_bindings_scope_project_stage'
    ),
    comment='每阶段模型绑定',
    mysql_charset='utf8mb4',
    mysql_collate='utf8mb4_unicode_ci'
    )


def downgrade() -> None:
    op.drop_table('model_bindings')
    op.drop_table('llm_providers')
