import pytest
from pydantic import ValidationError

from services.funding_service import schemas
from services.funding_service.hosted_routing import build_hosted_payment_challenge
from shared.config import AppConfig


RECIPIENT = "0x" + "2" * 40
TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def test_direct_transfer_switch_is_explicit_and_default_off(monkeypatch):
    monkeypatch.delenv("CLINK_DIRECT_TRANSFERS_ENABLED", raising=False)
    assert AppConfig.from_env().clink_direct_transfers_enabled is False
    monkeypatch.setenv("CLINK_DIRECT_TRANSFERS_ENABLED", "true")
    assert AppConfig.from_env().clink_direct_transfers_enabled is True


def test_transfer_product_configuration_honors_explicit_operator_whitelist(monkeypatch):
    monkeypatch.delenv("CLINK_ACCOUNT_ALLOWED_PRODUCTS", raising=False)
    assert "transfers" in AppConfig.from_env().account_allowed_products
    assert AppConfig(account_allowed_products=("marketplace",)).account_allowed_products == ("marketplace",)
    monkeypatch.setenv("CLINK_ACCOUNT_ALLOWED_PRODUCTS", "marketplace")
    assert AppConfig.from_env().account_allowed_products == ("marketplace",)


def request_payload(**updates):
    return {"user_id": "user", "agent_id": "agent", "request_id": "transfer-1",
            "to_address": RECIPIENT, "network": "eip155:8453",
            "amount_usdc": "2.000000", **updates}


def test_transfer_request_canonicalizes_decimal_without_float():
    request = schemas.CreateDirectTransferRequest(**request_payload())
    assert request.amount_usdc == "2"
    assert request.to_address == RECIPIENT


@pytest.mark.parametrize("updates", [
    {"amount_usdc": 2.0}, {"amount_usdc": "0"}, {"amount_usdc": "-1"},
    {"amount_usdc": "0.0000001"}, {"amount_usdc": "NaN"},
    {"amount_usdc": "1e2"}, {"amount_usdc": " "},
    {"to_address": "0x" + "0" * 40}, {"to_address": "alice.eth"},
    {"request_id": "a\nb"}, {"private_key": "not-accepted"},
    {"spending_grant_id": "caller-selected"}, {"opc_installation_id": "invalid"},
])
def test_transfer_request_rejects_unsafe_inputs(updates):
    with pytest.raises(ValidationError):
        schemas.CreateDirectTransferRequest(**request_payload(**updates))


def intent_and_row():
    intent = {"kind": "direct_transfer", "operation_id": "transfer_1",
              "reservation_id": "reserve_1", "network": "eip155:8453",
              "destination": RECIPIENT, "token": TOKEN, "amount_atomic": "2000000"}
    row = {"reservation_id": "reserve_1", "purchase_id": "transfer_1",
           "network": "eip155:8453", "destination": RECIPIENT,
           "token_address": TOKEN, "amount_atomic": "2000000",
           "product": "transfers", "venue": "clink_transfers"}
    return intent, row


def test_direct_intent_has_distinct_deterministic_hosted_challenge():
    intent, row = intent_and_row()
    value = build_hosted_payment_challenge(intent, row)
    assert len(value) == 66
    assert value == build_hosted_payment_challenge(intent, row)
    x402 = {"scheme": "exact", "network": row["network"], "asset": TOKEN,
            "pay_to": RECIPIENT, "amount_atomic": "2000000"}
    with pytest.raises(ValueError, match="direct transfer"):
        build_hosted_payment_challenge(x402, row)


@pytest.mark.parametrize("field,value", [
    ("network", "eip155:137"), ("operation_id", "transfer_2"),
    ("reservation_id", "reserve_2"), ("destination", "0x" + "3" * 40),
    ("amount_atomic", "2000001"), ("token", "0x" + "4" * 40),
])
def test_direct_intent_cannot_change_durable_scope(field, value):
    intent, row = intent_and_row()
    intent[field] = value
    with pytest.raises(ValueError):
        build_hosted_payment_challenge(intent, row)


def test_direct_intent_cannot_impersonate_marketplace():
    intent, row = intent_and_row()
    row.update(product="marketplace", venue="clink_marketplace")
    with pytest.raises(ValueError):
        build_hosted_payment_challenge(intent, row)
