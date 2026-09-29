from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.dialects import postgresql, sqlite

from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from services.marketplace_worker import _retry_finalizations
from storage.tables import PurchaseFinalizationRow, PurchaseRow, ReputationEventRow
from tests.test_purchase_result_and_reputation import (
    MerchantResponse,
    RecordingClient,
    RecordingCore,
    build_repository,
    build_purchase_service,
    event_rows,
    store_purchase,
)


def outbox_count(repository):
    with repository.sessions() as session:
        return session.scalar(select(func.count()).select_from(PurchaseFinalizationRow))


class RacingCore(RecordingCore):
    def __init__(self, *, race_external=False):
        super().__init__()
        self.lock = threading.Lock()
        self.first_entered = threading.Event()
        self.release_first = threading.Event()
        self.action_calls = 0
        self.external_calls = 0
        self.finalize_calls = 0
        self.race_external = race_external

    def _race(self, call_number):
        if call_number == 1:
            self.first_entered.set()
            self.release_first.wait(timeout=0.4)
        else:
            self.release_first.set()

    def create_action(self, payload):
        with self.lock:
            self.action_calls += 1
            call_number = self.action_calls
        if not self.race_external:
            self._race(call_number)
        return {"action_id": f"action_{call_number}"}

    def reserve(self, payload):
        with self.lock:
            self.reserves += 1
        return {"reservation_id": "reserve_1"}

    def settle(self, reservation_id, payload):
        with self.lock:
            self.settlements += 1
        return {
            "state": "settled",
            "receipt_id": "receipt_1",
            "receipt": {"receipt_id": "receipt_1"},
        }

    def external_finalize(self, reservation_id, payload):
        with self.lock:
            self.external_calls += 1
            call_number = self.external_calls
        self._race(call_number)
        return {"state": "settled", "receipt_id": "receipt_external_1"}

    def finalize(self, reservation_id, payload):
        with self.lock:
            self.finalize_calls += 1
        return {"state": "finalized"}


class OpposingClient:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0

    def request(self, *args, **kwargs):
        with self.lock:
            self.calls += 1
            call_number = self.calls
        return MerchantResponse(
            {"risk": "low"} if call_number == 1 else {"error": "down"},
            success=call_number == 1,
        )


class ProtocolTrackingCore(RecordingCore):
    def __init__(self):
        super().__init__()
        self.external_calls = 0

    def external_finalize(self, reservation_id, payload):
        self.external_calls += 1
        return {"state": "settled", "receipt_id": "receipt_external_1"}


class CanonicalScopeCore(RecordingCore):
    def __init__(self, *, approved=True, reason_code=None):
        super().__init__(approved=approved)
        self.reason_code = reason_code
        self.action_payload = None
        self.action_update_payload = None
        self.policy_payload = None
        self.reserve_payload = None

    def create_action(self, payload):
        self.action_payload = payload
        return {"action_id": "action_1"}

    def evaluate_policy(self, payload):
        self.policy_payload = payload
        return {
            "policy_decision_id": "policy_1",
            "approved": self.approved,
            "reason_code": self.reason_code or "APPROVED",
            "required_action": (
                "provide_exact_payment_target_and_network"
                if self.reason_code
                else None
            ),
        }

    def update_action(self, action_id, payload):
        self.action_update_payload = payload
        return {}

    def reserve(self, payload):
        self.reserve_payload = payload
        return super().reserve(payload)


def _replace_payment_recipient(repository, offering, recipient):
    payment = offering.payment_options[0].model_copy(
        update={
            "network": "eip155:8453",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "pay_to": recipient,
        }
    )
    updated = offering.model_copy(update={"payment_options": [payment]})
    repository.upsert_offering(updated, verified_at=datetime.now(UTC))
    return updated


def test_external_purchase_canonicalizes_evm_payment_scope_before_core(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    checksum_recipient = "0x6d6E695b09861467c7d462f5AAF31cF3540B9192"
    offering = _replace_payment_recipient(repository, offering, checksum_recipient)
    core = CanonicalScopeCore()
    service = build_purchase_service(repository, offering, core)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"url": "https://example.com"},
    )

    result = service.execute(preview.preview_id, user_confirmed=True)

    canonical = checksum_recipient.lower()
    assert result.state == "signing_required"
    assert core.action_payload["metadata"]["destination"] == canonical
    assert core.policy_payload["target_address"] == canonical
    assert core.policy_payload["metadata"]["destination"] == canonical
    assert core.action_update_payload == {
        "state": "policy_approved",
        "policy_decision_id": "policy_1",
    }
    assert core.reserve_payload["destination"] == canonical


def test_policy_block_reason_is_not_masked_as_confirmation_required(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    core = CanonicalScopeCore(
        approved=False,
        reason_code="PAYMENT_TARGET_BINDING_REQUIRED",
    )
    service = build_purchase_service(repository, offering, core)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"url": "https://example.com"},
    )

    result = service.execute(preview.preview_id, user_confirmed=True)

    assert result.state == "confirmation_required"
    assert result.reason_code == "PAYMENT_TARGET_BINDING_REQUIRED"
    assert result.metadata["policy_required_action"] == (
        "provide_exact_payment_target_and_network"
    )


def test_native_concurrent_execute_has_one_settlement_delivery_and_outcome(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RacingCore()
    client = OpposingClient()
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            service.execute,
            preview.preview_id,
            user_confirmed=True,
            spending_authorization_id="auth_1",
        )
        assert core.first_entered.wait(timeout=1)
        second = pool.submit(
            service.execute,
            preview.preview_id,
            user_confirmed=True,
            spending_authorization_id="auth_1",
        )
        results = [first.result(timeout=3), second.result(timeout=3)]

    stored = repository.get_purchase("purchase_" + preview.preview_id.removeprefix("preview_"))
    assert core.reserves == 1
    assert core.settlements == 1
    assert client.calls == 1
    assert core.finalize_calls == 1
    assert len(event_rows(repository)) == 1
    assert outbox_count(repository) == 0
    assert event_rows(repository)[0][1] == stored.state == "delivered"
    assert sum(result["service_result"] is not None for result in results) == 1


def test_external_concurrent_complete_has_one_finalize_delivery_and_outcome(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    core = RacingCore(race_external=True)
    client = OpposingClient()
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    pending = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )["purchase"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            service.complete_external,
            pending.purchase_id,
            transaction_hash="0xabc",
            payment_response={"signature": "0xsigned"},
        )
        assert core.first_entered.wait(timeout=1)
        second = pool.submit(
            service.complete_external,
            pending.purchase_id,
            transaction_hash="0xabc",
            payment_response={"signature": "0xsigned"},
        )
        results = [first.result(timeout=3), second.result(timeout=3)]

    stored = repository.get_purchase(pending.purchase_id)
    assert core.external_calls == 1
    assert client.calls == 1
    assert len(event_rows(repository)) == 1
    assert event_rows(repository)[0][1] == stored.state == "delivered"
    assert sum(result["service_result"] is not None for result in results) == 1


def test_confirmation_required_retry_can_advance_to_delivery(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore(approved=False)
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    waiting = service.execute(preview.preview_id)
    core.approved = True

    delivered = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert waiting["purchase"].state == "confirmation_required"
    assert delivered["purchase"].state == "delivered"
    assert delivered["service_result"] == {"risk": "low"}
    assert core.reserves == core.settlements == client.calls == 1
    assert len(event_rows(repository)) == 1


def test_spending_reserved_retry_advances_without_second_reserve(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "spending_reserved")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    result = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert result["purchase"].state == "delivered"
    assert core.reserves == 0
    assert core.settlements == client.calls == 1


def test_payment_submitted_retry_reconciles_without_second_settle(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "settled",
        "receipt_id": "receipt_1",
        "receipt": {"receipt_id": "receipt_1"},
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    result = service.execute(preview.preview_id)

    assert result["purchase"].state == "delivered"
    assert core.reconciliations == 1
    assert core.reservation_reads == 0
    assert core.settlements == 0
    assert client.calls == 1


def test_payment_submitted_recovery_does_not_reauthorize_after_core_auth_expires(
    tmp_path,
):
    repository, offering = build_repository(tmp_path)

    class ExpiringAuthorizationCore(RecordingCore):
        def __init__(self):
            super().__init__()
            self.authorization_calls = 0

        def resolve_authorization(self, payload):
            self.authorization_calls += 1
            if self.authorization_calls > 1:
                return {
                    "ready": False,
                    "reason_code": "SPENDING_GRANT_REQUIRED",
                    "next_action": "reconnect_wallet",
                }
            return super().resolve_authorization(payload)

        def create_account_session(self, _user_id):
            raise AssertionError(
                "payment_submitted recovery must not create an account session"
            )

    core = ExpiringAuthorizationCore()
    core.reservation_result = {
        "state": "settled",
        "receipt_id": "receipt_1",
        "tx_hash": "0x" + "1" * 64,
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    result = service.execute(preview.preview_id)

    assert result["purchase"].state == "delivered"
    assert result["purchase"].reason_code is None
    assert core.authorization_calls == 1
    assert core.reserves == 0
    assert core.settlements == 0
    assert core.reconciliations == 1
    assert client.calls == 1


def test_payment_submitted_recovery_does_not_settle_manual_review(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "payment_submitted",
        "reconciliation_status": "manual_review_required",
        "next_action": "operator_reconcile",
        "tx_hash": "0x" + "1" * 64,
        "receipt_id": None,
        "receipt": None,
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    result = service.execute(preview.preview_id)

    assert result["purchase"].state == "payment_submitted"
    assert result["purchase"].reason_code == "PAYMENT_MANUAL_REVIEW_REQUIRED"
    assert core.reconciliations == 1
    assert core.settlements == 0
    assert client.calls == 0


def test_native_pending_reconciliation_retries_only_after_core_marks_safe(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "payment_submitted",
        "reconciliation_status": "pending",
        "next_action": "reconcile_payment",
        "tx_hash": "0xpending",
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes", offering_id=offering.offering_id, service_input={"wallet": "0xabc"}
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    pending = service.execute(preview.preview_id)
    core.reservation_result = {
        "state": "spending_reserved",
        "reconciliation_status": "retryable",
        "next_action": "retry_settlement",
    }
    delivered = service.execute(preview.preview_id)

    assert pending.state == "payment_submitted"
    assert pending.reason_code == "PAYMENT_RECONCILIATION_PENDING"
    assert pending.metadata["settlement"]["tx_hash"] == "0xpending"
    assert delivered.state == "delivered"
    assert core.reconciliations == 2
    assert core.settlements == client.calls == 1


def test_native_initial_pending_result_never_delivers_before_reconciliation(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.settle = lambda _reservation_id, _payload: {
        "state": "payment_submitted",
        "reconciliation_status": "pending",
        "next_action": "reconcile_payment",
        "tx_hash": "0xnative",
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes", offering_id=offering.offering_id, service_input={"wallet": "0xabc"}
    )

    pending = service.execute(
        preview.preview_id, user_confirmed=True, spending_authorization_id="auth_1"
    )

    assert pending.state == "payment_submitted"
    assert pending.reason_code == "PAYMENT_RECONCILIATION_PENDING"
    assert client.calls == 0


def test_external_retry_accepts_corrected_proof_only_after_core_marks_retryable(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    core = ProtocolTrackingCore()
    core.reservation_result = {
        "state": "spending_reserved",
        "reconciliation_status": "retryable",
        "next_action": "retry_settlement",
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes", offering_id=offering.offering_id, service_input={"wallet": "0xabc"}
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={
        "execution_mode": "external_x402_signature", "reservation_id": "reserve_1"
    }))

    delivered = service.execute(
        preview.preview_id,
        transaction_hash="0xcorrected",
        payment_response={"signature": "0xcorrected"},
    )

    assert delivered.state == "delivered"
    assert core.reconciliations == 1
    assert core.external_calls == client.calls == 1


def test_external_pending_reconciliation_does_not_submit_different_proof(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    core = ProtocolTrackingCore()
    core.reservation_result = {
        "state": "payment_submitted",
        "reconciliation_status": "pending",
        "next_action": "reconcile_payment",
        "tx_hash": "0xoriginal",
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes", offering_id=offering.offering_id, service_input={"wallet": "0xabc"}
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={
        "execution_mode": "external_x402_signature", "reservation_id": "reserve_1"
    }))

    pending = service.execute(
        preview.preview_id,
        transaction_hash="0xdifferent",
        payment_response={"signature": "0xdifferent"},
    )

    assert pending.state == "payment_submitted"
    assert pending.reason_code == "PAYMENT_RECONCILIATION_PENDING"
    assert core.external_calls == client.calls == 0


def test_worker_reconciles_and_safely_resubmits_retryable_native_payment(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "spending_reserved",
        "reconciliation_status": "retryable",
        "next_action": "retry_settlement",
    }
    service = build_purchase_service(repository, offering, core)
    preview = service.create_preview(
        user_id="hermes", offering_id=offering.offering_id, service_input={"wallet": "0xabc"}
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    result = _retry_finalizations(repository, service)

    stored = repository.get_purchase(purchase_id)
    assert result["reconciled"] == 1
    assert stored.state == "payment_submitted"
    assert stored.reason_code == "PAYMENT_SETTLED_DELIVERY_RETRY_REQUIRED"
    assert stored.receipt_id is None
    assert stored.metadata["settlement"]["state"] == "settled"
    assert core.reconciliations == core.settlements == 1


def test_worker_stops_retrying_after_core_requires_manual_payment_review(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "payment_submitted",
        "reconciliation_status": "manual_review_required",
        "next_action": "operator_reconcile",
        "tx_hash": "0x" + "1" * 64,
        "reconciliation_attempts": 12,
        "reconciliation_started_at": "2026-07-13T00:00:00Z",
        "last_reconciliation_at": "2026-07-13T01:00:00Z",
        "manual_review_reason": "automatic reconciliation attempt limit reached",
        "manual_review_required_at": "2026-07-13T01:00:00Z",
    }
    service = build_purchase_service(repository, offering, core)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(
        purchase.model_copy(update={"reservation_id": "reserve_1"})
    )

    first_cycle = _retry_finalizations(repository, service)
    stored = repository.get_purchase(purchase_id)
    second_cycle = _retry_finalizations(repository, service)

    assert first_cycle["reconciled"] == 1
    assert stored.reason_code == "PAYMENT_MANUAL_REVIEW_REQUIRED"
    assert stored.metadata["settlement"]["next_action"] == "operator_reconcile"
    assert stored.metadata["settlement"]["reconciliation_attempts"] == 12
    assert stored.metadata["settlement"]["manual_review_reason"]
    assert second_cycle["reconciled"] == 0
    assert core.reconciliations == 1


def test_native_payment_submitted_rejects_external_completion_then_execute_advances(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = ProtocolTrackingCore()
    core.reservation_result = {
        "state": "settled",
        "receipt_id": "receipt_native_1",
        "receipt": {"receipt_id": "receipt_native_1"},
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(purchase.model_copy(update={"reservation_id": "reserve_1"}))

    with pytest.raises(ValueError, match="execution mode"):
        service.complete_external(
            purchase_id,
            transaction_hash="0xabc",
            payment_response={"signature": "0xsigned"},
        )

    assert core.external_calls == 0
    assert client.calls == 0
    delivered = service.execute(preview.preview_id)
    assert delivered["purchase"].state == "delivered"
    assert core.settlements == 0
    assert client.calls == 1


def test_external_payment_submitted_requires_proof_to_resume_delivery(tmp_path):
    repository, offering = build_repository(tmp_path, native=False)
    core = ProtocolTrackingCore()
    core.reservation_result = {
        "state": "settled",
        "receipt_id": "receipt_external_1",
        "receipt": {"receipt_id": "receipt_external_1"},
    }
    client = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=client)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(repository, offering, purchase_id, "payment_submitted")
    repository.save_purchase(
        purchase.model_copy(
            update={
                "execution_mode": "external_x402_signature",
                "reservation_id": "reserve_1",
            }
        )
    )

    waiting = service.execute(preview.preview_id)

    assert core.settlements == 0
    assert client.calls == 0
    assert waiting.state == "payment_submitted"
    delivered = service.execute(
        preview.preview_id,
        transaction_hash="0xabc",
        payment_response={"signature": "0xsigned"},
    )
    assert delivered["purchase"].state == "delivered"
    assert delivered["service_result"] == {"risk": "low"}
    assert core.external_calls == 0
    assert client.calls == 1


def test_guarded_transition_rejects_execution_mode_changed_after_claim(tmp_path):
    repository, offering = build_repository(tmp_path)
    purchase = store_purchase(repository, offering, "purchase_mode_race", "spending_reserved")
    claimed, claim_token = repository.claim_purchase_execution(
        purchase,
        allowed_states={"spending_reserved"},
        expected_execution_mode="clink_allowance",
    )
    with repository.sessions.begin() as session:
        session.get(PurchaseRow, purchase.purchase_id).execution_mode = (
            "external_x402_signature"
        )

    submitted = claimed.model_copy(update={"state": "payment_submitted"})
    with pytest.raises(RuntimeError, match="claim lost"):
        repository.save_claimed_purchase(
            submitted,
            claim_token,
            expected_execution_mode="clink_allowance",
            expected_states={"spending_reserved"},
        )

    stored = repository.get_purchase(purchase.purchase_id)
    assert stored.state == "spending_reserved"
    assert stored.execution_mode == "external_x402_signature"


def test_atomic_terminal_write_rejects_stale_caller_execution_mode(tmp_path):
    repository, offering = build_repository(tmp_path)
    stale = store_purchase(repository, offering, "purchase_stale_mode", "delivered")
    with repository.sessions.begin() as session:
        session.get(PurchaseRow, stale.purchase_id).execution_mode = (
            "external_x402_signature"
        )
    before = repository.get_purchase(stale.purchase_id)

    with pytest.raises(ValueError, match="execution mode"):
        repository.save_purchase_with_reputation_event(
            stale,
            "delivered",
            {"payment_success": 100, "delivery_success": 100},
            claim_token="stale_native_claim",
            expected_execution_mode="clink_allowance",
            finalization={
                "target_state": "delivered",
                "payload": {
                    "reservation_id": "reserve_stale",
                    "delivery_status": "delivered",
                    "output_hash": stale.output_hash,
                },
            },
        )

    assert repository.get_purchase(stale.purchase_id) == before
    assert event_rows(repository) == []
    assert outbox_count(repository) == 0


def test_terminal_purchase_event_and_native_outbox_roll_back_together(tmp_path):
    repository, offering = build_repository(tmp_path)
    purchase = store_purchase(repository, offering, "purchase_atomic", "spending_reserved")
    purchase = purchase.model_copy(update={"reservation_id": "reserve_atomic"})
    repository.save_purchase(purchase)
    claimed, claim_token = repository.claim_purchase_execution(
        purchase, allowed_states={"spending_reserved"}, expected_execution_mode="clink_allowance"
    )
    terminal = claimed.model_copy(
        update={
            "state": "delivered",
            "output_hash": "0xoutput",
            "receipt_id": "receipt_atomic",
            "updated_at": datetime.now(UTC),
        }
    )

    def fail_event_insert(mapper, connection, target):
        raise RuntimeError("injected reputation failure")

    event.listen(ReputationEventRow, "before_insert", fail_event_insert)
    try:
        with pytest.raises(RuntimeError, match="injected reputation failure"):
            repository.save_purchase_with_reputation_event(
                terminal,
                "delivered",
                {"payment_success": 100, "delivery_success": 100},
                claim_token=claim_token,
                expected_execution_mode="clink_allowance",
                finalization={
                    "target_state": "delivered",
                    "payload": {
                        "reservation_id": "reserve_atomic",
                        "delivery_status": "delivered",
                        "output_hash": "0xoutput",
                    },
                },
            )
    finally:
        event.remove(ReputationEventRow, "before_insert", fail_event_insert)

    assert repository.get_purchase(purchase.purchase_id).state == "spending_reserved"
    assert event_rows(repository) == []
    assert outbox_count(repository) == 0


def test_atomic_terminal_write_is_concurrently_idempotent(tmp_path):
    repository, offering = build_repository(tmp_path)
    purchase = store_purchase(repository, offering, "purchase_concurrent", "spending_reserved")
    purchase = purchase.model_copy(update={"reservation_id": "reserve_concurrent"})
    repository.save_purchase(purchase)
    claimed, claim_token = repository.claim_purchase_execution(
        purchase, allowed_states={"spending_reserved"}, expected_execution_mode="clink_allowance"
    )
    terminal = claimed.model_copy(
        update={
            "state": "delivered",
            "output_hash": "0xoutput",
            "receipt_id": "receipt_concurrent",
            "updated_at": datetime.now(UTC),
        }
    )

    def save_once():
        local = MarketplaceRepository(str(repository.engine.url))
        return local.save_purchase_with_reputation_event(
            terminal,
            "delivered",
            {"payment_success": 100, "delivery_success": 100},
            claim_token=claim_token,
            expected_execution_mode="clink_allowance",
            finalization={
                "target_state": "delivered",
                "payload": {
                    "reservation_id": "reserve_concurrent",
                    "delivery_status": "delivered",
                    "output_hash": "0xoutput",
                },
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=3) for future in [pool.submit(save_once), pool.submit(save_once)]]

    assert {result.state for result in results} == {"delivered"}
    assert len(event_rows(repository)) == 1
    assert outbox_count(repository) == 1


def test_claim_migration_adds_and_removes_portable_claim_columns(tmp_path, monkeypatch):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from tests.test_purchase_result_and_reputation import alembic_config

    database_url = f"sqlite+pysqlite:///{tmp_path / 'claims.sqlite3'}"
    config = alembic_config(monkeypatch, database_url)
    command.upgrade(config, "20260713_0005")
    engine = create_engine(database_url)
    assert "execution_claim_token" not in {
        column["name"] for column in inspect(engine).get_columns("purchases")
    }

    command.upgrade(config, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("purchases")}
    assert {"execution_claim_token", "execution_claim_until"} <= columns
    command.downgrade(config, "20260713_0005")
    columns = {column["name"] for column in inspect(engine).get_columns("purchases")}
    assert "execution_claim_token" not in columns


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_execution_claim_cas_compiles_for_supported_dialects(dialect):
    now = datetime.now(UTC)
    statement = MarketplaceRepository._execution_claim_update(
        "purchase_1", {"preview_created", "payment_submitted"}, "clink_allowance", now, "token_1", now
    )

    sql = str(statement.compile(dialect=dialect))

    assert "UPDATE purchases" in sql
    assert "execution_claim_token IS NULL" in sql
    assert "execution_mode" in sql
    assert "execution_claim_until IS NULL" in sql
    assert "execution_claim_until <=" in sql
