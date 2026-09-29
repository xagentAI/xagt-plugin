"""Small x402 v2 boundary for the paid qualification route.

The production path delegates verification and settlement to a facilitator.
Mock mode is deliberately explicit and is only for local protocol tests.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen


@dataclass(frozen=True)
class PaymentResult:
    payer: str | None
    transaction: str | None
    network: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def payment_requirements() -> dict[str, Any]:
    network = _env("X402_NETWORK", "hedera:testnet")
    requirements: dict[str, Any] = {
        "scheme": "exact",
        "network": network,
        "amount": _env("X402_AMOUNT", "100000"),
        "payTo": _env("X402_PAY_TO"),
        "maxTimeoutSeconds": int(_env("X402_MAX_TIMEOUT_SECONDS", "300")),
        "asset": _env("X402_ASSET", "0.0.0"),
        "extra": {"feePayer": _env("X402_FEE_PAYER")},
    }
    return requirements


def payment_required_response() -> dict[str, Any]:
    return {
        "x402Version": 2,
        "accepts": [payment_requirements()],
        "error": "Payment required",
    }


def encode_payment_required(response: dict[str, Any]) -> str:
    raw = json.dumps(response, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def decode_payment_payload(value: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(value, validate=True)
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid payment payload encoding") from exc
    if not isinstance(payload, dict) or payload.get("x402Version") != 2:
        raise ValueError("unsupported payment payload")
    return payload


def _post_json(url: str, body: dict[str, Any]) -> dict[str, Any]:
    request = UrlRequest(
        url,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310 - configured facilitator only
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("facilitator request failed") from exc
    if not isinstance(result, dict):
        raise RuntimeError("facilitator returned an invalid response")
    return result


def verify_and_settle(payload: dict[str, Any]) -> PaymentResult:
    mode = _env("X402_MODE", "disabled").lower()
    requirements = payment_requirements()
    if mode == "mock":
        if payload.get("payload", {}).get("mock") != "local-test-only":
            raise ValueError("mock payment marker missing")
        return PaymentResult("mock-payer", "mock-transaction", requirements["network"])
    if mode != "remote":
        raise RuntimeError("x402 is disabled; set X402_MODE=remote only for approved testnet use")
    if not requirements["payTo"] or "REPLACE_WITH" in requirements["payTo"]:
        raise RuntimeError("X402_PAY_TO is not configured")

    facilitator = _env("X402_FACILITATOR_URL", "https://api.testnet.blocky402.com").rstrip("/")
    body = {"x402Version": 2, "paymentPayload": payload, "paymentRequirements": requirements}
    verification = _post_json(f"{facilitator}/verify", body)
    if verification.get("isValid") is not True:
        raise ValueError("payment verification failed")
    settlement = _post_json(f"{facilitator}/settle", body)
    if settlement.get("success") is not True:
        raise ValueError("payment settlement failed")
    return PaymentResult(
        settlement.get("payer"),
        settlement.get("transaction"),
        settlement.get("network", requirements["network"]),
    )
