"""Allow the Hosted execution schema's four approved chain profiles."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0004"
down_revision: Union[str, None] = "20260825_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SUPPORTED_CHAINS = (
    "'eip155:8453', 'eip155:137', 'eip155:84532', 'eip155:80002'"
)
_TERMINAL_FINALITY = (
    "status NOT IN ('confirmed', 'finalized', 'reverted', 'reorg_review') OR "
    "(((chain IN ('eip155:8453', 'eip155:84532')) "
    "AND confirmations >= 2 AND finality_boundary = 'safe') OR "
    "((chain IN ('eip155:137', 'eip155:80002')) "
    "AND confirmations >= 3 AND finality_boundary = 'finalized')) "
    "AND safe_block_number IS NOT NULL AND safe_block_hash IS NOT NULL"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_hosted_execution_base_chain",
        "hosted_executions",
        type_="check",
    )
    op.drop_constraint(
        "ck_hosted_execution_terminal_safe_evidence",
        "hosted_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_execution_supported_chain",
        "hosted_executions",
        f"chain IN ({_SUPPORTED_CHAINS})",
    )
    op.create_check_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        _TERMINAL_FINALITY,
    )
    op.drop_constraint(
        "ck_hosted_relayer_nonce_base_chain",
        "hosted_relayer_nonce_allocations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_relayer_nonce_supported_chain",
        "hosted_relayer_nonce_allocations",
        f"chain IN ({_SUPPORTED_CHAINS})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_hosted_relayer_nonce_supported_chain",
        "hosted_relayer_nonce_allocations",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_relayer_nonce_base_chain",
        "hosted_relayer_nonce_allocations",
        "chain = 'eip155:8453'",
    )
    op.drop_constraint(
        "ck_hosted_execution_terminal_finality_evidence",
        "hosted_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_execution_terminal_safe_evidence",
        "hosted_executions",
        "status NOT IN ('confirmed', 'reverted') OR "
        "(confirmations >= 2 AND safe_block_number IS NOT NULL "
        "AND safe_block_hash IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_hosted_execution_supported_chain",
        "hosted_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_hosted_execution_base_chain",
        "hosted_executions",
        "chain = 'eip155:8453'",
    )
