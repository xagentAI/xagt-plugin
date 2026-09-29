from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from shared.hosted_facilitator_protocol import (
    HostedExecutionResponse,
    HostedPreflightResponse,
    HostedProtocolError,
    _jwk_thumbprint,
)


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_BYTES32 = re.compile(r"^0x[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_SIGNED_RESPONSE_BYTES = 64 * 1024


def validate_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def validate_digest(value: object, *, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{field_name} is invalid")
    return value


def validate_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _BYTES32.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class EnrollmentTokenRecord:
    tenant_id: str
    token_digest: bytes
    expires_at: int
    consumed_at: int | None = None
    enrolled_node_id: str | None = None
    enrollment_binding_digest: bytes | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.tenant_id, field_name="tenant_id")
        validate_digest(self.token_digest, field_name="token_digest")
        if type(self.expires_at) is not int or self.expires_at <= 0:
            raise ValueError("expires_at is invalid")
        if self.consumed_at is not None and (
            type(self.consumed_at) is not int or self.consumed_at <= 0
        ):
            raise ValueError("consumed_at is invalid")
        if (self.enrolled_node_id is None) != (
            self.enrollment_binding_digest is None
        ):
            raise ValueError("enrollment binding is incomplete")
        if self.enrolled_node_id is not None:
            validate_identifier(self.enrolled_node_id, field_name="enrolled_node_id")
            validate_digest(
                self.enrollment_binding_digest,
                field_name="enrollment_binding_digest",
            )


@dataclass(frozen=True, slots=True)
class HostedRotationRecord:
    rotation_id: str
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    expected_epoch: int
    next_epoch: int
    pending_public_jwk: dict[str, str]
    pending_device_key_id: str
    pending_access_token_digest: bytes
    status: Literal["prepared", "committed", "cancelled"]
    prepared_at: int
    committed_at: int | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.rotation_id, field_name="rotation_id")
        validate_identifier(self.tenant_id, field_name="tenant_id")
        validate_identifier(self.node_id, field_name="node_id")
        validate_identifier(self.wallet_binding_id, field_name="wallet_binding_id")
        if type(self.expected_epoch) is not int or self.expected_epoch <= 0:
            raise ValueError("expected_epoch is invalid")
        if type(self.next_epoch) is not int or self.next_epoch != self.expected_epoch + 1:
            raise ValueError("next_epoch is invalid")
        if not isinstance(self.pending_public_jwk, dict):
            raise ValueError("pending_public_jwk is invalid")
        if not isinstance(self.pending_device_key_id, str) or _KEY_ID.fullmatch(
            self.pending_device_key_id
        ) is None:
            raise ValueError("pending_device_key_id is invalid")
        try:
            pending_thumbprint = _jwk_thumbprint(self.pending_public_jwk)
        except (HostedProtocolError, TypeError, ValueError) as exc:
            raise ValueError("pending_public_jwk is invalid") from exc
        if pending_thumbprint != self.pending_device_key_id:
            raise ValueError("pending_device_key_id does not match pending_public_jwk")
        validate_digest(
            self.pending_access_token_digest,
            field_name="pending_access_token_digest",
        )
        if self.status not in {"prepared", "committed", "cancelled"}:
            raise ValueError("status is invalid")
        if type(self.prepared_at) is not int or self.prepared_at <= 0:
            raise ValueError("prepared_at is invalid")
        if self.committed_at is not None and (
            type(self.committed_at) is not int or self.committed_at <= 0
        ):
            raise ValueError("committed_at is invalid")
        if self.status == "committed" and self.committed_at is None:
            raise ValueError("committed_at is required")
        if self.status != "committed" and self.committed_at is not None:
            raise ValueError("committed_at is only valid for committed rotations")
        object.__setattr__(self, "pending_public_jwk", dict(self.pending_public_jwk))


@dataclass(frozen=True, slots=True)
class NodeRegistration:
    tenant_id: str
    node_id: str
    wallet_binding_id: str
    device_public_jwk: dict[str, str]
    device_key_id: str
    access_token_digest: bytes
    credential_epoch: int
    status: Literal["active", "revoked"]
    created_at: int
    updated_at: int
    revocation_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.tenant_id, field_name="tenant_id")
        validate_identifier(self.node_id, field_name="node_id")
        validate_identifier(self.wallet_binding_id, field_name="wallet_binding_id")
        if not isinstance(self.device_public_jwk, dict):
            raise ValueError("device_public_jwk is invalid")
        if not isinstance(self.device_key_id, str) or _KEY_ID.fullmatch(self.device_key_id) is None:
            raise ValueError("device_key_id is invalid")
        try:
            jwk_thumbprint = _jwk_thumbprint(self.device_public_jwk)
        except (HostedProtocolError, TypeError, ValueError) as exc:
            raise ValueError("device_public_jwk is invalid") from exc
        if jwk_thumbprint != self.device_key_id:
            raise ValueError("device_key_id does not match device_public_jwk")
        validate_digest(self.access_token_digest, field_name="access_token_digest")
        if type(self.credential_epoch) is not int or self.credential_epoch <= 0:
            raise ValueError("credential_epoch is invalid")
        if self.status not in {"active", "revoked"}:
            raise ValueError("status is invalid")
        if type(self.created_at) is not int or self.created_at <= 0:
            raise ValueError("created_at is invalid")
        if type(self.updated_at) is not int or self.updated_at <= 0:
            raise ValueError("updated_at is invalid")
        if self.revocation_id is not None:
            validate_identifier(self.revocation_id, field_name="revocation_id")
        object.__setattr__(self, "device_public_jwk", dict(self.device_public_jwk))


@dataclass(frozen=True, slots=True)
class PreflightRecord:
    tenant_id: str
    node_id: str
    request_id: str
    idempotency_key: str
    request_nonce: str
    capability_hash: str
    reservation_id: str
    request_hash: str
    signed_response_jws: str
    created_at: int

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "node_id",
            "request_id",
            "idempotency_key",
            "reservation_id",
        ):
            validate_identifier(getattr(self, field_name), field_name=field_name)
        validate_hash(self.request_nonce, field_name="request_nonce")
        validate_hash(self.capability_hash, field_name="capability_hash")
        validate_hash(self.request_hash, field_name="request_hash")
        if not isinstance(self.signed_response_jws, str) or not self.signed_response_jws:
            raise ValueError("signed_response_jws is invalid")
        try:
            signed_response_bytes = self.signed_response_jws.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("signed_response_jws is invalid") from exc
        if len(signed_response_bytes) > MAX_SIGNED_RESPONSE_BYTES:
            raise ValueError("signed_response_jws is invalid")
        if type(self.created_at) is not int or self.created_at <= 0:
            raise ValueError("created_at is invalid")


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    tenant_id: str
    node_id: str
    credential_epoch: int
    access_token: str = field(repr=False)
    response_public_jwk: dict[str, str] = field(default_factory=dict)
    response_key_id: str = ""


class ResponseSigner(Protocol):
    @property
    def public_jwk(self) -> dict[str, str]: ...

    @property
    def key_id(self) -> str: ...

    def sign(self, response: HostedPreflightResponse) -> str: ...

    def sign_execution(self, response: HostedExecutionResponse) -> str: ...
