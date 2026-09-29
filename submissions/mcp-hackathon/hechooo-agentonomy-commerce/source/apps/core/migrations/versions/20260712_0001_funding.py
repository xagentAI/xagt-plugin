"""Create atomic Clink funding ledger."""

import sqlalchemy as sa
from alembic import op


revision = "20260712_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "funding_locks",
        sa.Column("lock_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("lock_id"),
    )
    op.create_table(
        "funding_ledger_records",
        sa.Column("record_id", sa.String(length=96), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=96), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("action_id", sa.String(length=96), nullable=True),
        sa.Column("policy_decision_id", sa.String(length=96), nullable=True),
        sa.Column("reservation_id", sa.String(length=96), nullable=True),
        sa.Column("tx_hash", sa.String(length=80), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint("action_id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("policy_decision_id"),
        sa.UniqueConstraint("reservation_id"),
        sa.UniqueConstraint("tx_hash"),
    )
    op.create_index(
        op.f("ix_funding_ledger_records_purchase_id"),
        "funding_ledger_records",
        ["purchase_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_funding_ledger_records_record_type"),
        "funding_ledger_records",
        ["record_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_funding_ledger_records_record_type"),
        table_name="funding_ledger_records",
    )
    op.drop_index(
        op.f("ix_funding_ledger_records_purchase_id"),
        table_name="funding_ledger_records",
    )
    op.drop_table("funding_ledger_records")
    op.drop_table("funding_locks")
