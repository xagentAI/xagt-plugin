from __future__ import annotations

import base64
import binascii
import re
import secrets
import string
from collections.abc import Callable

from models import EnrollmentTokenRecord, HostedRotationRecord, NodeRegistration
from repository import (
    ControlPlaneRepository,
    RepositoryConflict,
    digest_secret,
)
from shared.hosted_facilitator_protocol import (
    DeviceSigningKey,
    HostedExecutionResponse,
    HostedPreflightResponse,
    HostedProtocolError,
    _jwk_thumbprint,
    sign_preflight_response,
    sign_execution_response,
)


class EnrollmentError(RuntimeError):
    """A bounded enrollment or credential lifecycle failure."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def _now(clock: Callable[[], int]) -> int:
    value = clock()
    if type(value) is not int or value <= 0:
        raise RuntimeError("clock is invalid")
    return value


def _opaque_token() -> str:
    # token_urlsafe(32) encodes 256 bits and produces an ASCII token suitable
    # for the Authorization header without retaining key material.
    return secrets.token_urlsafe(32)


def _validate_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 8192:
        raise EnrollmentError(f"{field_name} is invalid")
    if any(character not in string.printable or character in "\r\n\t " for character in value):
        raise EnrollmentError(f"{field_name} is invalid")
    return value


def _validate_public_jwk(value: object) -> tuple[dict[str, str], str]:
    if not isinstance(value, dict):
        raise EnrollmentError("public key is invalid")
    try:
        thumbprint = _jwk_thumbprint(value)
    except (HostedProtocolError, TypeError, ValueError) as exc:
        raise EnrollmentError("public key is invalid") from exc
    # _jwk_thumbprint normalizes the P-256 coordinates and rejects extra keys;
    # retain only the canonical public representation supplied by the protocol.
    if set(value) != {"kty", "crv", "x", "y"} or any(
        not isinstance(item, str) for item in value.values()
    ):
        raise EnrollmentError("public key is invalid")
    return dict(value), thumbprint


def _validate_wallet_binding(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EnrollmentError("wallet binding is invalid")
    return value


def _validate_identifier(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EnrollmentError(f"{field_name} is invalid")
    return value


def _validate_epoch(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise EnrollmentError(f"{field_name} is invalid")
    return value


def _validate_digest(value: object, *, field_name: str) -> bytes:
    if not isinstance(value, str) or _BASE64URL.fullmatch(value) is None:
        raise EnrollmentError(f"{field_name} is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise EnrollmentError(f"{field_name} is invalid") from exc
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise EnrollmentError(f"{field_name} is invalid")
    return decoded


class DeviceResponseSigner:
    """Adapter exposing the reviewed response-signing protocol to the service."""

    def __init__(self, key: DeviceSigningKey) -> None:
        if not isinstance(key, DeviceSigningKey):
            raise TypeError("response signer key is invalid")
        self._key = key

    @property
    def public_jwk(self) -> dict[str, str]:
        return dict(self._key.public_jwk)

    @property
    def key_id(self) -> str:
        return self._key.thumbprint

    def sign(self, response: HostedPreflightResponse) -> str:
        return sign_preflight_response(self._key, response)

    def sign_execution(self, response: HostedExecutionResponse) -> str:
        return sign_execution_response(self._key, response)


class EnrollmentService:
    def __init__(
        self,
        *,
        repository: ControlPlaneRepository,
        enrollment_ttl_seconds: int,
        clock: Callable[[], int],
    ) -> None:
        if type(enrollment_ttl_seconds) is not int or not 30 <= enrollment_ttl_seconds <= 900:
            raise ValueError("enrollment TTL is invalid")
        self.repository = repository
        self.enrollment_ttl_seconds = enrollment_ttl_seconds
        self.clock = clock

    def issue_enrollment_token(self, tenant_id: str) -> str:
        # The repository validates the tenant identifier and receives only the
        # digest; the plaintext token is returned to this internal caller once.
        token = _opaque_token()
        now = _now(self.clock)
        try:
            self.repository.put_enrollment_token(
                EnrollmentTokenRecord(
                    tenant_id=tenant_id,
                    token_digest=digest_secret(token),
                    expires_at=now + self.enrollment_ttl_seconds,
                )
            )
        except (RepositoryConflict, ValueError) as exc:
            raise EnrollmentError("enrollment token could not be issued") from exc
        return token

    def enroll(
        self,
        token: str,
        *,
        public_jwk: dict[str, str],
        wallet_binding_id: str,
        expected_epoch: int = 0,
        next_epoch: int = 1,
        access_token_digest: str,
        device_key_id: str | None = None,
        status: str = "pending",
    ) -> NodeRegistration:
        token = _validate_token(token, field_name="enrollment token")
        public_jwk, derived_device_key_id = _validate_public_jwk(public_jwk)
        if device_key_id is not None and device_key_id != derived_device_key_id:
            raise EnrollmentError("device key ID is invalid")
        device_key_id = derived_device_key_id
        wallet_binding_id = _validate_wallet_binding(wallet_binding_id)
        if type(expected_epoch) is not int or expected_epoch != 0:
            raise EnrollmentError("expected epoch is invalid")
        if type(next_epoch) is not int or next_epoch != 1:
            raise EnrollmentError("next epoch is invalid")
        if status != "pending":
            raise EnrollmentError("enrollment status is invalid")
        access_digest = _validate_digest(
            access_token_digest,
            field_name="access token digest",
        )
        now = _now(self.clock)
        token_digest = digest_secret(token)
        record = self.repository.get_enrollment_token(token_digest)
        if record is None:
            raise EnrollmentError("enrollment token is invalid")
        # A consumed invite is an idempotency key.  It remains replayable after
        # its original TTL, but only for the exact original client binding;
        # unconsumed invites still expire normally.
        if record.consumed_at is None and record.expires_at <= now:
            raise EnrollmentError("enrollment token expired")

        node_id = (
            record.enrolled_node_id
            if record.consumed_at is not None and record.enrolled_node_id is not None
            else "node_" + secrets.token_urlsafe(18)
        )
        node = NodeRegistration(
            tenant_id=record.tenant_id,
            node_id=node_id,
            wallet_binding_id=wallet_binding_id,
            device_public_jwk=public_jwk,
            device_key_id=device_key_id,
            access_token_digest=access_digest,
            credential_epoch=1,
            status="active",
            created_at=now,
            updated_at=now,
        )
        try:
            return self.repository.enroll_node(token_digest, node, now=now)
        except (RepositoryConflict, ValueError) as exc:
            raise EnrollmentError("enrollment token is invalid or already consumed") from exc

    def prepare_rotation(
        self,
        *,
        rotation_id: str,
        tenant_id: str,
        node_id: str,
        wallet_binding_id: str,
        expected_epoch: int,
        next_epoch: int,
        public_jwk: dict[str, str],
        device_key_id: str,
        access_token_digest: str,
    ) -> HostedRotationRecord:
        rotation_id = _validate_identifier(rotation_id, field_name="rotation_id")
        tenant_id = _validate_identifier(tenant_id, field_name="tenant_id")
        node_id = _validate_identifier(node_id, field_name="node_id")
        wallet_binding_id = _validate_wallet_binding(wallet_binding_id)
        expected_epoch = _validate_epoch(expected_epoch, field_name="expected epoch")
        if type(next_epoch) is not int or next_epoch != expected_epoch + 1:
            raise EnrollmentError("next epoch is invalid")
        public_jwk, thumbprint = _validate_public_jwk(public_jwk)
        if not isinstance(device_key_id, str) or device_key_id != thumbprint:
            raise EnrollmentError("device key ID is invalid")
        access_digest = _validate_digest(
            access_token_digest,
            field_name="access token digest",
        )
        now = _now(self.clock)
        record = HostedRotationRecord(
            rotation_id=rotation_id,
            tenant_id=tenant_id,
            node_id=node_id,
            wallet_binding_id=wallet_binding_id,
            expected_epoch=expected_epoch,
            next_epoch=next_epoch,
            pending_public_jwk=public_jwk,
            pending_device_key_id=device_key_id,
            pending_access_token_digest=access_digest,
            status="prepared",
            prepared_at=now,
        )
        try:
            return self.repository.prepare_rotation(record)
        except (RepositoryConflict, ValueError) as exc:
            raise EnrollmentError("rotation request is invalid or unavailable") from exc

    def commit_rotation(
        self,
        *,
        rotation_id: str,
        tenant_id: str,
        node_id: str,
        wallet_binding_id: str,
        expected_epoch: int,
        next_epoch: int,
        public_jwk: dict[str, str],
        device_key_id: str,
        access_token_digest: str,
    ) -> NodeRegistration:
        rotation_id = _validate_identifier(rotation_id, field_name="rotation_id")
        tenant_id = _validate_identifier(tenant_id, field_name="tenant_id")
        node_id = _validate_identifier(node_id, field_name="node_id")
        wallet_binding_id = _validate_wallet_binding(wallet_binding_id)
        expected_epoch = _validate_epoch(expected_epoch, field_name="expected epoch")
        if type(next_epoch) is not int or next_epoch != expected_epoch + 1:
            raise EnrollmentError("next epoch is invalid")
        public_jwk, thumbprint = _validate_public_jwk(public_jwk)
        if not isinstance(device_key_id, str) or device_key_id != thumbprint:
            raise EnrollmentError("device key ID is invalid")
        access_digest = _validate_digest(
            access_token_digest,
            field_name="access token digest",
        )
        try:
            pending = self.repository.get_pending_rotation_by_access_digest(
                access_digest,
                tenant_id=tenant_id,
                node_id=node_id,
            )
        except Exception:
            raise
        if pending is not None:
            if (
                pending.rotation_id != rotation_id
                or pending.wallet_binding_id != wallet_binding_id
                or pending.expected_epoch != expected_epoch
                or pending.next_epoch != next_epoch
                or pending.pending_public_jwk != public_jwk
                or pending.pending_device_key_id != device_key_id
                or pending.pending_access_token_digest != access_digest
            ):
                raise EnrollmentError("rotation request conflicts with prepared state")
        else:
            # A committed response can be lost.  The active replacement
            # credential is accepted only for this exact commit request; the
            # repository still verifies the durable rotation ID/state.
            current = self.repository.get_node(tenant_id, node_id)
            if (
                current is None
                or current.status != "active"
                or current.wallet_binding_id != wallet_binding_id
                or current.device_public_jwk != public_jwk
                or current.device_key_id != device_key_id
                or current.access_token_digest != access_digest
                or current.credential_epoch != next_epoch
            ):
                raise EnrollmentError("rotation request is unavailable")
        now = _now(self.clock)
        try:
            return self.repository.commit_rotation(
                rotation_id=rotation_id,
                tenant_id=tenant_id,
                node_id=node_id,
                expected_epoch=expected_epoch,
                pending_access_token_digest=access_digest,
                now=now,
            )
        except (RepositoryConflict, ValueError) as exc:
            raise EnrollmentError("rotation request is invalid or unavailable") from exc

    def revoke(
        self,
        *,
        revocation_id: str,
        tenant_id: str,
        node_id: str,
        wallet_binding_id: str,
        credential_epoch: int,
        expected_epoch: int,
        next_epoch: int,
        device_key_id: str,
        access_token_digest: str,
        status: str = "revoking",
    ) -> NodeRegistration:
        revocation_id = _validate_identifier(revocation_id, field_name="revocation_id")
        tenant_id = _validate_identifier(tenant_id, field_name="tenant_id")
        node_id = _validate_identifier(node_id, field_name="node_id")
        wallet_binding_id = _validate_wallet_binding(wallet_binding_id)
        credential_epoch = _validate_epoch(credential_epoch, field_name="credential epoch")
        expected_epoch = _validate_epoch(expected_epoch, field_name="expected epoch")
        if credential_epoch != expected_epoch:
            raise EnrollmentError("credential epoch is invalid")
        if type(next_epoch) is not int or next_epoch != expected_epoch + 1:
            raise EnrollmentError("next epoch is invalid")
        if status != "revoking":
            raise EnrollmentError("revocation status is invalid")
        access_digest = _validate_digest(
            access_token_digest,
            field_name="access token digest",
        )
        if not isinstance(device_key_id, str):
            raise EnrollmentError("device key ID is invalid")
        current = self.repository.get_node(tenant_id, node_id)
        if current is None:
            raise EnrollmentError("current node registration is unavailable")
        if current.status == "revoked":
            try:
                replay = self.repository.get_revoked_node_by_access_digest(
                    access_digest,
                    tenant_id=tenant_id,
                    node_id=node_id,
                    revocation_id=revocation_id,
                    expected_epoch=expected_epoch,
                )
            except Exception:
                raise
            if (
                replay is None
                or replay.wallet_binding_id != wallet_binding_id
                or replay.device_key_id != device_key_id
                or replay.credential_epoch != next_epoch
            ):
                raise EnrollmentError("revocation request is unavailable")
            return replay
        if (
            current.status != "active"
            or current.wallet_binding_id != wallet_binding_id
            or current.device_key_id != device_key_id
            or current.access_token_digest != access_digest
            or current.credential_epoch != expected_epoch
        ):
            raise EnrollmentError("revocation request is invalid or unavailable")
        try:
            return self.repository.revoke_node(
                tenant_id=tenant_id,
                node_id=node_id,
                expected_epoch=expected_epoch,
                revocation_id=revocation_id,
            )
        except (RepositoryConflict, ValueError) as exc:
            raise EnrollmentError("revocation request is invalid or unavailable") from exc
