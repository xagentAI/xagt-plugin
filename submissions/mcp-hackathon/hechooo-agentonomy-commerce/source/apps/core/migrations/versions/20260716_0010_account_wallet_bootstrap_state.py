"""Persist the one-time wallet bootstrap state for each account."""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0010"
down_revision = "20260716_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "account_wallet_bootstrap_states",
        sa.Column("user_id", sa.String(96), primary_key=True),
        sa.Column(
            "first_wallet_identity_id",
            sa.String(96),
            sa.ForeignKey("wallet_identities.wallet_identity_id"),
            nullable=False,
        ),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    identities = sa.Table("wallet_identities", metadata, autoload_with=bind)
    states = sa.Table("account_wallet_bootstrap_states", metadata, autoload_with=bind)
    allowances = sa.Table("asset_allowances", metadata, autoload_with=bind)
    seen_user_ids: set[str] = set()
    rows = bind.execute(
        sa.select(
            identities.c.user_id,
            identities.c.wallet_identity_id,
            identities.c.created_at,
        ).order_by(
            identities.c.user_id,
            identities.c.created_at,
            identities.c.wallet_identity_id,
        )
    )
    for row in rows:
        if row.user_id in seen_user_ids:
            continue
        seen_user_ids.add(row.user_id)
        bind.execute(
            sa.insert(states).values(
                user_id=row.user_id,
                first_wallet_identity_id=row.wallet_identity_id,
                initialized_at=row.created_at,
            )
        )
    bind.execute(
        sa.update(allowances)
        .where(
            allowances.c.status == "insufficient",
            allowances.c.observed_allowance_atomic != 0,
        )
        .values(status="active")
    )


def downgrade() -> None:
    op.drop_table("account_wallet_bootstrap_states")
