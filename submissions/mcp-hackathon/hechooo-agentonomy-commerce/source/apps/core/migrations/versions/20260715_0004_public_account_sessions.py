"""Persist public account console sessions by token digest."""

import sqlalchemy as sa
from alembic import op


revision = "20260715_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_account_sessions",
        sa.Column("public_account_session_id", sa.String(96), primary_key=True),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.String(96), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(token_digest) = 64 AND token_digest = lower(token_digest)",
            name="ck_public_account_session_digest",
        ),
        sa.CheckConstraint(
            "purpose = 'clink_account_console'",
            name="ck_public_account_session_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_public_account_session_status",
        ),
    )
    op.create_index(
        "ix_public_account_sessions_user_id",
        "public_account_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_public_account_sessions_status",
        "public_account_sessions",
        ["status"],
    )
    op.create_index(
        "ix_public_account_sessions_expires_at",
        "public_account_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_public_account_sessions_expires_at",
        table_name="public_account_sessions",
    )
    op.drop_index(
        "ix_public_account_sessions_status",
        table_name="public_account_sessions",
    )
    op.drop_index(
        "ix_public_account_sessions_user_id",
        table_name="public_account_sessions",
    )
    op.drop_table("public_account_sessions")
