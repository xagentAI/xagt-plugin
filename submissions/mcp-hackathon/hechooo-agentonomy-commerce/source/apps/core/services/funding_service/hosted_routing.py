"""Pure business-intent normalization for Core Hosted payment routing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from services.funding_service.schemas import (
    DirectTransferIntent,
    PredictionMarketBridgeTransferIntent,
    X402ExactIntent,
)
from shared.hosted_facilitator_protocol import canonical_json_bytes, sha256_identifier


HOSTED_PAYMENT_CHALLENGE_VERSION = "agentonomy-payment-challenge-v1"

HostedBusinessIntent = X402ExactIntent | PredictionMarketBridgeTransferIntent | DirectTransferIntent

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,95}$")


def normalize_hosted_business_intent(
    payload: Mapping[str, Any]
) -> HostedBusinessIntent:
    """Parse one existing product payment payload into a strict Core shape.

    Marketplace sends the five-field x402 exact payload without a discriminator;
    Core adds ``kind=x402_exact`` through the model default.  Polymarket sends
    its existing explicit bridge-transfer discriminator.  No Hosted enrollment
    identity is accepted by either shape.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Hosted business intent must be an object")
    if payload.get("kind") == "direct_transfer":
        try:
            return DirectTransferIntent.model_validate(dict(payload), strict=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("direct transfer business intent is invalid") from exc
    if "kind" not in payload:
        try:
            return X402ExactIntent.model_validate(dict(payload), strict=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("x402 exact business intent is invalid") from exc
    if payload.get("kind") != "prediction_market_bridge_transfer":
        raise ValueError("Hosted business intent kind is invalid")
    try:
        return PredictionMarketBridgeTransferIntent.model_validate(
            dict(payload), strict=True
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("prediction-market bridge business intent is invalid") from exc


def validate_hosted_business_intent(
    payload: Mapping[str, Any], reservation_row: Mapping[str, Any]
) -> HostedBusinessIntent:
    """Validate a product intent against the durable Core reservation scope."""

    intent = normalize_hosted_business_intent(payload)
    scope = _reservation_scope(reservation_row)
    if isinstance(intent, DirectTransferIntent) or reservation_row.get("product") == "transfers":
        if (
            not isinstance(intent, DirectTransferIntent)
            or reservation_row.get("product") != "transfers"
            or reservation_row.get("venue") != "clink_transfers"
        ):
            raise ValueError("direct transfer product and intent must match")
        _require_match("network", intent.network, scope["network"])
    if isinstance(intent, X402ExactIntent):
        _require_match("network", intent.network, scope["network"])
        _require_match("token", intent.token, scope["token"])
        _require_match("amount", intent.amount_atomic, scope["amount_atomic"])
        _require_match("destination", intent.destination, scope["destination"])
        return intent

    _require_match("reservation_id", intent.reservation_id, scope["reservation_id"])
    _require_match(
        "operation_id/purchase_id", intent.operation_id, scope["purchase_id"]
    )
    _require_match("destination", intent.destination, scope["destination"])
    _require_match("token", intent.token, scope["token"])
    _require_match("amount", intent.amount_atomic, scope["amount_atomic"])
    return intent


def build_hosted_payment_challenge(
    payload: Mapping[str, Any], reservation_row: Mapping[str, Any]
) -> str:
    """Return the deterministic lower-case bytes32 challenge for one payment."""

    intent = validate_hosted_business_intent(payload, reservation_row)
    scope = _reservation_scope(reservation_row)
    challenge_payload = {
        "domain": HOSTED_PAYMENT_CHALLENGE_VERSION,
        "version": HOSTED_PAYMENT_CHALLENGE_VERSION,
        "kind": intent.kind,
        "scheme": intent.scheme if isinstance(intent, X402ExactIntent) else None,
        "network": scope["network"],
        "token": scope["token"],
        "amount_atomic": scope["amount_atomic"],
        "destination": scope["destination"],
        "reservation_id": scope["reservation_id"],
        "purchase_id": scope["purchase_id"],
        "binding_id": (
            intent.binding_id
            if isinstance(intent, PredictionMarketBridgeTransferIntent)
            else None
        ),
    }
    return sha256_identifier(canonical_json_bytes(challenge_payload))


def _reservation_scope(row: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(row, Mapping):
        raise ValueError("durable reservation row is invalid")
    scope = {
        "reservation_id": _identifier(row.get("reservation_id"), "reservation_id"),
        "purchase_id": _identifier(row.get("purchase_id"), "purchase_id"),
        "network": _network(row.get("network")),
        "token": _address(row.get("token_address"), "token_address"),
        "amount_atomic": _amount(row.get("amount_atomic")),
        "destination": _address(row.get("destination"), "destination"),
    }
    return scope


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"durable reservation {field_name} is invalid")
    return value


def _network(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("durable reservation network is invalid")
    if re.fullmatch(r"^[a-z][a-z0-9+.-]{0,15}:[A-Za-z0-9:_-]{1,47}$", value) is None:
        raise ValueError("durable reservation network is invalid")
    return value


def _address(value: object, field_name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"0x[0-9a-fA-F]{40}", value) is None:
        raise ValueError(f"durable reservation {field_name} is invalid")
    normalized = value.lower()
    if normalized == "0x" + "0" * 40:
        raise ValueError(f"durable reservation {field_name} is invalid")
    return normalized


def _amount(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
        raise ValueError("durable reservation amount_atomic is invalid")
    if int(value) >= 2**256:
        raise ValueError("durable reservation amount_atomic is invalid")
    return value


def _require_match(field_name: str, actual: str, expected: str) -> None:
    if actual != expected:
        raise ValueError(
            f"Hosted business intent {field_name} does not match reservation"
        )
