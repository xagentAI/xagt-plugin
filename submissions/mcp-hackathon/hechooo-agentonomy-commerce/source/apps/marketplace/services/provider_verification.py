from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field

from shared.models import ServiceOffering
from shared.container_config import parse_boolean
from shared.security import validate_public_https_url


class VerificationResult(BaseModel):
    verified: bool
    reason_code: str
    reason: str
    http_status: int | None = None
    live_pay_to: list[str] = Field(default_factory=list)


def _resolve_host(hostname: str) -> list[str]:
    return sorted(
        {
            item[4][0]
            for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    )


class EndpointVerifier:
    def __init__(
        self,
        *,
        session: requests.Session | Any | None = None,
        resolver: Callable[[str], list[str]] | None = None,
        timeout_seconds: float = 5.0,
        request_attempts: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("endpoint verification timeout must be positive")
        if request_attempts <= 0:
            raise ValueError("endpoint verification attempts must be positive")
        self.session = session or requests.Session()
        self.resolver = resolver or _resolve_host
        self.timeout_seconds = timeout_seconds
        self.request_attempts = request_attempts
        self.read_only = parse_boolean(
            os.getenv("MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY", "false"),
            name="MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY",
        )

    def verify(self, offering: ServiceOffering) -> VerificationResult:
        if self.read_only and offering.method not in {"GET", "HEAD"}:
            return VerificationResult(
                verified=False,
                reason_code="READ_ONLY_METHOD_NOT_ALLOWED",
                reason="read-only discovery does not probe write-method endpoints",
            )
        validate_public_https_url(offering.endpoint)
        hostname = urlsplit(offering.endpoint).hostname
        if not hostname:
            return VerificationResult(
                verified=False,
                reason_code="INVALID_ENDPOINT",
                reason="service endpoint has no hostname",
            )

        addresses = self.resolver(hostname)
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            return VerificationResult(
                verified=False,
                reason_code="UNSAFE_RESOLVED_ADDRESS",
                reason="service hostname resolved to a private or non-global address",
            )

        request_kwargs: dict[str, Any] = {
            "method": offering.method,
            "url": offering.endpoint,
            "timeout": self.timeout_seconds,
            "allow_redirects": False,
        }
        input_info = offering.metadata.get("bazaar_info", {}).get("input", {})
        if offering.method == "GET" and isinstance(input_info.get("queryParams"), dict):
            request_kwargs["params"] = input_info["queryParams"]
        elif offering.method in {"POST", "PUT", "PATCH"} and isinstance(
            input_info.get("body"), dict
        ):
            request_kwargs["json"] = input_info["body"]

        response = None
        last_error: requests.RequestException | None = None
        for _ in range(self.request_attempts):
            try:
                response = self.session.request(**request_kwargs)
                break
            except requests.RequestException as exc:
                last_error = exc
        if response is None:
            assert last_error is not None
            return VerificationResult(
                verified=False,
                reason_code="ENDPOINT_UNREACHABLE",
                reason=f"{type(last_error).__name__}: {last_error}",
            )
        if response.status_code != 402:
            return VerificationResult(
                verified=False,
                reason_code="PAYMENT_REQUIRED_NOT_RETURNED",
                reason=f"expected HTTP 402, received {response.status_code}",
                http_status=response.status_code,
            )

        try:
            requirements = self._decode_payment_required(response.headers)
        except (ValueError, json.JSONDecodeError) as exc:
            return VerificationResult(
                verified=False,
                reason_code="INVALID_PAYMENT_REQUIREMENTS",
                reason=str(exc),
                http_status=response.status_code,
            )

        live_accepts = requirements.get("accepts", [])
        if not isinstance(live_accepts, list):
            live_accepts = []
        live_pay_to = [str(item.get("payTo")) for item in live_accepts if item.get("payTo")]
        recipient_matches = any(
            self._same_identifier(option.network, option.pay_to, str(live.get("payTo") or ""))
            for option in offering.payment_options
            for live in live_accepts
        )
        if not live_pay_to or not recipient_matches:
            return VerificationResult(
                verified=False,
                reason_code="PAYMENT_RECIPIENT_MISMATCH",
                reason="live payment recipient does not match the catalog",
                http_status=response.status_code,
                live_pay_to=live_pay_to,
            )
        requirements_match = any(
            self._payment_option_matches(option, live)
            for option in offering.payment_options
            for live in live_accepts
        )
        if not requirements_match:
            return VerificationResult(
                verified=False,
                reason_code="PAYMENT_REQUIREMENTS_MISMATCH",
                reason="live network, asset, amount, or scheme does not match the catalog",
                http_status=response.status_code,
                live_pay_to=live_pay_to,
            )
        return VerificationResult(
            verified=True,
            reason_code="VERIFIED",
            reason="endpoint returned compatible x402 payment requirements",
            http_status=response.status_code,
            live_pay_to=live_pay_to,
        )

    @classmethod
    def _payment_option_matches(cls, option: Any, live: dict[str, Any]) -> bool:
        live_amount = live.get("amount", live.get("maxAmountRequired"))
        try:
            amount_matches = Decimal(str(option.amount_atomic)) == Decimal(str(live_amount))
        except (InvalidOperation, TypeError):
            amount_matches = False
        return (
            option.scheme == str(live.get("scheme") or "")
            and option.network == str(live.get("network") or "")
            and amount_matches
            and cls._same_identifier(option.network, option.asset, str(live.get("asset") or ""))
            and cls._same_identifier(
                option.network,
                option.pay_to,
                str(live.get("payTo") or ""),
            )
        )

    @staticmethod
    def _same_identifier(network: str, expected: str, actual: str) -> bool:
        if network.startswith("eip155:"):
            return expected.lower() == actual.lower()
        return expected == actual

    @staticmethod
    def _decode_payment_required(headers: Any) -> dict[str, Any]:
        encoded = headers.get("PAYMENT-REQUIRED") or headers.get("payment-required")
        if not encoded:
            raise ValueError("PAYMENT-REQUIRED header is missing")
        padding = "=" * (-len(encoded) % 4)
        try:
            decoded = base64.urlsafe_b64decode(f"{encoded}{padding}")
        except Exception as exc:
            raise ValueError("PAYMENT-REQUIRED header is not valid base64") from exc
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise ValueError("PAYMENT-REQUIRED payload must be an object")
        return payload
