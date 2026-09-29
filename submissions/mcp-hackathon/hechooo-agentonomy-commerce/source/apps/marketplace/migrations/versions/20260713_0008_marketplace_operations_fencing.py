"""Fence marketplace operations and separate verification attempts."""

import sqlalchemy as sa
from alembic import op


revision = "20260713_0008"
down_revision = "20260713_0007"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table("providers"):
        provider_columns = _columns("providers")
        if "last_domain_check_at" not in provider_columns:
            op.add_column("providers", sa.Column("last_domain_check_at", sa.DateTime(timezone=True), nullable=True))
        if "ix_providers_last_domain_check_at" not in _indexes("providers"):
            op.create_index("ix_providers_last_domain_check_at", "providers", ["last_domain_check_at"])

    if inspector.has_table("offerings"):
        offering_columns = _columns("offerings")
        for column in (
            sa.Column("candidate_payload", sa.JSON(), nullable=True),
            sa.Column("candidate_registry_id", sa.String(length=128), nullable=True),
            sa.Column("last_check_attempt_at", sa.DateTime(timezone=True), nullable=True),
        ):
            if column.name not in offering_columns:
                op.add_column("offerings", column)
        if "ix_offerings_last_check_attempt_at" not in _indexes("offerings"):
            op.create_index("ix_offerings_last_check_attempt_at", "offerings", ["last_check_attempt_at"])

    if inspector.has_table("worker_stage_runs"):
        stage_columns = _columns("worker_stage_runs")
        if "cycle_token" not in stage_columns:
            op.add_column("worker_stage_runs", sa.Column("cycle_token", sa.String(length=64), nullable=True))
            op.execute("UPDATE worker_stage_runs SET cycle_token = 'legacy-cycle' WHERE cycle_token IS NULL")
            with op.batch_alter_table("worker_stage_runs") as batch:
                batch.alter_column("cycle_token", existing_type=sa.String(length=64), nullable=False)
        if "ix_worker_stage_runs_cycle_token" not in _indexes("worker_stage_runs"):
            op.create_index("ix_worker_stage_runs_cycle_token", "worker_stage_runs", ["cycle_token"])


def downgrade():
    inspector=sa.inspect(op.get_bind())
    if inspector.has_table("worker_stage_runs"):
        if "ix_worker_stage_runs_cycle_token" in _indexes("worker_stage_runs"):
            op.drop_index("ix_worker_stage_runs_cycle_token", table_name="worker_stage_runs")
        if "cycle_token" in _columns("worker_stage_runs"):
            with op.batch_alter_table("worker_stage_runs") as batch:
                batch.drop_column("cycle_token")

    if inspector.has_table("offerings"):
        if "ix_offerings_last_check_attempt_at" in _indexes("offerings"):
            op.drop_index("ix_offerings_last_check_attempt_at", table_name="offerings")
        offering_columns = _columns("offerings")
        for name in ("last_check_attempt_at", "candidate_registry_id", "candidate_payload"):
            if name in offering_columns:
                with op.batch_alter_table("offerings") as batch:
                    batch.drop_column(name)
                offering_columns.remove(name)

    if inspector.has_table("providers"):
        if "ix_providers_last_domain_check_at" in _indexes("providers"):
            op.drop_index("ix_providers_last_domain_check_at", table_name="providers")
        if "last_domain_check_at" in _columns("providers"):
            with op.batch_alter_table("providers") as batch:
                batch.drop_column("last_domain_check_at")
