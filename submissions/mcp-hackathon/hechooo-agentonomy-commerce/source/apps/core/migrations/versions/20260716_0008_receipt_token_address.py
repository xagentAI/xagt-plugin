"""Persist receipt token addresses as an explicit ledger field."""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0008"
down_revision = "20260716_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "funding_ledger_records",
        sa.Column("token_address", sa.String(length=42), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("funding_ledger_records", "token_address")
