"""Fail-closed Core authority lookup for Hosted execution."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

try:  # pragma: no cover - tests inject a small fake client.
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

from evm import ExecutionAuthorization, hash_execution
from execution_models import ExecutionIntent
from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES, HostedPaymentEnvelope


MAX_AUTHORITY_RESPONSE_BYTES = 64 * 1024
MAX_UINT256 = 2**256 - 1


class _DuplicateJSONMember(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONMember(key)
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-JSON numeric constant")


class CoreAuthorityError(RuntimeError):
    """Base class for bounded, provider-secret-free authority failures."""


class CoreAuthorityUnavailable(CoreAuthorityError):
    """Core could not be reached or returned an unusable response."""


class CoreAuthorityRejected(CoreAuthorityError):
    """Core rejected the immutable execution scope."""


def _is_loopback(hostname: str) -> bool:
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _canonical_origin(value: object, *, environment: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("Core authority origin is invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise ValueError("Core authority origin is invalid") from None
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Core authority origin is invalid")
    if parsed.scheme == "https":
        pass
    elif environment == "test" and parsed.scheme == "http" and _is_loopback(hostname):
        pass
    else:
        raise ValueError("Core authority origin must use HTTPS")
    if parsed.path == "/" or (
        port == 80 and parsed.scheme == "http"
    ) or (port == 443 and parsed.scheme == "https"):
        raise ValueError("Core authority origin is not canonical")
    return value


def _address(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError(f"{field} is invalid")
    try:
        raw = bytes.fromhex(value[2:])
    except ValueError:
        raise ValueError(f"{field} is invalid") from None
    if len(raw) != 20 or raw == bytes(20):
        raise ValueError(f"{field} is invalid")
    return "0x" + raw.hex()


def _bytes32(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 66
        or not value.startswith("0x")
        or any(character not in "0123456789abcdef" for character in value[2:])
    ):
        raise CoreAuthorityRejected(f"{field} is invalid")
    return value


class CoreAuthorityProjection:
    """Strict response projection without exposing any Core internals."""

    __slots__ = ("_values",)

    _FIELDS = frozenset(
        {
            "tenant_id",
            "node_id",
            "wallet_binding_id",
            "capability_id",
            "capability_hash",
            "reservation_id",
            "reservation_hash",
            "purchase_id",
            "request_id",
            "request_hash",
            "request_nonce",
            "idempotency_key",
            "chain_id",
            "owner",
            "payee",
            "token",
            "amount_atomic",
            "executor",
            "signer_epoch",
            "deadline",
            "execution_scope_hash",
            "execution_digest",
            "relayer_address",
            "payment_challenge_hash",
        }
    )

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping) or set(payload) != self._FIELDS:
            raise CoreAuthorityRejected("Core authority response is invalid")
        values = dict(payload)
        for field in (
            "tenant_id",
            "node_id",
            "wallet_binding_id",
            "capability_id",
            "reservation_id",
            "purchase_id",
            "request_id",
            "idempotency_key",
        ):
            if not isinstance(values[field], str) or not values[field] or len(values[field]) > 256:
                raise CoreAuthorityRejected("Core authority response is invalid")
        for field in (
            "capability_hash",
            "reservation_hash",
            "request_hash",
            "request_nonce",
            "execution_scope_hash",
            "execution_digest",
            "payment_challenge_hash",
        ):
            _bytes32(values[field], field=field)
        chain = values["chain_id"]
        profile = HOSTED_CHAIN_PROFILES.get(chain) if isinstance(chain, str) else None
        if profile is None:
            raise CoreAuthorityRejected("Core authority response is invalid")
        for field in ("owner", "payee", "token", "executor", "relayer_address"):
            values[field] = _address(values[field], field=field)
        if values["token"] != profile.token:
            raise CoreAuthorityRejected("Core authority response is invalid")
        if (
            not isinstance(values["amount_atomic"], str)
            or not values["amount_atomic"].isdigit()
            or values["amount_atomic"].startswith("0")
            or int(values["amount_atomic"]) > MAX_UINT256
        ):
            raise CoreAuthorityRejected("Core authority response is invalid")
        if type(values["signer_epoch"]) is not int or values["signer_epoch"] <= 0 or values["signer_epoch"] > MAX_UINT256:
            raise CoreAuthorityRejected("Core authority response is invalid")
        if type(values["deadline"]) is not int or values["deadline"] <= 0 or values["deadline"] > MAX_UINT256:
            raise CoreAuthorityRejected("Core authority response is invalid")
        self._values = values

    def __getitem__(self, field: str) -> Any:
        return self._values[field]

    def matches(self, expected: Mapping[str, Any]) -> bool:
        return all(self._values.get(field) == value for field, value in expected.items())

    def to_intent(self) -> ExecutionIntent:
        values = dict(self._values)
        values["chain"] = values.pop("chain_id")
        values["owner_nonce"] = int(values.pop("request_nonce"), 16)
        values.pop("payment_challenge_hash", None)
        return ExecutionIntent.model_validate(values, strict=True)


class CorePreflightProjection:
    """Strict echo of the Core-owned preflight scope."""

    __slots__ = ("_values",)

    _FIELDS = frozenset(
        {
            "protocol_version",
            "audience",
            "http_method",
            "http_path",
            "request_id",
            "request_hash",
            "idempotency_key",
            "tenant_id",
            "node_id",
            "wallet_binding_id",
            "payment_capability_version",
            "payment_capability_id",
            "payment_capability_hash",
            "wallet_identity_id",
            "wallet_address",
            "spending_grant_id",
            "spending_grant_hash",
            "asset_allowance_id",
            "reservation_id",
            "reservation_hash",
            "action_id",
            "policy_decision_id",
            "policy_snapshot_hash",
            "risk_evidence_hash",
            "purchase_id",
            "merchant_id",
            "quote_hash",
            "payment_challenge_hash",
            "chain_id",
            "asset_contract",
            "amount_atomic",
            "pay_to",
            "executor_contract",
            "execution_scope_hash",
            "request_nonce",
            "issued_at",
            "expires_at",
        }
    )

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping) or set(payload) != self._FIELDS:
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        values = dict(payload)
        for field in (
            "request_id",
            "idempotency_key",
            "tenant_id",
            "node_id",
            "wallet_binding_id",
            "payment_capability_id",
            "wallet_identity_id",
            "spending_grant_id",
            "asset_allowance_id",
            "reservation_id",
            "action_id",
            "policy_decision_id",
            "purchase_id",
            "merchant_id",
        ):
            value = values[field]
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 256
                or any(ord(character) < 32 or ord(character) == 127 for character in value)
            ):
                raise CoreAuthorityRejected("Core preflight authority response is invalid")
        if (
            values["protocol_version"] != "clink-hosted-v1"
            or values["audience"] != "hosted-facilitator"
            or values["http_method"] != "POST"
            or values["http_path"] != "/v1/preflight"
            or values["payment_capability_version"] != "clink-payment-capability-v1"
        ):
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        chain = values["chain_id"]
        profile = HOSTED_CHAIN_PROFILES.get(chain) if isinstance(chain, str) else None
        if profile is None:
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        for field in (
            "request_hash",
            "payment_capability_hash",
            "spending_grant_hash",
            "reservation_hash",
            "policy_snapshot_hash",
            "risk_evidence_hash",
            "quote_hash",
            "payment_challenge_hash",
            "execution_scope_hash",
            "request_nonce",
        ):
            _bytes32(values[field], field=field)
        for field in ("wallet_address", "asset_contract", "pay_to", "executor_contract"):
            values[field] = _address(values[field], field=field)
        if values["asset_contract"] != profile.token:
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        amount = values["amount_atomic"]
        if (
            not isinstance(amount, str)
            or not amount
            or amount.startswith("0")
            or any(character not in "0123456789" for character in amount)
            or int(amount) > MAX_UINT256
        ):
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        for field in ("issued_at", "expires_at"):
            value = values[field]
            if type(value) is not int or value <= 0 or value > MAX_UINT256:
                raise CoreAuthorityRejected("Core preflight authority response is invalid")
        if values["expires_at"] <= values["issued_at"]:
            raise CoreAuthorityRejected("Core preflight authority response is invalid")
        self._values = values

    def __getitem__(self, field: str) -> Any:
        return self._values[field]

    def matches(self, expected: Mapping[str, Any]) -> bool:
        return all(self._values.get(field) == value for field, value in expected.items())


class CoreAuthorityResolver:
    """Resolve and verify execution scope through the Core HTTPS boundary."""

    def __init__(
        self,
        *,
        origin: str,
        internal_token: str,
        relayer_address: str,
        signer_epoch: int,
        environment: str = "production",
        client: Any | None = None,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = MAX_AUTHORITY_RESPONSE_BYTES,
        chain: str,
        token: str,
        chain_id: int,
    ) -> None:
        if environment not in {"production", "test"}:
            raise ValueError("Core authority environment is invalid")
        self._origin = _canonical_origin(origin, environment=environment)
        if not isinstance(internal_token, str) or not internal_token or len(internal_token) > 4096:
            raise ValueError("Core authority token is required")
        if any(ord(char) < 0x21 or ord(char) > 0x7E for char in internal_token):
            raise ValueError("Core authority token is invalid")
        self._internal_token = internal_token
        self._relayer_address = _address(relayer_address, field="relayer address")
        profile = HOSTED_CHAIN_PROFILES.get(chain)
        if profile is None or profile.chain_id != chain_id:
            raise ValueError("Core authority chain profile is invalid")
        if not isinstance(token, str) or token.lower() != profile.token:
            raise ValueError("Core authority token does not match chain profile")
        self._chain = profile.chain
        self._chain_id = profile.chain_id
        self._token = profile.token
        if type(signer_epoch) is not int or signer_epoch <= 0 or signer_epoch > MAX_UINT256:
            raise ValueError("signer epoch is invalid")
        self._signer_epoch = signer_epoch
        if type(timeout_seconds) not in {int, float} or isinstance(timeout_seconds, bool) or timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Core authority timeout is invalid")
        if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= MAX_AUTHORITY_RESPONSE_BYTES:
            raise ValueError("Core authority response limit is invalid")
        if client is None:
            if httpx is None:
                raise ValueError("Core authority HTTP client is unavailable")
            client = httpx.Client()
            self._owns_client = True
        else:
            self._owns_client = False
        if not callable(getattr(client, "post", None)):
            raise ValueError("Core authority HTTP client is invalid")
        self._client = client
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes

    @property
    def relayer_address(self) -> str:
        return self._relayer_address

    @property
    def signer_epoch(self) -> int:
        return self._signer_epoch

    @property
    def chain(self) -> str:
        return self._chain

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def token(self) -> str:
        return self._token

    def __repr__(self) -> str:
        return f"{type(self).__name__}(origin={self._origin!r}, signer_epoch={self._signer_epoch!r})"

    def close(self) -> None:
        if self._owns_client:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()

    def resolve(self, envelope: HostedPaymentEnvelope, node: Any) -> ExecutionIntent:
        if not isinstance(envelope, HostedPaymentEnvelope):
            raise CoreAuthorityRejected("payment envelope is invalid")
        if envelope.http_path != "/v1/executions":
            raise CoreAuthorityRejected("payment envelope scope is invalid")
        self._require_bound_scope(envelope.chain_id, envelope.asset_contract)
        if any(
            getattr(node, field, None) != getattr(envelope, field)
            for field in ("tenant_id", "node_id", "wallet_binding_id")
        ):
            raise CoreAuthorityRejected("payment scope is invalid")
        payload = self._payload_from_envelope(envelope)
        projection = self._post(envelope.reservation_id, payload)
        expected = {key: value for key, value in payload.items() if key != "payment_challenge_hash"}
        expected["payment_challenge_hash"] = envelope.payment_challenge_hash
        if not projection.matches(expected):
            raise CoreAuthorityRejected("Core authority scope changed")
        return projection.to_intent()

    def preflight(
        self, envelope: HostedPaymentEnvelope, node: Any
    ) -> CorePreflightProjection:
        if not isinstance(envelope, HostedPaymentEnvelope):
            raise CoreAuthorityRejected("payment envelope is invalid")
        if envelope.http_path != "/v1/preflight":
            raise CoreAuthorityRejected("payment envelope scope is invalid")
        self._require_bound_scope(envelope.chain_id, envelope.asset_contract)
        if any(
            getattr(node, field, None) != getattr(envelope, field)
            for field in ("tenant_id", "node_id", "wallet_binding_id")
        ):
            raise CoreAuthorityRejected("payment scope is invalid")
        payload = self._preflight_payload_from_envelope(envelope)
        projection = self._post(
            envelope.reservation_id,
            payload,
            endpoint="hosted-preflight-authority",
            projection_type=CorePreflightProjection,
        )
        if not projection.matches(payload):
            raise CoreAuthorityRejected("Core preflight authority scope changed")
        return projection

    def verify(self, intent: ExecutionIntent) -> None:
        if not isinstance(intent, ExecutionIntent):
            raise CoreAuthorityRejected("execution intent is invalid")
        if intent.relayer_address != self._relayer_address or intent.signer_epoch != self._signer_epoch:
            raise CoreAuthorityRejected("relayer authority scope is invalid")
        self._require_bound_scope(intent.chain, intent.token)
        payload = self._payload_from_intent(intent)
        projection = self._post(intent.reservation_id, payload)
        expected = {key: value for key, value in payload.items() if key != "payment_challenge_hash"}
        if not projection.matches(expected):
            raise CoreAuthorityRejected("Core authority scope changed")

    def _payload_from_envelope(self, envelope: HostedPaymentEnvelope) -> dict[str, Any]:
        owner_nonce = int(envelope.request_nonce, 16)
        authorization = ExecutionAuthorization(
            capability_hash=envelope.payment_capability_hash,
            reservation_hash=envelope.reservation_hash,
            owner=envelope.wallet_address,
            payee=envelope.pay_to,
            token=envelope.asset_contract,
            amount=int(envelope.amount_atomic),
            nonce=owner_nonce,
            deadline=envelope.expires_at,
            signer_epoch=self._signer_epoch,
            relayer=self._relayer_address,
            chain_id=self._chain_id,
        )
        return {
            "tenant_id": envelope.tenant_id,
            "node_id": envelope.node_id,
            "wallet_binding_id": envelope.wallet_binding_id,
            "capability_id": envelope.payment_capability_id,
            "capability_hash": envelope.payment_capability_hash,
            "reservation_id": envelope.reservation_id,
            "reservation_hash": envelope.reservation_hash,
            "purchase_id": envelope.purchase_id,
            "request_id": envelope.request_id,
            "request_hash": envelope.request_hash,
            "request_nonce": envelope.request_nonce,
            "idempotency_key": envelope.idempotency_key,
            "chain_id": envelope.chain_id,
            "owner": envelope.wallet_address,
            "payee": envelope.pay_to,
            "token": envelope.asset_contract,
            "amount_atomic": envelope.amount_atomic,
            "executor": envelope.executor_contract,
            "signer_epoch": self._signer_epoch,
            "deadline": envelope.expires_at,
            "execution_scope_hash": envelope.execution_scope_hash,
            "execution_digest": "0x" + hash_execution(
                authorization,
                envelope.executor_contract,
                chain_id=self._chain_id,
            ).hex(),
            "relayer_address": self._relayer_address,
            "payment_challenge_hash": envelope.payment_challenge_hash,
        }

    def _preflight_payload_from_envelope(
        self, envelope: HostedPaymentEnvelope
    ) -> dict[str, Any]:
        return {
            "protocol_version": envelope.protocol_version,
            "audience": envelope.audience,
            "http_method": envelope.http_method,
            "http_path": envelope.http_path,
            "request_id": envelope.request_id,
            "request_hash": envelope.request_hash,
            "idempotency_key": envelope.idempotency_key,
            "tenant_id": envelope.tenant_id,
            "node_id": envelope.node_id,
            "wallet_binding_id": envelope.wallet_binding_id,
            "payment_capability_version": envelope.payment_capability_version,
            "payment_capability_id": envelope.payment_capability_id,
            "payment_capability_hash": envelope.payment_capability_hash,
            "wallet_identity_id": envelope.wallet_identity_id,
            "wallet_address": envelope.wallet_address,
            "spending_grant_id": envelope.spending_grant_id,
            "spending_grant_hash": envelope.spending_grant_hash,
            "asset_allowance_id": envelope.asset_allowance_id,
            "reservation_id": envelope.reservation_id,
            "reservation_hash": envelope.reservation_hash,
            "action_id": envelope.action_id,
            "policy_decision_id": envelope.policy_decision_id,
            "policy_snapshot_hash": envelope.policy_snapshot_hash,
            "risk_evidence_hash": envelope.risk_evidence_hash,
            "purchase_id": envelope.purchase_id,
            "merchant_id": envelope.merchant_id,
            "quote_hash": envelope.quote_hash,
            "payment_challenge_hash": envelope.payment_challenge_hash,
            "chain_id": envelope.chain_id,
            "asset_contract": envelope.asset_contract,
            "amount_atomic": envelope.amount_atomic,
            "pay_to": envelope.pay_to,
            "executor_contract": envelope.executor_contract,
            "execution_scope_hash": envelope.execution_scope_hash,
            "request_nonce": envelope.request_nonce,
            "issued_at": envelope.issued_at,
            "expires_at": envelope.expires_at,
        }

    def _payload_from_intent(self, intent: ExecutionIntent) -> dict[str, Any]:
        authorization = ExecutionAuthorization(
            capability_hash=intent.capability_hash,
            reservation_hash=intent.reservation_hash,
            owner=intent.owner,
            payee=intent.payee,
            token=intent.token,
            amount=int(intent.amount_atomic),
            nonce=intent.owner_nonce,
            deadline=intent.deadline,
            signer_epoch=intent.signer_epoch,
            relayer=intent.relayer_address,
            chain_id=self._chain_id,
        )
        expected_digest = "0x" + hash_execution(
            authorization,
            intent.executor,
            chain_id=self._chain_id,
        ).hex()
        if intent.execution_digest != expected_digest:
            raise CoreAuthorityRejected("execution digest is invalid")
        return {
            "tenant_id": intent.tenant_id,
            "node_id": intent.node_id,
            "wallet_binding_id": intent.wallet_binding_id,
            "capability_id": intent.capability_id,
            "capability_hash": intent.capability_hash,
            "reservation_id": intent.reservation_id,
            "reservation_hash": intent.reservation_hash,
            "purchase_id": intent.purchase_id,
            "request_id": intent.request_id,
            "request_hash": intent.request_hash,
            "request_nonce": f"0x{intent.owner_nonce:064x}",
            "idempotency_key": intent.idempotency_key,
            "chain_id": intent.chain,
            "owner": intent.owner,
            "payee": intent.payee,
            "token": intent.token,
            "amount_atomic": intent.amount_atomic,
            "executor": intent.executor,
            "signer_epoch": intent.signer_epoch,
            "deadline": intent.deadline,
            "execution_scope_hash": intent.execution_scope_hash,
            "execution_digest": expected_digest,
            "relayer_address": intent.relayer_address,
            "payment_challenge_hash": None,
        }

    def _require_bound_scope(self, chain: str, token: str) -> None:
        if chain != self._chain or token.lower() != self._token:
            raise CoreAuthorityRejected("chain or token does not match configured Hosted instance")

    def _post(
        self,
        reservation_id: str,
        payload: dict[str, Any],
        *,
        endpoint: str = "hosted-authority",
        projection_type: type[CoreAuthorityProjection] = CoreAuthorityProjection,
    ) -> CoreAuthorityProjection | CorePreflightProjection:
        endpoint = (
            f"{self._origin}/funding/spending-reservations/{reservation_id}/{endpoint}"
        )
        try:
            response = self._client.post(
                endpoint,
                json=payload,
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                    "authorization": f"Bearer {self._internal_token}",
                },
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise CoreAuthorityUnavailable("Core authority is unavailable") from None
        if getattr(response, "status_code", None) in {401, 403, 409, 422}:
            raise CoreAuthorityRejected("Core authority rejected the execution scope")
        if getattr(response, "status_code", None) != 200:
            raise CoreAuthorityUnavailable("Core authority is unavailable")
        if getattr(response, "is_redirect", False):
            raise CoreAuthorityUnavailable("Core authority redirect is not allowed")
        headers = getattr(response, "headers", {})
        if isinstance(headers, Mapping):
            if headers.get("content-encoding", "identity").lower() != "identity":
                raise CoreAuthorityUnavailable("Core authority response encoding is invalid")
            if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise CoreAuthorityUnavailable("Core authority response type is invalid")
        else:
            raise CoreAuthorityUnavailable("Core authority response headers are invalid")
        raw = getattr(response, "content", None)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) > self._max_response_bytes:
            raise CoreAuthorityUnavailable("Core authority response is unavailable")
        try:
            payload_value = json.loads(
                bytes(raw).decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, TypeError, ValueError):
            raise CoreAuthorityUnavailable("Core authority response is unavailable") from None
        try:
            return projection_type(payload_value)
        except CoreAuthorityError:
            raise
        except Exception:
            raise CoreAuthorityUnavailable("Core authority response is unavailable") from None
