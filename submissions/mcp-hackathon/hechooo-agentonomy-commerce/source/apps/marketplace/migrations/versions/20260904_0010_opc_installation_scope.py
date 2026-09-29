"""Bind purchase previews to an optional OPC installation."""

import sqlalchemy as sa
from alembic import op


revision = "20260904_0010"
down_revision = "20260720_0009"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_columns("purchase_previews")
    }


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("purchase_previews"):
        return
    if "opc_installation_id" not in _columns():
        op.add_column(
            "purchase_previews",
            sa.Column("opc_installation_id", sa.String(length=44), nullable=True),
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("purchase_previews"):
        return
    if "opc_installation_id" in _columns():
        with op.batch_alter_table("purchase_previews") as batch:
            batch.drop_column("opc_installation_id")
