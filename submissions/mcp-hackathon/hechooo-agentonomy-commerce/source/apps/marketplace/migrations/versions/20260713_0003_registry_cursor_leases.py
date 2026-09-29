"""Protect registry cursors with database leases."""

import sqlalchemy as sa
from alembic import op

revision = "20260713_0003"
down_revision = "20260713_0002"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("registry_cursors"):
        op.create_table(
            "registry_cursors",
            sa.Column("registry_id", sa.String(length=128), primary_key=True),
            sa.Column("cursor", sa.String(length=512), nullable=True),
            sa.Column("etag", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("sync_owner_token", sa.String(length=64), nullable=True),
            sa.Column("sync_lease_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    columns = {item["name"] for item in sa.inspect(bind).get_columns("registry_cursors")}
    if "sync_owner_token" not in columns:
        op.add_column("registry_cursors", sa.Column("sync_owner_token", sa.String(length=64), nullable=True))
    if "sync_lease_until" not in columns:
        op.add_column("registry_cursors", sa.Column("sync_lease_until", sa.DateTime(timezone=True), nullable=True))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("registry_cursors")}
    if "ix_registry_cursors_sync_lease_until" not in indexes:
        op.create_index("ix_registry_cursors_sync_lease_until", "registry_cursors", ["sync_lease_until"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("registry_cursors")}
    if "ix_registry_cursors_sync_lease_until" in indexes:
        op.drop_index("ix_registry_cursors_sync_lease_until", table_name="registry_cursors")
    columns = {item["name"] for item in sa.inspect(bind).get_columns("registry_cursors")}
    with op.batch_alter_table("registry_cursors") as batch:
        if "sync_lease_until" in columns:
            batch.drop_column("sync_lease_until")
        if "sync_owner_token" in columns:
            batch.drop_column("sync_owner_token")
