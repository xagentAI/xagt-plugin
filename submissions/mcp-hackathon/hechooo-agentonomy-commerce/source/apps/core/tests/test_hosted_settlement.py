from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from shared.hosted_facilitator_protocol import HostedExecutionResponse
from shared.payment_capability import PaymentCapabilityV1
from services.funding_service.service import FundingService


HASH = "0x" + "44" * 32
OWNER = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
EXECUTOR = "0x" + "33" * 20


def capability() -> PaymentCapabilityV1:
    return PaymentCapabilityV1(
        capability_id="capability_1",
        user_id="user_1",
        agent_id="agent_1",
        tenant_id="tenant_1",
        node_id="node_1",
        wallet_binding_id="binding_1",
        wallet_identity_id="identity_1",
        wallet_address=OWNER,
        spending_grant_id="grant_1",
        spending_grant_hash=HASH,
        asset_allowance_id="allowance_1",
        action_id="action_1",
        policy_decision_id="policy_1",
        policy_snapshot_hash=HASH,
        risk_evidence_hash=HASH,
        reservation_id="reservation_1",
        reservation_hash=HASH,
        purchase_id="purchase_1",
        merchant_id="merchant_1",
        product="marketplace",
        venue="clink_marketplace",
        quote_hash=HASH,
        payment_challenge_hash=HASH,
        network="eip155:8453",
        asset_contract=TOKEN,
        amount_atomic="1000000",
        pay_to=PAYEE,
        executor_contract=EXECUTOR,
        execution_scope_hash=HASH,
        confirmation_mode="user_approved",
        revocation_id=HASH,
        issued_at=100,
        expires_at=160,
    )


def response_for(cap: PaymentCapabilityV1, *, state: str, **updates):
    values = {
        "request_id": "request_1",
        "request_hash": HASH,
        "idempotency_key": "idempotency_1",
        "execution_id": "execution_1",
        "capability_id": cap.capability_id,
        "capability_hash": cap.capability_hash,
        "reservation_id": cap.reservation_id,
        "reservation_hash": cap.reservation_hash,
        "purchase_id": cap.purchase_id,
        "execution_scope_hash": cap.execution_scope_hash,
        "owner": cap.wallet_address,
        "payee": cap.pay_to,
        "token": cap.asset_contract,
        "amount_atomic": cap.amount_atomic,
        "executor": cap.executor_contract,
        "signer_epoch": 1,
        "owner_nonce": HASH,
        "deadline": cap.expires_at,
        "chain_id": cap.network,
        "state": state,
        "transaction_hash": "0x" + "aa" * 32,
        "receipt_block_hash": None,
        "receipt_block_number": None,
        "safe_block_hash": None,
        "safe_block_number": None,
        "confirmations": 0,
        "failure_reason_code": None,
        "issued_at": 100,
        "submitted_at": 100,
        "confirmed_at": None,
        "finalized_at": None,
        "reverted_at": None,
        "reorg_reviewed_at": None,
        "released_at": None,
        "expired_at": None,
        "watcher_version": "hosted-base-watcher-v1",
        "server_key_id": "server-key",
    }
    values.update(updates)
    return HostedExecutionResponse(**values)


class FakeTransaction:
    def __init__(self, row, cap):
        self.row = row
        self.cap = cap
        self.events = []

    def get(self, _reservation_id):
        return dict(self.row)

    def payment_capability_for_reservation(self, _reservation_id):
        return self.cap

    def put(self, _kind, _record_id, row, **_kwargs):
        self.events.append("put")
        self.row = dict(row)
        return dict(row)

    def record_hosted_watcher_evidence(self, row, evidence, *, now):
        self.events.append("evidence")
        return {
            **row,
            "hosted_watcher_evidence": evidence,
            "hosted_watcher_evidence_hash": HASH,
        }

    def record_hosted_watcher_release_evidence(self, row, evidence, *, now):
        canonical = HostedExecutionResponse.model_validate(
            evidence, strict=True
        ).model_dump(mode="json")
        if canonical["state"] != "released":
            raise ValueError("hosted watcher release evidence is invalid")
        previous = row.get("hosted_watcher_release_evidence")
        if previous is not None:
            if previous != canonical:
                raise ValueError("hosted watcher release evidence changed")
            return row
        self.events.append("release_evidence")
        return {
            **row,
            "hosted_watcher_release_evidence": canonical,
            "hosted_watcher_release_evidence_hash": HASH,
        }

    def settle_unified_budget(self, row, *, now):
        self.events.append("settle")
        return {**row, "budget_accounting_state": "settled"}

    def release_unified_budget(self, row, *, now):
        if row.get("budget_accounting_state") == "released":
            return row
        self.events.append("release")
        return {**row, "budget_accounting_state": "released"}

    def record_hosted_watcher_reorg_evidence(self, row, evidence, *, now):
        self.events.append("reorg")
        return {
            **row,
            "hosted_watcher_evidence": evidence,
            "hosted_watcher_evidence_hash": HASH,
        }


class FakeLedger:
    def __init__(self, row, cap):
        self.tx = FakeTransaction(row, cap)

    @contextmanager
    def transaction(self):
        yield self.tx


def service_for(cap: PaymentCapabilityV1, *, state="payment_submitted"):
    row = {
        "reservation_id": cap.reservation_id,
        "state": state,
        "settlement_rail": "hosted",
        "hosted_request_id": "request_1",
        "hosted_request_hash": HASH,
        "hosted_request_nonce": HASH,
        "idempotency_key": "idempotency_1",
        "hosted_execution_id": "execution_1",
        "budget_accounting_state": "reserved",
        "amount_usdc": "1",
        "destination": "destination",
        "resource": "resource",
        "purchase_id": cap.purchase_id,
        "merchant_id": "merchant_1",
        "quote_hash": HASH,
        "action_id": "action_1",
        "policy_decision_id": "policy_1",
        "single_submission": True,
        "replacement_forbidden": False,
        "failed_submission_evidence": [],
    }
    service = FundingService.__new__(FundingService)
    service.ledger = FakeLedger(row, cap)
    service._require_unified_reservation = lambda _row: None
    service._put_reservation = lambda tx, value, **kwargs: tx.put(
        "reservation", value["reservation_id"], value, **kwargs
    )
    service._reservation_authorization = lambda _row, tx=None: SimpleNamespace(
        spending_authorization_id="authorization_1"
    )
    service._record_spending_receipt = lambda **_kwargs: SimpleNamespace(
        to_dict=lambda: {"receipt_id": "receipt_1", "status": "settled"}
    )
    service._utc_now = lambda: __import__("datetime").datetime(2026, 8, 26)
    return service


def test_submission_rejected_keeps_reserved_budget_and_requires_status_only():
    cap = capability()
    service = service_for(cap, state="spending_reserved")
    rejected = response_for(
        cap,
        state="submission_rejected",
        transaction_hash="0x" + "bb" * 32,
        failure_reason_code="RPC_REJECTED",
    )
    result = service._apply_hosted_response(cap.reservation_id, rejected)

    assert result["state"] == "spending_reserved"
    assert result["budget_accounting_state"] == "reserved"
    assert result["hosted_status"] == "submission_rejected"
    assert result["reconciliation_status"] == "manual_review_required"
    assert result["next_action"] == "status_only"
    assert "release" not in service.ledger.tx.events


def test_released_response_releases_reserved_budget():
    cap = capability()
    service = service_for(cap, state="spending_reserved")
    released = safely_released_response(cap)

    result = service._apply_hosted_response(cap.reservation_id, released)

    assert result["state"] == "released"
    assert result["budget_accounting_state"] == "released"
    assert result["next_action"] == "terminal"
    assert service.ledger.tx.events[-1] == "put"
    assert "release" in service.ledger.tx.events


def release_evidence(**updates):
    values = {
        "receipt_status": 0,
        "canonical_receipt": True,
        "finality_boundary_timestamp": 161,
        "capability_used": False,
        "owner_nonce_used": False,
        "payment_event_found": False,
        "transfer_event_found": False,
    }
    values.update(updates)
    return values


def reverted_response(cap: PaymentCapabilityV1, **updates):
    return response_for(
        cap,
        state="reverted",
        receipt_block_hash="0x" + "bb" * 32,
        receipt_block_number=100,
        safe_block_hash="0x" + "cc" * 32,
        safe_block_number=102,
        confirmations=2,
        reverted_at=103,
        failure_reason_code="ONCHAIN_REVERT",
        finality_boundary="safe",
        **updates,
    )


def safely_released_response(cap: PaymentCapabilityV1, **updates):
    values = {
        "receipt_block_hash": "0x" + "bb" * 32,
        "receipt_block_number": 100,
        "safe_block_hash": "0x" + "cc" * 32,
        "safe_block_number": 102,
        "confirmations": 2,
        "reverted_at": 103,
        "released_at": 162,
        "failure_reason_code": "SAFE_RELEASE",
        "finality_boundary": "safe",
        "release_evidence": release_evidence(),
    }
    values.update(updates)
    return response_for(cap, state="released", **values)


def test_reverted_response_keeps_reserved_budget_until_safe_release_proof():
    cap = capability()
    service = service_for(cap, state="payment_submitted")

    result = service._apply_hosted_response(
        cap.reservation_id,
        reverted_response(cap),
    )
    replay = service._apply_hosted_response(
        cap.reservation_id,
        reverted_response(cap),
    )

    assert result["state"] == "payment_submitted"
    assert result["budget_accounting_state"] == "reserved"
    assert result["reconciliation_status"] == "pending"
    assert result["next_action"] == "status_only"
    assert replay["state"] == "payment_submitted"
    assert replay["budget_accounting_state"] == "reserved"
    assert "release" not in service.ledger.tx.events


def test_safe_release_proof_releases_reserved_budget_exactly_once():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._apply_hosted_response(cap.reservation_id, reverted_response(cap))

    result = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )
    replay = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    assert result["state"] == "released"
    assert result["budget_accounting_state"] == "released"
    assert result["next_action"] == "terminal"
    assert replay["state"] == "released"
    assert service.ledger.tx.events.count("release") == 1
    assert service.ledger.tx.events.count("release_evidence") == 1


def test_safe_release_replay_preserves_core_release_timestamp():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._apply_hosted_response(cap.reservation_id, reverted_response(cap))
    service._utc_now = lambda: datetime.fromtimestamp(200, UTC)

    released = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )
    service._utc_now = lambda: datetime.fromtimestamp(300, UTC)
    replay = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    assert replay == released
    assert replay["released_at"] == "1970-01-01T00:03:20+00:00Z"
    assert service.ledger.tx.events.count("release") == 1
    assert service.ledger.tx.events.count("release_evidence") == 1


def test_safe_release_proof_change_is_rejected_after_first_release():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._apply_hosted_response(cap.reservation_id, reverted_response(cap))
    service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    with pytest.raises(ValueError, match="release evidence"):
        service._apply_hosted_response(
            cap.reservation_id,
            safely_released_response(
                cap,
                release_evidence=release_evidence(
                    finality_boundary_timestamp=162,
                ),
            ),
        )


def test_safe_release_outer_proof_change_is_rejected_after_first_release():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._apply_hosted_response(cap.reservation_id, reverted_response(cap))
    service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    with pytest.raises(ValueError, match="release evidence"):
        service._apply_hosted_response(
            cap.reservation_id,
            safely_released_response(
                cap,
                receipt_block_hash="0x" + "dd" * 32,
            ),
        )


def test_stale_reverted_response_cannot_regress_released_reservation():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    reverted = reverted_response(cap)
    service._apply_hosted_response(cap.reservation_id, reverted)
    released = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    replay = service._apply_hosted_response(cap.reservation_id, reverted)

    assert replay == released
    assert replay["state"] == "released"
    assert replay["budget_accounting_state"] == "released"
    assert service.ledger.tx.events.count("release") == 1
    assert service.ledger.tx.events.count("release_evidence") == 1


def test_safe_release_recovers_lost_submission_and_binds_execution_once():
    cap = capability()
    service = service_for(cap, state="spending_reserved")
    service.ledger.tx.row.update(
        {
            "hosted_execution_id": None,
            "hosted_submission_unknown": True,
        }
    )

    result = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )
    replay = service._apply_hosted_response(
        cap.reservation_id,
        safely_released_response(cap),
    )

    assert result["state"] == replay["state"] == "released"
    assert result["hosted_execution_id"] == "execution_1"
    assert result["tx_hash"] == "0x" + "aa" * 32
    assert service.ledger.tx.events.count("release") == 1


def test_safe_release_rejects_finality_boundary_from_core_future():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._utc_now = lambda: datetime.fromtimestamp(105, UTC)

    with pytest.raises(ValueError, match="future"):
        service._apply_hosted_response(
            cap.reservation_id,
            safely_released_response(cap),
        )


def test_safe_release_execution_identity_change_is_rejected():
    cap = capability()
    service = service_for(cap, state="payment_submitted")
    service._apply_hosted_response(cap.reservation_id, reverted_response(cap))

    with pytest.raises(ValueError, match="identity"):
        service._apply_hosted_response(
            cap.reservation_id,
            safely_released_response(cap, execution_id="execution_2"),
        )


def finalized_response(cap: PaymentCapabilityV1, **updates):
    return response_for(
        cap,
        state="finalized",
        receipt_block_hash="0x" + "bb" * 32,
        receipt_block_number=100,
        safe_block_hash="0x" + "cc" * 32,
        safe_block_number=102,
        confirmations=2,
        confirmed_at=101,
        finalized_at=102,
        finality_boundary="safe",
        **updates,
    )


def test_finalized_recovery_from_reserved_records_evidence_before_settlement():
    cap = capability()
    service = service_for(cap, state="spending_reserved")
    finalized = finalized_response(cap)

    result = service._apply_hosted_response(cap.reservation_id, finalized)

    assert result["state"] == "settled"
    assert result["budget_accounting_state"] == "settled"
    assert result["tx_hash"] == finalized.transaction_hash
    assert result["hosted_watcher_evidence"]
    assert result["hosted_watcher_evidence"]["watcher_version"] == "hosted-base-watcher-v1"
    events = service.ledger.tx.events
    assert events.index("evidence") < events.index("settle")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"execution_id": "execution_2"}, "identity"),
        ({"execution_scope_hash": "0x" + "55" * 32}, "scope"),
    ],
)
def test_finalized_recovery_rejects_execution_or_scope_drift(updates, message):
    cap = capability()
    service = service_for(cap, state="spending_reserved")
    finalized = finalized_response(cap, **updates)

    with pytest.raises(ValueError, match=message):
        service._apply_hosted_response(cap.reservation_id, finalized)


def test_reorg_response_enters_manual_review_without_releasing_budget():
    cap = capability()
    service = service_for(cap)
    reorg = response_for(
        cap,
        state="reorg_review",
        receipt_block_hash="0x" + "bb" * 32,
        receipt_block_number=100,
        safe_block_hash="0x" + "cc" * 32,
        safe_block_number=102,
        confirmations=3,
        confirmed_at=101,
        reorg_reviewed_at=102,
        failure_reason_code="REORG_DETECTED",
        finality_boundary="safe",
    )
    result = service._apply_hosted_response(cap.reservation_id, reorg)

    assert result["state"] == "reorg_review"
    assert result["next_action"] == "manual_review"
