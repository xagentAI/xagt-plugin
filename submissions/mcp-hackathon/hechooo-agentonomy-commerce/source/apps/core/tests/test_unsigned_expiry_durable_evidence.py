from decimal import Decimal

import pytest

from services.funding_service.ledger import LedgerRow, TransactionBindingRow
from services.funding_service.schemas import SettleSpendingReservationRequest, HostedExecutionAuthorization
from test_direct_transfer_service import command
from test_unsigned_expiry_transfer import (
    _stage_submission_unknown, _install_recovery_reply, _unsigned_expiry_response, _unsigned_audits,
)


@pytest.mark.parametrize("recovery_state", ["unknown", "needs_marker", "known_execution"])
@pytest.mark.parametrize("field", ["settlement_raw_transaction", "external_payment_response", "column_tx_hash", "transaction_binding"])
def test_unsigned_expiry_checks_unredacted_durable_evidence(tmp_path, monkeypatch, field, recovery_state):
    service, funding, repo, client, _prepared, _now = _stage_submission_unknown(tmp_path, monkeypatch)
    transfer_id = "transfer_" + service._hash(["u", "hermes", "test-1"])[:48]
    reservation_id = service._reservation(transfer_id)["reservation_id"]
    with funding.ledger.transaction() as tx:
        stored = tx.s.get(LedgerRow, reservation_id)
        if recovery_state == "needs_marker":
            stored.payload = {**stored.payload, "hosted_submission_unknown": False}
        elif recovery_state == "known_execution":
            stored.payload = {**stored.payload, "hosted_execution_id": "execution_1", "hosted_submission_unknown": False}
        if field == "column_tx_hash":
            stored.tx_hash = "0x" + "ab" * 32
        elif field == "transaction_binding":
            tx.s.add(TransactionBindingRow(tx_hash="0x" + "ab" * 32, reservation_id=reservation_id, created_at=_now))
        else:
            stored.payload = {**stored.payload, field: "legacy-sensitive-evidence"}
    if field not in {"column_tx_hash", "transaction_binding"}:
        assert field not in funding.get_reservation(reservation_id)
    _install_recovery_reply(monkeypatch, client, _unsigned_expiry_response)
    if recovery_state == "known_execution":
        monkeypatch.setattr(client, "recover", lambda request, _execution_id: _unsigned_expiry_response(request).model_copy(update={"execution_id": "execution_1"}))
    result = service.create(command())
    assert result["status"] != "failed"
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    assert repo.spending_grant("grant_1").used_amount_usdc == 0
    assert not _unsigned_audits(repo)
    with funding.ledger.transaction() as tx:
        stored = tx.s.get(LedgerRow, reservation_id)
        assert stored.payload["budget_accounting_state"] == "reserved"
        assert stored.payload.get("hosted_unsigned_expiry_evidence") is None
        if field == "column_tx_hash":
            assert stored.tx_hash == "0x" + "ab" * 32
        elif field == "transaction_binding":
            assert tx.s.get(TransactionBindingRow, "0x" + "ab" * 32).reservation_id == reservation_id
        else:
            assert stored.payload[field] == "legacy-sensitive-evidence"


def test_late_funding_settlement_cannot_erase_private_evidence(tmp_path, monkeypatch):
    service, funding, repo, client, prepared, now = _stage_submission_unknown(tmp_path, monkeypatch)
    transfer_id = "transfer_" + service._hash(["u", "hermes", "test-1"])[:48]
    reservation_id = service._reservation(transfer_id)["reservation_id"]
    with funding.ledger.transaction() as tx:
        stored = tx.s.get(LedgerRow, reservation_id)
        stored.payload = {**stored.payload, "hosted_submission_unknown": False,
                          "settlement_raw_transaction": "legacy-sensitive-evidence"}
        authorization_hash = stored.payload["payment_authorization_hash"]
        cap = tx.payment_capability_for_reservation(reservation_id)
    from datetime import UTC, datetime
    funding._utc_now = lambda: datetime.fromtimestamp(prepared.envelope.issued_at + 1, UTC)

    def reply(request):
        funding._utc_now = lambda: now
        return _unsigned_expiry_response(request)

    _install_recovery_reply(monkeypatch, client, reply)
    authorization = HostedExecutionAuthorization(
        tenant_id=cap.tenant_id, node_id=cap.node_id, wallet_binding_id=cap.wallet_binding_id,
        executor_contract=cap.executor_contract, payment_challenge_hash=cap.payment_challenge_hash,
    )
    with pytest.raises(ValueError, match="durable transaction evidence"):
        funding._settle_hosted_reservation(
            reservation_id, SettleSpendingReservationRequest(payment_authorization={}),
            authorization=authorization, authorization_hash=authorization_hash,
        )
    assert len(client.submit_calls) == 1
    assert repo.spending_grant("grant_1").reserved_amount_usdc == Decimal("2")
    with funding.ledger.transaction() as tx:
        assert tx.s.get(LedgerRow, reservation_id).payload["settlement_raw_transaction"] == "legacy-sensitive-evidence"
