"""Persist allowance transaction attempts for read-only recovery."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from services.account_service.repository import UInt256Storage


revision = "20260916_0021"
down_revision = "20260904_0020"
branch_labels = None
depends_on = None


_OPEN_STATUSES = "'awaiting_wallet', 'pending', 'attention_required'"


def upgrade() -> None:
    op.create_table(
        "allowance_recovery_attempts",
        sa.Column("attempt_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", sa.String(length=96), nullable=False),
        sa.Column("wallet_identity_id", sa.String(length=96), nullable=False),
        sa.Column("network", sa.String(length=64), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=False),
        sa.Column("spender_address", sa.String(length=42), nullable=False),
        sa.Column("amount_atomic", UInt256Storage(), nullable=True),
        sa.Column("allowance_tx_hash", sa.String(length=66), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_key_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "check_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.ForeignKeyConstraint(
            ["wallet_identity_id"], ["wallet_identities.wallet_identity_id"]
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_wallet', 'pending', 'verified', 'rejected', "
            "'attention_required')",
            name="ck_allowance_recovery_status",
        ),
        sa.CheckConstraint(
            "network IN ('eip155:137', 'eip155:8453', 'eip155:80002')",
            name="ck_allowance_recovery_network",
        ),
        sa.CheckConstraint(
            "length(token_address) = 42 AND substr(token_address, 1, 2) = '0x' "
            "AND token_address = lower(token_address)",
            name="ck_allowance_recovery_token_address",
        ),
        sa.CheckConstraint(
            "length(spender_address) = 42 AND substr(spender_address, 1, 2) = '0x' "
            "AND spender_address = lower(spender_address)",
            name="ck_allowance_recovery_spender_address",
        ),
        sa.CheckConstraint(
            "amount_atomic IS NULL OR amount_atomic > 0",
            name="ck_allowance_recovery_amount_atomic_positive",
        ),
        sa.CheckConstraint(
            "allowance_tx_hash IS NULL OR "
            "(length(allowance_tx_hash) = 66 AND "
            "substr(allowance_tx_hash, 1, 2) = '0x' AND "
            "allowance_tx_hash = lower(allowance_tx_hash))",
            name="ck_allowance_recovery_tx_hash",
        ),
        sa.CheckConstraint(
            "request_key_digest IS NULL OR "
            "(length(request_key_digest) = 64 AND "
            "request_key_digest = lower(request_key_digest))",
            name="ck_allowance_recovery_request_key_digest",
        ),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN "
            "('rpc_unavailable', 'chain_pending', 'invalid_evidence', "
            "'wallet_unavailable')",
            name="ck_allowance_recovery_reason_code",
        ),
        sa.CheckConstraint(
            "check_count >= 0",
            name="ck_allowance_recovery_check_count_nonnegative",
        ),
    )

    op.create_index(
        "uq_allowance_recovery_open_scope",
        "allowance_recovery_attempts",
        ["wallet_identity_id", "network", "token_address", "spender_address"],
        unique=True,
        sqlite_where=sa.text(f"status IN ({_OPEN_STATUSES})"),
        postgresql_where=sa.text(f"status IN ({_OPEN_STATUSES})"),
    )
    op.create_index(
        "uq_allowance_recovery_wallet_network_hash",
        "allowance_recovery_attempts",
        ["wallet_identity_id", "network", "allowance_tx_hash"],
        unique=True,
        sqlite_where=sa.text("allowance_tx_hash IS NOT NULL"),
        postgresql_where=sa.text("allowance_tx_hash IS NOT NULL"),
    )
    op.create_index(
        "uq_allowance_recovery_request_key_digest",
        "allowance_recovery_attempts",
        ["request_key_digest"],
        unique=True,
        sqlite_where=sa.text("request_key_digest IS NOT NULL"),
        postgresql_where=sa.text("request_key_digest IS NOT NULL"),
    )
    op.create_index(
        "ix_allowance_recovery_wallet_created",
        "allowance_recovery_attempts",
        ["wallet_identity_id", "created_at", "attempt_id"],
    )
    op.create_index(
        "ix_allowance_recovery_due",
        "allowance_recovery_attempts",
        ["status", "next_check_at", "attempt_id"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_user_id",
        "allowance_recovery_attempts",
        ["user_id"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_wallet_identity_id",
        "allowance_recovery_attempts",
        ["wallet_identity_id"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_status",
        "allowance_recovery_attempts",
        ["status"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_created_at",
        "allowance_recovery_attempts",
        ["created_at"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_updated_at",
        "allowance_recovery_attempts",
        ["updated_at"],
    )
    op.create_index(
        "ix_allowance_recovery_attempts_next_check_at",
        "allowance_recovery_attempts",
        ["next_check_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_open = bind.execute(
        sa.text(
            "SELECT 1 FROM allowance_recovery_attempts "
            f"WHERE status IN ({_OPEN_STATUSES}) LIMIT 1"
        )
    ).first()
    if has_open is not None:
        raise RuntimeError(
            "cannot downgrade with open allowance recovery attempts"
        )

    for index_name in (
        "ix_allowance_recovery_attempts_next_check_at",
        "ix_allowance_recovery_attempts_updated_at",
        "ix_allowance_recovery_attempts_created_at",
        "ix_allowance_recovery_attempts_status",
        "ix_allowance_recovery_attempts_wallet_identity_id",
        "ix_allowance_recovery_attempts_user_id",
        "ix_allowance_recovery_due",
        "ix_allowance_recovery_wallet_created",
        "uq_allowance_recovery_request_key_digest",
        "uq_allowance_recovery_wallet_network_hash",
        "uq_allowance_recovery_open_scope",
    ):
        op.drop_index(index_name, table_name="allowance_recovery_attempts")
    op.drop_table("allowance_recovery_attempts")
