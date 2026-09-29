"""Persist merchant onboarding state."""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0002"
down_revision = "20260712_0001"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("merchant_sessions"):
        op.create_table(
            "merchant_sessions",
            sa.Column("token_hash", sa.String(length=64), primary_key=True),
            sa.Column("wallet_address", sa.String(length=42), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    indexes = {item["name"] for item in inspector.get_indexes("merchant_sessions")}
    if "ix_merchant_sessions_wallet_address" not in indexes:
        op.create_index("ix_merchant_sessions_wallet_address", "merchant_sessions", ["wallet_address"])
    if "ix_merchant_sessions_expires_at" not in indexes:
        op.create_index("ix_merchant_sessions_expires_at", "merchant_sessions", ["expires_at"])
    manifest_columns = {item["name"]: item for item in inspector.get_columns("manifests")}
    if "owner_wallet_address" not in manifest_columns:
        op.add_column("manifests", sa.Column("owner_wallet_address", sa.String(length=42), nullable=True))
    op.execute("UPDATE manifests SET owner_wallet_address = (SELECT wallet_address FROM providers WHERE providers.provider_id = manifests.provider_id) WHERE owner_wallet_address IS NULL")
    if bind.execute(sa.text("SELECT COUNT(*) FROM manifests WHERE owner_wallet_address IS NULL")).scalar_one():
        raise RuntimeError("cannot migrate manifest without provider wallet owner")
    owner_column = next(item for item in sa.inspect(bind).get_columns("manifests") if item["name"] == "owner_wallet_address")
    if owner_column["nullable"]:
        with op.batch_alter_table("manifests") as batch:
            batch.alter_column("owner_wallet_address", existing_type=sa.String(length=42), nullable=False)
    manifest_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("manifests")}
    if "ix_manifests_owner_wallet_address" not in manifest_indexes:
        op.create_index("ix_manifests_owner_wallet_address", "manifests", ["owner_wallet_address"])


def downgrade():
    bind = op.get_bind()
    manifest_columns = {item["name"] for item in sa.inspect(bind).get_columns("manifests")}
    if "owner_wallet_address" in manifest_columns:
        manifest_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("manifests")}
        if "ix_manifests_owner_wallet_address" in manifest_indexes:
            op.drop_index("ix_manifests_owner_wallet_address", table_name="manifests")
        with op.batch_alter_table("manifests") as batch:
            batch.drop_column("owner_wallet_address")
    op.drop_index("ix_merchant_sessions_expires_at", table_name="merchant_sessions")
    op.drop_index("ix_merchant_sessions_wallet_address", table_name="merchant_sessions")
    op.drop_table("merchant_sessions")
