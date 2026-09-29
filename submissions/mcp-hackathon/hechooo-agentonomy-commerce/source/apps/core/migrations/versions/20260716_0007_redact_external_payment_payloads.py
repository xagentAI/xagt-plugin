"""Remove persisted external payment signatures and raw payloads."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "20260716_0007"
down_revision = "20260716_0006"
branch_labels = None
depends_on = None


def _payload(value, dialect_name: str) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if dialect_name == "sqlite" and isinstance(value, str):
        return json.loads(value)
    raise RuntimeError("invalid persisted funding ledger payload")


def upgrade() -> None:
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
        if "external_payment_response" not in payload:
            continue
        payload.pop("external_payment_response", None)
        bind.execute(
            ledger.update()
            .where(ledger.c.record_id == row["record_id"])
            .values(payload=payload)
        )


def downgrade() -> None:
    # Redacted secrets cannot and must not be reconstructed.
    pass
