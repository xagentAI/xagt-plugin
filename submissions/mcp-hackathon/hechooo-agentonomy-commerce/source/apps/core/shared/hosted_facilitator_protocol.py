from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal, NamedTuple
from types import MappingProxyType
from urllib.parse import urlsplit, urlunsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from services.account_service.schemas import canonicalize_evm_address


HOSTED_PROTOCOL_VERSION = "clink-hosted-v1"
HOSTED_PAYMENT_AUDIENCE = "hosted-facilitator"
HOSTED_EXECUTION_AUDIENCE = HOSTED_PAYMENT_AUDIENCE
HOSTED_EXECUTION_ISSUER = "hosted-facilitator"
HOSTED_EXECUTION_CHAIN = "eip155:8453"
HOSTED_BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
HOSTED_POLYGON_USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
HOSTED_BASE_SEPOLIA_USDC = "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
HOSTED_POLYGON_AMOY_USDC = "0x41e94eb019c0762f9bfcf9fb1e58725bfb0e7582"


class HostedChainProfile(NamedTuple):
    """Immutable chain/token/finality policy shared by Hosted runtimes."""

    chain: str
    chain_id: int
    token: str
    finality_boundary: Literal["safe", "finalized"]
    min_confirmation_depth: int


HOSTED_CHAIN_PROFILES: Mapping[str, HostedChainProfile] = MappingProxyType(
    {
        "eip155:8453": HostedChainProfile(
            "eip155:8453",
            8453,
            HOSTED_BASE_USDC,
            "safe",
            2,
        ),
        "eip155:137": HostedChainProfile(
            "eip155:137",
            137,
            HOSTED_POLYGON_USDC,
            "finalized",
            3,
        ),
        "eip155:84532": HostedChainProfile(
            "eip155:84532",
            84532,
            HOSTED_BASE_SEPOLIA_USDC,
            "safe",
            2,
        ),
        "eip155:80002": HostedChainProfile(
            "eip155:80002",
            80002,
            HOSTED_POLYGON_AMOY_USDC,
            "finalized",
            3,
        ),
    }
)
HOSTED_CHAIN_PROFILES_BY_ID: Mapping[int, HostedChainProfile] = MappingProxyType(
    {profile.chain_id: profile for profile in HOSTED_CHAIN_PROFILES.values()}
)
HOSTED_CHAIN_IDS = frozenset(HOSTED_CHAIN_PROFILES_BY_ID)
HOSTED_PRODUCTION_CHAIN_IDS = frozenset({8453, 137})


def hosted_chain_profile(chain: str) -> HostedChainProfile:
    """Return the immutable profile for a CAIP-2 chain or reject it."""

    profile = HOSTED_CHAIN_PROFILES.get(chain)
    if profile is None:
        raise ValueError("chain_id is not an approved Hosted chain")
    return profile


def validate_hosted_chain_token(chain: str, token: str, *, field_name: str = "asset_contract") -> str:
    """Validate an exact canonical USDC contract for a supported chain."""

    profile = hosted_chain_profile(chain)
    if not isinstance(token, str) or token.lower() != profile.token:
        raise ValueError(f"{field_name} is not canonical USDC for chain")
    return token.lower()
MAX_PAYMENT_VALIDITY_SECONDS = 60
MAX_DPOP_AGE_SECONDS = 60
MAX_DPOP_FUTURE_SECONDS = 5
CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX = (1 << 53) - 1

_CANONICAL_ATOMIC_AMOUNT = re.compile(r"^[1-9][0-9]*$")
_CANONICAL_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_LOWERCASE_BYTES32 = re.compile(r"^0x[0-9a-f]{64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")
_HTTP_METHOD = re.compile(r"^[A-Z]+$")
_MAX_IDENTIFIER_LENGTH = 256
_MAX_COMPACT_JWS_LENGTH = 64 * 1024
_EXECUTION_RESPONSE_TYPE = "clink-execution-response+jwt"
_EXECUTION_FAILURE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ASCII_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
UNSIGNED_EXECUTION_EXPIRED = "UNSIGNED_EXECUTION_EXPIRED"


class HostedProtocolError(ValueError):
    """A bounded, secret-free hosted protocol failure."""


class _DuplicateJSONKey(ValueError):
    pass


def canonical_json_bytes(value) -> bytes:
    def validate_string(current: str, *, path: str) -> str:
        for index, character in enumerate(current):
            codepoint = ord(character)
            if (
                0xD800 <= codepoint <= 0xDFFF
                or 0xFDD0 <= codepoint <= 0xFDEF
                or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}
            ):
                raise ValueError(
                    f"canonical JSON does not allow Unicode noncharacter at "
                    f"{path}[{index}]"
                )
        return current

    def normalize(current: Any, *, path: str) -> Any:
        if current is None:
            return current
        if isinstance(current, str):
            return validate_string(current, path=path)
        if isinstance(current, bool):
            return current
        if type(current) is int:
            if abs(current) > CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX:
                raise ValueError(
                    f"canonical JSON integer exceeds safe integer range at {path}"
                )
            return current
        if isinstance(current, (float, Decimal)):
            raise ValueError(
                f"canonical JSON does not allow {type(current).__name__} at {path}"
            )
        if isinstance(current, Mapping):
            normalized: dict[str, Any] = {}
            for key, item in current.items():
                if not isinstance(key, str):
                    raise ValueError(
                        f"canonical JSON object keys must be strings at {path}"
                    )
                canonical_key = validate_string(key, path=f"{path}.<key>")
                normalized[canonical_key] = normalize(
                    item, path=f"{path}.{canonical_key}"
                )
            return normalized
        if isinstance(current, list):
            return [
                normalize(item, path=f"{path}[{index}]")
                for index, item in enumerate(current)
            ]
        raise ValueError(
            f"canonical JSON does not allow {type(current).__name__} at {path}"
        )

    return json.dumps(
        # The canonical profile is UTF-8 compact JSON with Python's Unicode
        # codepoint key ordering and I-JSON-safe integer values.
        normalize(value, path="$"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_identifier(value: bytes) -> str:
    return "0x" + hashlib.sha256(value).hexdigest()


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: object, *, expected_length: int | None = None) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or "=" in value
        or _BASE64URL.fullmatch(value) is None
    ):
        raise HostedProtocolError("public key is malformed")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise HostedProtocolError("public key is malformed") from exc
    if expected_length is not None and len(decoded) != expected_length:
        raise HostedProtocolError("public key is malformed")
    if _base64url_encode(decoded) != value:
        raise HostedProtocolError("public key is malformed")
    return decoded


def _constant_time_ascii_equal(left: object, right: str) -> bool:
    if not isinstance(left, str):
        return False
    try:
        return hmac.compare_digest(left.encode("ascii"), right.encode("ascii"))
    except UnicodeEncodeError:
        return False


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _decode_compact_json_segment(segment: str, *, label: str) -> dict[str, Any]:
    if not segment or _BASE64URL.fullmatch(segment) is None:
        raise HostedProtocolError(f"{label} is malformed")
    try:
        raw = base64.b64decode(
            segment + "=" * (-len(segment) % 4),
            altchars=b"-_",
            validate=True,
        )
        value = json.loads(raw, object_pairs_hook=_unique_json_object)
    except _DuplicateJSONKey as exc:
        raise HostedProtocolError(f"{label} contains a duplicate JSON member") from exc
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise HostedProtocolError(f"{label} is malformed") from exc
    if not isinstance(value, dict):
        raise HostedProtocolError(f"{label} is malformed")
    return value


def _inspect_compact_jws(token: object, *, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(token, str) or not token:
        raise HostedProtocolError(f"{label} is required")
    if len(token) > _MAX_COMPACT_JWS_LENGTH:
        raise HostedProtocolError(f"{label} is too large")
    parts = token.split(".")
    if len(parts) != 3:
        raise HostedProtocolError(f"{label} is malformed")
    return (
        _decode_compact_json_segment(parts[0], label=f"{label} header"),
        _decode_compact_json_segment(parts[1], label=f"{label} payload"),
    )


def _public_key_from_jwk(jwk_value: object) -> ec.EllipticCurvePublicKey:
    if not isinstance(jwk_value, dict) or set(jwk_value) != {"kty", "crv", "x", "y"}:
        raise HostedProtocolError("public key is malformed")
    if jwk_value.get("kty") != "EC" or jwk_value.get("crv") != "P-256":
        raise HostedProtocolError("public key is not a P-256 device key")
    x = _base64url_decode(jwk_value.get("x"), expected_length=32)
    y = _base64url_decode(jwk_value.get("y"), expected_length=32)
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(x, "big"),
            int.from_bytes(y, "big"),
            ec.SECP256R1(),
        ).public_key()
    except ValueError as exc:
        raise HostedProtocolError("public key is malformed") from exc


def _public_jwk(public_key: ec.EllipticCurvePublicKey) -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _base64url_encode(numbers.x.to_bytes(32, "big")),
        "y": _base64url_encode(numbers.y.to_bytes(32, "big")),
    }


def _jwk_thumbprint(jwk_value: object) -> str:
    public_key = _public_key_from_jwk(jwk_value)
    canonical_jwk = _public_jwk(public_key)
    return _base64url_encode(hashlib.sha256(canonical_json_bytes(canonical_jwk)).digest())


def _canonical_positive_atomic_amount(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or _CANONICAL_ATOMIC_AMOUNT.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be a positive canonical atomic integer string"
        )
    return value


class DeviceSigningKey:
    """A narrow wrapper around a local P-256 device key."""

    __slots__ = ("__private_key",)

    def __init__(self, private_key: ec.EllipticCurvePrivateKey) -> None:
        if not isinstance(private_key.curve, ec.SECP256R1):
            raise HostedProtocolError("private key is not a P-256 device key")
        self.__private_key = private_key

    @classmethod
    def generate(cls) -> "DeviceSigningKey":
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_pkcs8_der(cls, value: bytes) -> "DeviceSigningKey":
        if not isinstance(value, bytes) or not value:
            raise HostedProtocolError("private key is malformed")
        try:
            private_key = serialization.load_der_private_key(value, password=None)
        except (TypeError, ValueError) as exc:
            raise HostedProtocolError("private key is malformed") from exc
        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise HostedProtocolError("private key is not a P-256 device key")
        return cls(private_key)

    @property
    def pkcs8_der(self) -> bytes:
        return self.__private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @property
    def public_jwk(self) -> dict[str, str]:
        return _public_jwk(self.__private_key.public_key())

    @property
    def thumbprint(self) -> str:
        return _jwk_thumbprint(self.public_jwk)

    def _sign_jwt(self, payload: dict[str, Any], headers: dict[str, Any]) -> str:
        return jwt.encode(payload, self.__private_key, algorithm="ES256", headers=headers)


class HostedPaymentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["clink-hosted-v1"]
    audience: Literal["hosted-facilitator"]
    http_method: Literal["POST"]
    http_path: Literal["/v1/preflight", "/v1/executions"]
    request_id: str
    idempotency_key: str
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    payment_capability_version: Literal["clink-payment-capability-v1"]
    payment_capability_id: str
    payment_capability_hash: str
    wallet_identity_id: str
    wallet_address: str
    spending_grant_id: str
    spending_grant_hash: str
    asset_allowance_id: str
    reservation_id: str
    reservation_hash: str
    action_id: str
    policy_decision_id: str
    policy_snapshot_hash: str
    risk_evidence_hash: str
    purchase_id: str
    merchant_id: str
    quote_hash: str
    payment_challenge_hash: str
    chain_id: Literal["eip155:137", "eip155:8453", "eip155:84532", "eip155:80002"]
    asset_contract: str
    amount_atomic: str
    pay_to: str
    executor_contract: str
    execution_scope_hash: str
    request_nonce: str
    issued_at: int
    expires_at: int

    _canonical_addresses = field_validator(
        "wallet_address", "asset_contract", "pay_to", "executor_contract"
    )(canonicalize_evm_address)

    @field_validator(
        "audience",
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
        mode="before",
    )
    @classmethod
    def valid_identifier(cls, value, info) -> str:
        field_name = info.field_name
        if not isinstance(value, str) or not value or len(value) > _MAX_IDENTIFIER_LENGTH:
            raise ValueError(f"{field_name} must be a non-empty bounded string")
        if any(
            unicodedata.category(character).startswith("C")
            or unicodedata.category(character) in {"Zl", "Zp"}
            for character in value
        ):
            raise ValueError(f"{field_name} must not contain control characters")
        return value

    @field_validator("request_id", mode="before")
    @classmethod
    def reversible_request_id(cls, value) -> str:
        if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
            raise ValueError("request_id must be a reversible ASCII path segment")
        return value

    @field_validator("amount_atomic", mode="before")
    @classmethod
    def canonical_atomic_amount(cls, value) -> str:
        return _canonical_positive_atomic_amount(value, field_name="amount_atomic")

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def strict_timestamp(cls, value, info) -> int:
        if type(value) is not int:
            raise ValueError(f"{info.field_name} must be an integer timestamp")
        return value

    @field_validator(
        "spending_grant_hash",
        "policy_snapshot_hash",
        "risk_evidence_hash",
        "payment_capability_hash",
        "reservation_hash",
        "quote_hash",
        "payment_challenge_hash",
        "execution_scope_hash",
        "request_nonce",
        mode="before",
    )
    @classmethod
    def lowercase_bytes32(cls, value, info) -> str:
        if not isinstance(value, str) or _LOWERCASE_BYTES32.fullmatch(value) is None:
            raise ValueError(f"{info.field_name} must be 0x plus 64 lower-case hex characters")
        return value

    @model_validator(mode="after")
    def valid_validity_window(self) -> "HostedPaymentEnvelope":
        if self.issued_at <= 0 or self.expires_at <= 0:
            raise ValueError("payment timestamps must be positive")
        if self.expires_at <= self.issued_at:
            raise ValueError("payment validity window must end after it starts")
        if self.expires_at - self.issued_at > MAX_PAYMENT_VALIDITY_SECONDS:
            raise ValueError("payment validity window exceeds the maximum")
        validate_hosted_chain_token(self.chain_id, self.asset_contract)
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @property
    def request_hash(self) -> str:
        return sha256_identifier(self.canonical_bytes())


class HostedPreflightResponse(BaseModel):
    """The exact signed receipt shared by the Hosted client and service."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider_request_id: str
    request_id: str
    request_hash: str
    idempotency_key: str
    state: Literal["dry_run_accepted", "rejected"]
    chain_id: Literal["eip155:137", "eip155:8453", "eip155:84532", "eip155:80002"]
    asset_contract: str
    amount_atomic: str
    pay_to: str
    transaction_hash: str | None
    submitted_at: int | None
    confirmed_at: int | None
    server_key_id: str

    @field_validator(
        "provider_request_id",
        "request_id",
        "idempotency_key",
        "server_key_id",
        mode="before",
    )
    @classmethod
    def bounded_identifier(cls, value, info) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_IDENTIFIER_LENGTH
            or any(
                unicodedata.category(character).startswith("C")
                for character in value
            )
        ):
            raise ValueError(f"{info.field_name} must be a bounded identifier")
        return value

    @field_validator("request_hash", mode="before")
    @classmethod
    def canonical_request_hash(cls, value) -> str:
        if not isinstance(value, str) or _LOWERCASE_BYTES32.fullmatch(value) is None:
            raise ValueError("request_hash must be a canonical bytes32 value")
        return value

    @field_validator("asset_contract", "pay_to", mode="before")
    @classmethod
    def canonical_address(cls, value, info) -> str:
        if not isinstance(value, str) or _CANONICAL_ADDRESS.fullmatch(value) is None:
            raise ValueError(f"{info.field_name} must be a canonical EVM address")
        return value

    @field_validator("amount_atomic", mode="before")
    @classmethod
    def canonical_amount(cls, value) -> str:
        return _canonical_positive_atomic_amount(value, field_name="amount_atomic")

    @model_validator(mode="after")
    def valid_chain_token_pair(self) -> "HostedPreflightResponse":
        validate_hosted_chain_token(self.chain_id, self.asset_contract)
        return self

    @field_validator("transaction_hash", mode="before")
    @classmethod
    def canonical_transaction_hash(cls, value):
        if value is not None and (
            not isinstance(value, str) or _LOWERCASE_BYTES32.fullmatch(value) is None
        ):
            raise ValueError("transaction_hash must be null or a canonical bytes32 value")
        return value


class HostedRevertReleaseEvidence(BaseModel):
    """Strict proof that a finalized revert is safe to release."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    receipt_status: Literal[0]
    canonical_receipt: Literal[True]
    finality_boundary_timestamp: int
    capability_used: Literal[False]
    owner_nonce_used: Literal[False]
    payment_event_found: Literal[False]
    transfer_event_found: Literal[False]

    @field_validator("receipt_status", mode="before")
    @classmethod
    def exact_receipt_status_type(cls, value) -> int:
        if type(value) is not int:
            raise ValueError("receipt_status must be the integer zero")
        return value

    @field_validator(
        "canonical_receipt",
        "capability_used",
        "owner_nonce_used",
        "payment_event_found",
        "transfer_event_found",
        mode="before",
    )
    @classmethod
    def exact_boolean_type(cls, value, info) -> bool:
        if type(value) is not bool:
            raise ValueError(f"{info.field_name} must be a boolean")
        return value

    @field_validator("finality_boundary_timestamp", mode="before")
    @classmethod
    def positive_ijson_integer(cls, value) -> int:
        if (
            type(value) is not int
            or value <= 0
            or value > CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX
        ):
            raise ValueError(
                "finality_boundary_timestamp must be a positive I-JSON integer"
            )
        return value


class HostedExecutionResponse(BaseModel):
    """The immutable, signed status projection for one Hosted execution."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    protocol_version: Literal["clink-hosted-v1"] = HOSTED_PROTOCOL_VERSION
    http_path: Literal["/v1/executions"] = "/v1/executions"
    audience: Literal["hosted-facilitator"] = HOSTED_EXECUTION_AUDIENCE
    issuer: Literal["hosted-facilitator"] = HOSTED_EXECUTION_ISSUER
    chain_id: Literal["eip155:137", "eip155:8453", "eip155:84532", "eip155:80002"]

    request_id: str
    request_hash: str
    idempotency_key: str
    execution_id: str
    capability_id: str
    capability_hash: str
    reservation_id: str
    reservation_hash: str
    purchase_id: str
    execution_scope_hash: str
    owner: str
    payee: str
    token: str
    amount_atomic: str
    executor: str
    signer_epoch: int
    owner_nonce: str
    deadline: int

    state: Literal[
        "preparing",
        "submitted",
        "submission_unknown",
        "submission_rejected",
        "confirmed",
        "finalized",
        "reverted",
        "released",
        "expired",
        "reorg_review",
        "rejected",
    ]
    transaction_hash: str | None
    receipt_block_hash: str | None
    receipt_block_number: int | None
    safe_block_hash: str | None
    safe_block_number: int | None
    confirmations: int
    failure_reason_code: str | None

    issued_at: int
    submitted_at: int | None
    confirmed_at: int | None
    finalized_at: int | None
    reverted_at: int | None
    reorg_reviewed_at: int | None
    released_at: int | None
    expired_at: int | None
    server_key_id: str
    watcher_version: str | None = None
    finality_boundary: Literal["safe", "finalized"] | None = None
    release_evidence: HostedRevertReleaseEvidence | None = None

    @field_validator(
        "request_id",
        "idempotency_key",
        "execution_id",
        "capability_id",
        "reservation_id",
        "purchase_id",
        mode="before",
    )
    @classmethod
    def bounded_ascii_identifier(cls, value, info) -> str:
        if not isinstance(value, str) or _ASCII_IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{info.field_name} must be a bounded ASCII identifier")
        return value

    @field_validator("server_key_id", mode="before")
    @classmethod
    def bounded_server_key_id(cls, value) -> str:
        if (
            not isinstance(value, str)
            or not value
            or len(value) > _MAX_IDENTIFIER_LENGTH
            or _BASE64URL.fullmatch(value) is None
        ):
            raise ValueError("server_key_id must be a bounded ASCII identifier")
        return value

    @field_validator("watcher_version", mode="before")
    @classmethod
    def bounded_watcher_version(cls, value) -> str | None:
        if value is not None and (
            not isinstance(value, str)
            or not value
            or len(value) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("watcher_version must be a bounded public identifier or null")
        return value

    @field_validator(
        "request_hash",
        "capability_hash",
        "reservation_hash",
        "execution_scope_hash",
        "owner_nonce",
        "transaction_hash",
        "receipt_block_hash",
        "safe_block_hash",
        mode="before",
    )
    @classmethod
    def canonical_bytes32(cls, value, info):
        if value is not None and (
            not isinstance(value, str) or _LOWERCASE_BYTES32.fullmatch(value) is None
        ):
            raise ValueError(
                f"{info.field_name} must be null or canonical lower-case bytes32"
            )
        return value

    @field_validator("owner", "payee", "token", "executor", mode="before")
    @classmethod
    def canonical_address(cls, value, info) -> str:
        if not isinstance(value, str) or _CANONICAL_ADDRESS.fullmatch(value) is None:
            raise ValueError(f"{info.field_name} must be a canonical EVM address")
        return value

    @field_validator("amount_atomic", mode="before")
    @classmethod
    def canonical_amount(cls, value) -> str:
        return _canonical_positive_atomic_amount(value, field_name="amount_atomic")

    @field_validator("signer_epoch", "issued_at", "deadline", mode="before")
    @classmethod
    def positive_ijson_integer(cls, value, info) -> int:
        if (
            type(value) is not int
            or value <= 0
            or value > CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX
        ):
            raise ValueError(f"{info.field_name} must be a positive I-JSON integer")
        return value

    @field_validator(
        "receipt_block_number",
        "safe_block_number",
        "confirmations",
        "submitted_at",
        "confirmed_at",
        "finalized_at",
        "reverted_at",
        "reorg_reviewed_at",
        "released_at",
        "expired_at",
        mode="before",
    )
    @classmethod
    def optional_ijson_integer(cls, value, info):
        if value is not None and (
            type(value) is not int
            or value < 0
            or value > CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX
        ):
            raise ValueError(f"{info.field_name} must be an I-JSON integer or null")
        return value

    @field_validator("failure_reason_code", mode="before")
    @classmethod
    def bounded_failure_code(cls, value):
        if value is not None and (
            not isinstance(value, str) or _EXECUTION_FAILURE_CODE.fullmatch(value) is None
        ):
            raise ValueError("failure_reason_code must be a bounded machine code or null")
        return value

    @model_validator(mode="after")
    def valid_execution_state(self) -> "HostedExecutionResponse":
        profile = hosted_chain_profile(self.chain_id)
        if (
            self.failure_reason_code == UNSIGNED_EXECUTION_EXPIRED
            and self.state != "expired"
        ):
            raise ValueError(
                "unsigned expiry attestation is only valid for expired execution"
            )
        if self.state != "released" and self.release_evidence is not None:
            raise ValueError("release_evidence is only valid for released execution")
        if (
            self.state == "expired"
            and self.failure_reason_code == UNSIGNED_EXECUTION_EXPIRED
        ):
            if self.expired_at is None:
                raise ValueError(
                    "unsigned expiry attestation requires expired_at"
                )
            if self.expired_at < self.deadline:
                raise ValueError(
                    "unsigned expiry attestation expired_at precedes deadline"
                )
            if (
                self.released_at is not None
                and self.released_at != self.expired_at
            ):
                raise ValueError(
                    "unsigned expiry attestation released_at must equal expired_at"
                )
            for field_name, value in (
                ("transaction_hash", self.transaction_hash),
                ("submitted_at", self.submitted_at),
                ("receipt_block_hash", self.receipt_block_hash),
                ("receipt_block_number", self.receipt_block_number),
                ("safe_block_hash", self.safe_block_hash),
                ("safe_block_number", self.safe_block_number),
                ("confirmations", self.confirmations),
                ("confirmed_at", self.confirmed_at),
                ("finalized_at", self.finalized_at),
                ("reverted_at", self.reverted_at),
                ("reorg_reviewed_at", self.reorg_reviewed_at),
                ("watcher_version", self.watcher_version),
                ("finality_boundary", self.finality_boundary),
                ("release_evidence", self.release_evidence),
            ):
                if value is not None and not (
                    field_name == "confirmations" and value == 0
                ):
                    raise ValueError(
                        "unsigned expiry attestation contains " + field_name
                    )
        if self.token != profile.token:
            raise ValueError("token is not canonical USDC for chain")
        if self.finality_boundary is not None and self.finality_boundary != profile.finality_boundary:
            raise ValueError("finality boundary does not match chain")
        if self.safe_block_number is None:
            if self.safe_block_hash is not None:
                raise ValueError("safe block identity is incomplete")
        elif self.safe_block_hash is None:
            raise ValueError("safe block identity is incomplete")
        if (
            self.receipt_block_number is None
            and self.receipt_block_hash is not None
        ) or (
            self.receipt_block_number is not None
            and self.receipt_block_hash is None
        ):
            raise ValueError("receipt block identity is incomplete")
        if (
            self.safe_block_number is not None
            and self.receipt_block_number is not None
            and self.safe_block_number < self.receipt_block_number
        ):
            raise ValueError("safe block precedes receipt block")

        previous_time = self.issued_at
        for timestamp in (
            self.submitted_at,
            self.confirmed_at,
            self.finalized_at,
            self.reverted_at,
            self.reorg_reviewed_at,
            self.released_at,
            self.expired_at,
        ):
            if timestamp is not None and timestamp < previous_time:
                raise ValueError("execution timestamps are not ordered")
            if timestamp is not None:
                previous_time = timestamp

        receipt_states = {"confirmed", "finalized", "reverted", "reorg_review"}
        failure_states = {
            "submission_rejected",
            "reverted",
            "released",
            "expired",
            "reorg_review",
            "rejected",
        }
        if self.state in {"confirmed", "finalized", "reverted", "released", "reorg_review"}:
            if self.watcher_version is None:
                raise ValueError("watcher-derived execution requires watcher_version")
        if self.state in {"confirmed", "finalized", "reverted", "released", "reorg_review"}:
            if self.finality_boundary != profile.finality_boundary:
                raise ValueError("watcher-derived execution requires finality_boundary")
        if self.state == "preparing":
            if (
                self.transaction_hash is not None
                or self.receipt_block_hash is not None
                or self.receipt_block_number is not None
                or self.safe_block_hash is not None
                or self.safe_block_number is not None
                or self.confirmations != 0
                or self.submitted_at is not None
                or self.confirmed_at is not None
                or self.finalized_at is not None
                or self.reverted_at is not None
                or self.reorg_reviewed_at is not None
                or self.released_at is not None
                or self.expired_at is not None
                or self.failure_reason_code is not None
            ):
                raise ValueError("preparing execution cannot contain outcome evidence")
            return self
        if self.state == "rejected":
            if (
                self.transaction_hash is not None
                or self.receipt_block_hash is not None
                or self.receipt_block_number is not None
                or self.safe_block_hash is not None
                or self.safe_block_number is not None
                or self.confirmations != 0
                or self.submitted_at is not None
                or self.confirmed_at is not None
                or self.finalized_at is not None
                or self.reverted_at is not None
                or self.reorg_reviewed_at is not None
                or self.released_at is not None
                or self.expired_at is not None
            ):
                raise ValueError("rejected execution cannot contain chain evidence")
            if self.failure_reason_code is None:
                raise ValueError("rejected execution requires a failure reason code")
            return self

        if self.state == "expired":
            if (
                self.transaction_hash is not None
                or self.submitted_at is not None
                or self.receipt_block_hash is not None
                or self.receipt_block_number is not None
                or self.safe_block_hash is not None
                or self.safe_block_number is not None
                or self.confirmations != 0
                or self.expired_at is None
            ):
                raise ValueError("expired execution contains chain evidence")
            if self.failure_reason_code is None:
                raise ValueError("expired execution requires a failure reason code")
            return self

        if self.transaction_hash is None:
            raise ValueError("non-rejected execution requires a transaction hash")
        if self.submitted_at is None:
            raise ValueError("execution requires submitted_at")
        if self.state in {"submitted", "submission_unknown", "submission_rejected"}:
            if self.submitted_at is None:
                raise ValueError("submitted execution requires submitted_at")
            if (
                self.receipt_block_hash is not None
                or self.receipt_block_number is not None
                or self.safe_block_hash is not None
                or self.safe_block_number is not None
                or self.confirmations != 0
                or self.confirmed_at is not None
                or self.finalized_at is not None
                or self.reverted_at is not None
                or self.reorg_reviewed_at is not None
                or self.released_at is not None
                or self.expired_at is not None
            ):
                raise ValueError("submitted execution contains premature chain evidence")
        if self.state == "submission_rejected" and self.failure_reason_code is None:
            raise ValueError("submission rejection requires a failure reason code")
        if self.state == "released":
            if (
                self.released_at is None
                or self.reverted_at is None
                or self.failure_reason_code is None
            ):
                raise ValueError("released execution requires release evidence")
            if self.release_evidence is None:
                raise ValueError("released execution requires release evidence")
            if self.receipt_block_hash is None or self.receipt_block_number is None:
                raise ValueError("released execution requires receipt block identity")
            if self.safe_block_hash is None or self.safe_block_number is None:
                raise ValueError("released execution requires safe block identity")
            if self.confirmations < profile.min_confirmation_depth:
                raise ValueError(
                    "released execution does not satisfy the chain confirmation depth"
                )
            if self.release_evidence.finality_boundary_timestamp < self.deadline:
                raise ValueError(
                    "released execution finality boundary precedes authorization deadline"
                )
            if self.release_evidence.finality_boundary_timestamp > self.released_at:
                raise ValueError(
                    "released execution precedes its finality boundary"
                )
        if self.state in receipt_states and (
            self.receipt_block_hash is None or self.receipt_block_number is None
        ):
            raise ValueError("receipt state requires receipt block identity")
        if self.state in {"confirmed", "finalized"} and self.confirmed_at is None:
            raise ValueError("confirmed execution requires confirmed_at")
        if self.state == "confirmed" and self.confirmations < 1:
            raise ValueError("confirmed execution requires a confirmation")
        if self.state == "finalized":
            if self.finalized_at is None:
                raise ValueError("finalized execution requires finalized_at")
            if self.safe_block_hash is None or self.safe_block_number is None:
                raise ValueError("finalized execution requires safe block identity")
            if self.confirmations < profile.min_confirmation_depth:
                raise ValueError(
                    "finalized execution does not satisfy the chain confirmation depth"
                )
        if self.state == "reverted":
            if self.reverted_at is None:
                raise ValueError("reverted execution requires reverted_at")
            if self.safe_block_hash is None or self.safe_block_number is None:
                raise ValueError("reverted execution requires safe block identity")
            if self.confirmations < profile.min_confirmation_depth:
                raise ValueError(
                    "reverted execution does not satisfy the chain confirmation depth"
                )
        if self.state == "reorg_review" and self.reorg_reviewed_at is None:
            raise ValueError("reorg review requires reorg_reviewed_at")
        if self.state in {"submitted", "submission_unknown", "confirmed", "finalized"}:
            if self.failure_reason_code is not None:
                raise ValueError("successful execution cannot contain a failure reason")
        if self.state in failure_states and self.failure_reason_code is None:
            raise ValueError("failed execution requires a failure reason code")
        return self


def validate_payment_window(envelope: HostedPaymentEnvelope, now: int) -> None:
    if envelope.issued_at > now:
        raise ValueError("payment envelope is from the future")
    if envelope.expires_at <= now:
        raise ValueError("payment envelope has expired")


class DPoPClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    htu: str
    htm: str
    iat: int
    jti: str
    ath: str

    @field_validator("htu")
    @classmethod
    def canonical_htu(cls, value: str) -> str:
        if _normalize_htu(value) != value:
            raise ValueError("htu must be an exact normalized URI")
        return value

    @field_validator("htm")
    @classmethod
    def uppercase_method(cls, value: str) -> str:
        if _HTTP_METHOD.fullmatch(value) is None:
            raise ValueError("htm must be an uppercase HTTP method")
        return value

    @field_validator("jti")
    @classmethod
    def bounded_jti(cls, value: str) -> str:
        if (
            not value
            or len(value) > _MAX_IDENTIFIER_LENGTH
            or any(unicodedata.category(character).startswith("C") for character in value)
        ):
            raise ValueError("jti must be a non-empty bounded identifier")
        return value

    @field_validator("ath")
    @classmethod
    def token_hash(cls, value: str) -> str:
        if len(value) != 43 or _BASE64URL.fullmatch(value) is None:
            raise ValueError("ath must be a SHA-256 base64url value")
        return value


def _normalize_htu(url: object) -> str:
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise HostedProtocolError("DPoP request URI is invalid")
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise HostedProtocolError("DPoP request URI is invalid") from exc
    if (
        scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise HostedProtocolError("DPoP request URI is invalid")
    try:
        canonical_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise HostedProtocolError("DPoP request URI is invalid") from exc
    is_loopback = canonical_host == "localhost"
    if not is_loopback:
        try:
            parsed_ip = ipaddress.ip_address(canonical_host)
        except ValueError:
            parsed_ip = None
        is_loopback = (
            isinstance(parsed_ip, ipaddress.IPv4Address)
            and parsed_ip in ipaddress.ip_network("127.0.0.0/8")
        ) or parsed_ip == ipaddress.IPv6Address("::1")
    if scheme == "http" and not is_loopback:
        raise HostedProtocolError(
            "DPoP request URI must use HTTPS outside explicit loopback"
        )
    if ":" in canonical_host:
        canonical_host = f"[{canonical_host}]"
    if port is not None and not (
        (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    ):
        canonical_host = f"{canonical_host}:{port}"
    return urlunsplit((scheme, canonical_host, parsed.path or "/", "", ""))


def _access_token_hash(access_token: object) -> str:
    if not isinstance(access_token, str) or not access_token:
        raise HostedProtocolError("DPoP access token is required")
    return _base64url_encode(hashlib.sha256(access_token.encode("utf-8")).digest())


def _verify_es256_signature(
    token: str,
    public_key: ec.EllipticCurvePublicKey,
    *,
    label: str,
) -> None:
    try:
        jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            options={
                "verify_aud": False,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except jwt.InvalidTokenError as exc:
        raise HostedProtocolError(f"{label} signature verification failed") from exc


def sign_payment_envelope(key: DeviceSigningKey, envelope: HostedPaymentEnvelope) -> str:
    if not isinstance(key, DeviceSigningKey):
        raise HostedProtocolError("payment device key is invalid")
    if not isinstance(envelope, HostedPaymentEnvelope):
        raise HostedProtocolError("payment envelope is invalid")
    return key._sign_jwt(
        envelope.model_dump(mode="json"),
        {
            "alg": "ES256",
            "typ": "clink-payment+jwt",
            "kid": key.thumbprint,
        },
    )


def sign_preflight_response(
    key: DeviceSigningKey,
    response: HostedPreflightResponse,
) -> str:
    if not isinstance(key, DeviceSigningKey):
        raise HostedProtocolError("response signing key is invalid")
    if not isinstance(response, HostedPreflightResponse):
        raise HostedProtocolError("preflight response is invalid")
    if response.server_key_id != key.thumbprint:
        raise HostedProtocolError("preflight response key ID does not match")
    return key._sign_jwt(
        response.model_dump(mode="json"),
        {
            "alg": "ES256",
            "typ": "clink-response+jwt",
            "kid": key.thumbprint,
        },
    )


def verify_preflight_response(
    token: str,
    trusted_public_jwk: object,
    expected_envelope: HostedPaymentEnvelope,
) -> HostedPreflightResponse:
    if not isinstance(expected_envelope, HostedPaymentEnvelope):
        raise HostedProtocolError("expected payment envelope is invalid")
    header, payload = _inspect_compact_jws(token, label="response JWS")
    if (
        header.get("alg") != "ES256"
        or header.get("typ") != "clink-response+jwt"
        or set(header) != {"alg", "typ", "kid"}
    ):
        raise HostedProtocolError("response JWS header is invalid")

    public_key = _public_key_from_jwk(trusted_public_jwk)
    trusted_thumbprint = _jwk_thumbprint(trusted_public_jwk)
    if not _constant_time_ascii_equal(header.get("kid"), trusted_thumbprint):
        raise HostedProtocolError("response server key does not match trusted key")
    _verify_es256_signature(token, public_key, label="response")

    try:
        response = HostedPreflightResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise HostedProtocolError("response payload is invalid") from exc
    if response.state != "dry_run_accepted":
        raise HostedProtocolError("preflight response is not dry_run_accepted")
    if response.server_key_id != trusted_thumbprint:
        raise HostedProtocolError("response server key ID does not match trusted key")
    if (
        response.transaction_hash is not None
        or response.submitted_at is not None
        or response.confirmed_at is not None
    ):
        raise HostedProtocolError("response contains execution data in verification mode")
    expected_fields = (
        "request_id",
        "request_hash",
        "idempotency_key",
        "chain_id",
        "asset_contract",
        "amount_atomic",
        "pay_to",
    )
    for field_name in expected_fields:
        if getattr(response, field_name) != getattr(expected_envelope, field_name, None):
            raise HostedProtocolError(
                f"response {field_name} does not match expected payment envelope"
            )
    return response


def sign_execution_response(
    key: DeviceSigningKey,
    response: HostedExecutionResponse,
) -> str:
    if not isinstance(key, DeviceSigningKey):
        raise HostedProtocolError("response signing key is invalid")
    if not isinstance(response, HostedExecutionResponse):
        raise HostedProtocolError("execution response is invalid")
    if response.server_key_id != key.thumbprint:
        raise HostedProtocolError("execution response key ID does not match")
    return key._sign_jwt(
        response.model_dump(mode="json"),
        {
            "alg": "ES256",
            "typ": _EXECUTION_RESPONSE_TYPE,
            "kid": key.thumbprint,
        },
    )


def verify_execution_response(
    token: str,
    trusted_public_jwk: object,
    expected_envelope: HostedPaymentEnvelope,
    now: int | None = None,
    expected_execution_id: str | None = None,
) -> HostedExecutionResponse:
    if not isinstance(expected_envelope, HostedPaymentEnvelope):
        raise HostedProtocolError("expected payment envelope is invalid")
    if (
        expected_envelope.http_method != "POST"
        or expected_envelope.http_path != "/v1/executions"
    ):
        raise HostedProtocolError("execution response route does not match expected envelope")
    try:
        expected_profile = hosted_chain_profile(expected_envelope.chain_id)
    except ValueError as exc:
        raise HostedProtocolError("execution response chain is not supported") from exc
    if expected_envelope.audience != HOSTED_EXECUTION_AUDIENCE:
        raise HostedProtocolError("execution response audience is invalid")
    if expected_envelope.asset_contract != expected_profile.token:
        raise HostedProtocolError("execution response token does not match chain")
    header, payload = _inspect_compact_jws(token, label="execution response JWS")
    if (
        header.get("alg") != "ES256"
        or header.get("typ") != _EXECUTION_RESPONSE_TYPE
        or set(header) != {"alg", "typ", "kid"}
    ):
        raise HostedProtocolError("execution response JWS header is invalid")

    public_key = _public_key_from_jwk(trusted_public_jwk)
    trusted_thumbprint = _jwk_thumbprint(trusted_public_jwk)
    if not _constant_time_ascii_equal(header.get("kid"), trusted_thumbprint):
        raise HostedProtocolError("execution response server key does not match trusted key")
    _verify_es256_signature(token, public_key, label="execution response")

    try:
        response = HostedExecutionResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise HostedProtocolError("execution response payload is invalid") from exc
    if response.server_key_id != trusted_thumbprint:
        raise HostedProtocolError("execution response server key ID does not match trusted key")
    if response.audience != expected_envelope.audience:
        raise HostedProtocolError("execution response audience does not match expected envelope")
    if response.issuer != HOSTED_EXECUTION_ISSUER:
        raise HostedProtocolError("execution response issuer is invalid")
    if response.http_path != expected_envelope.http_path:
        raise HostedProtocolError("execution response route does not match expected envelope")
    if expected_execution_id is not None:
        if (
            not isinstance(expected_execution_id, str)
            or _ASCII_IDENTIFIER.fullmatch(expected_execution_id) is None
        ):
            raise HostedProtocolError("expected execution ID is invalid")
        if response.execution_id != expected_execution_id:
            raise HostedProtocolError("execution response execution ID does not match")

    expected_fields = (
        ("request_id", "request_id"),
        ("request_hash", "request_hash"),
        ("idempotency_key", "idempotency_key"),
        ("capability_id", "payment_capability_id"),
        ("capability_hash", "payment_capability_hash"),
        ("reservation_id", "reservation_id"),
        ("reservation_hash", "reservation_hash"),
        ("purchase_id", "purchase_id"),
        ("execution_scope_hash", "execution_scope_hash"),
        ("owner", "wallet_address"),
        ("payee", "pay_to"),
        ("token", "asset_contract"),
        ("amount_atomic", "amount_atomic"),
        ("executor", "executor_contract"),
        ("owner_nonce", "request_nonce"),
        ("deadline", "expires_at"),
        ("chain_id", "chain_id"),
    )
    for response_field, envelope_field in expected_fields:
        if getattr(response, response_field) != getattr(expected_envelope, envelope_field):
            raise HostedProtocolError(
                f"execution response {response_field} does not match expected payment envelope"
            )

    if response.finality_boundary is not None and response.finality_boundary != expected_profile.finality_boundary:
        raise HostedProtocolError("execution response finality boundary does not match chain")

    if response.issued_at < expected_envelope.issued_at:
        raise HostedProtocolError("execution response time precedes expected envelope")
    if response.issued_at > expected_envelope.expires_at:
        raise HostedProtocolError("execution response time exceeds expected envelope window")
    if now is not None:
        if type(now) is not int or now < 0 or now > CANONICAL_JSON_IJSON_SAFE_INTEGER_MAX:
            raise HostedProtocolError("execution response verification time is invalid")
        for timestamp in (
            response.issued_at,
            response.submitted_at,
            response.confirmed_at,
            response.finalized_at,
            response.reverted_at,
            response.reorg_reviewed_at,
            response.released_at,
            response.expired_at,
            (
                response.release_evidence.finality_boundary_timestamp
                if response.release_evidence is not None
                else None
            ),
        ):
            if timestamp is not None and timestamp > now:
                raise HostedProtocolError("execution response time is from the future")
    return response


def verify_payment_envelope(
    token: str,
    trusted_public_jwk: object,
    now: int,
) -> HostedPaymentEnvelope:
    header, payload = _inspect_compact_jws(token, label="payment JWS")
    if header.get("alg") != "ES256":
        raise HostedProtocolError("payment JWS algorithm is not allowed")
    if header.get("typ") != "clink-payment+jwt":
        raise HostedProtocolError("payment JWS type is not allowed")
    if set(header) != {"alg", "typ", "kid"} or not isinstance(header.get("kid"), str):
        raise HostedProtocolError("payment JWS header is invalid")

    public_key = _public_key_from_jwk(trusted_public_jwk)
    trusted_thumbprint = _jwk_thumbprint(trusted_public_jwk)
    _verify_es256_signature(token, public_key, label="payment")
    if not _constant_time_ascii_equal(header["kid"], trusted_thumbprint):
        raise HostedProtocolError("payment device key does not match the trusted public key")

    try:
        envelope = HostedPaymentEnvelope.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise HostedProtocolError("payment payload is invalid") from exc
    if envelope.audience != HOSTED_PAYMENT_AUDIENCE:
        raise HostedProtocolError("payment audience is invalid")
    try:
        validate_payment_window(envelope, now)
    except ValueError as exc:
        if envelope.expires_at <= now:
            raise HostedProtocolError("payment envelope has expired") from exc
        raise HostedProtocolError("payment envelope is from the future") from exc
    return envelope


def build_dpop_proof(
    key: DeviceSigningKey,
    *,
    method: str,
    url: str,
    access_token: str,
    now: int,
    jti: str | None = None,
) -> str:
    if not isinstance(key, DeviceSigningKey):
        raise HostedProtocolError("DPoP device key is invalid")
    if not isinstance(now, int) or isinstance(now, bool):
        raise HostedProtocolError("DPoP issued-at time is invalid")
    normalized_url = _normalize_htu(url)
    normalized_method = method.upper() if isinstance(method, str) else ""
    if _HTTP_METHOD.fullmatch(normalized_method) is None:
        raise HostedProtocolError("DPoP request method is invalid")
    claims = DPoPClaims(
        htu=normalized_url,
        htm=normalized_method,
        iat=now,
        jti=jti if jti is not None else secrets.token_urlsafe(24),
        ath=_access_token_hash(access_token),
    )
    return key._sign_jwt(
        claims.model_dump(mode="json"),
        {"alg": "ES256", "typ": "dpop+jwt", "jwk": key.public_jwk},
    )


def verify_dpop_proof(
    proof: str,
    *,
    trusted_public_jwk: object,
    method: str,
    url: str,
    access_token: str,
    now: int,
) -> DPoPClaims:
    header, payload = _inspect_compact_jws(proof, label="DPoP proof")
    if header.get("alg") != "ES256":
        raise HostedProtocolError("DPoP algorithm is not allowed")
    if header.get("typ") != "dpop+jwt":
        raise HostedProtocolError("DPoP type is not allowed")
    if set(header) != {"alg", "typ", "jwk"}:
        raise HostedProtocolError("DPoP header is invalid")

    presented_jwk = header.get("jwk")
    presented_thumbprint = _jwk_thumbprint(presented_jwk)
    trusted_key = _public_key_from_jwk(trusted_public_jwk)
    trusted_thumbprint = _jwk_thumbprint(trusted_public_jwk)
    if not _constant_time_ascii_equal(presented_thumbprint, trusted_thumbprint):
        raise HostedProtocolError("DPoP device key does not match the trusted device key")
    _verify_es256_signature(proof, trusted_key, label="DPoP")

    if "jti" not in payload:
        raise HostedProtocolError("DPoP jti is required")
    try:
        claims = DPoPClaims.model_validate(payload)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False)
        if any(error.get("loc") == ("jti",) for error in errors):
            raise HostedProtocolError("DPoP jti is invalid") from exc
        if any(error.get("loc") == ("ath",) for error in errors):
            raise HostedProtocolError("DPoP access token hash is invalid") from exc
        raise HostedProtocolError("DPoP claims are invalid") from exc

    expected_url = _normalize_htu(url)
    if claims.htu != expected_url:
        raise HostedProtocolError("DPoP request URI does not match")
    expected_method = method.upper() if isinstance(method, str) else ""
    if _HTTP_METHOD.fullmatch(expected_method) is None:
        raise HostedProtocolError("DPoP request method is invalid")
    if claims.htm != expected_method:
        raise HostedProtocolError("DPoP request method does not match")
    if not _constant_time_ascii_equal(claims.ath, _access_token_hash(access_token)):
        raise HostedProtocolError("DPoP access token hash does not match")
    if not isinstance(now, int) or isinstance(now, bool):
        raise HostedProtocolError("DPoP verification time is invalid")
    if claims.iat > now + MAX_DPOP_FUTURE_SECONDS:
        raise HostedProtocolError("DPoP proof is from the future")
    if claims.iat < now - MAX_DPOP_AGE_SECONDS:
        raise HostedProtocolError("DPoP proof is too old")
    return claims
