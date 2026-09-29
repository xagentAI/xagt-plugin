"""Create persistent unified wallet authorization tables."""

import sqlalchemy as sa
from alembic import op


revision = "20260715_0003"
down_revision = "20260713_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallet_identities",
        sa.Column("wallet_identity_id", sa.String(96), primary_key=True),
        sa.Column("user_id", sa.String(96), nullable=False),
        sa.Column("chain_family", sa.String(32), nullable=False),
        sa.Column("wallet_address", sa.String(42), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("proof_scheme", sa.String(16), nullable=False),
        sa.Column("proof_hash", sa.String(128), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "chain_family", "wallet_address", name="uq_wallet_identity_scope"
        ),
    )
    op.create_index("ix_wallet_identities_user_id", "wallet_identities", ["user_id"])
    op.create_index("ix_wallet_identities_status", "wallet_identities", ["status"])

    op.create_table(
        "account_sessions",
        sa.Column("account_session_id", sa.String(96), primary_key=True),
        sa.Column("user_id", sa.String(96), nullable=False),
        sa.Column("wallet_address", sa.String(42), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False, unique=True),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column(
            "wallet_identity_id",
            sa.String(96),
            sa.ForeignKey("wallet_identities.wallet_identity_id"),
        ),
        sa.Column("payload", sa.JSON()),
        sa.Column("payload_hash", sa.String(66)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_account_sessions_user_id", "account_sessions", ["user_id"])
    op.create_index(
        "ix_account_sessions_wallet_identity_id",
        "account_sessions",
        ["wallet_identity_id"],
    )
    op.create_index("ix_account_sessions_expires_at", "account_sessions", ["expires_at"])

    op.create_table(
        "spending_grants",
        sa.Column("spending_grant_id", sa.String(96), primary_key=True),
        sa.Column(
            "wallet_identity_id",
            sa.String(96),
            sa.ForeignKey("wallet_identities.wallet_identity_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(96), nullable=False),
        sa.Column("agent_id", sa.String(96), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_reason", sa.String(64)),
        sa.Column("max_amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("per_transaction_limit_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("daily_limit_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("used_amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("reserved_amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("product_scopes", sa.JSON(), nullable=False),
        sa.Column("venue_scopes", sa.JSON(), nullable=False),
        sa.Column("merchant_scopes", sa.JSON(), nullable=False),
        sa.Column("network_scopes", sa.JSON(), nullable=False),
        sa.Column("asset_scopes", sa.JSON(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_spending_grants_wallet_identity_id", "spending_grants", ["wallet_identity_id"]
    )
    op.create_index("ix_spending_grants_user_id", "spending_grants", ["user_id"])
    op.create_index("ix_spending_grants_status", "spending_grants", ["status"])
    op.create_index("ix_spending_grants_expires_at", "spending_grants", ["expires_at"])

    op.create_table(
        "asset_allowances",
        sa.Column("asset_allowance_id", sa.String(96), primary_key=True),
        sa.Column(
            "wallet_identity_id",
            sa.String(96),
            sa.ForeignKey("wallet_identities.wallet_identity_id"),
            nullable=False,
        ),
        sa.Column("network", sa.String(64), nullable=False),
        sa.Column("token_address", sa.String(42), nullable=False),
        sa.Column("token_symbol", sa.String(32), nullable=False),
        sa.Column("token_decimals", sa.Integer(), nullable=False),
        sa.Column("spender_address", sa.String(42), nullable=False),
        sa.Column(
            "approved_amount_atomic",
            sa.Numeric(78, 0).with_variant(sa.String(78), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "observed_allowance_atomic",
            sa.Numeric(78, 0).with_variant(sa.String(78), "sqlite"),
            nullable=False,
        ),
        sa.Column("allowance_tx_hash", sa.String(66)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confirmed_block", sa.BigInteger()),
        sa.Column("last_chain_check_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "wallet_identity_id",
            "network",
            "token_address",
            "spender_address",
            name="uq_asset_allowance_scope",
        ),
    )
    op.create_index(
        "ix_asset_allowances_wallet_identity_id", "asset_allowances", ["wallet_identity_id"]
    )
    op.create_index("ix_asset_allowances_status", "asset_allowances", ["status"])
    op.create_index(
        "ix_asset_allowances_wallet_status",
        "asset_allowances",
        ["wallet_identity_id", "status"],
    )

    op.create_table(
        "spending_grant_daily_usage",
        sa.Column("spending_grant_daily_usage_id", sa.String(96), primary_key=True),
        sa.Column(
            "spending_grant_id",
            sa.String(96),
            sa.ForeignKey("spending_grants.spending_grant_id"),
            nullable=False,
        ),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("used_amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("reserved_amount_usdc", sa.Numeric(38, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("spending_grant_id", "usage_date", name="uq_grant_daily_usage"),
    )
    op.create_index(
        "ix_spending_grant_daily_usage_spending_grant_id",
        "spending_grant_daily_usage",
        ["spending_grant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_spending_grant_daily_usage_spending_grant_id",
        table_name="spending_grant_daily_usage",
    )
    op.drop_table("spending_grant_daily_usage")
    op.drop_index("ix_asset_allowances_wallet_status", table_name="asset_allowances")
    op.drop_index("ix_asset_allowances_status", table_name="asset_allowances")
    op.drop_index("ix_asset_allowances_wallet_identity_id", table_name="asset_allowances")
    op.drop_table("asset_allowances")
    op.drop_index("ix_spending_grants_expires_at", table_name="spending_grants")
    op.drop_index("ix_spending_grants_status", table_name="spending_grants")
    op.drop_index("ix_spending_grants_user_id", table_name="spending_grants")
    op.drop_index("ix_spending_grants_wallet_identity_id", table_name="spending_grants")
    op.drop_table("spending_grants")
    op.drop_index("ix_account_sessions_expires_at", table_name="account_sessions")
    op.drop_index("ix_account_sessions_wallet_identity_id", table_name="account_sessions")
    op.drop_index("ix_account_sessions_user_id", table_name="account_sessions")
    op.drop_table("account_sessions")
    op.drop_index("ix_wallet_identities_status", table_name="wallet_identities")
    op.drop_index("ix_wallet_identities_user_id", table_name="wallet_identities")
    op.drop_table("wallet_identities")
