from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.ephemeral import EphemeralStore
from shared.models import PaymentOption, Provider, ServiceOffering
from storage.tables import PurchasePreviewRow


ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
PAY_TO = "0x" + "2" * 40
PAYER = "0x" + "5" * 40


def encoded(value: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode()
    ).decode().rstrip("=")


class UniversalPayerCore:
    def __init__(self):
        self.reserve_payload = None
        self.settle_calls = 0
        self.prepare_calls = 0
        self.proxy_finalize_calls = 0
        self.finalize_calls = 0
        self.release_calls = []
        self.events = []
        self.prepared_payment = None
        self.payer_funded = False

    def funding_readiness(self):
        return {
            "spender_address": PAYER,
            "payer_address": PAYER,
            "universal_payer_ready": True,
            "automatic_payment_rail": "clink_payer_proxy",
            "supported_assets": {"eip155:8453": ASSET.lower()},
        }

    def resolve_authorization(self, payload):
        assert payload["authorization_rail"] == "clink_payer_proxy"
        return {
            "ready": True,
            "authorization_rail": "clink_payer_proxy",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
            "asset_allowance_id": "asset_allowance_1",
            "notification_mode": "silent_under_limits",
            "user_interaction_required": False,
        }

    def create_action(self, _payload):
        return {"action_id": "action_1"}

    def evaluate_policy(self, _payload):
        return {"policy_decision_id": "policy_1", "approved": True}

    def update_action(self, *_args, **_kwargs):
        return {}

    def audit(self, _payload):
        return {"event_id": "audit_1"}

    def reserve(self, payload):
        self.reserve_payload = payload
        return {"reservation_id": "reserve_1"}

    def settle(self, reservation_id, _payload):
        assert reservation_id == "reserve_1"
        self.events.append("settle")
        self.settle_calls += 1
        self.payer_funded = True
        return {
            "reservation_id": reservation_id,
            "state": "proxy_payment_ready",
            "reimbursement_tx_hash": "0x" + "a" * 64,
            "payment_payload": self.prepared_payment,
        }

    def release(self, reservation_id, reason):
        assert reservation_id == "reserve_1"
        self.release_calls.append(reason)
        return {"reservation_id": reservation_id, "state": "released"}

    def proxy_prepare(self, reservation_id, payload):
        assert reservation_id == "reserve_1"
        assert payload["payment_requirement"]["pay_to"] == PAY_TO.lower()
        self.events.append("prepare")
        self.prepare_calls += 1
        result = {
            "reservation_id": reservation_id,
            "state": (
                "proxy_payment_ready"
                if self.payer_funded
                else "proxy_authorization_ready"
            ),
            "payment_payload": {
                "x402Version": 2,
                "resource": {"url": "https://merchant.example/contents"},
                "accepted": {
                    "scheme": "exact",
                    "network": "eip155:8453",
                    "amount": "1000",
                    "asset": ASSET.lower(),
                    "payTo": PAY_TO.lower(),
                    "extra": {"name": "USD Coin", "version": "2"},
                },
                "payload": {
                    "signature": "0x" + "1" * 130,
                    "authorization": {
                        "from": PAYER,
                        "to": PAY_TO.lower(),
                        "value": "1000",
                        "validAfter": "100",
                        "validBefore": "200",
                        "nonce": "0x" + "9" * 64,
                    },
                },
            },
        }
        self.prepared_payment = result["payment_payload"]
        return result

    def proxy_finalize(self, reservation_id, payload):
        assert reservation_id == "reserve_1"
        assert payload["transaction_hash"] == "0x" + "b" * 64
        assert payload["payment_response"]["pay_to"] == PAY_TO.lower()
        self.proxy_finalize_calls += 1
        return {
            "reservation_id": reservation_id,
            "state": "settled",
            "receipt_id": "receipt_proxy_1",
            "tx_hash": payload["transaction_hash"],
        }

    def finalize(self, reservation_id, _payload):
        assert reservation_id == "reserve_1"
        self.finalize_calls += 1
        return {"state": "finalized"}


class RecoveringUniversalPayerCore(UniversalPayerCore):
    def __init__(self, *, fail_prepare=False, fail_finalize=False):
        super().__init__()
        self.fail_prepare = fail_prepare
        self.fail_finalize = fail_finalize
        self.reconcile_result = {
            "reservation_id": "reserve_1",
            "state": "spending_reserved",
        }

    def reconcile(self, reservation_id):
        assert reservation_id == "reserve_1"
        return self.reconcile_result

    def proxy_prepare(self, reservation_id, payload):
        if self.fail_prepare:
            self.fail_prepare = False
            raise RuntimeError("temporary Core prepare failure")
        return super().proxy_prepare(reservation_id, payload)

    def settle(self, reservation_id, payload):
        result = super().settle(reservation_id, payload)
        self.reconcile_result = result
        return result

    def proxy_finalize(self, reservation_id, payload):
        if self.fail_finalize:
            self.fail_finalize = False
            raise RuntimeError("temporary Core finalize failure")
        return super().proxy_finalize(reservation_id, payload)


class Response:
    def __init__(self, status_code, payload, headers):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers
        self.is_success = 200 <= status_code < 300
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class Merchant:
    def __init__(self, payment_required):
        self.payment_required = payment_required
        self.calls = []

    def request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if len(self.calls) == 1:
            return Response(
                402,
                {},
                {"PAYMENT-REQUIRED": encoded(self.payment_required)},
            )
        payment = json.loads(
            base64.urlsafe_b64decode(
                kwargs["headers"]["PAYMENT-SIGNATURE"]
                + "=" * (-len(kwargs["headers"]["PAYMENT-SIGNATURE"]) % 4)
            )
        )
        assert payment["payload"]["authorization"]["from"] == PAYER
        return Response(
            200,
            {"text": "merchant result"},
            {
                "content-type": "application/json",
                "PAYMENT-RESPONSE": encoded(
                    {
                        "success": True,
                        "transaction": "0x" + "b" * 64,
                        "network": "eip155:8453",
                        "payer": PAYER,
                    }
                ),
            },
        )


def test_registry_x402_uses_clink_payer_without_per_purchase_signature(tmp_path):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="External x402",
        domain="merchant.example",
        source="cdp_bazaar",
        status="discovered",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://merchant.example/contents",
        name="Contents",
        endpoint="https://merchant.example/contents",
        method="POST",
        status="registry_verified",
        metadata={"trust_tier": "registry_verified"},
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:8453",
                asset=ASSET,
                amount_atomic="1000",
                pay_to=PAY_TO,
                price_usd="0.001",
            )
        ],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    required = {
        "x402Version": 2,
        "resource": {"url": offering.endpoint},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": "1000",
                "asset": ASSET,
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "assetTransferMethod": "eip3009",
                    "name": "USD Coin",
                    "version": "2",
                },
            }
        ],
    }
    core = UniversalPayerCore()
    merchant = Merchant(required)
    service = PurchaseService(repository, core, client=merchant)

    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"url": "https://example.com"},
    )
    result = service.execute(preview.preview_id)
    replay = service.execute(preview.preview_id)

    assert preview.execution_mode == "clink_payer_proxy"
    assert preview.payment_capability == {
        "rail": "clink_payer_proxy",
        "mandate_compatible": True,
        "auto_pay_compatible": True,
        "requires_purchase_signature": False,
        "reason_code": None,
    }
    assert result.state == "delivered"
    assert result["service_result"] == {"text": "merchant result"}
    assert "signing_url" not in result["purchase"].metadata
    assert replay.state == "delivered"
    assert core.reserve_payload["authorization_rail"] == "clink_payer_proxy"
    assert core.reserve_payload["asset_allowance_id"] == "asset_allowance_1"
    assert core.settle_calls == 1
    # Core revalidates the short-lived EIP-3009 authorization immediately
    # before merchant submission, refreshing it when it has expired.
    assert core.prepare_calls == 2
    assert core.proxy_finalize_calls == 1
    assert core.events[:2] == ["prepare", "settle"]
    assert len(merchant.calls) == 2


def build_proxy_purchase(tmp_path, core):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="External x402",
        domain="merchant.example",
        source="cdp_bazaar",
        status="discovered",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://merchant.example/contents",
        name="Contents",
        endpoint="https://merchant.example/contents",
        method="POST",
        status="registry_verified",
        metadata={"trust_tier": "registry_verified"},
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:8453",
                asset=ASSET,
                amount_atomic="1000",
                pay_to=PAY_TO,
                price_usd="0.001",
            )
        ],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    required = {
        "x402Version": 2,
        "resource": {"url": offering.endpoint},
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": "1000",
                "asset": ASSET,
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "assetTransferMethod": "eip3009",
                    "name": "USD Coin",
                    "version": "2",
                },
            }
        ],
    }
    merchant = Merchant(required)
    service = PurchaseService(repository, core, client=merchant)
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"url": "https://example.com"},
    )
    return repository, merchant, service, preview


def test_registry_x402_falls_back_when_universal_payer_is_not_ready(tmp_path):
    class NotReadyCore(UniversalPayerCore):
        def funding_readiness(self):
            return {
                "spender_address": PAYER,
                "payer_address": PAYER,
                "universal_payer_ready": False,
                "automatic_payment_rail": None,
                "supported_assets": {},
            }

    _repository, _merchant, _service, preview = build_proxy_purchase(
        tmp_path, NotReadyCore()
    )

    assert preview.execution_mode == "external_x402_signature"
    assert preview.payment_capability["requires_purchase_signature"] is True


def test_registry_x402_falls_back_when_payer_does_not_match_spender(tmp_path):
    class MismatchedPayerCore(UniversalPayerCore):
        def funding_readiness(self):
            readiness = super().funding_readiness()
            readiness["payer_address"] = "0x" + "6" * 40
            return readiness

    _repository, _merchant, _service, preview = build_proxy_purchase(
        tmp_path, MismatchedPayerCore()
    )

    assert preview.execution_mode == "external_x402_signature"
    assert preview.payment_capability["requires_purchase_signature"] is True


def test_incompatible_live_challenge_releases_budget_without_funding_payer(tmp_path):
    core = UniversalPayerCore()
    _repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)
    merchant.payment_required["x402Version"] = 1

    result = service.execute(preview.preview_id)

    assert result.state == "failed"
    assert result.reason_code == "MERCHANT_X402_PROXY_INCOMPATIBLE"
    assert core.release_calls == ["merchant_x402_proxy_incompatible"]
    assert core.settle_calls == 0
    assert core.prepare_calls == 0
    assert core.proxy_finalize_calls == 0
    assert len(merchant.calls) == 1

    fallback = service.create_preview(
        user_id="user",
        offering_id=preview.offering_id,
        service_input={"url": "https://example.com"},
    )
    assert fallback.execution_mode == "external_x402_signature"
    assert fallback.payment_capability["requires_purchase_signature"] is True


def test_core_prepare_failure_never_funds_payer(tmp_path):
    core = RecoveringUniversalPayerCore(fail_prepare=True)
    _repository, _merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)

    assert waiting.state == "payment_submitted"
    assert waiting.reason_code == "PROXY_PREPARE_RETRY_REQUIRED"
    assert core.settle_calls == 0
    assert core.events == []


def test_core_incompatibility_releases_budget_and_downgrades_next_preview(tmp_path):
    class ProxyIncompatibleError(RuntimeError):
        status_code = 409
        code = "PROXY_INCOMPATIBLE"

    class IncompatibleCore(UniversalPayerCore):
        def proxy_prepare(self, _reservation_id, _payload):
            raise ProxyIncompatibleError(
                "merchant token domain does not match trusted Core configuration"
            )

    core = IncompatibleCore()
    _repository, _merchant, service, preview = build_proxy_purchase(tmp_path, core)

    result = service.execute(preview.preview_id)
    fallback = service.create_preview(
        user_id="user",
        offering_id=preview.offering_id,
        service_input={"url": "https://example.com"},
    )

    assert result.state == "failed"
    assert result.reason_code == "MERCHANT_X402_PROXY_INCOMPATIBLE"
    assert core.release_calls == ["merchant_x402_proxy_incompatible"]
    assert core.settle_calls == 0
    assert fallback.execution_mode == "external_x402_signature"


def claim_for_reconciliation(repository, purchase_id):
    purchase = repository.get_purchase(purchase_id)
    return repository.claim_purchase_execution(
        purchase,
        allowed_states={"payment_submitted"},
        expected_execution_mode="clink_payer_proxy",
    )


def test_worker_resumes_proxy_after_core_prepare_timeout(tmp_path):
    core = RecoveringUniversalPayerCore(fail_prepare=True)
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert waiting.state == "payment_submitted"
    assert waiting.reason_code == "PROXY_PREPARE_RETRY_REQUIRED"
    assert result.state == "delivered"
    assert result["service_result"] == {"text": "merchant result"}
    assert core.settle_calls == 1
    assert core.prepare_calls == 2
    assert core.proxy_finalize_calls == 1
    assert len(merchant.calls) == 2


def test_worker_uses_saved_result_after_proxy_finalize_timeout(tmp_path):
    core = RecoveringUniversalPayerCore(fail_finalize=True)
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    service.inputs.delete(service._proxy_challenge_key(waiting.purchase_id))
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert waiting.state == "payment_submitted"
    assert result.state == "delivered"
    assert result["service_result"] == {"text": "merchant result"}
    assert len(merchant.calls) == 2
    assert core.settle_calls == 1
    assert core.prepare_calls == 2
    assert core.proxy_finalize_calls == 1


def test_worker_never_recontacts_merchant_when_ephemeral_handoff_is_lost(tmp_path):
    core = RecoveringUniversalPayerCore(fail_finalize=True)
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    service.inputs.delete(service._proxy_handoff_key(waiting.purchase_id))
    service.inputs.delete(preview.preview_id)
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert result.state == "paid_but_undelivered"
    assert result.reason_code == "PROXY_DELIVERY_RESULT_UNAVAILABLE"
    assert result.output_hash is not None
    assert len(merchant.calls) == 2
    assert core.settle_calls == 1
    assert core.proxy_finalize_calls == 1


def test_confirmed_failed_merchant_payment_rotates_nonce_and_retries(tmp_path):
    core = RecoveringUniversalPayerCore(fail_finalize=True)
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    core.reconcile_result = {
        "reservation_id": "reserve_1",
        "state": "payer_funded",
        "failed_merchant_tx_hashes": ["0x" + "b" * 64],
    }
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert result.state == "delivered"
    assert result["service_result"] == {"text": "merchant result"}
    assert core.settle_calls == 1
    assert core.prepare_calls == 4
    assert core.proxy_finalize_calls == 1
    assert len(merchant.calls) == 3
    assert merchant.calls[1][2]["headers"]["Idempotency-Key"].endswith(
        ":payment:0"
    )
    assert merchant.calls[2][2]["headers"]["Idempotency-Key"].endswith(
        ":payment:1"
    )


def test_expired_preview_does_not_fail_an_inflight_proxy_purchase(tmp_path):
    core = RecoveringUniversalPayerCore(fail_prepare=True)
    repository, _merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    with repository.sessions.begin() as session:
        row = session.get(PurchasePreviewRow, preview.preview_id)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    result = service.execute(preview.preview_id)

    assert waiting.state == "payment_submitted"
    assert result.state == "delivered"
    assert core.settle_calls == 1


def test_slow_failed_merchant_payment_keeps_retry_context(tmp_path):
    now = [0.0]
    store = EphemeralStore(clock=lambda: now[0])
    core = RecoveringUniversalPayerCore(fail_finalize=True)
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)
    service.inputs = store
    service.inputs.set(
        preview.preview_id,
        {"url": "https://example.com"},
        service.preview_ttl,
    )

    waiting = service.execute(preview.preview_id)
    now[0] += service.preview_ttl + 1
    core.reconcile_result = {
        "reservation_id": "reserve_1",
        "state": "payer_funded",
        "failed_merchant_tx_hashes": ["0x" + "b" * 64],
    }
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert result.state == "delivered"
    assert len(merchant.calls) == 3


def test_incompatibility_release_retries_without_recontacting_merchant(tmp_path):
    class ProxyIncompatibleError(RuntimeError):
        status_code = 409
        code = "PROXY_INCOMPATIBLE"

    class ReleaseOnceCore(RecoveringUniversalPayerCore):
        def __init__(self):
            super().__init__()
            self.release_attempts = 0

        def proxy_prepare(self, _reservation_id, _payload):
            raise ProxyIncompatibleError("merchant token domain mismatch")

        def release(self, reservation_id, reason):
            self.release_attempts += 1
            if self.release_attempts == 1:
                raise RuntimeError("temporary release failure")
            return super().release(reservation_id, reason)

    core = ReleaseOnceCore()
    repository, merchant, service, preview = build_proxy_purchase(tmp_path, core)

    waiting = service.execute(preview.preview_id)
    purchase, claim_token = claim_for_reconciliation(
        repository, waiting.purchase_id
    )
    result = service.process_reconciliation(purchase, claim_token)

    assert waiting.reason_code == "PROXY_COMPATIBILITY_RELEASE_PENDING"
    assert result.state == "failed"
    assert result.reason_code == "MERCHANT_X402_PROXY_INCOMPATIBLE"
    assert core.release_attempts == 2
    assert core.release_calls == ["merchant_x402_proxy_incompatible"]
    assert len(merchant.calls) == 1
