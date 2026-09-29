"""Persist marketplace worker stage operations state."""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0007"
down_revision = "20260713_0006"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("worker_stage_runs"):
        op.create_table(
            "worker_stage_runs",
            sa.Column("worker_id", sa.String(length=128), nullable=False),
            sa.Column("stage", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("worker_id", "stage"),
        )
    indexes = {
        item["name"]
        for item in sa.inspect(bind).get_indexes("worker_stage_runs")
    }
    for name, columns in (
        ("ix_worker_stage_runs_status", ["status"]),
        ("ix_worker_stage_runs_updated_at", ["updated_at"]),
    ):
        if name not in indexes:
            op.create_index(name, "worker_stage_runs", columns)


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("worker_stage_runs"):
        op.drop_table("worker_stage_runs")
