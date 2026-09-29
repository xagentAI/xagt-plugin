"""Bind wallet challenges to their creating public browser session."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260716_0012"
down_revision = "20260716_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account_sessions") as batch:
        batch.add_column(
            sa.Column("created_by_public_account_session_id", sa.String(length=96))
        )
        batch.create_foreign_key(
            "fk_account_sessions_created_by_public_account_session_id",
            "public_account_sessions",
            ["created_by_public_account_session_id"],
            ["public_account_session_id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_account_sessions_created_by_public_account_session_id",
            ["created_by_public_account_session_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("account_sessions") as batch:
        batch.drop_index("ix_account_sessions_created_by_public_account_session_id")
        batch.drop_constraint(
            "fk_account_sessions_created_by_public_account_session_id",
            type_="foreignkey",
        )
        batch.drop_column("created_by_public_account_session_id")
