"""Require wallet-authenticated public account browser sessions."""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0009"
down_revision = "20260716_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("public_account_sessions") as batch:
        batch.add_column(
            sa.Column("authenticated_wallet_identity_id", sa.String(96))
        )
        batch.add_column(sa.Column("authenticated_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key(
            "fk_public_account_sessions_authenticated_wallet_identity_id",
            "wallet_identities",
            ["authenticated_wallet_identity_id"],
            ["wallet_identity_id"],
        )
        batch.create_check_constraint(
            "ck_public_account_session_authentication",
            "(authenticated_wallet_identity_id IS NULL AND authenticated_at IS NULL) OR "
            "(authenticated_wallet_identity_id IS NOT NULL AND authenticated_at IS NOT NULL)",
        )
        batch.create_index(
            "ix_public_account_sessions_authenticated_wallet_identity_id",
            ["authenticated_wallet_identity_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("public_account_sessions") as batch:
        batch.drop_index(
            "ix_public_account_sessions_authenticated_wallet_identity_id"
        )
        batch.drop_constraint(
            "ck_public_account_session_authentication", type_="check"
        )
        batch.drop_constraint(
            "fk_public_account_sessions_authenticated_wallet_identity_id",
            type_="foreignkey",
        )
        batch.drop_column("authenticated_at")
        batch.drop_column("authenticated_wallet_identity_id")
