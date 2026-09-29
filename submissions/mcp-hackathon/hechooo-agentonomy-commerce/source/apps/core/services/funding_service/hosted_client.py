"""Small, fail-closed client for the Hosted Base execution API.

The client owns transport and protocol verification only.  It does not decide
whether a Core reservation may be spent and it never submits an on-chain
transaction itself.  A caller must persist the request envelope before calling
``submit`` and must use ``recover`` for an existing execution.
"""

from __future__ import annotations

import asyncio
import json
import math
import secrets
import time
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HostedChainProfile,
    HostedExecutionResponse,
    HostedPaymentEnvelope,
    HostedProtocolError,
    _inspect_compact_jws,
    _jwk_thumbprint,
    _public_key_from_jwk,
    build_dpop_proof,
    canonical_json_bytes,
    hosted_chain_profile,
    sign_payment_envelope,
    verify_execution_response,
)
from shared.payment_capability import PaymentCapabilityV1


_EXECUTION_PATH = "/v1/executions"
_EXECUTION_LOOKUP_PATH = "/v1/execution-lookups"
_MAX_ORIGIN_LENGTH = 2048
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_ACCESS_TOKEN_LENGTH = 8192
_MAX_IDENTIFIER_LENGTH = 256
_MAX_TIMEOUT_SECONDS = 60.0
_REQUEST_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
)


class _DuplicateJSONKey(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-JSON numeric constant")

_T = TypeVar("_T")


class HostedFacilitatorError(RuntimeError):
    """A bounded, secret-free Hosted client error."""


class HostedExecutionUnknown(HostedFacilitatorError):
    """The POST outcome is unknown and must never be retried with another POST."""


class HostedExecutionNotFound(HostedFacilitatorError):
    """A GET-only recovery lookup definitively found no Hosted execution."""


class HostedFacilitatorUnavailable(HostedFacilitatorError):
    """No execution result was established because the service was unavailable."""


@dataclass(frozen=True)
class HostedExecutionRequest:
    """The immutable request data that Core must persist before submission."""

    envelope: HostedPaymentEnvelope
    payment_jws: str

    @property
    def request_hash(self) -> str:
        return self.envelope.request_hash


def _bounded_identifier(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(
            unicodedata.category(char).startswith("C")
            or unicodedata.category(char) in {"Zl", "Zp"}
            for char in value
        )
    ):
        raise ValueError(f"{field_name} is invalid")
    if any(char not in _REQUEST_ID_CHARS for char in value):
        raise ValueError(f"{field_name} is invalid")
    return value


def _trusted_server_jwk(value: object) -> dict[str, str]:
    if isinstance(value, str):
        if len(value) > 16 * 1024:
            raise ValueError("Hosted response key is invalid")
        try:
            parsed = json.loads(
                value,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (TypeError, ValueError, RecursionError):
            raise ValueError("Hosted response key is invalid") from None
    elif isinstance(value, Mapping):
        parsed = dict(value)
    else:
        raise ValueError("Hosted response key is invalid")
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"kty", "crv", "x", "y"}
        or any(not isinstance(item, str) for item in parsed.values())
    ):
        raise ValueError("Hosted response key is invalid")
    try:
        _public_key_from_jwk(parsed)
        _jwk_thumbprint(parsed)
    except (HostedProtocolError, ValueError):
        raise ValueError("Hosted response key is invalid") from None
    return parsed


def _strict_json_object(value: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (
        _DuplicateJSONKey,
        UnicodeDecodeError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise HostedFacilitatorUnavailable(
            "hosted facilitator response is invalid"
        ) from None
    if not isinstance(parsed, dict) or set(parsed) != {"response_jws"}:
        raise HostedFacilitatorUnavailable(
            "hosted facilitator response is invalid"
        )
    if not isinstance(parsed["response_jws"], str):
        raise HostedFacilitatorUnavailable(
            "hosted facilitator response is invalid"
        )
    return parsed


class HostedFacilitatorClient:
    """Transport and signature verifier for one Hosted enrollment.

    ``submit`` performs the only POST this object exposes.  ``recover`` is
    intentionally GET-only and requires the already returned execution id.
    This keeps an ambiguous broadcast from becoming a second economic action.
    """

    __slots__ = (
        "_access_token",
        "_clock",
        "_chain_id",
        "_device_key",
        "_max_response_bytes",
        "_monotonic",
        "_node_id",
        "_origin",
        "_server_key_id",
        "_server_public_jwk",
        "_tenant_id",
        "_timeout_seconds",
        "_transport_factory",
        "_wallet_binding_id",
    )

    def __init__(
        self,
        *,
        origin: str,
        tenant_id: str,
        node_id: str,
        wallet_binding_id: str,
        access_token: str,
        device_key: DeviceSigningKey,
        server_public_jwk: object,
        chain_id: str,
        clock: Callable[[], int] | None = None,
        monotonic: Callable[[], float] | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 64 * 1024,
        transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        if not isinstance(origin, str) or not origin or len(origin) > _MAX_ORIGIN_LENGTH:
            raise ValueError("Hosted facilitator origin is invalid")
        normalized = origin.rstrip("/")
        try:
            parsed = httpx.URL(normalized)
        except (TypeError, ValueError, httpx.InvalidURL):
            raise ValueError("Hosted facilitator origin is invalid") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.host
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
            or (parsed.scheme != "https" and parsed.host not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("Hosted facilitator origin is invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or timeout_seconds > _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("Hosted facilitator timeout is invalid")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes <= 0
            or max_response_bytes > _MAX_RESPONSE_BYTES
        ):
            raise ValueError("Hosted facilitator response limit is invalid")
        if not isinstance(device_key, DeviceSigningKey):
            raise ValueError("Hosted device key is invalid")
        if not isinstance(chain_id, str):
            raise ValueError("Hosted facilitator chain_id is invalid")
        try:
            profile = hosted_chain_profile(chain_id)
        except ValueError:
            raise ValueError("Hosted facilitator chain_id is invalid") from None
        if (
            not isinstance(access_token, str)
            or not access_token
            or len(access_token) > _MAX_ACCESS_TOKEN_LENGTH
            or any(ord(char) < 0x21 or ord(char) > 0x7E for char in access_token)
        ):
            raise ValueError("Hosted access token is invalid")
        _bounded_identifier(tenant_id, field_name="tenant_id")
        _bounded_identifier(node_id, field_name="node_id")
        _bounded_identifier(wallet_binding_id, field_name="wallet_binding_id")
        if transport_factory is not None and not callable(transport_factory):
            raise ValueError("Hosted transport factory is invalid")
        trusted = _trusted_server_jwk(server_public_jwk)
        self._origin = normalized
        self._chain_id = profile.chain
        self._tenant_id = tenant_id
        self._node_id = node_id
        self._wallet_binding_id = wallet_binding_id
        self._access_token = access_token
        self._device_key = device_key
        self._server_public_jwk = trusted
        self._server_key_id = _jwk_thumbprint(trusted)
        self._clock = clock or (lambda: int(time.time()))
        self._monotonic = monotonic or time.monotonic
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._transport_factory = transport_factory

    @property
    def server_key_id(self) -> str:
        return self._server_key_id

    @property
    def origin(self) -> str:
        return self._origin

    @property
    def chain_id(self) -> str:
        """Return the immutable chain binding."""
        return self._chain_id

    @property
    def profile(self) -> HostedChainProfile:
        return hosted_chain_profile(self._chain_id)

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def wallet_binding_id(self) -> str:
        return self._wallet_binding_id

    def prepare_execution(
        self,
        capability: PaymentCapabilityV1,
        *,
        request_id: str,
        idempotency_key: str,
        request_nonce: str | None = None,
        now: int | None = None,
    ) -> HostedExecutionRequest:
        if not isinstance(capability, PaymentCapabilityV1):
            raise ValueError("payment capability is invalid")
        if capability.network != self._chain_id:
            raise ValueError("Hosted execution chain does not match client")
        profile = hosted_chain_profile(self._chain_id)
        if capability.asset_contract != profile.token:
            raise ValueError("Hosted execution token does not match client chain")
        if (
            capability.tenant_id != self._tenant_id
            or capability.node_id != self._node_id
            or capability.wallet_binding_id != self._wallet_binding_id
        ):
            raise ValueError(
                "Hosted execution enrollment identity does not match capability"
            )
        request_id = _bounded_identifier(request_id, field_name="request_id")
        idempotency_key = _bounded_identifier(
            idempotency_key, field_name="idempotency_key"
        )
        issued_at = self._now() if now is None else now
        if type(issued_at) is not int or issued_at <= 0:
            raise ValueError("Hosted execution clock is invalid")
        if issued_at >= capability.expires_at:
            raise ValueError("payment capability has expired")
        if request_nonce is None:
            request_nonce = "0x" + secrets.token_hex(32)
        envelope = HostedPaymentEnvelope(
            protocol_version="clink-hosted-v1",
            audience="hosted-facilitator",
            http_method="POST",
            http_path=_EXECUTION_PATH,
            request_id=request_id,
            idempotency_key=idempotency_key,
            tenant_id=self._tenant_id,
            node_id=self._node_id,
            wallet_binding_id=self._wallet_binding_id,
            payment_capability_version=capability.capability_version,
            payment_capability_id=capability.capability_id,
            payment_capability_hash=capability.capability_hash,
            wallet_identity_id=capability.wallet_identity_id,
            wallet_address=capability.wallet_address,
            spending_grant_id=capability.spending_grant_id,
            spending_grant_hash=capability.spending_grant_hash,
            asset_allowance_id=capability.asset_allowance_id,
            reservation_id=capability.reservation_id,
            reservation_hash=capability.reservation_hash,
            action_id=capability.action_id,
            policy_decision_id=capability.policy_decision_id,
            policy_snapshot_hash=capability.policy_snapshot_hash,
            risk_evidence_hash=capability.risk_evidence_hash,
            purchase_id=capability.purchase_id,
            merchant_id=capability.merchant_id,
            quote_hash=capability.quote_hash,
            payment_challenge_hash=capability.payment_challenge_hash,
            chain_id=capability.network,
            asset_contract=capability.asset_contract,
            amount_atomic=capability.amount_atomic,
            pay_to=capability.pay_to,
            executor_contract=capability.executor_contract,
            execution_scope_hash=capability.execution_scope_hash,
            request_nonce=request_nonce,
            issued_at=issued_at,
            expires_at=capability.expires_at,
        )
        return HostedExecutionRequest(
            envelope=envelope,
            payment_jws=sign_payment_envelope(self._device_key, envelope),
        )

    def submit(self, request: HostedExecutionRequest | HostedPaymentEnvelope) -> HostedExecutionResponse:
        return self._run_sync(self.asubmit, request)

    async def asubmit(
        self, request: HostedExecutionRequest | HostedPaymentEnvelope
    ) -> HostedExecutionResponse:
        prepared = self._coerce_request(request)
        return await self._request_execution(prepared, method="POST")

    def recover(
        self,
        request: HostedExecutionRequest | HostedPaymentEnvelope,
        execution_id: str,
    ) -> HostedExecutionResponse:
        return self._run_sync(self.arecover, request, execution_id)

    async def arecover(
        self,
        request: HostedExecutionRequest | HostedPaymentEnvelope,
        execution_id: str,
    ) -> HostedExecutionResponse:
        prepared = self._coerce_request(request)
        execution_id = _bounded_identifier(execution_id, field_name="execution_id")
        return await self._request_execution(
            prepared, method="GET", execution_id=execution_id
        )

    def recover_by_idempotency(
        self, request: HostedExecutionRequest | HostedPaymentEnvelope
    ) -> HostedExecutionResponse:
        return self._run_sync(self.arecover_by_idempotency, request)

    async def arecover_by_idempotency(
        self, request: HostedExecutionRequest | HostedPaymentEnvelope
    ) -> HostedExecutionResponse:
        prepared = self._coerce_request(request)
        idempotency_key = _bounded_identifier(
            prepared.envelope.idempotency_key,
            field_name="idempotency_key",
        )
        return await self._request_execution(
            prepared,
            method="GET",
            lookup_idempotency_key=idempotency_key,
        )

    def _coerce_request(
        self, request: HostedExecutionRequest | HostedPaymentEnvelope
    ) -> HostedExecutionRequest:
        if isinstance(request, HostedExecutionRequest):
            if request.envelope.http_path != _EXECUTION_PATH:
                raise ValueError("Hosted execution route is invalid")
            self._validate_envelope_binding(request.envelope)
            return request
        if isinstance(request, HostedPaymentEnvelope):
            if request.http_path != _EXECUTION_PATH:
                raise ValueError("Hosted execution route is invalid")
            self._validate_envelope_binding(request)
            return HostedExecutionRequest(
                envelope=request,
                payment_jws=sign_payment_envelope(self._device_key, request),
            )
        raise ValueError("Hosted execution request is invalid")

    def _validate_envelope_binding(self, envelope: HostedPaymentEnvelope) -> None:
        expected_chain = self._chain_id
        if envelope.chain_id != expected_chain:
            raise ValueError("Hosted execution chain does not match client")
        if (
            envelope.tenant_id != self._tenant_id
            or envelope.node_id != self._node_id
            or envelope.wallet_binding_id != self._wallet_binding_id
        ):
            raise ValueError(
                "Hosted execution enrollment identity does not match client"
            )
        profile = hosted_chain_profile(expected_chain)
        if envelope.asset_contract != profile.token:
            raise ValueError("Hosted execution token does not match client chain")

    async def _request_execution(
        self,
        request: HostedExecutionRequest,
        *,
        method: str,
        execution_id: str | None = None,
        lookup_idempotency_key: str | None = None,
    ) -> HostedExecutionResponse:
        url = f"{self._origin}{_EXECUTION_PATH}"
        if method == "GET":
            if execution_id is not None and lookup_idempotency_key is not None:
                raise ValueError("Hosted recovery route is ambiguous")
            if execution_id is not None:
                url = f"{url}/{execution_id}"
            elif lookup_idempotency_key is not None:
                url = (
                    f"{self._origin}{_EXECUTION_LOOKUP_PATH}/"
                    f"{lookup_idempotency_key}"
                )
            else:
                raise ValueError("execution ID or idempotency key is required for recovery")
        elif execution_id is not None or lookup_idempotency_key is not None:
            raise ValueError("Hosted execution route is ambiguous")
        request_dispatched = False
        try:
            async with self._new_client() as client:
                headers = {
                    "authorization": f"DPoP {self._access_token}",
                    "accept": "application/json",
                    "accept-encoding": "identity",
                }
                content = None
                if method == "POST":
                    headers["content-type"] = "application/json"
                    content = canonical_json_bytes({"payment_jws": request.payment_jws})
                http_request = client.build_request(
                    method,
                    url,
                    headers=headers,
                    content=content,
                )
                http_request.extensions["follow_redirects"] = False
                http_request.headers["dpop"] = build_dpop_proof(
                    self._device_key,
                    method=method,
                    url=str(http_request.url),
                    access_token=self._access_token,
                    now=self._now(),
                )
                request_dispatched = True
                response = await client.send(
                    http_request,
                    stream=True,
                    follow_redirects=False,
                )
                try:
                    body = await self._read_response(response)
                finally:
                    await response.aclose()
        except HostedExecutionUnknown:
            raise
        except HostedFacilitatorUnavailable:
            if method == "POST" and request_dispatched:
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise
        except HostedFacilitatorError:
            if method == "POST" and request_dispatched:
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise
        except (httpx.TimeoutException, httpx.TransportError, OSError) as exc:
            if method == "POST" and request_dispatched:
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise HostedFacilitatorUnavailable(
                "hosted execution status is unavailable"
            ) from None
        except Exception:
            if method == "POST" and request_dispatched:
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise HostedFacilitatorUnavailable(
                "hosted execution request failed"
            ) from None

        try:
            if method == "GET" and response.status_code == 404:
                raise HostedExecutionNotFound(
                    "hosted execution was not found"
                )
            if response.status_code not in {200, 201, 409}:
                if method == "POST":
                    raise HostedExecutionUnknown(
                        "hosted execution submission outcome is unknown"
                    )
                raise HostedFacilitatorUnavailable(
                    "hosted facilitator returned an unsuccessful response"
                )
            container = _strict_json_object(body)
            header, _payload = _inspect_compact_jws(
                container["response_jws"], label="execution response JWS"
            )
            if header.get("kid") != self._server_key_id:
                raise HostedProtocolError("execution response key is not trusted")
            now = self._now()
            result = verify_execution_response(
                container["response_jws"],
                self._server_public_jwk,
                request.envelope,
                now=now,
                expected_execution_id=execution_id,
            )
            if result.issued_at > now or any(
                timestamp is not None and timestamp > now
                for timestamp in (
                    result.submitted_at,
                    result.confirmed_at,
                    result.finalized_at,
                    result.reverted_at,
                    result.reorg_reviewed_at,
                )
            ):
                raise HostedFacilitatorUnavailable(
                    "hosted execution response time is invalid"
                )
            return result
        except HostedExecutionUnknown:
            raise
        except HostedFacilitatorError:
            if method == "POST":
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise
        except Exception:
            if method == "POST":
                raise HostedExecutionUnknown(
                    "hosted execution submission outcome is unknown"
                ) from None
            raise HostedFacilitatorUnavailable(
                "hosted execution response is not trusted"
            ) from None

    async def _read_response(self, response: httpx.Response) -> bytes:
        if response.is_redirect:
            raise HostedFacilitatorUnavailable("hosted facilitator redirect is not allowed")
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise HostedFacilitatorUnavailable(
                "hosted facilitator response encoding is not allowed"
            )
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HostedFacilitatorUnavailable(
                "hosted facilitator response type is invalid"
            )
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._max_response_bytes:
                raise HostedFacilitatorUnavailable(
                    "hosted facilitator response is too large"
                )
        return bytes(body)

    def _new_client(self) -> httpx.AsyncClient:
        transport = None
        if self._transport_factory is not None:
            try:
                transport = self._transport_factory()
            except Exception:
                raise HostedFacilitatorUnavailable(
                    "hosted facilitator transport is unavailable"
                ) from None
            if not isinstance(transport, httpx.AsyncBaseTransport):
                raise ValueError("Hosted transport factory returned an invalid transport")
        return httpx.AsyncClient(
            verify=True,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(self._timeout_seconds),
            transport=transport,
        )

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value <= 0:
            raise HostedFacilitatorUnavailable("hosted facilitator clock is invalid")
        return value

    @staticmethod
    def _run_sync(
        async_method: Callable[..., Awaitable[_T]], *args: object
    ) -> _T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(async_method(*args))
        raise RuntimeError(
            "Hosted facilitator sync API cannot run inside an event loop"
        )
