"""Allow Polygon Amoy policy provenance for explicit hosted rehearsals."""

from __future__ import annotations

from alembic import op


revision = "20260901_0019"
down_revision = "20260825_0018"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "ck_policy_decision_chain_canonical"
PRODUCTION_AND_AMOY_CHAINS = (
    "chain IS NULL OR chain IN "
    "('eip155:137', 'eip155:8453', 'eip155:80002')"
)
PRODUCTION_CHAINS = "chain IS NULL OR chain IN ('eip155:137', 'eip155:8453')"


def _replace_chain_constraint(expression: str) -> None:
    with op.batch_alter_table("policy_decisions") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch_op.create_check_constraint(CONSTRAINT_NAME, expression)


def upgrade() -> None:
    _replace_chain_constraint(PRODUCTION_AND_AMOY_CHAINS)


def downgrade() -> None:
    _replace_chain_constraint(PRODUCTION_CHAINS)
