from __future__ import annotations

from tests.test_purchase_result_and_reputation import (
    MerchantResponse,
    RecordingClient,
    RecordingCore,
    build_purchase_service,
    build_repository,
    store_purchase,
)


class CoreExecutionBoundary(RecordingCore):
    """A test double that makes non-Core execution paths observable."""

    def __init__(self) -> None:
        super().__init__()
        self.hosted_calls = 0
        self.relayer_calls = 0

    def hosted_execute(self, *_args, **_kwargs):
        self.hosted_calls += 1
        raise AssertionError("Marketplace must not call Hosted directly")

    def relayer_submit(self, *_args, **_kwargs):
        self.relayer_calls += 1
        raise AssertionError("Marketplace must not call a relayer directly")


def test_paid_but_undelivered_replay_keeps_one_purchase_and_core_payment(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = CoreExecutionBoundary()
    merchant = RecordingClient(
        MerchantResponse({"error": "delivery unavailable"}, success=False)
    )
    service = build_purchase_service(
        repository, offering, core, client=merchant
    )
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )

    first = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )
    replay = service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="auth_1",
    )

    assert first["purchase"].state == "paid_but_undelivered"
    assert replay["purchase"].purchase_id == first["purchase"].purchase_id
    assert replay["purchase"].state == "paid_but_undelivered"
    assert core.reserves == 1
    assert core.settlements == 1
    assert merchant.calls == 1
    assert core.hosted_calls == 0
    assert core.relayer_calls == 0


def test_reconciliation_does_not_resubmit_until_core_marks_safe(tmp_path):
    repository, offering = build_repository(tmp_path)
    core = RecordingCore()
    core.reservation_result = {
        "state": "spending_reserved",
        "reconciliation_status": "pending",
        "next_action": "reconcile_payment",
    }
    merchant = RecordingClient(MerchantResponse({"risk": "low"}))
    service = build_purchase_service(repository, offering, core, client=merchant)
    preview = service.create_preview(
        user_id="hermes",
        offering_id=offering.offering_id,
        service_input={"wallet": "0xabc"},
    )
    purchase_id = "purchase_" + preview.preview_id.removeprefix("preview_")
    purchase = store_purchase(
        repository, offering, purchase_id, "payment_submitted"
    )
    repository.save_purchase(
        purchase.model_copy(update={"reservation_id": "reserve_1"})
    )

    pending = service.execute(preview.preview_id)

    assert pending["purchase"].state == "payment_submitted"
    assert pending["purchase"].reason_code == "PAYMENT_RECONCILIATION_PENDING"
    assert core.reconciliations == 1
    assert core.settlements == 0
    assert merchant.calls == 0
