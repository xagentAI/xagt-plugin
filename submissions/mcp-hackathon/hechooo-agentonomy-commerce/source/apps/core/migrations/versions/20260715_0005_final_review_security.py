"""Apply final-review security persistence requirements."""

import sqlalchemy as sa
from alembic import op


revision = "20260715_0005"
down_revision = "20260715_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("public_account_sessions") as batch:
        batch.add_column(sa.Column("browser_session_digest", sa.String(64)))
        batch.add_column(sa.Column("csrf_token_digest", sa.String(64)))
        batch.add_column(sa.Column("exchanged_at", sa.DateTime(timezone=True)))
        batch.create_unique_constraint(
            "uq_public_account_sessions_browser_session_digest",
            ["browser_session_digest"],
        )
        batch.create_check_constraint(
            "ck_public_account_browser_session_digest",
            "browser_session_digest IS NULL OR "
            "(length(browser_session_digest) = 64 AND browser_session_digest = lower(browser_session_digest))",
        )
        batch.create_check_constraint(
            "ck_public_account_csrf_token_digest",
            "csrf_token_digest IS NULL OR "
            "(length(csrf_token_digest) = 64 AND csrf_token_digest = lower(csrf_token_digest))",
        )
    op.create_table(
        "audit_events",
        sa.Column(
            "audit_sequence_id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column("event_id", sa.String(96), nullable=False, unique=True),
        sa.Column("event_type", sa.String(96), nullable=False),
        sa.Column("source_service", sa.String(96), nullable=False),
        sa.Column("action_id", sa.String(96)),
        sa.Column("user_id", sa.String(96)),
        sa.Column("agent_id", sa.String(96)),
        sa.Column("policy_decision_id", sa.String(96)),
        sa.Column("payment_id", sa.String(96)),
        sa.Column("order_id", sa.String(96)),
        sa.Column("receipt_id", sa.String(96)),
        sa.Column("tx_hash", sa.String(66)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "event_type",
        "source_service",
        "action_id",
        "user_id",
        "agent_id",
        "created_at",
    ):
        op.create_index(f"ix_audit_events_{column}", "audit_events", [column])
    op.get_bind().execute(
        sa.text(
            "INSERT INTO funding_locks (lock_id) VALUES (1) "
            "ON CONFLICT (lock_id) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM funding_locks WHERE lock_id = 1")
    )
    for column in reversed(
        (
            "event_type",
            "source_service",
            "action_id",
            "user_id",
            "agent_id",
            "created_at",
        )
    ):
        op.drop_index(f"ix_audit_events_{column}", table_name="audit_events")
    op.drop_table("audit_events")
    with op.batch_alter_table("public_account_sessions") as batch:
        batch.drop_constraint(
            "ck_public_account_csrf_token_digest", type_="check"
        )
        batch.drop_constraint(
            "ck_public_account_browser_session_digest", type_="check"
        )
        batch.drop_constraint(
            "uq_public_account_sessions_browser_session_digest", type_="unique"
        )
        batch.drop_column("exchanged_at")
        batch.drop_column("csrf_token_digest")
        batch.drop_column("browser_session_digest")
