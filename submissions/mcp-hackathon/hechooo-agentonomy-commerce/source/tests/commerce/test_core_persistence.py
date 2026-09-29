"""Restart and fail-closed coverage for the persistent local Core sandbox."""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from examples.commerce.core_bridge import CoreBridge
sys.path.insert(0, str(Path(__file__).parent))
from test_core_bridge import (
    _authorization,
    _execute_purchase,
)


METADATA_FILENAME = "core-state.json"
RECEIPT_SECRET_FILENAME = "receipt-secret"
SETTLEMENT_JOURNAL_FILENAME = "settlement-rpc.json"


def test_persistent_core_reuses_identity_grant_and_receipt_secret_after_restart(
    tmp_path: Path,
):
    with CoreBridge(tmp_path, persistent=True) as core:
        first = core.snapshot()

    with CoreBridge(tmp_path, persistent=True) as core:
        second = core.snapshot()

    assert second["wallet_identity_id"] == first["wallet_identity_id"]
    assert second["grant_id"] == first["grant_id"]
    assert second["receipt_signing_key"] == first["receipt_signing_key"]
    assert Decimal(second["budget_usdc"]) == Decimal("1.00")
    expires_at = datetime.fromisoformat(second["grant_expires_at"])
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(days=29) < remaining <= timedelta(days=30, seconds=1)
    assert (tmp_path / METADATA_FILENAME).exists()


def test_persistent_core_retains_depleted_grant_without_minting_a_replacement(
    tmp_path: Path,
):
    with CoreBridge(tmp_path, persistent=True) as core:
        first = core.snapshot()
        _execute_purchase(core, "purchase_030", "0.30")
        _execute_purchase(core, "purchase_070", "0.70")
        depleted = core.snapshot()
        assert depleted["grant_status"] == "exhausted"

    with CoreBridge(tmp_path, persistent=True) as core:
        second = core.snapshot()
        assert second["grant_id"] == first["grant_id"]
        assert second["grant_status"] == "exhausted"
        assert Decimal(second["used_amount_usdc"]) == Decimal("1.00")
        authorization = _authorization(core)
        assert authorization["ready"] is False
        assert authorization["reason_code"] in {
            "SPENDING_GRANT_REQUIRED",
            "BUDGET_EXCEEDED",
        }


def test_persistent_core_retains_revocation_without_minting_a_replacement(
    tmp_path: Path,
):
    with CoreBridge(tmp_path, persistent=True) as core:
        first = core.snapshot()
        assert _authorization(core)["ready"] is True
        revoked = core.revoke()
        assert revoked["status"] == "revoked"

    with CoreBridge(tmp_path, persistent=True) as core:
        second = core.snapshot()
        assert second["grant_id"] == first["grant_id"]
        assert second["grant_status"] == "revoked"
        assert _authorization(core)["ready"] is False


@pytest.mark.parametrize("corruption", ["missing", "invalid-json"])
def test_persistent_core_fails_closed_for_missing_or_corrupt_metadata(
    tmp_path: Path, corruption: str
):
    with CoreBridge(tmp_path, persistent=True):
        pass

    metadata = tmp_path / METADATA_FILENAME
    if corruption == "missing":
        metadata.unlink()
    else:
        metadata.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="(?i)(metadata|state|persistent)"):
        with CoreBridge(tmp_path, persistent=True):
            pass


def test_persistent_core_journals_simulated_receipt_and_submission_count(
    tmp_path: Path,
):
    with CoreBridge(tmp_path, persistent=True) as core:
        settlement = _execute_purchase(core, "purchase_030", "0.30")
        reservation_id = settlement["reservation_id"]
        tx_hash = settlement["tx_hash"]
        receipt = settlement["simulation_receipt"]
        assert core.snapshot()["settlement_submissions"] == 1

    with CoreBridge(tmp_path, persistent=True) as core:
        reconciled = core.reconcile(reservation_id)
        assert reconciled["state"] == "settled"
        assert reconciled["tx_hash"] == tx_hash
        assert reconciled["settlement_receipt_verified"] is True
        assert reconciled["simulation_receipt"] == receipt
        assert core.snapshot()["settlement_submissions"] == 1


@pytest.mark.parametrize(
    "corruption",
    [
        "transaction-record-type",
        "missing-receipt",
        "transaction-hash-mismatch",
        "receipt-hash-mismatch",
        "submission-count-mismatch",
    ],
)
def test_persistent_core_fails_closed_for_parseable_corrupt_settlement_journal(
    tmp_path: Path, corruption: str
):
    with CoreBridge(tmp_path, persistent=True) as core:
        _execute_purchase(core, "purchase_030", "0.30")

    journal_path = tmp_path / SETTLEMENT_JOURNAL_FILENAME
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    transaction_hash = next(iter(journal["transactions"]))
    if corruption == "transaction-record-type":
        journal["transactions"][transaction_hash] = "corrupt"
    elif corruption == "missing-receipt":
        del journal["receipts"][transaction_hash]
    elif corruption == "transaction-hash-mismatch":
        journal["transactions"][transaction_hash]["hash"] = "0x" + "00" * 32
    elif corruption == "receipt-hash-mismatch":
        journal["receipts"][transaction_hash]["transactionHash"] = "0x" + "00" * 32
    else:
        journal["sent_networks"] = []
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(RuntimeError, match="(?i)(journal|settlement|persistent)"):
        with CoreBridge(tmp_path, persistent=True):
            pass


def test_persistent_metadata_contains_public_ids_but_no_wallet_key_and_secret_is_private(
    tmp_path: Path,
):
    with CoreBridge(tmp_path, persistent=True) as core:
        snapshot = core.snapshot()

    metadata_path = tmp_path / METADATA_FILENAME
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    serialized = json.dumps(metadata, sort_keys=True)
    assert metadata["wallet_address"] == snapshot["wallet_address"]
    assert metadata["wallet_identity_id"] == snapshot["wallet_identity_id"]
    assert metadata["spending_grant_id"] == snapshot["grant_id"]
    assert "private_key" not in serialized.lower()
    assert "wallet_key" not in serialized.lower()
    assert "secret" not in metadata

    secret_path = tmp_path / RECEIPT_SECRET_FILENAME
    assert secret_path.exists()
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert os.access(secret_path, os.R_OK)


def test_persistent_core_rejects_a_second_owner(tmp_path: Path):
    first = CoreBridge(tmp_path, persistent=True)
    first.__enter__()
    try:
        with pytest.raises(RuntimeError, match="(?i)(lock|owner|running)"):
            with CoreBridge(tmp_path, persistent=True):
                pass
    finally:
        first.__exit__(None, None, None)
