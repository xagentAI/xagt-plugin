"""Persist wallet rebind generations without reviving revoked identities."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260725_0016"
down_revision = "20260720_0015"
branch_labels = None
depends_on = None


OPEN_IDENTITY_STATUSES = "status IN ('pending', 'active', 'suspended')"


def upgrade() -> None:
    with op.batch_alter_table("wallet_identities") as batch_op:
        batch_op.drop_constraint("uq_wallet_identity_scope", type_="unique")

    op.create_index(
        "uq_wallet_identity_open_scope",
        "wallet_identities",
        ["user_id", "chain_family", "wallet_address"],
        unique=True,
        sqlite_where=sa.text(OPEN_IDENTITY_STATUSES),
        postgresql_where=sa.text(OPEN_IDENTITY_STATUSES),
    )

    with op.batch_alter_table("account_wallet_bootstrap_states") as batch_op:
        batch_op.add_column(
            sa.Column(
                "binding_state",
                sa.String(16),
                nullable=False,
                server_default="bound",
            )
        )
        batch_op.add_column(
            sa.Column(
                "binding_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "unbound_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_account_wallet_bootstrap_binding_state",
            "binding_state IN ('bound', 'unbound')",
        )
        batch_op.create_check_constraint(
            "ck_account_wallet_bootstrap_unbound_at",
            "(binding_state = 'bound' AND unbound_at IS NULL) OR "
            "(binding_state = 'unbound' AND unbound_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("account_wallet_bootstrap_states") as batch_op:
        batch_op.drop_constraint(
            "ck_account_wallet_bootstrap_unbound_at",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_account_wallet_bootstrap_binding_state",
            type_="check",
        )
        batch_op.drop_column("unbound_at")
        batch_op.drop_column("binding_generation")
        batch_op.drop_column("binding_state")

    op.drop_index(
        "uq_wallet_identity_open_scope",
        table_name="wallet_identities",
    )
    with op.batch_alter_table("wallet_identities") as batch_op:
        batch_op.create_unique_constraint(
            "uq_wallet_identity_scope",
            ["user_id", "chain_family", "wallet_address"],
        )
