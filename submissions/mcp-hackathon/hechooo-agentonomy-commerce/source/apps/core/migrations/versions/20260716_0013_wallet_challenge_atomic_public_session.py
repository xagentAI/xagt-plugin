"""Require and retain the public session that created wallet challenges."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260716_0013"
down_revision = "20260716_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing unbound challenges cannot be attributed safely, so invalidate them.
    op.execute(
        "DELETE FROM account_sessions "
        "WHERE purpose = 'clink_wallet_identity' "
        "AND created_by_public_account_session_id IS NULL"
    )
    with op.batch_alter_table("account_sessions") as batch:
        batch.drop_constraint(
            "fk_account_sessions_created_by_public_account_session_id",
            type_="foreignkey",
        )
        batch.create_foreign_key(
            "fk_account_sessions_created_by_public_account_session_id",
            "public_account_sessions",
            ["created_by_public_account_session_id"],
            ["public_account_session_id"],
        )
        batch.create_check_constraint(
            "ck_wallet_challenge_creating_public_session",
            "purpose <> 'clink_wallet_identity' OR "
            "created_by_public_account_session_id IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("account_sessions") as batch:
        batch.drop_constraint(
            "ck_wallet_challenge_creating_public_session", type_="check"
        )
        batch.drop_constraint(
            "fk_account_sessions_created_by_public_account_session_id",
            type_="foreignkey",
        )
        batch.create_foreign_key(
            "fk_account_sessions_created_by_public_account_session_id",
            "public_account_sessions",
            ["created_by_public_account_session_id"],
            ["public_account_session_id"],
            ondelete="SET NULL",
        )
