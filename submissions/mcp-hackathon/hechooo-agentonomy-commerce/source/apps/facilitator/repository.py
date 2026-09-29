from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import replace
from threading import RLock
from typing import Protocol

from sqlalchemy import (
    CheckConstraint,
    Index,
    JSON,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from models import (
    EnrollmentTokenRecord,
    HostedRotationRecord,
    NodeRegistration,
    PreflightRecord,
)


class RepositoryError(RuntimeError):
    pass


class RepositoryConflict(RepositoryError):
    pass


class RepositoryUnavailable(RepositoryError):
    pass


def digest_secret(value: str | bytes) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    if not isinstance(value, bytes) or not value:
        raise ValueError("secret is invalid")
    return hashlib.sha256(value).digest()


def enrollment_binding_digest(node: NodeRegistration) -> bytes:
    """Hash the client-provided enrollment binding, excluding server node id."""

    if not isinstance(node, NodeRegistration):
        raise TypeError("node is invalid")
    canonical = json.dumps(
        {
            "tenant_id": node.tenant_id,
            "wallet_binding_id": node.wallet_binding_id,
            "device_public_jwk": {
                key: node.device_public_jwk[key]
                for key in ("crv", "kty", "x", "y")
            },
            "device_key_id": node.device_key_id,
            "access_token_digest": node.access_token_digest.hex(),
            "credential_epoch": node.credential_epoch,
            "status": node.status,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).digest()


def _enrollment_binding_for(
    node: NodeRegistration,
    binding_digest: bytes | None,
) -> bytes:
    expected = enrollment_binding_digest(node)
    if binding_digest is None:
        return expected
    try:
        valid = isinstance(binding_digest, bytes) and len(binding_digest) == 32
    except TypeError:
        valid = False
    if not valid or binding_digest != expected:
        raise RepositoryConflict("enrollment binding conflict")
    return binding_digest


def _rotation_request_binding(record: HostedRotationRecord) -> tuple[object, ...]:
    """Return only client-bound rotation fields for idempotency comparison."""

    return (
        record.rotation_id,
        record.tenant_id,
        record.node_id,
        record.wallet_binding_id,
        record.expected_epoch,
        record.next_epoch,
        json.dumps(
            record.pending_public_jwk,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        record.pending_device_key_id,
        record.pending_access_token_digest,
        record.status,
    )


class ControlPlaneBase(DeclarativeBase):
    pass


class TenantRow(ControlPlaneBase):
    __tablename__ = "hosted_tenants"

    tenant_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class EnrollmentTokenRow(ControlPlaneBase):
    __tablename__ = "hosted_enrollment_tokens"
    __table_args__ = (
        CheckConstraint(
            "(enrolled_node_id IS NULL AND enrollment_binding_digest IS NULL) OR "
            "(enrolled_node_id IS NOT NULL AND enrollment_binding_digest IS NOT NULL)",
            name="ck_hosted_enrollment_binding",
        ),
        UniqueConstraint(
            "tenant_id",
            "enrolled_node_id",
            name="uq_hosted_enrollment_node_binding",
        ),
    )

    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    consumed_at: Mapped[int | None] = mapped_column(Integer)
    enrolled_node_id: Mapped[str | None] = mapped_column(String(256))
    enrollment_binding_digest: Mapped[bytes | None] = mapped_column(
        LargeBinary(32)
    )


class NodeRegistrationRow(ControlPlaneBase):
    __tablename__ = "hosted_node_registrations"
    __table_args__ = (
        UniqueConstraint("access_token_digest", name="uq_hosted_node_access_digest"),
        UniqueConstraint("revocation_id", name="uq_hosted_node_revocation_id"),
    )

    tenant_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    wallet_binding_id: Mapped[str] = mapped_column(String(256), nullable=False)
    device_public_jwk: Mapped[dict] = mapped_column(JSON, nullable=False)
    device_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    access_token_digest: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False
    )
    credential_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)
    revocation_id: Mapped[str | None] = mapped_column(String(256))


class HostedRotationRow(ControlPlaneBase):
    __tablename__ = "hosted_node_rotations"
    __table_args__ = (
        CheckConstraint(
            "expected_epoch > 0",
            name="ck_hosted_rotation_expected_epoch_positive",
        ),
        CheckConstraint(
            "next_epoch = expected_epoch + 1",
            name="ck_hosted_rotation_epoch_step",
        ),
        CheckConstraint(
            "status IN ('prepared', 'committed', 'cancelled')",
            name="ck_hosted_rotation_status",
        ),
        CheckConstraint(
            "(status = 'committed' AND committed_at IS NOT NULL) OR "
            "(status IN ('prepared', 'cancelled') AND committed_at IS NULL)",
            name="ck_hosted_rotation_commit_timestamp",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "expected_epoch",
            name="uq_hosted_rotation_node_expected_epoch",
        ),
        UniqueConstraint(
            "pending_access_token_digest",
            name="uq_hosted_rotation_pending_access_digest",
        ),
        Index(
            "ix_hosted_node_rotations_scope_status",
            "tenant_id",
            "node_id",
            "status",
        ),
    )

    rotation_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    wallet_binding_id: Mapped[str] = mapped_column(String(256), nullable=False)
    expected_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    next_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    pending_public_jwk: Mapped[dict] = mapped_column(JSON, nullable=False)
    pending_device_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    pending_access_token_digest: Mapped[bytes] = mapped_column(
        LargeBinary(32), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    prepared_at: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_at: Mapped[int | None] = mapped_column(Integer)


class RetiredCredentialRow(ControlPlaneBase):
    __tablename__ = "hosted_retired_credentials"

    access_token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    retired_at: Mapped[int] = mapped_column(Integer, nullable=False)


class DPoPReplayRow(ControlPlaneBase):
    __tablename__ = "hosted_dpop_replays"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "credential_epoch",
            "jti",
            name="uq_hosted_dpop_scope_jti",
        ),
    )

    replay_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    credential_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    jti: Mapped[str] = mapped_column(String(256), nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class PreflightRow(ControlPlaneBase):
    __tablename__ = "hosted_preflight_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "request_id",
            name="uq_hosted_preflight_request_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "idempotency_key",
            name="uq_hosted_preflight_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "request_nonce",
            name="uq_hosted_preflight_request_nonce",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "capability_hash",
            name="uq_hosted_preflight_capability",
        ),
        UniqueConstraint(
            "tenant_id",
            "node_id",
            "reservation_id",
            name="uq_hosted_preflight_reservation",
        ),
    )

    record_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    request_id: Mapped[str] = mapped_column(String(256), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_nonce: Mapped[str] = mapped_column(String(66), nullable=False)
    capability_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    reservation_id: Mapped[str] = mapped_column(String(256), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(66), nullable=False)
    signed_response_jws: Mapped[str] = mapped_column(String(64 * 1024), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class ControlPlaneRepository(Protocol):
    def put_enrollment_token(self, record: EnrollmentTokenRecord) -> None: ...

    def get_enrollment_token(self, token_digest: bytes) -> EnrollmentTokenRecord | None: ...

    def consume_enrollment_token(
        self, token_digest: bytes, *, now: int
    ) -> EnrollmentTokenRecord | None: ...

    def enroll_node(
        self,
        token_digest: bytes,
        node: NodeRegistration,
        *,
        now: int,
        binding_digest: bytes | None = None,
    ) -> NodeRegistration: ...

    def put_node(self, node: NodeRegistration) -> None: ...

    def get_node(self, tenant_id: str, node_id: str) -> NodeRegistration | None: ...

    def get_node_by_access_digest(self, access_token_digest: bytes) -> NodeRegistration | None: ...

    def rotate_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        replacement: NodeRegistration,
    ) -> NodeRegistration: ...

    def prepare_rotation(
        self, record: HostedRotationRecord
    ) -> HostedRotationRecord: ...

    def commit_rotation(
        self,
        *,
        rotation_id: str,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        pending_access_token_digest: bytes,
        now: int,
    ) -> NodeRegistration: ...

    def get_pending_rotation_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
    ) -> HostedRotationRecord | None: ...

    def revoke_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        revocation_id: str | None = None,
    ) -> NodeRegistration: ...

    def get_revoked_node_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
        revocation_id: str,
        expected_epoch: int,
    ) -> NodeRegistration | None: ...

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        expires_at: int,
        now: int,
    ) -> bool: ...

    def bind_preflight(self, record: PreflightRecord) -> PreflightRecord: ...


def _record_from_row(row: EnrollmentTokenRow) -> EnrollmentTokenRecord:
    return EnrollmentTokenRecord(
        tenant_id=row.tenant_id,
        token_digest=bytes(row.token_digest),
        expires_at=row.expires_at,
        consumed_at=row.consumed_at,
        enrolled_node_id=row.enrolled_node_id,
        enrollment_binding_digest=(
            bytes(row.enrollment_binding_digest)
            if row.enrollment_binding_digest is not None
            else None
        ),
    )


def _node_from_row(row: NodeRegistrationRow) -> NodeRegistration:
    return NodeRegistration(
        tenant_id=row.tenant_id,
        node_id=row.node_id,
        wallet_binding_id=row.wallet_binding_id,
        device_public_jwk=dict(row.device_public_jwk),
        device_key_id=row.device_key_id,
        access_token_digest=bytes(row.access_token_digest),
        credential_epoch=row.credential_epoch,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        revocation_id=row.revocation_id,
    )


def _rotation_from_row(row: HostedRotationRow) -> HostedRotationRecord:
    return HostedRotationRecord(
        rotation_id=row.rotation_id,
        tenant_id=row.tenant_id,
        node_id=row.node_id,
        wallet_binding_id=row.wallet_binding_id,
        expected_epoch=row.expected_epoch,
        next_epoch=row.next_epoch,
        pending_public_jwk=dict(row.pending_public_jwk),
        pending_device_key_id=row.pending_device_key_id,
        pending_access_token_digest=bytes(row.pending_access_token_digest),
        status=row.status,
        prepared_at=row.prepared_at,
        committed_at=row.committed_at,
    )


class InMemoryRepository:
    """Unit-test repository; production app rejects this adapter."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._tokens: dict[bytes, EnrollmentTokenRecord] = {}
        self._nodes: dict[tuple[str, str], NodeRegistration] = {}
        self._rotations: dict[str, HostedRotationRecord] = {}
        self._retired_access_digests: set[bytes] = set()
        self._dpop_jtis: dict[tuple[str, str, int, str], int] = {}
        self._preflights: dict[tuple[str, str, str], PreflightRecord] = {}
        self._requests: dict[tuple[str, str, str], PreflightRecord] = {}
        self._nonces: dict[tuple[str, str, str], PreflightRecord] = {}
        self._capabilities: dict[tuple[str, str, str], PreflightRecord] = {}
        self._reservations: dict[tuple[str, str, str], PreflightRecord] = {}

    def put_enrollment_token(self, record: EnrollmentTokenRecord) -> None:
        with self._lock:
            if record.token_digest in self._tokens:
                raise RepositoryConflict("enrollment token already exists")
            if record.enrolled_node_id is not None and any(
                existing.tenant_id == record.tenant_id
                and existing.enrolled_node_id == record.enrolled_node_id
                for existing in self._tokens.values()
            ):
                raise RepositoryConflict("enrollment node binding already exists")
            self._tokens[record.token_digest] = record

    def get_enrollment_token(self, token_digest: bytes) -> EnrollmentTokenRecord | None:
        with self._lock:
            return self._tokens.get(token_digest)

    def consume_enrollment_token(
        self, token_digest: bytes, *, now: int
    ) -> EnrollmentTokenRecord | None:
        with self._lock:
            record = self._tokens.get(token_digest)
            if record is None or record.consumed_at is not None:
                return None
            if record.expires_at <= now:
                raise RepositoryConflict("enrollment token expired")
            consumed = replace(record, consumed_at=now)
            self._tokens[token_digest] = consumed
            return consumed

    def enroll_node(
        self,
        token_digest: bytes,
        node: NodeRegistration,
        *,
        now: int,
        binding_digest: bytes | None = None,
    ) -> NodeRegistration:
        with self._lock:
            record = self._tokens.get(token_digest)
            if record is None:
                raise RepositoryConflict("enrollment token is invalid")
            binding_digest = _enrollment_binding_for(node, binding_digest)
            if record.consumed_at is not None:
                if (
                    record.enrolled_node_id is None
                    or record.enrollment_binding_digest != binding_digest
                ):
                    raise RepositoryConflict("enrollment binding conflict")
                existing = self._nodes.get((record.tenant_id, record.enrolled_node_id))
                if existing is None or enrollment_binding_digest(existing) != binding_digest:
                    raise RepositoryConflict("enrollment binding conflict")
                return existing
            if record.expires_at <= now:
                raise RepositoryConflict("enrollment token expired")
            if node.tenant_id != record.tenant_id:
                raise RepositoryConflict("enrollment tenant mismatch")
            if (node.tenant_id, node.node_id) in self._nodes:
                raise RepositoryConflict("node already exists")
            if any(
                existing.tenant_id == node.tenant_id
                and existing.enrolled_node_id == node.node_id
                for existing in self._tokens.values()
            ):
                raise RepositoryConflict("enrollment node binding already exists")
            if node.revocation_id is not None and any(
                item.revocation_id == node.revocation_id
                for existing_key, item in self._nodes.items()
                if existing_key != (node.tenant_id, node.node_id)
            ):
                raise RepositoryConflict("revocation ID already exists")
            if (
                node.access_token_digest in self._retired_access_digests
                or any(
                    item.access_token_digest == node.access_token_digest
                    for item in self._nodes.values()
                )
            ):
                raise RepositoryConflict("access token already exists")
            self._tokens[token_digest] = replace(
                record,
                consumed_at=now,
                enrolled_node_id=node.node_id,
                enrollment_binding_digest=binding_digest,
            )
            self._nodes[(node.tenant_id, node.node_id)] = node
            return node

    def put_node(self, node: NodeRegistration) -> None:
        with self._lock:
            key = (node.tenant_id, node.node_id)
            if key in self._nodes or node.access_token_digest in self._retired_access_digests:
                raise RepositoryConflict("node or access token already exists")
            if any(item.access_token_digest == node.access_token_digest for item in self._nodes.values()):
                raise RepositoryConflict("access token already exists")
            if node.revocation_id is not None and any(
                item.revocation_id == node.revocation_id
                for existing_key, item in self._nodes.items()
                if existing_key != key
            ):
                raise RepositoryConflict("revocation ID already exists")
            self._nodes[key] = node

    def get_node(self, tenant_id: str, node_id: str) -> NodeRegistration | None:
        with self._lock:
            return self._nodes.get((tenant_id, node_id))

    def get_node_by_access_digest(self, access_token_digest: bytes) -> NodeRegistration | None:
        with self._lock:
            for node in self._nodes.values():
                if (
                    node.status == "active"
                    and node.access_token_digest == access_token_digest
                    and access_token_digest not in self._retired_access_digests
                ):
                    return node
            return None

    def prepare_rotation(self, record: HostedRotationRecord) -> HostedRotationRecord:
        with self._lock:
            if record.status != "prepared":
                raise RepositoryConflict("rotation status is invalid")
            existing = self._rotations.get(record.rotation_id)
            if existing is not None:
                if _rotation_request_binding(existing) == _rotation_request_binding(record):
                    return existing
                raise RepositoryConflict("rotation request conflict")
            for current in self._rotations.values():
                if (
                    current.tenant_id == record.tenant_id
                    and current.node_id == record.node_id
                    and current.expected_epoch == record.expected_epoch
                ):
                    raise RepositoryConflict("rotation request conflict")
                if current.pending_access_token_digest == record.pending_access_token_digest:
                    raise RepositoryConflict("rotation credential conflict")
            if record.status != "prepared":
                raise RepositoryConflict("rotation status is invalid")
            current = self._nodes.get((record.tenant_id, record.node_id))
            if current is None or current.status != "active":
                raise RepositoryConflict("node is revoked")
            if current.credential_epoch != record.expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if current.wallet_binding_id != record.wallet_binding_id:
                raise RepositoryConflict("rotation scope conflict")
            self._rotations[record.rotation_id] = record
            return record

    def get_pending_rotation_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
    ) -> HostedRotationRecord | None:
        with self._lock:
            for record in self._rotations.values():
                if (
                    record.status == "prepared"
                    and record.pending_access_token_digest == access_token_digest
                    and record.tenant_id == tenant_id
                    and record.node_id == node_id
                ):
                    return record
            return None

    def commit_rotation(
        self,
        *,
        rotation_id: str,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        pending_access_token_digest: bytes,
        now: int,
    ) -> NodeRegistration:
        with self._lock:
            record = self._rotations.get(rotation_id)
            if record is None:
                raise RepositoryConflict("rotation is unavailable")
            if (
                record.tenant_id != tenant_id
                or record.node_id != node_id
                or record.expected_epoch != expected_epoch
                or record.pending_access_token_digest != pending_access_token_digest
            ):
                raise RepositoryConflict("rotation request conflict")
            if type(now) is not int or now <= 0:
                raise RepositoryConflict("rotation timestamp is invalid")
            current = self._nodes.get((tenant_id, node_id))
            if record.status == "committed":
                if (
                    current is None
                    or current.status != "active"
                    or current.credential_epoch != record.next_epoch
                    or current.wallet_binding_id != record.wallet_binding_id
                    or current.device_public_jwk != record.pending_public_jwk
                    or current.device_key_id != record.pending_device_key_id
                    or current.access_token_digest
                    != record.pending_access_token_digest
                    or current.revocation_id is not None
                ):
                    raise RepositoryConflict("rotation state conflict")
                return current
            if record.status != "prepared":
                raise RepositoryConflict("rotation is cancelled")
            if current is None or current.status != "active":
                raise RepositoryConflict("node is revoked")
            if current.credential_epoch != expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if current.wallet_binding_id != record.wallet_binding_id:
                raise RepositoryConflict("rotation scope conflict")
            if pending_access_token_digest == current.access_token_digest:
                raise RepositoryConflict("replacement access token must be new")
            if pending_access_token_digest in self._retired_access_digests or any(
                item.access_token_digest == pending_access_token_digest
                for key, item in self._nodes.items()
                if key != (tenant_id, node_id)
            ):
                raise RepositoryConflict("access token already exists")
            self._retired_access_digests.add(current.access_token_digest)
            active = replace(
                current,
                device_public_jwk=record.pending_public_jwk,
                device_key_id=record.pending_device_key_id,
                access_token_digest=record.pending_access_token_digest,
                credential_epoch=record.next_epoch,
                updated_at=now,
                revocation_id=None,
            )
            self._nodes[(tenant_id, node_id)] = active
            self._rotations[rotation_id] = replace(
                record,
                status="committed",
                committed_at=now,
            )
            return active

    def rotate_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        replacement: NodeRegistration,
    ) -> NodeRegistration:
        if (
            replacement.tenant_id != tenant_id
            or replacement.node_id != node_id
            or replacement.credential_epoch != expected_epoch + 1
            or replacement.status != "active"
        ):
            raise RepositoryConflict("rotation is invalid")
        current = self.get_node(tenant_id, node_id)
        if current is None:
            raise RepositoryConflict("node is revoked")
        record = HostedRotationRecord(
            rotation_id="rotation_" + secrets.token_urlsafe(18),
            tenant_id=tenant_id,
            node_id=node_id,
            wallet_binding_id=current.wallet_binding_id,
            expected_epoch=expected_epoch,
            next_epoch=expected_epoch + 1,
            pending_public_jwk=replacement.device_public_jwk,
            pending_device_key_id=replacement.device_key_id,
            pending_access_token_digest=replacement.access_token_digest,
            status="prepared",
            prepared_at=replacement.updated_at,
        )
        self.prepare_rotation(record)
        return self.commit_rotation(
            rotation_id=record.rotation_id,
            tenant_id=tenant_id,
            node_id=node_id,
            expected_epoch=expected_epoch,
            pending_access_token_digest=replacement.access_token_digest,
            now=replacement.updated_at,
        )

    def revoke_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        revocation_id: str | None = None,
    ) -> NodeRegistration:
        with self._lock:
            if type(expected_epoch) is not int or expected_epoch <= 0:
                raise RepositoryConflict("credential epoch conflict")
            current = self._nodes.get((tenant_id, node_id))
            if current is None:
                raise RepositoryConflict("node is unavailable")
            if current.status == "revoked":
                if (
                    current.revocation_id == revocation_id
                    and current.credential_epoch == expected_epoch + 1
                ):
                    return current
                raise RepositoryConflict("revocation request conflict")
            if current.credential_epoch != expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if revocation_id is None:
                revocation_id = "revocation_" + secrets.token_urlsafe(18)
            if any(
                item.revocation_id == revocation_id
                for key, item in self._nodes.items()
                if key != (tenant_id, node_id)
            ):
                raise RepositoryConflict("revocation ID already exists")
            self._retired_access_digests.add(current.access_token_digest)
            revoked = replace(
                current,
                credential_epoch=current.credential_epoch + 1,
                status="revoked",
                updated_at=current.updated_at + 1,
                revocation_id=revocation_id,
            )
            self._nodes[(tenant_id, node_id)] = revoked
            return revoked

    def get_revoked_node_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
        revocation_id: str,
        expected_epoch: int,
    ) -> NodeRegistration | None:
        with self._lock:
            current = self._nodes.get((tenant_id, node_id))
            if current is None or current.status != "revoked":
                return None
            if (
                current.access_token_digest != access_token_digest
                or current.revocation_id != revocation_id
                or current.credential_epoch != expected_epoch + 1
            ):
                return None
            return current

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        expires_at: int,
        now: int,
    ) -> bool:
        key = (tenant_id, node_id, credential_epoch, jti)
        with self._lock:
            self._dpop_jtis = {
                stored: expiry
                for stored, expiry in self._dpop_jtis.items()
                if expiry > now
            }
            if key in self._dpop_jtis:
                return False
            self._dpop_jtis[key] = expires_at
            return True

    def bind_preflight(self, record: PreflightRecord) -> PreflightRecord:
        scope = (record.tenant_id, record.node_id)
        with self._lock:
            idempotency_key = (*scope, record.idempotency_key)
            existing = self._preflights.get(idempotency_key)
            if existing is not None:
                if existing.request_hash == record.request_hash:
                    return existing
                raise RepositoryConflict("idempotency key conflict")
            if (*scope, record.request_id) in self._requests:
                raise RepositoryConflict("request ID conflict")
            if (*scope, record.request_nonce) in self._nonces:
                raise RepositoryConflict("request nonce replay")
            if (*scope, record.capability_hash) in self._capabilities:
                raise RepositoryConflict("capability hash conflict")
            if (*scope, record.reservation_id) in self._reservations:
                raise RepositoryConflict("reservation conflict")
            self._preflights[idempotency_key] = record
            self._requests[(*scope, record.request_id)] = record
            self._nonces[(*scope, record.request_nonce)] = record
            self._capabilities[(*scope, record.capability_hash)] = record
            self._reservations[(*scope, record.reservation_id)] = record
            return record


class PostgresRepository:
    """Durable production repository; SQLite and memory URLs are rejected."""

    def __init__(self, database_url: str, *, engine=None) -> None:
        scheme = database_url.split(":", 1)[0].lower() if isinstance(database_url, str) else ""
        if scheme not in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
            raise ValueError("production repository requires PostgreSQL")
        if engine is not None and getattr(getattr(engine, "dialect", None), "name", None) != "postgresql":
            raise ValueError("production repository engine must use PostgreSQL")
        self.engine = engine or create_engine(database_url, pool_pre_ping=True)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def _run(self, operation):
        try:
            with self.sessions.begin() as session:
                return operation(session)
        except RepositoryError:
            raise
        except IntegrityError as exc:
            raise RepositoryConflict("repository uniqueness conflict") from exc
        except SQLAlchemyError as exc:
            raise RepositoryUnavailable("repository unavailable") from exc

    def put_enrollment_token(self, record: EnrollmentTokenRecord) -> None:
        def operation(session: Session) -> None:
            session.add(
                EnrollmentTokenRow(
                    token_digest=record.token_digest,
                    tenant_id=record.tenant_id,
                    expires_at=record.expires_at,
                    consumed_at=record.consumed_at,
                    enrolled_node_id=record.enrolled_node_id,
                    enrollment_binding_digest=record.enrollment_binding_digest,
                )
            )

        self._run(operation)

    def get_enrollment_token(self, token_digest: bytes) -> EnrollmentTokenRecord | None:
        def operation(session: Session):
            row = session.get(EnrollmentTokenRow, token_digest)
            return _record_from_row(row) if row is not None else None

        return self._run(operation)

    def consume_enrollment_token(
        self, token_digest: bytes, *, now: int
    ) -> EnrollmentTokenRecord | None:
        def operation(session: Session):
            row = session.execute(
                select(EnrollmentTokenRow)
                .where(EnrollmentTokenRow.token_digest == token_digest)
                .with_for_update()
            ).scalar_one_or_none()
            if row is None or row.consumed_at is not None:
                return None
            if row.expires_at <= now:
                raise RepositoryConflict("enrollment token expired")
            row.consumed_at = now
            return _record_from_row(row)

        return self._run(operation)

    def enroll_node(
        self,
        token_digest: bytes,
        node: NodeRegistration,
        *,
        now: int,
        binding_digest: bytes | None = None,
    ) -> NodeRegistration:
        def operation(session: Session):
            expected_binding = _enrollment_binding_for(node, binding_digest)
            row = session.execute(
                select(EnrollmentTokenRow)
                .where(EnrollmentTokenRow.token_digest == token_digest)
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise RepositoryConflict("enrollment token is invalid")
            if row.consumed_at is not None:
                if (
                    row.enrolled_node_id is None
                    or bytes(row.enrollment_binding_digest or b"") != expected_binding
                ):
                    raise RepositoryConflict("enrollment binding conflict")
                existing = session.execute(
                    select(NodeRegistrationRow)
                    .where(
                        NodeRegistrationRow.tenant_id == row.tenant_id,
                        NodeRegistrationRow.node_id == row.enrolled_node_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if existing is None:
                    raise RepositoryConflict("enrollment binding conflict")
                enrolled = _node_from_row(existing)
                if enrollment_binding_digest(enrolled) != expected_binding:
                    raise RepositoryConflict("enrollment binding conflict")
                return enrolled
            if row.expires_at <= now:
                raise RepositoryConflict("enrollment token expired")
            if node.tenant_id != row.tenant_id:
                raise RepositoryConflict("enrollment tenant mismatch")
            if session.get(RetiredCredentialRow, node.access_token_digest) is not None:
                raise RepositoryConflict("access token is retired")
            session.add(_node_row(node))
            row.consumed_at = now
            row.enrolled_node_id = node.node_id
            row.enrollment_binding_digest = expected_binding
            return node

        return self._run(operation)

    def put_node(self, node: NodeRegistration) -> None:
        def operation(session: Session) -> None:
            if session.get(RetiredCredentialRow, node.access_token_digest) is not None:
                raise RepositoryConflict("access token is retired")
            session.add(_node_row(node))

        self._run(operation)

    def get_node(self, tenant_id: str, node_id: str) -> NodeRegistration | None:
        def operation(session: Session):
            row = session.get(NodeRegistrationRow, (tenant_id, node_id))
            return _node_from_row(row) if row is not None else None

        return self._run(operation)

    def get_node_by_access_digest(self, access_token_digest: bytes) -> NodeRegistration | None:
        def operation(session: Session):
            row = session.execute(
                select(NodeRegistrationRow).where(
                    NodeRegistrationRow.access_token_digest == access_token_digest,
                    NodeRegistrationRow.status == "active",
                )
            ).scalar_one_or_none()
            return _node_from_row(row) if row is not None else None

        return self._run(operation)

    def prepare_rotation(self, record: HostedRotationRecord) -> HostedRotationRecord:
        def operation(session: Session):
            if record.status != "prepared":
                raise RepositoryConflict("rotation status is invalid")
            current = session.execute(
                select(NodeRegistrationRow)
                .where(
                    NodeRegistrationRow.tenant_id == record.tenant_id,
                    NodeRegistrationRow.node_id == record.node_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            existing = session.execute(
                select(HostedRotationRow)
                .where(HostedRotationRow.rotation_id == record.rotation_id)
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                current_record = _rotation_from_row(existing)
                if _rotation_request_binding(current_record) == _rotation_request_binding(
                    record
                ):
                    return current_record
                raise RepositoryConflict("rotation request conflict")
            if current is None or current.status != "active":
                raise RepositoryConflict("node is revoked")
            if current.credential_epoch != record.expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if current.wallet_binding_id != record.wallet_binding_id:
                raise RepositoryConflict("rotation scope conflict")
            conflicting_epoch = session.execute(
                select(HostedRotationRow)
                .where(
                    HostedRotationRow.tenant_id == record.tenant_id,
                    HostedRotationRow.node_id == record.node_id,
                    HostedRotationRow.expected_epoch == record.expected_epoch,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if conflicting_epoch is not None:
                raise RepositoryConflict("rotation request conflict")
            conflicting_digest = session.execute(
                select(HostedRotationRow)
                .where(
                    HostedRotationRow.pending_access_token_digest
                    == record.pending_access_token_digest
                )
            ).scalar_one_or_none()
            if conflicting_digest is not None:
                raise RepositoryConflict("rotation credential conflict")
            try:
                with session.begin_nested():
                    session.add(_rotation_row(record))
                    session.flush()
            except IntegrityError as exc:
                existing = session.execute(
                    select(HostedRotationRow)
                    .where(HostedRotationRow.rotation_id == record.rotation_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if existing is not None:
                    current = _rotation_from_row(existing)
                    if _rotation_request_binding(current) == _rotation_request_binding(
                        record
                    ):
                        return current
                    raise RepositoryConflict("rotation request conflict") from exc
                raise RepositoryConflict("rotation request conflict") from exc
            return record

        return self._run(operation)

    def get_pending_rotation_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
    ) -> HostedRotationRecord | None:
        def operation(session: Session):
            row = session.execute(
                select(HostedRotationRow)
                .where(
                    HostedRotationRow.tenant_id == tenant_id,
                    HostedRotationRow.node_id == node_id,
                    HostedRotationRow.pending_access_token_digest
                    == access_token_digest,
                    HostedRotationRow.status == "prepared",
                )
            ).scalar_one_or_none()
            return _rotation_from_row(row) if row is not None else None

        return self._run(operation)

    def commit_rotation(
        self,
        *,
        rotation_id: str,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        pending_access_token_digest: bytes,
        now: int,
    ) -> NodeRegistration:
        def operation(session: Session):
            if type(now) is not int or now <= 0:
                raise RepositoryConflict("rotation timestamp is invalid")
            row = session.execute(
                select(NodeRegistrationRow)
                .where(
                    NodeRegistrationRow.tenant_id == tenant_id,
                    NodeRegistrationRow.node_id == node_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise RepositoryConflict("node is unavailable")
            record_row = session.execute(
                select(HostedRotationRow)
                .where(HostedRotationRow.rotation_id == rotation_id)
                .with_for_update()
            ).scalar_one_or_none()
            if record_row is None:
                raise RepositoryConflict("rotation is unavailable")
            record = _rotation_from_row(record_row)
            if (
                record.tenant_id != tenant_id
                or record.node_id != node_id
                or record.expected_epoch != expected_epoch
                or record.pending_access_token_digest != pending_access_token_digest
            ):
                raise RepositoryConflict("rotation request conflict")
            if record.status == "committed":
                if (
                    row.status != "active"
                    or row.credential_epoch != record.next_epoch
                    or row.wallet_binding_id != record.wallet_binding_id
                    or dict(row.device_public_jwk) != record.pending_public_jwk
                    or row.device_key_id != record.pending_device_key_id
                    or bytes(row.access_token_digest)
                    != record.pending_access_token_digest
                    or row.revocation_id is not None
                ):
                    raise RepositoryConflict("rotation state conflict")
                return _node_from_row(row)
            if record.status != "prepared":
                raise RepositoryConflict("rotation is cancelled")
            if row.status != "active":
                raise RepositoryConflict("node is revoked")
            if row.credential_epoch != expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if row.wallet_binding_id != record.wallet_binding_id:
                raise RepositoryConflict("rotation scope conflict")
            if pending_access_token_digest == row.access_token_digest:
                raise RepositoryConflict("replacement access token must be new")
            if session.get(RetiredCredentialRow, pending_access_token_digest) is not None:
                raise RepositoryConflict("access token is retired")
            duplicate = session.execute(
                select(NodeRegistrationRow).where(
                    NodeRegistrationRow.access_token_digest
                    == pending_access_token_digest,
                    ~(
                        (NodeRegistrationRow.tenant_id == tenant_id)
                        & (NodeRegistrationRow.node_id == node_id)
                    ),
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise RepositoryConflict("access token already exists")
            session.add(
                RetiredCredentialRow(
                    access_token_digest=row.access_token_digest,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    retired_at=now,
                )
            )
            row.wallet_binding_id = record.wallet_binding_id
            row.device_public_jwk = dict(record.pending_public_jwk)
            row.device_key_id = record.pending_device_key_id
            row.access_token_digest = record.pending_access_token_digest
            row.credential_epoch = record.next_epoch
            row.status = "active"
            row.updated_at = now
            row.revocation_id = None
            record_row.status = "committed"
            record_row.committed_at = now
            return _node_from_row(row)

        return self._run(operation)

    def rotate_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        replacement: NodeRegistration,
    ) -> NodeRegistration:
        if (
            replacement.tenant_id != tenant_id
            or replacement.node_id != node_id
            or replacement.status != "active"
            or replacement.credential_epoch != expected_epoch + 1
        ):
            raise RepositoryConflict("rotation is invalid")
        current = self.get_node(tenant_id, node_id)
        if current is None:
            raise RepositoryConflict("node is revoked")
        record = HostedRotationRecord(
            rotation_id="rotation_" + secrets.token_urlsafe(18),
            tenant_id=tenant_id,
            node_id=node_id,
            wallet_binding_id=current.wallet_binding_id,
            expected_epoch=expected_epoch,
            next_epoch=expected_epoch + 1,
            pending_public_jwk=replacement.device_public_jwk,
            pending_device_key_id=replacement.device_key_id,
            pending_access_token_digest=replacement.access_token_digest,
            status="prepared",
            prepared_at=replacement.updated_at,
        )
        self.prepare_rotation(record)
        return self.commit_rotation(
            rotation_id=record.rotation_id,
            tenant_id=tenant_id,
            node_id=node_id,
            expected_epoch=expected_epoch,
            pending_access_token_digest=replacement.access_token_digest,
            now=replacement.updated_at,
        )

    def revoke_node(
        self,
        *,
        tenant_id: str,
        node_id: str,
        expected_epoch: int,
        revocation_id: str | None = None,
    ) -> NodeRegistration:
        request_revocation_id = revocation_id

        def operation(session: Session):
            effective_revocation_id = request_revocation_id
            if type(expected_epoch) is not int or expected_epoch <= 0:
                raise RepositoryConflict("credential epoch conflict")
            row = session.execute(
                select(NodeRegistrationRow)
                .where(
                    NodeRegistrationRow.tenant_id == tenant_id,
                    NodeRegistrationRow.node_id == node_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if row is None:
                raise RepositoryConflict("node is unavailable")
            if row.status == "revoked":
                if (
                    row.revocation_id == effective_revocation_id
                    and row.credential_epoch == expected_epoch + 1
                ):
                    return _node_from_row(row)
                raise RepositoryConflict("revocation request conflict")
            if row.credential_epoch != expected_epoch:
                raise RepositoryConflict("credential epoch conflict")
            if effective_revocation_id is None:
                effective_revocation_id = "revocation_" + secrets.token_urlsafe(18)
            conflicting_revocation = session.execute(
                select(NodeRegistrationRow)
                .where(
                    NodeRegistrationRow.revocation_id == effective_revocation_id,
                    ~(
                        (NodeRegistrationRow.tenant_id == tenant_id)
                        & (NodeRegistrationRow.node_id == node_id)
                    ),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if conflicting_revocation is not None:
                raise RepositoryConflict("revocation ID already exists")
            row.status = "revoked"
            row.credential_epoch += 1
            row.updated_at += 1
            row.revocation_id = effective_revocation_id
            session.add(
                RetiredCredentialRow(
                    access_token_digest=row.access_token_digest,
                    tenant_id=row.tenant_id,
                    node_id=row.node_id,
                    retired_at=row.updated_at,
                )
            )
            return _node_from_row(row)

        return self._run(operation)

    def get_revoked_node_by_access_digest(
        self,
        access_token_digest: bytes,
        *,
        tenant_id: str,
        node_id: str,
        revocation_id: str,
        expected_epoch: int,
    ) -> NodeRegistration | None:
        def operation(session: Session):
            row = session.execute(
                select(NodeRegistrationRow).where(
                    NodeRegistrationRow.tenant_id == tenant_id,
                    NodeRegistrationRow.node_id == node_id,
                    NodeRegistrationRow.access_token_digest == access_token_digest,
                    NodeRegistrationRow.revocation_id == revocation_id,
                    NodeRegistrationRow.credential_epoch == expected_epoch + 1,
                    NodeRegistrationRow.status == "revoked",
                )
            ).scalar_one_or_none()
            return _node_from_row(row) if row is not None else None

        return self._run(operation)

    def consume_dpop_jti(
        self,
        *,
        tenant_id: str,
        node_id: str,
        credential_epoch: int,
        jti: str,
        expires_at: int,
        now: int,
    ) -> bool:
        def operation(session: Session):
            session.execute(delete(DPoPReplayRow).where(DPoPReplayRow.expires_at <= now))
            row = DPoPReplayRow(
                replay_id=f"dpop_{secrets.token_urlsafe(18)}",
                tenant_id=tenant_id,
                node_id=node_id,
                credential_epoch=credential_epoch,
                jti=jti,
                expires_at=expires_at,
                created_at=now,
            )
            session.add(row)
            try:
                with session.begin_nested():
                    session.flush()
            except IntegrityError:
                return False
            return True

        return self._run(operation)

    def bind_preflight(self, record: PreflightRecord) -> PreflightRecord:
        def operation(session: Session):
            existing = session.execute(
                select(PreflightRow).where(
                    PreflightRow.tenant_id == record.tenant_id,
                    PreflightRow.node_id == record.node_id,
                    PreflightRow.idempotency_key == record.idempotency_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                current = _preflight_from_row(existing)
                if current.request_hash == record.request_hash:
                    return current
                raise RepositoryConflict("idempotency key conflict")
            for column, value, detail in (
                (PreflightRow.request_id, record.request_id, "request ID conflict"),
                (PreflightRow.request_nonce, record.request_nonce, "request nonce replay"),
                (PreflightRow.capability_hash, record.capability_hash, "capability hash conflict"),
                (PreflightRow.reservation_id, record.reservation_id, "reservation conflict"),
            ):
                if session.execute(
                    select(PreflightRow).where(
                        PreflightRow.tenant_id == record.tenant_id,
                        PreflightRow.node_id == record.node_id,
                        column == value,
                    )
                ).scalar_one_or_none() is not None:
                    raise RepositoryConflict(detail)
            try:
                with session.begin_nested():
                    session.add(
                        PreflightRow(
                            record_id=f"preflight_{secrets.token_urlsafe(18)}",
                            tenant_id=record.tenant_id,
                            node_id=record.node_id,
                            request_id=record.request_id,
                            idempotency_key=record.idempotency_key,
                            request_nonce=record.request_nonce,
                            capability_hash=record.capability_hash,
                            reservation_id=record.reservation_id,
                            request_hash=record.request_hash,
                            signed_response_jws=record.signed_response_jws,
                            created_at=record.created_at,
                        )
                    )
                    session.flush()
            except IntegrityError as exc:
                existing = session.execute(
                    select(PreflightRow)
                    .where(
                        PreflightRow.tenant_id == record.tenant_id,
                        PreflightRow.node_id == record.node_id,
                        PreflightRow.idempotency_key == record.idempotency_key,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if existing is not None:
                    current = _preflight_from_row(existing)
                    if current.request_hash == record.request_hash:
                        return current
                    raise RepositoryConflict("idempotency key conflict") from exc
                raise
            return record

        return self._run(operation)


def _node_row(node: NodeRegistration) -> NodeRegistrationRow:
    return NodeRegistrationRow(
        tenant_id=node.tenant_id,
        node_id=node.node_id,
        wallet_binding_id=node.wallet_binding_id,
        device_public_jwk=dict(node.device_public_jwk),
        device_key_id=node.device_key_id,
        access_token_digest=node.access_token_digest,
        credential_epoch=node.credential_epoch,
        status=node.status,
        created_at=node.created_at,
        updated_at=node.updated_at,
        revocation_id=node.revocation_id,
    )


def _rotation_row(record: HostedRotationRecord) -> HostedRotationRow:
    return HostedRotationRow(
        rotation_id=record.rotation_id,
        tenant_id=record.tenant_id,
        node_id=record.node_id,
        wallet_binding_id=record.wallet_binding_id,
        expected_epoch=record.expected_epoch,
        next_epoch=record.next_epoch,
        pending_public_jwk=dict(record.pending_public_jwk),
        pending_device_key_id=record.pending_device_key_id,
        pending_access_token_digest=record.pending_access_token_digest,
        status=record.status,
        prepared_at=record.prepared_at,
        committed_at=record.committed_at,
    )


def _apply_node_row(row: NodeRegistrationRow, node: NodeRegistration) -> None:
    row.wallet_binding_id = node.wallet_binding_id
    row.device_public_jwk = dict(node.device_public_jwk)
    row.device_key_id = node.device_key_id
    row.access_token_digest = node.access_token_digest
    row.credential_epoch = node.credential_epoch
    row.status = node.status
    row.updated_at = node.updated_at
    row.revocation_id = node.revocation_id


def _preflight_from_row(row: PreflightRow) -> PreflightRecord:
    return PreflightRecord(
        tenant_id=row.tenant_id,
        node_id=row.node_id,
        request_id=row.request_id,
        idempotency_key=row.idempotency_key,
        request_nonce=row.request_nonce,
        capability_hash=row.capability_hash,
        reservation_id=row.reservation_id,
        request_hash=row.request_hash,
        signed_response_jws=row.signed_response_jws,
        created_at=row.created_at,
    )
