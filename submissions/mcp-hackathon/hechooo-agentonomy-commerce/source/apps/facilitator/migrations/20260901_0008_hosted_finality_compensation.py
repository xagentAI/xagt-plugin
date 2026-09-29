"""Repair the Hosted terminal-finality check after the original multichain revision."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0008"
down_revision: Union[str, None] = "20260827_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TERMINAL_STATUSES = "('confirmed', 'finalized', 'reverted', 'reorg_review')"
_LEGACY_TERMINAL_FINALITY = (
    "status NOT IN ('confirmed', 'finalized', 'reverted', 'reorg_review') OR "
    "(((chain IN ('eip155:8453', 'eip155:84532')) "
    "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
    "((chain IN ('eip155:137', 'eip155:80002')) "
    "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
    "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL"
)
_TERMINAL_FINALITY = (
    "status NOT IN ('confirmed', 'finalized', 'reverted', 'reorg_review') OR "
    "(finality_boundary IS NOT NULL AND (((chain IN ('eip155:8453', 'eip155:84532')) "
    "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
    "((chain IN ('eip155:137', 'eip155:80002')) "
    "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
    "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL)"
)


def _unrecoverable_rows_guard_sql() -> str:
    return (
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM hosted_executions "
        f"WHERE status IN {_TERMINAL_STATUSES} AND NOT ("
        "finality_boundary IS NOT NULL AND (((chain IN ('eip155:8453', 'eip155:84532')) "
        "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
        "((chain IN ('eip155:137', 'eip155:80002')) "
        "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
        "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL)"
        ") THEN RAISE EXCEPTION "
        "'cannot upgrade hosted finality evidence with unrecoverable rows'; "
        "END IF; END $$"
    )


def _invalid_rows_guard_sql() -> str:
    return (
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM hosted_executions "
        f"WHERE status IN {_TERMINAL_STATUSES} AND NOT ("
        "finality_boundary IS NOT NULL AND (((chain IN ('eip155:8453', 'eip155:84532')) "
        "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
        "((chain IN ('eip155:137', 'eip155:80002')) "
        "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
        "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL)"
        ") THEN RAISE EXCEPTION "
        "'cannot downgrade hosted finality evidence with invalid rows'; "
        "END IF; END $$"
    )


def upgrade() -> None:
    """Backfill inferable Base evidence, then install the strict check."""
    op.drop_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        type_="check",
    )
    op.execute(
        sa.text(
            "UPDATE hosted_executions "
            "SET finality_boundary = 'safe' "
            "WHERE chain = 'eip155:8453' "
            "AND status IN ('confirmed', 'finalized', 'reverted', 'reorg_review') "
            "AND finality_boundary IS NULL "
            "AND confirmations >= 2 "
            "AND safe_block_number IS NOT NULL "
            "AND safe_block_hash IS NOT NULL"
        )
    )
    op.execute(sa.text(_unrecoverable_rows_guard_sql()))
    op.create_check_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        _TERMINAL_FINALITY,
    )


def downgrade() -> None:
    """Refuse to weaken the check if existing data is not strictly valid."""
    op.execute(sa.text(_invalid_rows_guard_sql()))
    op.drop_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        _LEGACY_TERMINAL_FINALITY,
    )
