"""Add rolling-hour and merchant trust controls to spending grants."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260720_0015"
down_revision = "20260716_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "spending_grants",
        sa.Column("hourly_limit_usdc", sa.Numeric(38, 6), nullable=True),
    )
    op.add_column(
        "spending_grants",
        sa.Column("merchant_trust_scopes", sa.JSON(), nullable=True),
    )
    op.add_column(
        "spending_grants",
        sa.Column("notification_mode", sa.String(32), nullable=True),
    )
    op.execute(
        "UPDATE spending_grants SET hourly_limit_usdc = daily_limit_usdc, "
        "merchant_trust_scopes = '[\"clink_verified\"]', "
        "notification_mode = 'notify_all'"
    )
    # SQLite does not support ALTER COLUMN. Alembic batch mode rebuilds the
    # table there while keeping native ALTER statements on PostgreSQL.
    with op.batch_alter_table("spending_grants") as batch_op:
        batch_op.alter_column("hourly_limit_usdc", nullable=False)
        batch_op.alter_column("merchant_trust_scopes", nullable=False)
        batch_op.alter_column("notification_mode", nullable=False)

    op.create_table(
        "spending_grant_rolling_usage",
        sa.Column("reservation_id", sa.String(96), primary_key=True),
        sa.Column("spending_grant_id", sa.String(96), nullable=False),
        sa.Column("amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["spending_grant_id"], ["spending_grants.spending_grant_id"]
        ),
    )
    op.create_index(
        "ix_spending_grant_rolling_usage_spending_grant_id",
        "spending_grant_rolling_usage",
        ["spending_grant_id"],
    )
    op.create_index(
        "ix_spending_grant_rolling_usage_state",
        "spending_grant_rolling_usage",
        ["state"],
    )
    op.create_index(
        "ix_spending_grant_rolling_usage_occurred_at",
        "spending_grant_rolling_usage",
        ["occurred_at"],
    )
    op.create_index(
        "ix_grant_rolling_usage_window",
        "spending_grant_rolling_usage",
        ["spending_grant_id", "occurred_at", "state"],
    )


def downgrade() -> None:
    op.drop_table("spending_grant_rolling_usage")
    with op.batch_alter_table("spending_grants") as batch_op:
        batch_op.drop_column("notification_mode")
        batch_op.drop_column("merchant_trust_scopes")
        batch_op.drop_column("hourly_limit_usdc")
