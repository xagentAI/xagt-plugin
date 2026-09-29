"""Add audit idempotency and remove persisted signed transactions."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260716_0011"
down_revision = "20260716_0010"
branch_labels = None
depends_on = None


def _payload(value, dialect_name: str) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if dialect_name == "sqlite" and isinstance(value, str):
        return json.loads(value)
    raise RuntimeError("invalid persisted funding ledger payload")


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=128)))
        batch.create_unique_constraint(
            "uq_audit_events_idempotency_key", ["idempotency_key"]
        )

    bind = op.get_bind()
    ledger = sa.table(
        "funding_ledger_records",
        sa.column("record_id", sa.String()),
        sa.column("record_type", sa.String()),
        sa.column("payload", sa.JSON()),
    )
    rows = list(
        bind.execute(
            sa.select(ledger.c.record_id, ledger.c.payload).where(
                ledger.c.record_type == "reservation"
            )
        ).mappings()
    )
    for row in rows:
        payload = _payload(row["payload"], bind.dialect.name)
        if "settlement_raw_transaction" not in payload:
            continue
        payload.pop("settlement_raw_transaction", None)
        bind.execute(
            ledger.update()
            .where(ledger.c.record_id == row["record_id"])
            .values(payload=payload)
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch:
        batch.drop_constraint("uq_audit_events_idempotency_key", type_="unique")
        batch.drop_column("idempotency_key")

    # Redacted signed transactions cannot and must not be reconstructed.
