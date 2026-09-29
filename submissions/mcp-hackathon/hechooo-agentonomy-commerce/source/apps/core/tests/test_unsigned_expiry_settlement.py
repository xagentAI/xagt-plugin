from datetime import UTC, datetime

import pytest

from test_hosted_settlement import capability, response_for, service_for


def unsigned_response(cap, **updates):
    values = dict(transaction_hash=None, submitted_at=None, watcher_version=None,
                  expired_at=161, issued_at=100,
                  failure_reason_code="UNSIGNED_EXECUTION_EXPIRED")
    values.update(updates)
    return response_for(cap, state="expired", **values)


def unsigned_service():
    cap = capability()
    service = service_for(cap, state="spending_reserved")

    def record(row, evidence, *, now):
        canonical = {k: v for k, v in evidence.items() if k != "server_key_id"}
        previous = row.get("hosted_unsigned_expiry_evidence")
        if previous is not None and previous != canonical:
            raise ValueError("Hosted unsigned expiry evidence changed")
        if previous is None:
            service.ledger.tx.events.append("unsigned_evidence")
        return {**row, "hosted_unsigned_expiry_evidence": canonical}

    service.ledger.tx.record_hosted_unsigned_expiry_evidence = record
    return cap, service


def test_unsigned_expiry_releases_once_and_preserves_semantic_proof():
    cap, service = unsigned_service()
    first = service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))
    assert first["state"] == "released"
    assert first["budget_accounting_state"] == "released"
    assert first["release_reason"] == "UNSIGNED_EXECUTION_EXPIRED"
    assert first["next_action"] == "terminal"
    assert first.get("tx_hash") is None
    again = service._apply_hosted_response(cap.reservation_id, unsigned_response(cap, server_key_id="rotated-key"))
    assert again == first
    assert service.ledger.tx.events.count("release") == 1
    assert service.ledger.tx.events.count("unsigned_evidence") == 1


@pytest.mark.parametrize("field,value", [
    ("tx_hash", "0x" + "ab" * 32), ("receipt_id", "receipt_1"),
    ("receipt", {"status": "settled"}), ("hosted_watcher_evidence", {"state": "reverted"}),
    ("settlement_raw_transaction", "0xsigned"),
    ("hosted_response", {"state": "submitted", "transaction_hash": "0x" + "ab" * 32}),
    ("failed_submission_evidence", [{"tx_hash": "0x" + "ab" * 32}]),
    ("receipt", {}), ("hosted_watcher_evidence", {}), ("settlement_transaction", {}),
    ("failed_submission_evidence", {}), ("tx_hash", ""),
])
def test_unsigned_expiry_never_overwrites_existing_chain_evidence(field, value):
    cap, service = unsigned_service()
    service.ledger.tx.row[field] = value
    with pytest.raises(ValueError):
        service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))
    assert "release" not in service.ledger.tx.events


def test_legacy_expiry_remains_reserved():
    cap, service = unsigned_service()
    result = service._apply_hosted_response(cap.reservation_id, unsigned_response(
        cap, failure_reason_code="AUTHORIZATION_EXPIRED"))
    assert result["budget_accounting_state"] == "reserved"
    assert result["reconciliation_status"] == "manual_review_required"


def test_unsigned_expiry_rejects_future_proof():
    cap, service = unsigned_service()
    service._utc_now = lambda: datetime.fromtimestamp(160, UTC)
    with pytest.raises(ValueError):
        service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))
    assert "release" not in service.ledger.tx.events


def test_unsigned_expiry_conflicting_replay_is_not_silently_accepted():
    cap, service = unsigned_service()
    service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))
    with pytest.raises(ValueError, match="evidence changed"):
        service._apply_hosted_response(cap.reservation_id, unsigned_response(cap, expired_at=162))
    assert service.ledger.tx.events.count("release") == 1


def test_unsigned_expiry_requires_original_execution_identity_or_unknown_marker():
    cap, service = unsigned_service()
    service.ledger.tx.row["hosted_execution_id"] = None
    with pytest.raises(ValueError):
        service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))
    service.ledger.tx.row["hosted_submission_unknown"] = True
    assert service._apply_hosted_response(cap.reservation_id, unsigned_response(cap))["state"] == "released"
