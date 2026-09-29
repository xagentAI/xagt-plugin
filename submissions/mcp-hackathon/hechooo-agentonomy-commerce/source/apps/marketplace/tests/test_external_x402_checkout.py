from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from eth_account import Account

from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.models import PaymentOption, Provider, ServiceOffering


def test_browser_checkout_uses_agentonomy_public_name():
    script = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "assets"
        / "x402_checkout.js"
    ).read_text(encoding="utf-8")

    assert "hermes" not in script.lower()
    assert "return to Agentonomy" in script


def encoded(value: dict) -> str:
    return base64.urlsafe_b64encode(
        json.dumps(value, separators=(",", ":")).encode()
    ).decode().rstrip("=")


class Core:
    def __init__(self):
        self.reserve_payload = None
        self.action_payload = None
        self.policy_payload = None
        self.finalize_payload = None

    def resolve_authorization(self, payload):
        assert payload["authorization_rail"] == "external_x402"
        return {
            "ready": True,
            "authorization_rail": "external_x402",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
            "next_action": "create_action_and_evaluate_policy",
        }

    def wallet_identities(self, user_id):
        assert user_id == "user"
        return [
            {
                "wallet_identity_id": "wallet_identity_1",
                "wallet_address": Account.from_key("0x" + "11" * 32).address,
            }
        ]

    def create_action(self, payload):
        self.action_payload = payload
        return {"action_id": "action_1"}

    def evaluate_policy(self, payload):
        self.policy_payload = payload
        return {"policy_decision_id": "policy_1", "approved": True}

    def update_action(self, *_args, **_kwargs):
        return {}

    def audit(self, _payload):
        return {"event_id": "audit_1"}

    def reserve(self, payload):
        self.reserve_payload = payload
        return {
            "reservation_id": "reserve_1",
            "nonce": "0x" + "9" * 64,
            "valid_after": "100",
            "valid_before": "200",
        }

    def reservation(self, reservation_id):
        assert reservation_id == "reserve_1"
        return {
            "reservation_id": "reserve_1",
            "nonce": "0x" + "9" * 64,
            "valid_after": "100",
            "valid_before": "200",
        }

    def external_finalize(self, _reservation_id, payload):
        self.finalize_payload = payload
        return {
            "state": "settled",
            "tx_hash": payload["transaction_hash"],
            "external_payment_response": payload["payment_response"],
        }

    def finalize(self, *_args, **_kwargs):
        return {"state": "finalized"}


class RecoveringCore(Core):
    def __init__(self):
        super().__init__()
        self.reconciliation = {
            "state": "spending_reserved",
            "reconciliation_status": "retryable",
            "next_action": "retry_settlement",
        }

    def external_finalize(self, _reservation_id, payload):
        self.finalize_payload = payload
        raise RuntimeError("Core temporarily rejected facilitator calldata")

    def reconcile(self, _reservation_id):
        return self.reconciliation


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
        assert "PAYMENT-SIGNATURE" in kwargs["headers"]
        return Response(
            200,
            {"markdown": "# Example"},
            {
                "content-type": "application/json",
                "PAYMENT-RESPONSE": encoded(
                    {
                        "success": True,
                        "transaction": "0x" + "a" * 64,
                        "network": "eip155:8453",
                        "payer": Account.from_key("0x" + "11" * 32).address,
                    }
                ),
            },
        )


def test_browser_checkout_signs_and_delivers_same_paid_request(tmp_path):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="External x402",
        domain="merchant.example",
        source="cdp_bazaar",
        status="active",
    )
    asset = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    pay_to = "0x" + "2" * 40
    payment = PaymentOption(
        scheme="exact",
        network="eip155:8453",
        asset=asset,
        amount_atomic="10000",
        pay_to=pay_to,
        price_usd="0.01",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://merchant.example/scrape",
        name="Scrape",
        endpoint="https://merchant.example/scrape",
        method="POST",
        status="registry_verified",
        metadata={"trust_tier": "registry_verified"},
        payment_options=[payment],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    accepted = {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "10000",
        "asset": asset,
        "payTo": pay_to,
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USD Coin", "version": "2"},
    }
    required = {
        "x402Version": 2,
        "resource": {
            "url": offering.endpoint,
            "description": offering.description,
            "mimeType": "application/json",
        },
        "accepts": [accepted],
    }
    core = Core()
    merchant = Merchant(required)
    service = PurchaseService(
        repository,
        core,
        client=merchant,
        public_base_url="https://marketplace.clink.example",
        eip3009_domains={"eip155:8453": {"name": "USD Coin", "version": "2"}},
    )
    bazaar_input = {
        "type": "http",
        "bodyType": "json",
        "method": "POST",
        "body": {"url": "https://example.com"},
    }
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input=bazaar_input,
    )
    pending = service.execute(preview.preview_id, user_confirmed=True)
    token = urlsplit(pending["purchase"].metadata["signing_url"]).fragment.removeprefix(
        "token="
    )
    account = Account.from_key("0x" + "11" * 32)

    challenge = service.prepare_external_checkout(
        pending.purchase_id,
        checkout_token=token,
        payer_address=account.address,
    )
    signature = Account.sign_typed_data(
        account.key, full_message=challenge["typed_data"]
    ).signature.hex()
    result = service.complete_external_checkout(
        pending.purchase_id,
        checkout_token=token,
        payer_address=account.address,
        signature="0x" + signature.removeprefix("0x"),
    )

    assert challenge["payment"]["amount"] == "10000"
    assert challenge["typed_data"]["message"]["nonce"] == "0x" + "9" * 64
    assert challenge["typed_data"]["message"]["validAfter"] == "100"
    assert challenge["typed_data"]["message"]["validBefore"] == "200"
    assert result.state == "delivered"
    assert result["service_result"] == {"markdown": "# Example"}
    assert len(merchant.calls) == 2
    assert merchant.calls[0][2]["json"] == bazaar_input["body"]
    assert merchant.calls[1][2]["json"] == bazaar_input["body"]
    assert core.reserve_payload["spending_authorization_id"] is None
    assert core.reserve_payload["authorization_rail"] == "external_x402"
    assert core.reserve_payload["wallet_identity_id"] == "wallet_identity_1"
    assert core.reserve_payload["spending_grant_id"] == "spending_grant_1"
    assert core.finalize_payload["payment_response"]["nonce"] == "0x" + "9" * 64
    assert core.action_payload["metadata"] == core.policy_payload["metadata"]

    with pytest.raises(ValueError, match="not awaiting wallet signature"):
        service.complete_external_checkout(
            pending.purchase_id,
            checkout_token=token,
            payer_address=account.address,
            signature="0x" + signature.removeprefix("0x"),
        )
    assert len(merchant.calls) == 2


def test_worker_delivers_saved_merchant_result_after_core_reconciliation(tmp_path):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="External x402",
        domain="merchant.example",
        source="cdp_bazaar",
        status="active",
    )
    asset = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    pay_to = "0x" + "2" * 40
    payment = PaymentOption(
        scheme="exact",
        network="eip155:8453",
        asset=asset,
        amount_atomic="10000",
        pay_to=pay_to,
        price_usd="0.01",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://merchant.example/scrape",
        name="Scrape",
        endpoint="https://merchant.example/scrape",
        method="POST",
        status="registry_verified",
        metadata={"trust_tier": "registry_verified"},
        payment_options=[payment],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    accepted = {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "10000",
        "asset": asset,
        "payTo": pay_to,
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USD Coin", "version": "2"},
    }
    required = {
        "x402Version": 2,
        "resource": {"url": offering.endpoint},
        "accepts": [accepted],
    }
    core = RecoveringCore()
    merchant = Merchant(required)
    service = PurchaseService(
        repository,
        core,
        client=merchant,
        public_base_url="https://marketplace.clink.example",
        eip3009_domains={"eip155:8453": {"name": "USD Coin", "version": "2"}},
    )
    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={"url": "https://example.com"},
    )
    pending = service.execute(preview.preview_id, user_confirmed=True)
    token = urlsplit(pending["purchase"].metadata["signing_url"]).fragment.removeprefix(
        "token="
    )
    account = Account.from_key("0x" + "11" * 32)
    challenge = service.prepare_external_checkout(
        pending.purchase_id,
        checkout_token=token,
        payer_address=account.address,
    )
    signature = Account.sign_typed_data(
        account.key, full_message=challenge["typed_data"]
    ).signature.hex()

    waiting = service.complete_external_checkout(
        pending.purchase_id,
        checkout_token=token,
        payer_address=account.address,
        signature="0x" + signature.removeprefix("0x"),
    )

    assert waiting.state == "payment_submitted"
    core.reconciliation = {
        "state": "settled",
        "receipt_id": "receipt_1",
        "tx_hash": "0x" + "b" * 64,
    }
    purchase = repository.get_purchase(pending.purchase_id)
    claimed, claim_token = repository.claim_purchase_execution(
        purchase,
        allowed_states={"payment_submitted"},
        expected_execution_mode="external_x402_signature",
    )
    mismatch = service.process_reconciliation(claimed, claim_token)

    assert mismatch.state == "payment_submitted"
    assert mismatch.reason_code == "PAYMENT_HANDOFF_MISMATCH"

    core.reconciliation["tx_hash"] = "0x" + "a" * 64
    purchase = repository.get_purchase(pending.purchase_id)
    claimed, claim_token = repository.claim_purchase_execution(
        purchase,
        allowed_states={"payment_submitted"},
        expected_execution_mode="external_x402_signature",
    )
    result = service.process_reconciliation(claimed, claim_token)

    assert result.state == "delivered"
    assert result["service_result"] == {"markdown": "# Example"}
    assert service.result_for_purchase(pending.purchase_id) == {
        "markdown": "# Example"
    }
    assert repository.get_purchase(pending.purchase_id).state == "delivered"
    assert len(merchant.calls) == 2
    assert service.inputs.get(f"x402_handoff:{pending.purchase_id}") is None
    assert "# Example" not in str(
        repository.get_purchase(pending.purchase_id).model_dump()
    )


@pytest.mark.parametrize("body", [[{"url": "https://example.com"}], "raw", 7, None])
def test_bazaar_json_envelope_unwraps_any_json_body(body):
    offering = SimpleNamespace(source="cdp_bazaar", method="POST")

    payload = PurchaseService._merchant_request_payload(
        offering,
        {
            "type": "http",
            "bodyType": "json",
            "method": "POST",
            "body": body,
        },
    )

    if body is None:
        assert payload == {"content": b"null"}
    else:
        assert payload == {"json": body}


def test_bazaar_explicit_json_null_is_sent_on_the_wire():
    merchant = Merchant({})
    service = PurchaseService(object(), object(), client=merchant)
    offering = SimpleNamespace(
        source="cdp_bazaar",
        method="POST",
        endpoint="https://merchant.example/null",
    )

    service._merchant_request(
        offering,
        {
            "type": "http",
            "bodyType": "json",
            "method": "POST",
            "body": None,
        },
        headers={"Idempotency-Key": "purchase_1"},
    )

    request = merchant.calls[0][2]
    assert request["content"] == b"null"
    assert request["headers"]["Content-Type"] == "application/json"


def test_bazaar_method_mismatch_is_rejected_before_preview_or_merchant_call(tmp_path):
    repository = MarketplaceRepository(
        f"sqlite+pysqlite:///{tmp_path / 'marketplace.sqlite3'}"
    )
    provider = Provider(
        name="External x402",
        domain="merchant.example",
        source="cdp_bazaar",
        status="active",
    )
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="cdp_bazaar",
        source_id="POST https://merchant.example/scrape",
        name="Scrape",
        endpoint="https://merchant.example/scrape",
        method="POST",
        status="registry_verified",
        metadata={"trust_tier": "registry_verified"},
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:8453",
                asset="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                amount_atomic="10000",
                pay_to="0x" + "2" * 40,
                price_usd="0.01",
            )
        ],
    )
    repository.upsert_provider(provider)
    repository.upsert_offering(offering, verified_at=datetime.now(UTC))
    merchant = Merchant({})
    core = Core()
    service = PurchaseService(repository, core, client=merchant)
    mismatched_input = {
        "type": "http",
        "bodyType": "json",
        "method": "GET",
        "body": {"url": "https://example.com"},
    }

    with pytest.raises(ValueError, match="method does not match"):
        service.create_preview(
            user_id="user",
            offering_id=offering.offering_id,
            service_input=mismatched_input,
        )

    preview = service.create_preview(
        user_id="user",
        offering_id=offering.offering_id,
        service_input={
            "type": "http",
            "bodyType": "json",
            "method": "POST",
            "body": {"url": "https://example.com"},
        },
    )
    service.inputs.set(
        preview.preview_id,
        mismatched_input,
        300,
    )

    result = service.execute(preview.preview_id, user_confirmed=True)

    assert result.state == "failed"
    assert result.reason_code == "INVALID_SERVICE_INPUT"
    assert core.action_payload is None
    assert core.reserve_payload is None
    assert merchant.calls == []
