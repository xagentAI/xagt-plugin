"""Move Action and Policy provenance to the shared Core database."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260716_0014"
down_revision = "20260716_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_intents",
        sa.Column("action_id", sa.String(length=96), primary_key=True),
        sa.Column("user_id", sa.String(length=96), nullable=False),
        sa.Column("agent_id", sa.String(length=96), nullable=False),
        sa.Column("action_type", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("policy_decision_id", sa.String(length=96)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(action_id) > 0", name="ck_action_intent_id_nonempty"),
        sa.CheckConstraint("length(state) > 0", name="ck_action_intent_state_nonempty"),
    )
    op.create_index("ix_action_intents_user_id", "action_intents", ["user_id"])
    op.create_index("ix_action_intents_agent_id", "action_intents", ["agent_id"])
    op.create_index("ix_action_intents_action_type", "action_intents", ["action_type"])
    op.create_index("ix_action_intents_state", "action_intents", ["state"])
    op.create_index(
        "ix_action_intents_policy_decision_id", "action_intents", ["policy_decision_id"]
    )
    op.create_index("ix_action_intents_created_at", "action_intents", ["created_at"])
    op.create_index("ix_action_intents_updated_at", "action_intents", ["updated_at"])
    op.create_index(
        "ix_action_intents_user_agent_created",
        "action_intents",
        ["user_id", "agent_id", "created_at"],
    )

    op.create_table(
        "action_approvals",
        sa.Column("approval_id", sa.String(length=96), primary_key=True),
        sa.Column("action_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", sa.String(length=96), nullable=False),
        sa.Column("agent_id", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("proof_hash", sa.String(length=66)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["action_id"], ["action_intents.action_id"]),
        sa.CheckConstraint(
            "proof_hash IS NULL OR (length(proof_hash) = 66 AND "
            "substr(proof_hash, 1, 2) = '0x' AND proof_hash = lower(proof_hash))",
            name="ck_action_approval_proof_hash_canonical",
        ),
        sa.CheckConstraint("length(state) > 0", name="ck_action_approval_state_nonempty"),
    )
    op.create_index("ix_action_approvals_action_id", "action_approvals", ["action_id"])
    op.create_index("ix_action_approvals_user_id", "action_approvals", ["user_id"])
    op.create_index("ix_action_approvals_agent_id", "action_approvals", ["agent_id"])
    op.create_index("ix_action_approvals_state", "action_approvals", ["state"])
    op.create_index("ix_action_approvals_created_at", "action_approvals", ["created_at"])
    op.create_index(
        "ix_action_approvals_action_created",
        "action_approvals",
        ["action_id", "created_at"],
    )

    op.create_table(
        "policy_decisions",
        sa.Column("policy_decision_id", sa.String(length=96), primary_key=True),
        sa.Column("action_id", sa.String(length=96)),
        sa.Column("user_id", sa.String(length=96), nullable=False),
        sa.Column("agent_id", sa.String(length=96), nullable=False),
        sa.Column("action_type", sa.String(length=96), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("target_address", sa.String(length=42)),
        sa.Column("chain", sa.String(length=64)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "target_address IS NULL OR (length(target_address) = 42 AND "
            "substr(target_address, 1, 2) = '0x' AND "
            "target_address = lower(target_address))",
            name="ck_policy_decision_target_canonical",
        ),
        sa.CheckConstraint(
            "chain IS NULL OR chain IN ('eip155:137', 'eip155:8453')",
            name="ck_policy_decision_chain_canonical",
        ),
    )
    op.create_index("ix_policy_decisions_action_id", "policy_decisions", ["action_id"])
    op.create_index("ix_policy_decisions_user_id", "policy_decisions", ["user_id"])
    op.create_index("ix_policy_decisions_agent_id", "policy_decisions", ["agent_id"])
    op.create_index("ix_policy_decisions_action_type", "policy_decisions", ["action_type"])
    op.create_index("ix_policy_decisions_decision", "policy_decisions", ["decision"])
    op.create_index("ix_policy_decisions_evaluated_at", "policy_decisions", ["evaluated_at"])
    op.create_index(
        "ix_policy_decisions_action_evaluated",
        "policy_decisions",
        ["action_id", "evaluated_at"],
    )


def downgrade() -> None:
    op.drop_table("policy_decisions")
    op.drop_table("action_approvals")
    op.drop_table("action_intents")
