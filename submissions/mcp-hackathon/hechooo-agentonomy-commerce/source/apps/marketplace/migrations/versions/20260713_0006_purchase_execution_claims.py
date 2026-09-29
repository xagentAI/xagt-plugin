"""Add fenced purchase execution claims."""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchases"):
        return
    columns = {column["name"] for column in inspector.get_columns("purchases")}
    if "execution_claim_token" not in columns:
        op.add_column(
            "purchases",
            sa.Column("execution_claim_token", sa.String(length=64), nullable=True),
        )
    if "execution_claim_until" not in columns:
        op.add_column(
            "purchases",
            sa.Column("execution_claim_until", sa.DateTime(timezone=True), nullable=True),
        )

    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("purchases")}
    if "ix_purchases_execution_claim_token" not in indexes:
        op.create_index(
            "ix_purchases_execution_claim_token", "purchases", ["execution_claim_token"]
        )
    if "ix_purchases_execution_claim_until" not in indexes:
        op.create_index(
            "ix_purchases_execution_claim_until", "purchases", ["execution_claim_until"]
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("purchases"):
        return
    indexes = {item["name"] for item in inspector.get_indexes("purchases")}
    if "ix_purchases_execution_claim_until" in indexes:
        op.drop_index("ix_purchases_execution_claim_until", table_name="purchases")
    if "ix_purchases_execution_claim_token" in indexes:
        op.drop_index("ix_purchases_execution_claim_token", table_name="purchases")

    columns = {column["name"] for column in sa.inspect(bind).get_columns("purchases")}
    if "execution_claim_until" in columns:
        op.drop_column("purchases", "execution_claim_until")
    if "execution_claim_token" in columns:
        op.drop_column("purchases", "execution_claim_token")
