from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from services.core_gateway import CoreGatewayError, HttpCoreGateway
from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.models import PaymentOption, Provider, ServiceOffering

USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x" + "5" * 40

class RecordingCoreGateway(HttpCoreGateway):
    def __init__(self):
        self.policy_url = "https://core.example"
        self.funding_url = "https://funding.example"
        self.last_path = None

    def _post(self, url, payload):
        self.last_path = urlsplit(url).path
        return {}


class RecordingCore:
    def __init__(self):
        self.reserved_payload = None

    def create_action(self, payload):
        return {"action_id": "action_1"}

    def evaluate_policy(self, payload):
        return {"policy_decision_id": "policy_1", "approved": True}

    def update_action(self, *args, **kwargs):
        return {}

    def audit(self, payload):
        return {"event_id": "audit_1"}

    def funding_readiness(self):
        return {"spender_address": SPENDER}

    def resolve_authorization(self, payload):
        result = {
            "ready": True,
            "authorization_rail": payload["authorization_rail"],
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_id": "spending_grant_1",
        }
        if payload["authorization_rail"] == "native_allowance":
            result["asset_allowance_id"] = "asset_allowance_1"
        return result

    def reserve(self, payload):
        self.reserved_payload = payload
        return {"reservation_id": "reserve_1"}

    def settle(self, reservation_id, payload):
        return {"state": "settled", "receipt_id": "receipt_1", "receipt": {}}

    def finalize(self, reservation_id, payload):
        return {"state": "finalized"}


class Response:
    is_success = True
    headers = {"content-type": "application/json"}

    def json(self):
        return {"risk": "low"}


class Client:
    def request(self, *args, **kwargs):
        return Response()


@pytest.fixture
def repository(tmp_path):
    repo = MarketplaceRepository(f"sqlite+pysqlite:///{Path(tmp_path) / 'market.db'}")
    provider = Provider(name="Risk", domain="risk.example", source="merchant", status="active")
    offering = ServiceOffering(
        provider_id=provider.provider_id,
        source="merchant",
        source_id="POST https://risk.example/check",
        name="Risk",
        endpoint="https://risk.example/check",
        method="POST",
        status="verified",
        metadata={"accepts_clink_receipt": True},
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset=USDC,
                amount_atomic="10000",
                pay_to="0x" + "3" * 40,
                price_usd="0.01",
            ),
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset=USDC,
                amount_atomic="20000",
                pay_to="0x" + "4" * 40,
                price_usd="0.02",
            ),
        ],
    )
    repo.upsert_provider(provider)
    repo.upsert_offering(offering, verified_at=datetime.now(UTC))
    return repo


@pytest.fixture
def core():
    return RecordingCore()


def create_preview_with_payment_index(repository, payment_index, *, core=None, client=None):
    offering = repository.search()[0]
    service = PurchaseService(
        repository,
        core or RecordingCore(),
        client=client,
        native_provider_ids={offering.provider_id},
    )
    preview = service.create_preview(
        user_id="user_1",
        offering_id=offering.offering_id,
        service_input={"request": "risk-check"},
        payment_index=payment_index,
    )
    return preview, service


def replace_payment_amount(repository, payment_index, amount_atomic):
    offering = repository.search()[0]
    payments = list(offering.payment_options)
    payments[payment_index] = payments[payment_index].model_copy(
        update={"amount_atomic": amount_atomic}
    )
    repository.upsert_offering(offering.model_copy(update={"payment_options": payments}))


def replace_second_payment_amount(repository, amount_atomic):
    replace_payment_amount(repository, payment_index=1, amount_atomic=amount_atomic)


def replace_first_payment_amount(repository, amount_atomic):
    replace_payment_amount(repository, payment_index=0, amount_atomic=amount_atomic)


def test_core_gateway_uses_plural_policy_path():
    gateway = RecordingCoreGateway()
    gateway.evaluate_policy({"action_id": "act_1"})
    assert gateway.last_path == "/policies/evaluate"


def test_core_gateway_uses_reservation_reconciliation_path():
    gateway = RecordingCoreGateway()
    gateway.reconcile("reserve_1")
    assert gateway.last_path == "/funding/spending-reservations/reserve_1/reconcile"


def test_core_gateway_uses_universal_payer_prepare_path():
    gateway = RecordingCoreGateway()
    gateway.proxy_prepare("reserve_1", {"payment_requirement": {}})
    assert (
        gateway.last_path
        == "/funding/spending-reservations/reserve_1/proxy-prepare"
    )


def test_core_gateway_uses_universal_payer_finalize_path():
    gateway = RecordingCoreGateway()
    gateway.proxy_finalize("reserve_1", {"transaction_hash": "0x1"})
    assert (
        gateway.last_path
        == "/funding/spending-reservations/reserve_1/proxy-finalize"
    )


def test_core_gateway_preserves_structured_proxy_incompatibility():
    def handler(_request):
        return httpx.Response(
            409,
            json={
                "detail": {
                    "code": "PROXY_INCOMPATIBLE",
                    "message": "merchant token domain does not match trusted Core configuration",
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gateway = HttpCoreGateway(
        action_url="http://core/action",
        policy_url="http://core/policy",
        audit_url="http://core/audit",
        funding_url="http://core/funding",
        token="internal-token",
        client=client,
    )

    with pytest.raises(CoreGatewayError) as exc_info:
        gateway.proxy_prepare("reserve_1", {"payment_requirement": {}})

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "PROXY_INCOMPATIBLE"


def test_execute_rejects_when_selected_payment_drifted(repository, core):
    preview, service = create_preview_with_payment_index(
        repository, payment_index=1, core=core
    )
    replace_second_payment_amount(repository, "2000000")
    purchase = service.execute(preview.preview_id)
    assert purchase.reason_code == "QUOTE_DRIFT"


def test_execute_keeps_selected_payment_when_first_option_changes(repository, core):
    preview, service = create_preview_with_payment_index(
        repository, payment_index=1, core=core, client=Client()
    )
    replace_first_payment_amount(repository, "9000000")
    service.execute(
        preview.preview_id,
        user_confirmed=True,
        spending_authorization_id="fund_auth_1",
    )
    assert core.reserved_payload["amount_atomic"] == preview.payment["amount_atomic"]
