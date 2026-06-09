"""initial message_records テーブル

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-09

ORM（app/repositories/orm.py: MessageRecordORM）と一致させる. SQLite では
init_db() の create_all で十分だが, Postgres 昇格時はこのマイグレーションで
スキーマを管理する.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_records",
        sa.Column("message_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("email", sa.JSON(), nullable=False),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("triage_score", sa.Float(), nullable=False),
        sa.Column("is_unread", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_message_records_state", "message_records", ["state"]
    )
    op.create_index(
        "ix_message_records_triage_score", "message_records", ["triage_score"]
    )


def downgrade() -> None:
    op.drop_index("ix_message_records_triage_score", table_name="message_records")
    op.drop_index("ix_message_records_state", table_name="message_records")
    op.drop_table("message_records")
