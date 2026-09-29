"""Fence recoverable signing claims and safely recycle unused relayer nonces."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0007"
down_revision: Union[str, None] = "20260827_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hosted_executions",
        sa.Column(
            "signing_claim_generation",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "hosted_executions",
        sa.Column("signing_claim_expires_at", sa.BigInteger(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE hosted_executions SET signing_claim_generation = 1, "
            "signing_claim_expires_at = LEAST(deadline, updated_at + 15) "
            "WHERE status = 'signing'"
        )
    )
    op.create_check_constraint(
        "ck_hosted_execution_signing_claim_generation_nonnegative",
        "hosted_executions",
        "signing_claim_generation >= 0",
    )
    op.create_check_constraint(
        "ck_hosted_execution_signing_claim_expiry",
        "hosted_executions",
        "signing_claim_expires_at IS NULL OR "
        "(signing_claim_generation > 0 AND signing_claim_expires_at > 0)",
    )
    op.drop_constraint(
        "uq_hosted_execution_chain_relayer_nonce",
        "hosted_executions",
        type_="unique",
    )
    op.create_index(
        "uq_hosted_execution_active_chain_relayer_nonce",
        "hosted_executions",
        ["chain", "relayer_address", "relayer_nonce"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('expired', 'released')"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM hosted_executions GROUP BY chain, "
            "relayer_address, relayer_nonce HAVING COUNT(*) > 1) THEN "
            "RAISE EXCEPTION 'cannot downgrade hosted signing claims with recycled nonces'; "
            "END IF; END $$"
        )
    )
    op.drop_index(
        "uq_hosted_execution_active_chain_relayer_nonce",
        table_name="hosted_executions",
    )
    op.create_unique_constraint(
        "uq_hosted_execution_chain_relayer_nonce",
        "hosted_executions",
        ["chain", "relayer_address", "relayer_nonce"],
    )
    op.drop_constraint(
        "ck_hosted_execution_signing_claim_expiry",
        "hosted_executions",
        type_="check",
    )
    op.drop_constraint(
        "ck_hosted_execution_signing_claim_generation_nonnegative",
        "hosted_executions",
        type_="check",
    )
    op.drop_column("hosted_executions", "signing_claim_expires_at")
    op.drop_column("hosted_executions", "signing_claim_generation")
