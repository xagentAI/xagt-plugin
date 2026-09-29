"""Persist independently confirmed allowance amount mismatch evidence."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from services.account_service.repository import UInt256Storage


revision = "20260916_0022"
down_revision = "20260916_0021"
branch_labels = None
depends_on = None


TABLE = "allowance_recovery_attempts"
STATUS_CHECK = (
    "status IN ('awaiting_wallet', 'pending', 'verified', 'rejected', "
    "'attention_required', 'confirmed_mismatch')"
)
OLD_STATUS_CHECK = (
    "status IN ('awaiting_wallet', 'pending', 'verified', 'rejected', "
    "'attention_required')"
)
REASON_CHECK = (
    "reason_code IS NULL OR reason_code IN "
    "('rpc_unavailable', 'chain_pending', 'invalid_evidence', "
    "'wallet_unavailable', 'amount_mismatch')"
)
OLD_REASON_CHECK = (
    "reason_code IS NULL OR reason_code IN "
    "('rpc_unavailable', 'chain_pending', 'invalid_evidence', "
    "'wallet_unavailable')"
)
ACTUAL_AMOUNT_CHECK = (
    "actual_approved_amount_atomic IS NULL OR "
    "actual_approved_amount_atomic > 0"
)
CONFIRMED_BLOCK_CHECK = (
    "confirmed_block IS NULL OR confirmed_block >= 0"
)
CONFIRMED_BLOCK_HASH_CHECK = (
    "confirmed_block_hash IS NULL OR "
    "(length(confirmed_block_hash) = 66 AND "
    "substr(confirmed_block_hash, 1, 2) = '0x' AND "
    "confirmed_block_hash = lower(confirmed_block_hash))"
)
MISMATCH_EVIDENCE_CHECK = (
    "((status = 'confirmed_mismatch' AND allowance_tx_hash IS NOT NULL "
    "AND reason_code IS NOT NULL AND reason_code = 'amount_mismatch' "
    "AND next_check_at IS NULL "
    "AND amount_atomic IS NOT NULL "
    "AND actual_approved_amount_atomic IS NOT NULL "
    "AND observed_allowance_atomic IS NOT NULL "
    "AND confirmed_block IS NOT NULL "
    "AND confirmed_block_hash IS NOT NULL AND verified_at IS NOT NULL "
    "AND actual_approved_amount_atomic <> amount_atomic) OR "
    "(status <> 'confirmed_mismatch' "
    "AND actual_approved_amount_atomic IS NULL "
    "AND observed_allowance_atomic IS NULL "
    "AND confirmed_block IS NULL "
    "AND confirmed_block_hash IS NULL AND verified_at IS NULL))"
)


def _replace_checks(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    status_sql = OLD_STATUS_CHECK if downgrade else STATUS_CHECK
    reason_sql = OLD_REASON_CHECK if downgrade else REASON_CHECK
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_constraint("ck_allowance_recovery_status", type_="check")
            batch.drop_constraint("ck_allowance_recovery_reason_code", type_="check")
            if not downgrade:
                batch.create_check_constraint(
                    "ck_allowance_recovery_actual_amount_positive",
                    ACTUAL_AMOUNT_CHECK,
                )
                batch.create_check_constraint(
                    "ck_allowance_recovery_confirmed_block_nonnegative",
                    CONFIRMED_BLOCK_CHECK,
                )
                batch.create_check_constraint(
                    "ck_allowance_recovery_confirmed_block_hash",
                    CONFIRMED_BLOCK_HASH_CHECK,
                )
                batch.create_check_constraint(
                    "ck_allowance_recovery_mismatch_evidence_complete",
                    MISMATCH_EVIDENCE_CHECK,
                )
            else:
                batch.drop_constraint(
                    "ck_allowance_recovery_actual_amount_positive", type_="check"
                )
                batch.drop_constraint(
                    "ck_allowance_recovery_confirmed_block_nonnegative", type_="check"
                )
                batch.drop_constraint(
                    "ck_allowance_recovery_confirmed_block_hash", type_="check"
                )
                batch.drop_constraint(
                    "ck_allowance_recovery_mismatch_evidence_complete", type_="check"
                )
            batch.create_check_constraint("ck_allowance_recovery_status", status_sql)
            batch.create_check_constraint(
                "ck_allowance_recovery_reason_code", reason_sql
            )
        return

    op.drop_constraint("ck_allowance_recovery_status", TABLE, type_="check")
    op.drop_constraint("ck_allowance_recovery_reason_code", TABLE, type_="check")
    if not downgrade:
        op.create_check_constraint(
            "ck_allowance_recovery_actual_amount_positive", TABLE, ACTUAL_AMOUNT_CHECK
        )
        op.create_check_constraint(
            "ck_allowance_recovery_confirmed_block_nonnegative",
            TABLE,
            CONFIRMED_BLOCK_CHECK,
        )
        op.create_check_constraint(
            "ck_allowance_recovery_confirmed_block_hash",
            TABLE,
            CONFIRMED_BLOCK_HASH_CHECK,
        )
        op.create_check_constraint(
            "ck_allowance_recovery_mismatch_evidence_complete",
            TABLE,
            MISMATCH_EVIDENCE_CHECK,
        )
    else:
        op.drop_constraint(
            "ck_allowance_recovery_actual_amount_positive", TABLE, type_="check"
        )
        op.drop_constraint(
            "ck_allowance_recovery_confirmed_block_nonnegative", TABLE, type_="check"
        )
        op.drop_constraint(
            "ck_allowance_recovery_confirmed_block_hash", TABLE, type_="check"
        )
        op.drop_constraint(
            "ck_allowance_recovery_mismatch_evidence_complete", TABLE, type_="check"
        )
    op.create_check_constraint("ck_allowance_recovery_status", TABLE, status_sql)
    op.create_check_constraint("ck_allowance_recovery_reason_code", TABLE, reason_sql)


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("actual_approved_amount_atomic", UInt256Storage(), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("observed_allowance_atomic", UInt256Storage(), nullable=True),
    )
    op.add_column(TABLE, sa.Column("confirmed_block", sa.Integer(), nullable=True))
    op.add_column(
        TABLE,
        sa.Column("confirmed_block_hash", sa.String(length=66), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    _replace_checks()


def downgrade() -> None:
    bind = op.get_bind()
    evidence_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM allowance_recovery_attempts "
            "WHERE status = 'confirmed_mismatch' "
            "OR actual_approved_amount_atomic IS NOT NULL "
            "OR observed_allowance_atomic IS NOT NULL "
            "OR confirmed_block IS NOT NULL "
            "OR confirmed_block_hash IS NOT NULL "
            "OR verified_at IS NOT NULL LIMIT 1"
        )
    ).first()
    if evidence_exists is not None:
        raise RuntimeError(
            "cannot downgrade with confirmed allowance mismatch evidence"
        )

    _replace_checks(downgrade=True)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("verified_at")
            batch.drop_column("confirmed_block_hash")
            batch.drop_column("confirmed_block")
            batch.drop_column("observed_allowance_atomic")
            batch.drop_column("actual_approved_amount_atomic")
    else:
        for column_name in (
            "verified_at",
            "confirmed_block_hash",
            "confirmed_block",
            "observed_allowance_atomic",
            "actual_approved_amount_atomic",
        ):
            op.drop_column(TABLE, column_name)
