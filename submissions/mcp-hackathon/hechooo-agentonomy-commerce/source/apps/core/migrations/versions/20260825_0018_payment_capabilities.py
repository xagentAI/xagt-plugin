"""Persist immutable Core payment capabilities in a dedicated table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0018"
down_revision: Union[str, None] = "20260725_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "funding_payment_capabilities",
        sa.Column("capability_id", sa.String(length=96), nullable=False),
        sa.Column(
            "capability_version", sa.String(length=64), nullable=False
        ),
        sa.Column("capability_hash", sa.String(length=66), nullable=False),
        sa.Column("reservation_id", sa.String(length=96), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("wallet_binding_id", sa.String(length=256), nullable=False),
        sa.Column("wallet_identity_id", sa.String(length=96), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.PrimaryKeyConstraint("capability_id"),
        sa.UniqueConstraint("capability_hash", name="uq_payment_capability_hash"),
        sa.UniqueConstraint(
            "reservation_id", name="uq_payment_capability_reservation"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_payment_capability_idempotency"
        ),
        sa.CheckConstraint(
            "capability_version = 'clink-payment-capability-v1'",
            name="ck_payment_capability_version",
        ),
        sa.CheckConstraint(
            "length(capability_hash) = 66 AND substr(capability_hash, 1, 2) = '0x' "
            "AND capability_hash = lower(capability_hash)",
            name="ck_payment_capability_hash_canonical",
        ),
        sa.CheckConstraint(
            "issued_at > 0 AND expires_at > issued_at",
            name="ck_payment_capability_lifetime",
        ),
    )
    op.create_index(
        "ix_payment_capability_reservation",
        "funding_payment_capabilities",
        ["reservation_id"],
    )
    op.create_index(
        "ix_payment_capability_idempotency",
        "funding_payment_capabilities",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_capability_idempotency",
        table_name="funding_payment_capabilities",
    )
    op.drop_index(
        "ix_payment_capability_reservation",
        table_name="funding_payment_capabilities",
    )
    op.drop_table("funding_payment_capabilities")
