"""Persist fair watcher retry timestamps for Hosted reconciliation."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260825_0003"
down_revision: Union[str, None] = "20260825_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hosted_executions",
        sa.Column("watcher_attempted_at", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_hosted_execution_watch_attempt",
        "hosted_executions",
        ["status", "watcher_attempted_at", "execution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hosted_execution_watch_attempt", table_name="hosted_executions"
    )
    op.drop_column("hosted_executions", "watcher_attempted_at")
