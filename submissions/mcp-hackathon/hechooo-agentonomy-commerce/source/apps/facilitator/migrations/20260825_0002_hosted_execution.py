"""Persist Hosted execution state, transaction attempts and chain evidence."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0002"
down_revision: Union[str, None] = "20260825_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosted_executions",
        sa.Column("execution_id", sa.String(length=96), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("wallet_binding_id", sa.String(length=256), nullable=False),
        sa.Column("capability_id", sa.String(length=256), nullable=False),
        sa.Column("reservation_id", sa.String(length=256), nullable=False),
        sa.Column("purchase_id", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("chain", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=42), nullable=False),
        sa.Column("payee", sa.String(length=42), nullable=False),
        sa.Column("token", sa.String(length=42), nullable=False),
        sa.Column("amount_atomic", sa.String(length=78), nullable=False),
        sa.Column("executor", sa.String(length=42), nullable=False),
        sa.Column("signer_epoch", sa.Integer(), nullable=False),
        sa.Column("owner_nonce", sa.String(length=78), nullable=False),
        sa.Column("deadline", sa.BigInteger(), nullable=False),
        sa.Column("capability_hash", sa.String(length=66), nullable=False),
        sa.Column("reservation_hash", sa.String(length=66), nullable=False),
        sa.Column("execution_scope_hash", sa.String(length=66), nullable=False),
        sa.Column("execution_digest", sa.String(length=66), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("signature", sa.LargeBinary(), nullable=True),
        sa.Column("relayer_address", sa.String(length=42), nullable=False),
        sa.Column("relayer_nonce", sa.BigInteger(), nullable=False),
        sa.Column("unsigned_transaction_hash", sa.String(length=66), nullable=True),
        sa.Column("raw_transaction", sa.LargeBinary(), nullable=True),
        sa.Column("raw_transaction_hash", sa.String(length=66), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "broadcast_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("broadcasted_at", sa.BigInteger(), nullable=True),
        sa.Column("receipt_status", sa.Integer(), nullable=True),
        sa.Column("receipt_block_number", sa.BigInteger(), nullable=True),
        sa.Column("receipt_block_hash", sa.String(length=66), nullable=True),
        sa.Column(
            "confirmations",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("safe_block_number", sa.BigInteger(), nullable=True),
        sa.Column("safe_block_hash", sa.String(length=66), nullable=True),
        sa.Column("watcher_version", sa.String(length=128), nullable=True),
        sa.Column("finality_boundary", sa.String(length=32), nullable=True),
        sa.Column(
            "reorg_state",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
        sa.Column("reorg_evidence", sa.JSON(), nullable=True),
        sa.Column("submission_failure_code", sa.String(length=64), nullable=True),
        sa.Column("release_evidence", sa.JSON(), nullable=True),
        sa.Column("confirmed_at", sa.BigInteger(), nullable=True),
        sa.Column("finalized_at", sa.BigInteger(), nullable=True),
        sa.Column("reverted_at", sa.BigInteger(), nullable=True),
        sa.Column("released_at", sa.BigInteger(), nullable=True),
        sa.Column("expired_at", sa.BigInteger(), nullable=True),
        sa.Column("reorg_reviewed_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "chain = 'eip155:8453'", name="ck_hosted_execution_base_chain"
        ),
        sa.CheckConstraint(
            "length(amount_atomic) > 0", name="ck_hosted_execution_amount_present"
        ),
        sa.CheckConstraint(
            "length(capability_hash) = 66",
            name="ck_hosted_execution_capability_hash_length",
        ),
        sa.CheckConstraint(
            "length(reservation_hash) = 66",
            name="ck_hosted_execution_reservation_hash_length",
        ),
        sa.CheckConstraint(
            "length(execution_scope_hash) = 66",
            name="ck_hosted_execution_scope_hash_length",
        ),
        sa.CheckConstraint(
            "length(execution_digest) = 66",
            name="ck_hosted_execution_digest_length",
        ),
        sa.CheckConstraint(
            "length(canonical_hash) = 66",
            name="ck_hosted_execution_canonical_hash_length",
        ),
        sa.CheckConstraint(
            "signer_epoch > 0", name="ck_hosted_execution_signer_epoch_positive"
        ),
        sa.CheckConstraint(
            "length(owner_nonce) > 0",
            name="ck_hosted_execution_owner_nonce_present",
        ),
        sa.CheckConstraint(
            "relayer_nonce >= 0",
            name="ck_hosted_execution_relayer_nonce_nonnegative",
        ),
        sa.CheckConstraint(
            "deadline > 0", name="ck_hosted_execution_deadline_positive"
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'preflight_approved', 'signing', 'signed', "
            "'submitted', 'submission_unknown', 'submission_rejected', "
            "'confirmed', 'finalized', 'reverted', 'expired', 'released', "
            "'reorg_review')",
            name="ck_hosted_execution_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('confirmed', 'reverted') OR "
            "(confirmations >= 2 AND safe_block_number IS NOT NULL "
            "AND safe_block_hash IS NOT NULL)",
            name="ck_hosted_execution_terminal_safe_evidence",
        ),
        sa.PrimaryKeyConstraint("execution_id"),
        sa.UniqueConstraint(
            "capability_id", name="uq_hosted_execution_capability"
        ),
        sa.UniqueConstraint(
            "reservation_id", name="uq_hosted_execution_reservation"
        ),
        sa.UniqueConstraint("purchase_id", name="uq_hosted_execution_purchase"),
        sa.UniqueConstraint(
            "tenant_id",
            "node_id",
            "idempotency_key",
            name="uq_hosted_execution_idempotency",
        ),
        sa.UniqueConstraint(
            "chain",
            "relayer_address",
            "relayer_nonce",
            name="uq_hosted_execution_chain_relayer_nonce",
        ),
    )
    op.create_index(
        "ix_hosted_execution_status_updated",
        "hosted_executions",
        ["status", "updated_at"],
    )

    op.create_table(
        "hosted_relayer_nonce_allocations",
        sa.Column("chain", sa.String(length=32), nullable=False),
        sa.Column("relayer_address", sa.String(length=42), nullable=False),
        sa.Column("next_nonce", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "chain = 'eip155:8453'",
            name="ck_hosted_relayer_nonce_base_chain",
        ),
        sa.CheckConstraint(
            "next_nonce >= 0", name="ck_hosted_relayer_nonce_nonnegative"
        ),
        sa.PrimaryKeyConstraint("chain", "relayer_address"),
    )

    op.create_table(
        "hosted_execution_attempts",
        sa.Column("attempt_id", sa.String(length=96), nullable=False),
        sa.Column("execution_id", sa.String(length=96), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("attempt_kind", sa.String(length=32), nullable=False),
        sa.Column("raw_transaction_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["hosted_executions.execution_id"]
        ),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "execution_id",
            "attempt_number",
            name="uq_hosted_execution_attempt_number",
        ),
    )
    op.create_index(
        "ix_hosted_execution_attempts_execution_created",
        "hosted_execution_attempts",
        ["execution_id", "created_at"],
    )

    op.create_table(
        "hosted_execution_observations",
        sa.Column("observation_id", sa.String(length=96), nullable=False),
        sa.Column("execution_id", sa.String(length=96), nullable=False),
        sa.Column("tx_hash", sa.String(length=66), nullable=False),
        sa.Column("block_number", sa.BigInteger(), nullable=False),
        sa.Column("block_hash", sa.String(length=66), nullable=False),
        sa.Column("receipt_status", sa.Integer(), nullable=False),
        sa.Column("confirmations", sa.Integer(), nullable=False),
        sa.Column("safe_block_number", sa.BigInteger(), nullable=True),
        sa.Column("safe_block_hash", sa.String(length=66), nullable=True),
        sa.Column("watcher_version", sa.String(length=128), nullable=False),
        sa.Column("canonical", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"], ["hosted_executions.execution_id"]
        ),
        sa.PrimaryKeyConstraint("observation_id"),
        sa.UniqueConstraint(
            "execution_id",
            "tx_hash",
            "block_hash",
            name="uq_hosted_execution_observation_block",
        ),
    )
    op.create_index(
        "ix_hosted_execution_observations_execution_observed",
        "hosted_execution_observations",
        ["execution_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hosted_execution_observations_execution_observed",
        table_name="hosted_execution_observations",
    )
    op.drop_table("hosted_execution_observations")
    op.drop_index(
        "ix_hosted_execution_attempts_execution_created",
        table_name="hosted_execution_attempts",
    )
    op.drop_table("hosted_execution_attempts")
    op.drop_table("hosted_relayer_nonce_allocations")
    op.drop_index(
        "ix_hosted_execution_status_updated", table_name="hosted_executions"
    )
    op.drop_table("hosted_executions")
