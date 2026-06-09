"""is_archived 列を message_records に追加

Revision ID: 0002_add_is_archived
Revises: 0001_initial
Create Date: 2026-06-09

既存テーブルへの追加列. 既存行は is_archived=False（アーカイブ対象外）として扱う.
SQLite では server_default="0" が即座に適用される.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_add_is_archived"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_records",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_message_records_is_archived", "message_records", ["is_archived"]
    )


def downgrade() -> None:
    op.drop_index("ix_message_records_is_archived", table_name="message_records")
    op.drop_column("message_records", "is_archived")
