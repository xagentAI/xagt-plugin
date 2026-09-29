"""Enforce one open wallet login per user and repair revoked-only history."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260725_0017"
down_revision = "20260725_0016"
branch_labels = None
depends_on = None


OPEN_IDENTITY_STATUSES = ("pending", "active", "suspended")


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    identities = sa.Table("wallet_identities", metadata, autoload_with=bind)
    states = sa.Table(
        "account_wallet_bootstrap_states",
        metadata,
        autoload_with=bind,
    )

    open_identity_count = sa.func.count(identities.c.wallet_identity_id)
    duplicate_users = bind.execute(
        sa.select(identities.c.user_id)
        .where(identities.c.status.in_(OPEN_IDENTITY_STATUSES))
        .group_by(identities.c.user_id)
        .having(open_identity_count > 1)
    ).scalars().all()
    if duplicate_users:
        raise RuntimeError(
            "cannot enforce one wallet login while users have multiple open identities"
        )

    open_user_ids = set(
        bind.execute(
            sa.select(identities.c.user_id)
            .where(identities.c.status.in_(OPEN_IDENTITY_STATUSES))
            .distinct()
        ).scalars()
    )
    for state in bind.execute(
        sa.select(
            states.c.user_id,
            states.c.binding_generation,
            states.c.initialized_at,
        )
    ):
        if state.user_id in open_user_ids:
            continue
        latest_revoked_at = bind.execute(
            sa.select(sa.func.max(identities.c.updated_at)).where(
                identities.c.user_id == state.user_id,
                identities.c.status == "revoked",
            )
        ).scalar_one_or_none()
        bind.execute(
            sa.update(states)
            .where(states.c.user_id == state.user_id)
            .values(
                binding_state="unbound",
                binding_generation=max(state.binding_generation, 1),
                unbound_at=latest_revoked_at or state.initialized_at,
            )
        )

    predicate = sa.text(
        "status IN ('pending', 'active', 'suspended')"
    )
    op.create_index(
        "uq_wallet_identity_open_user",
        "wallet_identities",
        ["user_id"],
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_wallet_identity_open_user",
        table_name="wallet_identities",
    )
