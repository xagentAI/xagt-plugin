"""Persist purchase preview payment capability metadata."""

import json

import sqlalchemy as sa
from alembic import op


revision = "20260720_0009"
down_revision = "20260713_0008"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("purchase_previews"):
        return
    columns = {item["name"] for item in inspector.get_columns("purchase_previews")}
    if "payment_capability" in columns:
        return
    op.add_column(
        "purchase_previews",
        sa.Column("payment_capability", sa.JSON(), nullable=True),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT preview_id, execution_mode FROM purchase_previews")
    ).mappings()
    for row in rows:
        external = row["execution_mode"] == "external_x402_signature"
        capability = {
            "rail": row["execution_mode"],
            "mandate_compatible": not external,
            "auto_pay_compatible": False,
            "requires_purchase_signature": external,
            "reason_code": (
                "MERCHANT_SCOPED_EIP3009_SIGNATURE_REQUIRED"
                if external
                else "CORE_AUTHORIZATION_CHECK_REQUIRED"
            ),
        }
        connection.execute(
            sa.text(
                "UPDATE purchase_previews SET payment_capability = :capability "
                "WHERE preview_id = :preview_id"
            ),
            {
                "preview_id": row["preview_id"],
                "capability": json.dumps(capability),
            },
        )
    with op.batch_alter_table("purchase_previews") as batch:
        batch.alter_column(
            "payment_capability",
            existing_type=sa.JSON(),
            nullable=False,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("purchase_previews"):
        return
    columns = {item["name"] for item in inspector.get_columns("purchase_previews")}
    if "payment_capability" in columns:
        with op.batch_alter_table("purchase_previews") as batch:
            batch.drop_column("payment_capability")
