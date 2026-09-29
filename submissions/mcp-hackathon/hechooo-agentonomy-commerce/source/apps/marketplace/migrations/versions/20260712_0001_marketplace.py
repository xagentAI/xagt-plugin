"""Create the initial Clink Marketplace trusted registry schema."""

import sqlalchemy as sa
from alembic import op


revision = "20260712_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "providers",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("wallet_address", sa.String(length=42), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("domain_failures", sa.Integer(), nullable=False),
        sa.Column("last_domain_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_id"),
        sa.UniqueConstraint("domain", name="uq_providers_domain"),
    )
    op.create_index("ix_providers_domain", "providers", ["domain"])
    op.create_index("ix_providers_wallet_address", "providers", ["wallet_address"])
    op.create_index("ix_providers_status", "providers", ["status"])

    op.create_table(
        "offerings",
        sa.Column("offering_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("offering_id"),
    )
    op.create_index("ix_offerings_provider_id", "offerings", ["provider_id"])
    op.create_index("ix_offerings_status", "offerings", ["status"])
    op.create_index("ix_offerings_last_verified_at", "offerings", ["last_verified_at"])
    op.create_index(
        "ix_offerings_public", "offerings", ["status", "last_verified_at"]
    )

    op.create_table(
        "offering_provenance",
        sa.Column("provenance_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("offering_id", sa.String(length=64), nullable=False),
        sa.Column("registry_id", sa.String(length=128), nullable=False),
        sa.Column("source_id", sa.String(length=512), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["offering_id"], ["offerings.offering_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("provenance_id"),
        sa.UniqueConstraint(
            "offering_id",
            "registry_id",
            "source_id",
            name="uq_offering_provenance_source",
        ),
    )
    op.create_index(
        "ix_offering_provenance_offering_id",
        "offering_provenance",
        ["offering_id"],
    )

    op.create_table(
        "manifests",
        sa.Column("manifest_id", sa.String(length=64), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("manifest_hash", sa.String(length=66), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("signer", sa.String(length=42), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.provider_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("manifest_id"),
        sa.UniqueConstraint("manifest_hash", name="uq_manifests_manifest_hash"),
    )
    op.create_index("ix_manifests_provider_id", "manifests", ["provider_id"])
    op.create_index("ix_manifests_status", "manifests", ["status"])

    op.create_table(
        "auth_challenges",
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("nonce"),
    )
    op.create_index("ix_auth_challenges_purpose", "auth_challenges", ["purpose"])
    op.create_index("ix_auth_challenges_subject", "auth_challenges", ["subject"])
    op.create_index("ix_auth_challenges_expires_at", "auth_challenges", ["expires_at"])

    op.create_table(
        "reputation_snapshots",
        sa.Column("reputation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("offering_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["offering_id"], ["offerings.offering_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("reputation_id"),
    )
    op.create_index(
        "ix_reputation_snapshots_offering_id",
        "reputation_snapshots",
        ["offering_id"],
    )
    op.create_index(
        "ix_reputation_snapshots_created_at",
        "reputation_snapshots",
        ["created_at"],
    )

    op.create_table(
        "purchase_previews",
        sa.Column("preview_id", sa.String(length=64), nullable=False),
        sa.Column("offering_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("quote_hash", sa.String(length=66), nullable=False),
        sa.Column("input_hash", sa.String(length=66), nullable=False),
        sa.Column("payment", sa.JSON(), nullable=False),
        sa.Column("execution_mode", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["offering_id"], ["offerings.offering_id"]),
        sa.PrimaryKeyConstraint("preview_id"),
    )
    op.create_index(
        "ix_purchase_previews_offering_id", "purchase_previews", ["offering_id"]
    )
    op.create_index("ix_purchase_previews_user_id", "purchase_previews", ["user_id"])
    op.create_index(
        "ix_purchase_previews_quote_hash", "purchase_previews", ["quote_hash"]
    )
    op.create_index("ix_purchase_previews_state", "purchase_previews", ["state"])
    op.create_index(
        "ix_purchase_previews_expires_at", "purchase_previews", ["expires_at"]
    )

    op.create_table(
        "purchases",
        sa.Column("purchase_id", sa.String(length=64), nullable=False),
        sa.Column("preview_id", sa.String(length=64), nullable=False),
        sa.Column("offering_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("execution_mode", sa.String(length=40), nullable=False),
        sa.Column("input_hash", sa.String(length=66), nullable=False),
        sa.Column("output_hash", sa.String(length=66), nullable=True),
        sa.Column("reservation_id", sa.String(length=96), nullable=True),
        sa.Column("action_id", sa.String(length=96), nullable=True),
        sa.Column("policy_decision_id", sa.String(length=96), nullable=True),
        sa.Column("receipt_id", sa.String(length=96), nullable=True),
        sa.Column("audit_event_ids", sa.JSON(), nullable=False),
        sa.Column("reason_code", sa.String(length=96), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["preview_id"], ["purchase_previews.preview_id"]),
        sa.ForeignKeyConstraint(["offering_id"], ["offerings.offering_id"]),
        sa.PrimaryKeyConstraint("purchase_id"),
        sa.UniqueConstraint("preview_id", name="uq_purchases_preview_id"),
        sa.UniqueConstraint("reservation_id", name="uq_purchases_reservation_id"),
        sa.UniqueConstraint("action_id", name="uq_purchases_action_id"),
        sa.UniqueConstraint(
            "policy_decision_id", name="uq_purchases_policy_decision_id"
        ),
        sa.UniqueConstraint("receipt_id", name="uq_purchases_receipt_id"),
    )
    op.create_index("ix_purchases_offering_id", "purchases", ["offering_id"])
    op.create_index("ix_purchases_user_id", "purchases", ["user_id"])
    op.create_index("ix_purchases_state", "purchases", ["state"])
    op.create_index("ix_purchases_updated_at", "purchases", ["updated_at"])

    op.create_table(
        "purchase_finalizations",
        sa.Column("outbox_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purchase_id", sa.String(length=64), nullable=False),
        sa.Column("target_state", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_id"], ["purchases.purchase_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("outbox_id"),
        sa.UniqueConstraint(
            "purchase_id", name="uq_purchase_finalizations_purchase_id"
        ),
    )
    op.create_index(
        "ix_purchase_finalizations_purchase_id",
        "purchase_finalizations",
        ["purchase_id"],
    )
    op.create_index(
        "ix_purchase_finalizations_claim_token",
        "purchase_finalizations",
        ["claim_token"],
    )
    op.create_index(
        "ix_purchase_finalizations_claimed_until",
        "purchase_finalizations",
        ["claimed_until"],
    )

    op.create_table(
        "registry_cursors",
        sa.Column("registry_id", sa.String(length=128), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("etag", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("registry_id"),
    )

    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_worker_heartbeats_updated_at", "worker_heartbeats", ["updated_at"]
    )


def downgrade():
    op.drop_table("worker_heartbeats")
    op.drop_table("registry_cursors")
    op.drop_table("purchase_finalizations")
    op.drop_table("purchases")
    op.drop_table("purchase_previews")
    op.drop_table("reputation_snapshots")
    op.drop_table("auth_challenges")
    op.drop_table("manifests")
    op.drop_table("offering_provenance")
    op.drop_table("offerings")
    op.drop_table("providers")
