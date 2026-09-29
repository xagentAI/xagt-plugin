"""Persist Hosted pilot admission controls, usage reservations and audit events."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_0006"
down_revision: Union[str, None] = "20260827_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hosted_gate_controls",
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column(
            "paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('platform', 'tenant', 'node')",
            name="ck_hosted_gate_control_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'platform' AND tenant_id = '' AND node_id = '') OR "
            "(scope_type = 'tenant' AND length(tenant_id) > 0 AND node_id = '') OR "
            "(scope_type = 'node' AND length(tenant_id) > 0 AND length(node_id) > 0)",
            name="ck_hosted_gate_control_scope_shape",
        ),
        sa.PrimaryKeyConstraint("scope_type", "tenant_id", "node_id"),
    )

    op.create_table(
        "hosted_gate_reservations",
        sa.Column("execution_id", sa.String(length=96), nullable=False),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("utc_day", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "gas_cost_usd_micros",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("gas_utc_day", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_hosted_gate_reservation_state",
        ),
        sa.CheckConstraint(
            "gas_cost_usd_micros >= 0",
            name="ck_hosted_gate_reservation_gas_nonnegative",
        ),
        sa.CheckConstraint(
            "(gas_cost_usd_micros = 0 AND gas_utc_day IS NULL) OR "
            "(gas_cost_usd_micros > 0 AND gas_utc_day >= 0)",
            name="ck_hosted_gate_reservation_gas_day",
        ),
        sa.CheckConstraint(
            "utc_day >= 0",
            name="ck_hosted_gate_reservation_utc_day_nonnegative",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["hosted_executions.execution_id"]),
        sa.PrimaryKeyConstraint("execution_id"),
    )
    op.create_index(
        "ix_hosted_gate_reservations_tenant_node_day_state",
        "hosted_gate_reservations",
        ["tenant_id", "node_id", "utc_day", "state"],
    )
    op.create_index(
        "ix_hosted_gate_reservations_platform_day_state",
        "hosted_gate_reservations",
        ["gas_utc_day", "state"],
    )
    op.execute(
        sa.text(
            "INSERT INTO hosted_gate_reservations "
            "(execution_id, tenant_id, node_id, idempotency_key, utc_day, state, "
            "gas_cost_usd_micros, gas_utc_day, created_at, updated_at) "
            "SELECT execution_id, tenant_id, node_id, idempotency_key, "
            "CAST(created_at / 86400 AS INTEGER), "
            "CASE "
            "WHEN status IN ('finalized', 'reverted', 'reorg_review') THEN 'settled' "
            "WHEN status IN ('expired', 'released') THEN 'released' "
            "ELSE 'reserved' END, "
            "0, NULL, created_at, updated_at FROM hosted_executions"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO hosted_gate_controls "
            "(scope_type, tenant_id, node_id, paused, reason_code, updated_at) "
            "SELECT 'platform', '', '', TRUE, 'migration_review_required', "
            "COALESCE(MAX(updated_at), 1) FROM hosted_executions"
        )
    )

    op.create_table(
        "hosted_gate_events",
        sa.Column("event_id", sa.String(length=96), nullable=False),
        sa.Column("execution_id", sa.String(length=96), nullable=True),
        sa.Column("tenant_id", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=256), nullable=False),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=True),
        sa.Column(
            "gas_cost_usd_micros",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('allowed', 'denied', 'gas_reserved', 'settled', "
            "'released', 'pause_changed')",
            name="ck_hosted_gate_event_type",
        ),
        sa.CheckConstraint(
            "gas_cost_usd_micros >= 0",
            name="ck_hosted_gate_event_gas_nonnegative",
        ),
        sa.ForeignKeyConstraint(["execution_id"], ["hosted_executions.execution_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_hosted_gate_events_execution_created",
        "hosted_gate_events",
        ["execution_id", "created_at"],
    )
    op.create_index(
        "ix_hosted_gate_events_tenant_node_created",
        "hosted_gate_events",
        ["tenant_id", "node_id", "created_at"],
    )
    op.execute(
        sa.text(
            "INSERT INTO hosted_gate_events "
            "(event_id, execution_id, tenant_id, node_id, idempotency_key, event_type, "
            "reason_code, gas_cost_usd_micros, created_at) "
            "SELECT execution_id, execution_id, tenant_id, node_id, idempotency_key, "
            "CASE WHEN state = 'reserved' THEN 'allowed' ELSE state END, "
            "'migration_backfill', gas_cost_usd_micros, updated_at "
            "FROM hosted_gate_reservations"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO hosted_gate_events "
            "(event_id, execution_id, tenant_id, node_id, idempotency_key, event_type, "
            "reason_code, gas_cost_usd_micros, created_at) "
            "SELECT 'gate_event_migration_review_required', NULL, '', '', '', "
            "'pause_changed', 'migration_review_required', 0, updated_at "
            "FROM hosted_gate_controls WHERE scope_type = 'platform' "
            "AND tenant_id = '' AND node_id = ''"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hosted_gate_events_tenant_node_created",
        table_name="hosted_gate_events",
    )
    op.drop_index(
        "ix_hosted_gate_events_execution_created",
        table_name="hosted_gate_events",
    )
    op.drop_table("hosted_gate_events")
    op.drop_index(
        "ix_hosted_gate_reservations_platform_day_state",
        table_name="hosted_gate_reservations",
    )
    op.drop_index(
        "ix_hosted_gate_reservations_tenant_node_day_state",
        table_name="hosted_gate_reservations",
    )
    op.drop_table("hosted_gate_reservations")
    op.drop_table("hosted_gate_controls")
