from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
BASE_REVISION = "20260712_0001"


def _legacy_database(path: Path, hashes: list[str]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE funding_locks (lock_id INTEGER NOT NULL PRIMARY KEY);
        INSERT INTO funding_locks (lock_id) VALUES (1);
        CREATE TABLE funding_ledger_records (
            record_id VARCHAR(96) NOT NULL PRIMARY KEY,
            record_type VARCHAR(32) NOT NULL,
            purchase_id VARCHAR(96),
            idempotency_key VARCHAR(128),
            action_id VARCHAR(96),
            policy_decision_id VARCHAR(96),
            reservation_id VARCHAR(96),
            tx_hash VARCHAR(80) UNIQUE,
            payload JSON NOT NULL,
            updated_at DATETIME NOT NULL
        );
        CREATE TABLE alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        );
        INSERT INTO alembic_version (version_num) VALUES ('20260712_0001');
        """
    )
    for index, tx_hash in enumerate(hashes, start=1):
        payload = {
            "reservation_id": f"reserve_{index}",
            "purchase_id": f"purchase_{index}",
            "tx_hash": tx_hash,
            "failed_tx_hashes": [tx_hash],
        }
        connection.execute(
            """
            INSERT INTO funding_ledger_records (
                record_id, record_type, purchase_id, reservation_id,
                tx_hash, payload, updated_at
            ) VALUES (?, 'reservation', ?, ?, ?, ?, '2026-07-13 00:00:00')
            """,
            (
                f"reserve_{index}",
                f"purchase_{index}",
                f"reserve_{index}",
                tx_hash,
                json.dumps(payload),
            ),
        )
    connection.commit()
    connection.close()


def _upgrade(path: Path) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{path}")
    command.upgrade(config, "head")


def test_upgrade_normalizes_existing_hashes_and_enforces_canonical_uniqueness(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    uppercase_hash = "0x" + "AB" * 32
    canonical_hash = uppercase_hash.lower()
    _legacy_database(database, [uppercase_hash])

    _upgrade(database)

    connection = sqlite3.connect(database)
    tx_hash, payload_json = connection.execute(
        "SELECT tx_hash, payload FROM funding_ledger_records"
    ).fetchone()
    payload = json.loads(payload_json)
    index_names = {
        row[1]
        for row in connection.execute(
            "PRAGMA index_list('funding_ledger_records')"
        ).fetchall()
    }
    assert tx_hash == canonical_hash
    assert payload["tx_hash"] == canonical_hash
    assert payload["failed_tx_hashes"] == [canonical_hash]
    assert "uq_funding_ledger_tx_hash_normalized" in index_names
    binding = connection.execute(
        "SELECT tx_hash, reservation_id FROM funding_transaction_bindings"
    ).fetchone()
    assert binding == (canonical_hash, "reserve_1")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO funding_ledger_records (
                record_id, record_type, tx_hash, payload, updated_at
            ) VALUES ('reserve_2', 'reservation', ?, '{}', '2026-07-13 00:00:00')
            """,
            (uppercase_hash,),
        )
    connection.close()


def test_upgrade_fails_closed_when_legacy_hashes_normalize_to_same_transaction(tmp_path):
    database = tmp_path / "collision.sqlite3"
    _legacy_database(database, ["0x" + "ab" * 32, "0x" + "AB" * 32])

    with pytest.raises(RuntimeError, match="duplicate normalized transaction hash"):
        _upgrade(database)

    connection = sqlite3.connect(database)
    revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert revision == BASE_REVISION
    connection.close()


def test_upgrade_preserves_failed_transaction_binding_after_current_hash_was_cleared(
    tmp_path,
):
    database = tmp_path / "failed-history.sqlite3"
    uppercase_hash = "0x" + "CD" * 32
    canonical_hash = uppercase_hash.lower()
    _legacy_database(database, [uppercase_hash])
    connection = sqlite3.connect(database)
    payload = json.loads(
        connection.execute(
            "SELECT payload FROM funding_ledger_records"
        ).fetchone()[0]
    )
    payload["tx_hash"] = None
    connection.execute(
        "UPDATE funding_ledger_records SET tx_hash = NULL, payload = ?",
        (json.dumps(payload),),
    )
    connection.commit()
    connection.close()

    _upgrade(database)

    connection = sqlite3.connect(database)
    binding = connection.execute(
        "SELECT tx_hash, reservation_id FROM funding_transaction_bindings"
    ).fetchone()
    migrated_payload = json.loads(
        connection.execute(
            "SELECT payload FROM funding_ledger_records"
        ).fetchone()[0]
    )
    assert binding == (canonical_hash, "reserve_1")
    assert migrated_payload["tx_hash"] is None
    assert migrated_payload["failed_tx_hashes"] == [canonical_hash]
    connection.close()


def test_upgrade_removes_legacy_external_payment_response_payloads(tmp_path):
    database = tmp_path / "external-payment-secrets.sqlite3"
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database}")
    command.upgrade(config, "20260715_0005")
    connection = sqlite3.connect(database)
    payload = {
        "reservation_id": "reserve_external_1",
        "network": "eip155:137",
        "token_address": "0x" + "11" * 20,
        "payment_proof_hash": "0x" + "22" * 32,
        "external_payment_response": {
            "signature": "legacy-signature-secret",
            "merchant_payload": {"secret": "legacy-merchant-secret"},
        },
    }
    connection.execute(
        """
        INSERT INTO funding_ledger_records (
            record_id, record_type, reservation_id, payload, updated_at
        ) VALUES (?, 'reservation', ?, ?, '2026-07-16 00:00:00')
        """,
        ("reserve_external_1", "reserve_external_1", json.dumps(payload)),
    )
    connection.commit()
    connection.close()

    command.upgrade(config, "head")

    connection = sqlite3.connect(database)
    migrated = json.loads(
        connection.execute(
            "SELECT payload FROM funding_ledger_records "
            "WHERE record_id = 'reserve_external_1'"
        ).fetchone()[0]
    )
    connection.close()
    assert "external_payment_response" not in migrated
    assert migrated["payment_proof_hash"] == payload["payment_proof_hash"]
