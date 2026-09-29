"""Add durable per-network relayer nonce allocation."""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0006"
down_revision = "20260715_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("funding_relayer_nonces"):
        return
    op.create_table(
        "funding_relayer_nonces",
        sa.Column("network", sa.String(64), nullable=False),
        sa.Column("relayer_address", sa.String(42), nullable=False),
        sa.Column("next_nonce", sa.Numeric(20, 0), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "next_nonce >= 0", name="ck_funding_relayer_nonce_nonnegative"
        ),
        sa.CheckConstraint(
            "length(relayer_address) = 42 AND "
            "substr(relayer_address, 1, 2) = '0x' AND "
            "relayer_address = lower(relayer_address)",
            name="ck_funding_relayer_address_canonical",
        ),
        sa.PrimaryKeyConstraint(
            "network", "relayer_address", name="pk_funding_relayer_nonces"
        ),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("funding_relayer_nonces"):
        op.drop_table("funding_relayer_nonces")
