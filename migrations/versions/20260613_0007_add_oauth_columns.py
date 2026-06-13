"""account_configs に OAuth 用列を追加.

Revision ID: 0007_add_oauth_columns
Revises: 0006_add_account_address
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_add_oauth_columns"
down_revision = "0006_add_account_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_configs") as batch_op:
        batch_op.add_column(sa.Column("auth_type", sa.String(), nullable=False, server_default="imap"))
        batch_op.add_column(sa.Column("refresh_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("access_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("token_expiry", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("scopes", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("auth_status", sa.String(), nullable=False, server_default="ok"))


def downgrade() -> None:
    with op.batch_alter_table("account_configs") as batch_op:
        for col in ("auth_status", "scopes", "token_expiry", "access_token", "refresh_token", "auth_type"):
            batch_op.drop_column(col)
