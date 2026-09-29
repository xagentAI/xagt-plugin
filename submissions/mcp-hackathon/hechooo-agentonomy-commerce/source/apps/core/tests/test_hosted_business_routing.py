from __future__ import annotations

import pytest

from services.funding_service.hosted_routing import (
    build_hosted_payment_challenge,
    normalize_hosted_business_intent,
    validate_hosted_business_intent,
)
from services.funding_service.schemas import (
    PredictionMarketBridgeTransferIntent,
    X402ExactIntent,
)


TOKEN = "0x" + "11" * 20
PAYEE = "0x" + "22" * 20
RESERVATION = "reservation_1"
PURCHASE = "purchase_1"
BINDING = "pm_binding_1"


def exact_payload() -> dict[str, str]:
    return {
        "scheme": "exact",
        "network": "eip155:8453",
        "asset": TOKEN.upper(),
        "amount_atomic": "1000000",
        "pay_to": PAYEE.upper(),
    }


def reservation_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "reservation_id": RESERVATION,
        "purchase_id": PURCHASE,
        "network": "eip155:8453",
        "token_address": TOKEN,
        "amount_atomic": "1000000",
        "destination": PAYEE,
    }
    row.update(updates)
    return row


def pm_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": "prediction_market_bridge_transfer",
        "operation_id": PURCHASE,
        "reservation_id": RESERVATION,
        "binding_id": BINDING,
        "bridge_address": PAYEE.upper(),
        "source_token": TOKEN.upper(),
        "amount_atomic": "1000000",
    }
    payload.update(updates)
    return payload


def test_marketplace_exact_payload_is_strictly_normalized_without_kind():
    intent = normalize_hosted_business_intent(exact_payload())

    assert isinstance(intent, X402ExactIntent)
    assert intent.kind == "x402_exact"
    assert intent.scheme == "exact"
    assert intent.network == "eip155:8453"
    assert intent.token == TOKEN
    assert intent.destination == PAYEE
    assert intent.amount_atomic == "1000000"
    assert set(intent.model_dump()) == {
        "kind",
        "scheme",
        "network",
        "token",
        "amount_atomic",
        "destination",
    }


def test_prediction_market_payload_is_strictly_normalized():
    intent = normalize_hosted_business_intent(pm_payload())

    assert isinstance(intent, PredictionMarketBridgeTransferIntent)
    assert intent.kind == "prediction_market_bridge_transfer"
    assert intent.operation_id == PURCHASE
    assert intent.reservation_id == RESERVATION
    assert intent.binding_id == BINDING
    assert intent.destination == PAYEE
    assert intent.token == TOKEN
    assert intent.amount_atomic == "1000000"
    assert set(intent.model_dump()) == {
        "kind",
        "operation_id",
        "reservation_id",
        "binding_id",
        "destination",
        "token",
        "amount_atomic",
    }


def test_prediction_market_binding_id_is_canonicalized_and_enters_challenge():
    intent = validate_hosted_business_intent(
        pm_payload(binding_id="  pm_binding_1  "), reservation_row()
    )

    assert intent.binding_id == BINDING
    first = build_hosted_payment_challenge(
        pm_payload(binding_id="  pm_binding_1  "), reservation_row()
    )
    second = build_hosted_payment_challenge(
        pm_payload(binding_id="pm_binding_2"), reservation_row()
    )
    assert first.startswith("0x")
    assert len(first) == 66
    assert first == first.lower()
    assert first != second


@pytest.mark.parametrize(
    ("payload", "row", "message"),
    [
        (exact_payload(), reservation_row(network="eip155:137"), "network"),
        (exact_payload(), reservation_row(token_address="0x" + "33" * 20), "token"),
        (exact_payload(), reservation_row(amount_atomic="1000001"), "amount"),
        (exact_payload(), reservation_row(destination="0x" + "44" * 20), "destination"),
        (pm_payload(reservation_id="reservation_2"), reservation_row(), "reservation"),
        (pm_payload(operation_id="purchase_2"), reservation_row(), "purchase"),
        (pm_payload(bridge_address="0x" + "33" * 20), reservation_row(), "destination"),
        (pm_payload(source_token="0x" + "33" * 20), reservation_row(), "token"),
        (pm_payload(amount_atomic="1000001"), reservation_row(), "amount"),
    ],
)
def test_business_intent_must_match_durable_reservation(
    payload: dict[str, object], row: dict[str, object], message: str
):
    with pytest.raises(ValueError, match=message):
        build_hosted_payment_challenge(payload, row)


@pytest.mark.parametrize(
    "payload",
    [
        {**exact_payload(), "tenant_id": "tenant_1"},
        {**exact_payload(), "kind": "x402_exact"},
        {**pm_payload(), "executor": TOKEN},
        {**pm_payload(), "wallet_binding_id": BINDING},
        {"kind": "unknown"},
        {
            "network": "eip155:8453",
            "asset": TOKEN,
            "amount_atomic": "1000000",
            "pay_to": PAYEE,
        },
        {"scheme": "exact", "network": "eip155:8453", "asset": TOKEN},
    ],
)
def test_business_intent_rejects_extra_or_malformed_payload(payload: dict[str, object]):
    with pytest.raises(ValueError):
        normalize_hosted_business_intent(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset", "0x" + "0" * 40),
        ("pay_to", "0x" + "0" * 40),
        ("amount_atomic", "0"),
        ("amount_atomic", "01"),
        ("amount_atomic", 1),
        ("network", " eip155:8453"),
    ],
)
def test_exact_model_fails_closed_on_malformed_scope(field: str, value: object):
    payload = exact_payload()
    payload[field] = value  # type: ignore[assignment]
    with pytest.raises(ValueError):
        normalize_hosted_business_intent(payload)


def test_challenge_uses_fixed_domain_and_version_vector():
    challenge = build_hosted_payment_challenge(exact_payload(), reservation_row())

    assert (
        challenge
        == "0x898403139eb3f8e4135f99f206b567f337e6c9d9b4a1401dbfdad7369c94c693"
    )


def test_challenge_rejects_malformed_durable_row():
    with pytest.raises(ValueError):
        build_hosted_payment_challenge(
            exact_payload(), reservation_row(token_address="0x" + "0" * 40)
        )


def test_business_models_do_not_accept_hosted_internal_identity_fields():
    for payload in (
        {**exact_payload(), "tenant_id": "tenant_1"},
        {**pm_payload(), "node_id": "node_1"},
    ):
        with pytest.raises(ValueError):
            normalize_hosted_business_intent(payload)
