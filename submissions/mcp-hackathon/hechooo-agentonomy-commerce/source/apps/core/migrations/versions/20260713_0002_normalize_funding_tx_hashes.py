"""Normalize and durably constrain funding transaction hashes."""

from __future__ import annotations

import json
import re

import sqlalchemy as sa
from alembic import op


revision = "20260713_0002"
down_revision = "20260712_0001"
branch_labels = None
depends_on = None

HASH_PATTERN = re.compile(r"^0[xX]([0-9a-fA-F]{64})$")
CHECK_NAME = "ck_funding_ledger_tx_hash_canonical"
INDEX_NAME = "uq_funding_ledger_tx_hash_normalized"
BINDING_TABLE = "funding_transaction_bindings"
CHECK_SQL = (
    "tx_hash IS NULL OR (length(tx_hash) = 66 AND "
    "substr(tx_hash, 1, 2) = '0x' AND tx_hash = lower(tx_hash))"
)


def _canonical_hash(value: str) -> str:
    match = HASH_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise RuntimeError(f"invalid persisted transaction hash: {value!r}")
    return "0x" + match.group(1).lower()


def _payload(value, dialect_name: str) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if dialect_name == "sqlite" and isinstance(value, str):
        return json.loads(value)
    raise RuntimeError("invalid persisted funding ledger payload")


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name
    ledger = sa.table(
        "funding_ledger_records",
        sa.column("record_id", sa.String()),
        sa.column("record_type", sa.String()),
        sa.column("tx_hash", sa.String()),
        sa.column("payload", sa.JSON()),
    )
    rows = list(
        bind.execute(
            sa.select(
                ledger.c.record_id,
                ledger.c.tx_hash,
                ledger.c.payload,
            ).where(ledger.c.record_type == "reservation")
        ).mappings()
    )
    normalized_rows = []
    owners: dict[str, set[str]] = {}
    for row in rows:
        payload = _payload(row["payload"], dialect_name)
        canonical_hash = (
            _canonical_hash(row["tx_hash"])
            if row["tx_hash"] is not None
            else None
        )
        failed_hashes = [
            _canonical_hash(value)
            for value in payload.get("failed_tx_hashes", [])
        ]
        reservation_id = str(payload.get("reservation_id") or row["record_id"])
        normalized_rows.append(
            (row, payload, canonical_hash, failed_hashes, reservation_id)
        )
        bound_hashes = set(failed_hashes)
        if canonical_hash:
            bound_hashes.add(canonical_hash)
        for bound_hash in bound_hashes:
            owners.setdefault(bound_hash, set()).add(reservation_id)
    collisions = {key: value for key, value in owners.items() if len(value) > 1}
    if collisions:
        details = ", ".join(
            f"{tx_hash}: {','.join(sorted(record_ids))}"
            for tx_hash, record_ids in sorted(collisions.items())
        )
        raise RuntimeError(
            f"duplicate normalized transaction hash in funding ledger: {details}"
        )

    for row, payload, canonical_hash, failed_hashes, _reservation_id in normalized_rows:
        payload["tx_hash"] = canonical_hash
        if "failed_tx_hashes" in payload:
            payload["failed_tx_hashes"] = failed_hashes
        bind.execute(
            ledger.update()
            .where(ledger.c.record_id == row["record_id"])
            .values(tx_hash=canonical_hash, payload=payload)
        )

    inspector = sa.inspect(bind)
    if not inspector.has_table(BINDING_TABLE):
        op.create_table(
            BINDING_TABLE,
            sa.Column("tx_hash", sa.String(66), primary_key=True),
            sa.Column("reservation_id", sa.String(96), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "length(tx_hash) = 66 AND substr(tx_hash, 1, 2) = '0x' "
                "AND tx_hash = lower(tx_hash)",
                name="ck_funding_transaction_binding_hash_canonical",
            ),
        )
        op.create_index(
            "ix_funding_transaction_bindings_reservation_id",
            BINDING_TABLE,
            ["reservation_id"],
        )
    bindings = sa.table(
        BINDING_TABLE,
        sa.column("tx_hash", sa.String()),
        sa.column("reservation_id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for tx_hash, reservation_ids in sorted(owners.items()):
        reservation_id = next(iter(reservation_ids))
        existing = bind.execute(
            sa.select(bindings.c.reservation_id).where(
                bindings.c.tx_hash == tx_hash
            )
        ).scalar_one_or_none()
        if existing and existing != reservation_id:
            raise RuntimeError(
                "duplicate normalized transaction hash in funding bindings: "
                f"{tx_hash}: {existing},{reservation_id}"
            )
        if not existing:
            bind.execute(
                bindings.insert().values(
                    tx_hash=tx_hash,
                    reservation_id=reservation_id,
                    created_at=sa.func.now(),
                )
            )

    inspector = sa.inspect(bind)
    check_names = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints(
            "funding_ledger_records"
        )
    }
    if CHECK_NAME not in check_names:
        if dialect_name == "sqlite":
            with op.batch_alter_table("funding_ledger_records") as batch:
                batch.create_check_constraint(CHECK_NAME, CHECK_SQL)
        else:
            op.create_check_constraint(
                CHECK_NAME, "funding_ledger_records", CHECK_SQL
            )
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
            "ON funding_ledger_records (lower(tx_hash)) "
            "WHERE tx_hash IS NOT NULL"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
    check_names = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_check_constraints(
            "funding_ledger_records"
        )
    }
    if CHECK_NAME in check_names:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("funding_ledger_records") as batch:
                batch.drop_constraint(CHECK_NAME, type_="check")
        else:
            op.drop_constraint(
                CHECK_NAME, "funding_ledger_records", type_="check"
            )
    if sa.inspect(bind).has_table(BINDING_TABLE):
        op.drop_table(BINDING_TABLE)
