"""account_configs テーブルを追加

Revision ID: 0005_add_account_configs
Revises: 0004_add_urgency_score
Create Date: 2026-06-10

Gmail / 将来 Slack・Outlook のアカウント設定を保存するテーブル.
credential（アプリパスワード等）は PoC のため平文保存.
本番環境では暗号化を検討すること.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_account_configs"
down_revision: Union[str, None] = "0004_add_urgency_score"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("credential", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_configs_provider", "account_configs", ["provider"]
    )


def downgrade() -> None:
    op.drop_index("ix_account_configs_provider", table_name="account_configs")
    op.drop_table("account_configs")
