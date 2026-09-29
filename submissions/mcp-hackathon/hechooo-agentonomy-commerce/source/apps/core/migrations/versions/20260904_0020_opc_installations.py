"""Persist OPC installations, pairings, and short-lived access credentials."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0020"
down_revision = "20260901_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "opc_installations",
        sa.Column("installation_id", sa.String(length=96), primary_key=True),
        sa.Column("public_jwk", sa.JSON(), nullable=False),
        sa.Column("public_jwk_thumbprint", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=96), nullable=True),
        sa.Column("wallet_identity_id", sa.String(length=96), nullable=True),
        sa.Column("spending_grant_id", sa.String(length=96), nullable=True),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_hash", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'consent_required', 'revoked')",
            name="ck_opc_installation_status",
        ),
        sa.CheckConstraint("scope = 'payments'", name="ck_opc_installation_scope"),
        sa.ForeignKeyConstraint(
            ["wallet_identity_id"], ["wallet_identities.wallet_identity_id"]
        ),
        sa.ForeignKeyConstraint(
            ["spending_grant_id"], ["spending_grants.spending_grant_id"]
        ),
        sa.UniqueConstraint(
            "public_jwk_thumbprint", name="uq_opc_installation_thumbprint"
        ),
    )
    op.create_index(
        "ix_opc_installations_status", "opc_installations", ["status"]
    )
    op.create_index(
        "ix_opc_installations_user_id", "opc_installations", ["user_id"]
    )
    op.create_index(
        "ix_opc_installations_wallet_identity_id",
        "opc_installations",
        ["wallet_identity_id"],
    )
    op.create_index(
        "ix_opc_installations_spending_grant_id",
        "opc_installations",
        ["spending_grant_id"],
    )
    op.create_index(
        "ix_opc_installations_consent_expires_at",
        "opc_installations",
        ["consent_expires_at"],
    )

    op.create_table(
        "opc_pairings",
        sa.Column("pairing_id", sa.String(length=96), primary_key=True),
        sa.Column("installation_id", sa.String(length=96), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("public_account_session_id", sa.String(length=96), nullable=False),
        sa.Column("target_user_id", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'claimed', 'linked', 'expired', 'revoked')",
            name="ck_opc_pairing_status",
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["opc_installations.installation_id"]
        ),
        sa.ForeignKeyConstraint(
            ["public_account_session_id"],
            ["public_account_sessions.public_account_session_id"],
        ),
        sa.UniqueConstraint(
            "installation_id",
            "request_id",
            name="uq_opc_pairing_installation_request",
        ),
    )
    op.create_index("ix_opc_pairings_status", "opc_pairings", ["status"])
    op.create_index(
        "ix_opc_pairings_installation_id", "opc_pairings", ["installation_id"]
    )
    op.create_index(
        "ix_opc_pairings_public_account_session_id",
        "opc_pairings",
        ["public_account_session_id"],
    )
    op.create_index(
        "ix_opc_pairings_target_user_id", "opc_pairings", ["target_user_id"]
    )
    op.create_index("ix_opc_pairings_expires_at", "opc_pairings", ["expires_at"])

    op.create_table(
        "opc_access_credentials",
        sa.Column("credential_id", sa.String(length=96), primary_key=True),
        sa.Column("installation_id", sa.String(length=96), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')", name="ck_opc_credential_status"
        ),
        sa.ForeignKeyConstraint(
            ["installation_id"], ["opc_installations.installation_id"]
        ),
        sa.UniqueConstraint("token_digest", name="uq_opc_credential_token_digest"),
        sa.UniqueConstraint(
            "installation_id",
            "request_id",
            name="uq_opc_credential_installation_request",
        ),
    )
    op.create_index(
        "ix_opc_access_credentials_installation_id",
        "opc_access_credentials",
        ["installation_id"],
    )
    op.create_index(
        "ix_opc_access_credentials_status", "opc_access_credentials", ["status"]
    )
    op.create_index(
        "ix_opc_access_credentials_expires_at",
        "opc_access_credentials",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("opc_access_credentials")
    op.drop_table("opc_pairings")
    op.drop_table("opc_installations")
