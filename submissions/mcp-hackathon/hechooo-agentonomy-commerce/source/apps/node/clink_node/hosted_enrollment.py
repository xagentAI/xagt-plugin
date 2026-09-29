from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .secrets import RestrictedFileSecretStore, SecretStore


_SECRET_NAME = "hosted-enrollment-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,8192}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
_STATES = frozenset(
    {
        "enrollment_pending",
        "active",
        "rotation_pending",
        "revocation_pending",
    }
)
_BUNDLE_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "wallet_binding_id",
        "tenant_id",
        "node_id",
        "credential_epoch",
        "private_key_pkcs8_b64",
        "access_token",
        "trust_fingerprint",
        "invite_digest",
        "rotation_id",
        "pending_private_key_pkcs8_b64",
        "pending_access_token",
        "rotation_prepared",
        "revocation_pending",
        "revocation_id",
    }
)

# A manager may be recreated after a response is lost.  Keep the default lock
# tied to the store's identity so managers operating on one store serialize
# their read/persist/remote/persist sequence together.  File-backed stores use
# a second registry keyed by canonical backing path so separate store objects
# in one process share the same descriptor and reentrant depth.
_DEFAULT_MUTATION_LOCKS: dict[int, tuple[object, AbstractContextManager[object]]] = {}
_DEFAULT_MUTATION_LOCKS_GUARD = threading.Lock()
_FILE_MUTATION_LOCKS: dict[str, "_FileMutationLockState"] = {}
_FILE_MUTATION_LOCKS_GUARD = threading.Lock()


class EnrollmentConflict(RuntimeError):
    """The local enrollment state conflicts with the requested operation."""


class EnrollmentRequestNotDispatched(RuntimeError):
    """The transport confirms that a request never reached the remote."""


@dataclass(frozen=True, slots=True)
class HostedTargetTrust:
    chain_id: int
    endpoint: str
    response_public_jwk: Mapping[str, str]
    executor_contract: str
    response_key_id: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.chain_id) is not int or self.chain_id not in {8453, 137}:
            raise ValueError("Hosted target chain is unsupported")
        _canonical_https_origin(self.endpoint)
        if (
            type(self.executor_contract) is not str
            or _EVM_ADDRESS.fullmatch(self.executor_contract) is None
            or self.executor_contract == "0x" + "0" * 40
        ):
            raise ValueError("Hosted target executor contract is invalid")
        normalized, thumbprint = _validate_public_jwk(self.response_public_jwk)
        object.__setattr__(
            self,
            "response_public_jwk",
            MappingProxyType(normalized),
        )
        object.__setattr__(self, "response_key_id", thumbprint)


@dataclass(frozen=True, slots=True)
class EnrollmentTrust:
    enrollment_endpoint: str
    targets: Mapping[int, HostedTargetTrust]
    trust_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _canonical_enrollment_endpoint(self.enrollment_endpoint)
        if not isinstance(self.targets, Mapping):
            raise ValueError("Hosted trust targets are invalid")
        targets = dict(self.targets)
        if set(targets) != {8453, 137}:
            raise ValueError("Hosted trust must contain exact Base and Polygon targets")
        if any(
            type(chain_id) is not int
            or type(target) is not HostedTargetTrust
            or chain_id != target.chain_id
            for chain_id, target in targets.items()
        ):
            raise ValueError("Hosted target chain does not match its trust key")
        object.__setattr__(self, "targets", MappingProxyType(targets))
        object.__setattr__(self, "trust_fingerprint", _trust_fingerprint(self))


@dataclass(frozen=True, slots=True)
class EnrollmentAuthentication:
    tenant_id: str
    node_id: str
    credential_epoch: int
    private_key_pkcs8_b64: str = field(repr=False)
    access_token: str = field(repr=False)


class EnrollmentTransport(Protocol):
    @property
    def endpoint(self) -> str: ...

    def enroll(self, request: dict[str, object]) -> dict[str, object]: ...

    def prepare_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]: ...

    def commit_rotation(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]: ...

    def revoke(
        self,
        request: dict[str, object],
        *,
        authentication: EnrollmentAuthentication,
    ) -> dict[str, object]: ...


class _FileMutationLockState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.gate = threading.RLock()
        self.depth = 0
        self.descriptor: int | None = None


class _FileMutationLock(AbstractContextManager[object]):
    def __init__(self, state: _FileMutationLockState) -> None:
        self._state = state

    def __enter__(self) -> "_FileMutationLock":
        self._state.gate.acquire()
        if self._state.depth == 0:
            try:
                descriptor = _open_file_mutation_lock(self._state.path)
            except BaseException:
                self._state.gate.release()
                raise
            self._state.descriptor = descriptor
        self._state.depth += 1
        return self

    def __exit__(self, *args: object) -> None:
        if self._state.depth <= 0 or self._state.descriptor is None:
            self._state.gate.release()
            raise RuntimeError("hosted mutation lock is not held")
        self._state.depth -= 1
        try:
            if self._state.depth == 0:
                descriptor = self._state.descriptor
                self._state.descriptor = None
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        finally:
            self._state.gate.release()


def _shared_mutation_lock(store: SecretStore) -> AbstractContextManager[object]:
    key = id(store)
    with _DEFAULT_MUTATION_LOCKS_GUARD:
        existing = _DEFAULT_MUTATION_LOCKS.get(key)
        if existing is not None and existing[0] is store:
            return existing[1]
        if isinstance(store, RestrictedFileSecretStore):
            lock = _file_mutation_lock_for_store(store)
        else:
            lock = threading.RLock()
        _DEFAULT_MUTATION_LOCKS[key] = (store, lock)
        return lock


def _file_mutation_lock_for_store(
    store: RestrictedFileSecretStore,
) -> AbstractContextManager[object]:
    backing_path = _canonical_backing_path(store.path)
    lock_path = backing_path.parent / "hosted-enrollment.lock"
    key = os.fspath(lock_path)
    with _FILE_MUTATION_LOCKS_GUARD:
        state = _FILE_MUTATION_LOCKS.get(key)
        if state is None:
            state = _FileMutationLockState(lock_path)
            _FILE_MUTATION_LOCKS[key] = state
    return _FileMutationLock(state)


def _canonical_backing_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _open_file_mutation_lock(path: Path) -> int:
    _validate_file_mutation_parent(path.parent)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EISDIR, errno.ENOTDIR}:
            raise PermissionError(
                f"hosted mutation lock must be a regular file: {path}"
            ) from None
        raise
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise PermissionError(
                f"hosted mutation lock must be owner-only: {path}"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_file_mutation_parent(parent: Path) -> None:
    try:
        metadata = os.lstat(parent)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"hosted mutation lock directory does not exist: {parent}"
        ) from None
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PermissionError(
            f"hosted mutation lock directory is not owner-only: {parent}"
        )


@dataclass(frozen=True, slots=True)
class HostedEnrollmentBundle:
    state: Literal[
        "enrollment_pending",
        "active",
        "rotation_pending",
        "revocation_pending",
    ]
    wallet_binding_id: str
    tenant_id: str
    node_id: str
    credential_epoch: int
    private_key_pkcs8_b64: str = field(repr=False)
    access_token: str = field(repr=False)
    trust_fingerprint: str = field(repr=False)
    invite_digest: str | None = field(default=None, repr=False)
    rotation_id: str | None = None
    pending_private_key_pkcs8_b64: str | None = field(default=None, repr=False)
    pending_access_token: str | None = field(default=None, repr=False)
    rotation_prepared: bool = False
    revocation_pending: bool = False
    revocation_id: str | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not str or self.state not in _STATES:
            raise ValueError("state is invalid")
        _require_identifier(self.wallet_binding_id, "wallet_binding_id")
        _validate_token(self.access_token, "access_token")
        _load_private_key(self.private_key_pkcs8_b64)
        if not _is_sha256_hex(self.trust_fingerprint):
            raise ValueError("trust_fingerprint is invalid")
        if type(self.rotation_prepared) is not bool:
            raise ValueError("rotation_prepared is invalid")
        if type(self.revocation_pending) is not bool:
            raise ValueError("revocation_pending is invalid")
        if self.state == "enrollment_pending":
            if (
                type(self.tenant_id) is not str
                or type(self.node_id) is not str
                or self.tenant_id
                or self.node_id
                or type(self.credential_epoch) is not int
                or self.credential_epoch != 0
            ):
                raise ValueError("pending enrollment identity is invalid")
            if not _is_sha256_hex(self.invite_digest):
                raise ValueError("pending enrollment invite digest is invalid")
            if self.rotation_id is not None or self.pending_access_token is not None:
                raise ValueError("pending enrollment rotation state is invalid")
        else:
            _require_identifier(self.tenant_id, "tenant_id")
            _require_identifier(self.node_id, "node_id")
            if type(self.credential_epoch) is not int or self.credential_epoch <= 0:
                raise ValueError("credential_epoch is invalid")
            if self.invite_digest is not None:
                raise ValueError("active enrollment must not retain invite state")
        if self.state == "rotation_pending":
            _require_identifier(self.rotation_id, "rotation_id")
            if self.pending_private_key_pkcs8_b64 is None:
                raise ValueError("pending rotation key is required")
            _load_private_key(self.pending_private_key_pkcs8_b64)
            _validate_token(self.pending_access_token, "pending_access_token")
        elif any(
            value is not None
            for value in (
                self.rotation_id,
                self.pending_private_key_pkcs8_b64,
                self.pending_access_token,
            )
        ) or self.rotation_prepared:
            raise ValueError("inactive rotation state is invalid")
        if self.state == "revocation_pending":
            if not self.revocation_pending:
                raise ValueError("pending revocation marker is required")
            _require_identifier(self.revocation_id, "revocation_id")
        elif self.revocation_pending or self.revocation_id is not None:
            raise ValueError("inactive revocation state is invalid")
        if self.state == "enrollment_pending" and self.revocation_pending:
            raise ValueError("pending enrollment revocation state is invalid")

    @property
    def public_jwk(self) -> dict[str, str]:
        return _public_jwk(_load_private_key(self.private_key_pkcs8_b64))

    @property
    def device_key_id(self) -> str:
        return _jwk_thumbprint(self.public_jwk)

    @property
    def access_token_digest(self) -> str:
        return _sha256_b64(self.access_token.encode("ascii"))

    def authentication(self) -> EnrollmentAuthentication:
        if self.state != "active":
            raise EnrollmentConflict("only active enrollment is authenticated")
        return self._active_authentication()

    def _active_authentication(self) -> EnrollmentAuthentication:
        if self.state != "active":
            raise EnrollmentConflict("only active enrollment is authenticated")
        return EnrollmentAuthentication(
            tenant_id=self.tenant_id,
            node_id=self.node_id,
            credential_epoch=self.credential_epoch,
            private_key_pkcs8_b64=self.private_key_pkcs8_b64,
            access_token=self.access_token,
        )

    def _rotation_prepare_authentication(self) -> EnrollmentAuthentication:
        if self.state != "rotation_pending" or self.rotation_prepared:
            raise EnrollmentConflict("rotation prepare requires an unprepared rotation")
        return self._credential_authentication(
            credential_epoch=self.credential_epoch,
            private_key_pkcs8_b64=self.private_key_pkcs8_b64,
            access_token=self.access_token,
        )

    def _pending_commit_authentication(self) -> EnrollmentAuthentication:
        if self.state != "rotation_pending" or not self.rotation_prepared:
            raise EnrollmentConflict("pending commit requires a prepared rotation")
        assert self.pending_private_key_pkcs8_b64 is not None
        assert self.pending_access_token is not None
        return self._credential_authentication(
            credential_epoch=self.credential_epoch + 1,
            private_key_pkcs8_b64=self.pending_private_key_pkcs8_b64,
            access_token=self.pending_access_token,
        )

    def _revocation_authentication(self) -> EnrollmentAuthentication:
        if self.state != "revocation_pending" or not self.revocation_pending:
            raise EnrollmentConflict("pending revocation is not authenticated")
        return self._credential_authentication(
            credential_epoch=self.credential_epoch,
            private_key_pkcs8_b64=self.private_key_pkcs8_b64,
            access_token=self.access_token,
        )

    def _credential_authentication(
        self,
        *,
        credential_epoch: int,
        private_key_pkcs8_b64: str,
        access_token: str,
    ) -> EnrollmentAuthentication:
        return EnrollmentAuthentication(
            tenant_id=self.tenant_id,
            node_id=self.node_id,
            credential_epoch=credential_epoch,
            private_key_pkcs8_b64=private_key_pkcs8_b64,
            access_token=access_token,
        )


class HostedEnrollmentManager:
    def __init__(
        self,
        *,
        secret_store: SecretStore,
        transport: EnrollmentTransport,
        trust: EnrollmentTrust,
        mutation_lock: AbstractContextManager[object] | None = None,
    ) -> None:
        self._store = secret_store
        self._transport = transport
        self.trust = trust
        try:
            transport_endpoint = transport.endpoint
        except Exception as exc:
            raise ValueError("transport endpoint is invalid") from exc
        if (
            type(transport_endpoint) is not str
            or transport_endpoint != trust.enrollment_endpoint
        ):
            raise ValueError("transport endpoint does not match enrollment trust")
        if mutation_lock is not None and isinstance(
            secret_store,
            RestrictedFileSecretStore,
        ):
            raise ValueError(
                "file-backed enrollment requires its canonical mutation lock"
            )
        if mutation_lock is None:
            self._mutation_lock = _shared_mutation_lock(secret_store)
        else:
            key = id(secret_store)
            with _DEFAULT_MUTATION_LOCKS_GUARD:
                existing = _DEFAULT_MUTATION_LOCKS.get(key)
                if existing is not None and existing[0] is secret_store:
                    if existing[1] is not mutation_lock:
                        raise ValueError(
                            "a different mutation lock is already registered"
                        )
                else:
                    _DEFAULT_MUTATION_LOCKS[key] = (secret_store, mutation_lock)
            self._mutation_lock = mutation_lock

    def current(self) -> HostedEnrollmentBundle | None:
        with self._mutation_lock:
            return self._current_unlocked()

    def _current_unlocked(self) -> HostedEnrollmentBundle | None:
        encoded = self._store.get(_SECRET_NAME)
        if encoded is None:
            return None
        bundle = _decode_bundle(encoded)
        if bundle.trust_fingerprint != self.trust.trust_fingerprint:
            raise EnrollmentConflict("Enrollment trust fingerprint does not match")
        return bundle

    def enroll(
        self,
        *,
        invite_code: str,
        wallet_binding_id: str,
    ) -> HostedEnrollmentBundle:
        invite_code = _validate_token(invite_code, "invite_code")
        _require_identifier(wallet_binding_id, "wallet_binding_id")
        with self._mutation_lock:
            return self._enroll_locked(
                invite_code=invite_code,
                wallet_binding_id=wallet_binding_id,
            )

    def _enroll_locked(
        self,
        *,
        invite_code: str,
        wallet_binding_id: str,
    ) -> HostedEnrollmentBundle:
        invite_digest = hashlib.sha256(invite_code.encode("ascii")).hexdigest()
        bundle = self._current_unlocked()
        if bundle is not None and bundle.state != "enrollment_pending":
            raise EnrollmentConflict("Node is already enrolled")
        if bundle is None:
            private_key = ec.generate_private_key(ec.SECP256R1())
            bundle = HostedEnrollmentBundle(
                state="enrollment_pending",
                wallet_binding_id=wallet_binding_id,
                tenant_id="",
                node_id="",
                credential_epoch=0,
                private_key_pkcs8_b64=_serialize_private_key(private_key),
                access_token=secrets.token_urlsafe(32),
                trust_fingerprint=self.trust.trust_fingerprint,
                invite_digest=invite_digest,
            )
            self._save(bundle)
        elif (
            bundle.invite_digest != invite_digest
            or bundle.wallet_binding_id != wallet_binding_id
        ):
            raise EnrollmentConflict("Pending enrollment does not match this request")

        request = {
            "token": invite_code,
            "wallet_binding_id": bundle.wallet_binding_id,
            "expected_epoch": bundle.credential_epoch,
            "next_epoch": 1,
            "public_jwk": bundle.public_jwk,
            "device_key_id": bundle.device_key_id,
            "access_token_digest": bundle.access_token_digest,
            "status": "pending",
        }
        response = self._transport.enroll(request)
        _validate_enrollment_response(
            response,
            bundle=bundle,
            expected_epoch=bundle.credential_epoch,
            next_epoch=1,
        )
        tenant_id = _response_identifier(response, "tenant_id")
        node_id = _response_identifier(response, "node_id")
        credential_epoch = _response_epoch(response, "credential_epoch")
        _expect_equal(response, "credential_epoch", 1)
        active = replace(
            bundle,
            state="active",
            tenant_id=tenant_id,
            node_id=node_id,
            credential_epoch=credential_epoch,
            invite_digest=None,
        )
        self._save(active)
        return active

    def rotate(self) -> HostedEnrollmentBundle:
        with self._mutation_lock:
            return self._rotate_locked()

    def _rotate_locked(self) -> HostedEnrollmentBundle:
        bundle = self._current_unlocked()
        if bundle is None or bundle.state != "active":
            raise EnrollmentConflict("An active enrollment is required")
        pending_key = ec.generate_private_key(ec.SECP256R1())
        pending = replace(
            bundle,
            state="rotation_pending",
            rotation_id="rotation_" + secrets.token_urlsafe(18),
            pending_private_key_pkcs8_b64=_serialize_private_key(pending_key),
            pending_access_token=secrets.token_urlsafe(32),
            rotation_prepared=False,
        )
        self._save(pending)
        return self._resume_rotation_locked(pending)

    def resume_rotation(self) -> HostedEnrollmentBundle:
        with self._mutation_lock:
            bundle = self._current_unlocked()
            if bundle is None or bundle.state != "rotation_pending":
                raise EnrollmentConflict("No pending rotation exists")
            return self._resume_rotation_locked(bundle)

    def revoke(self) -> None:
        with self._mutation_lock:
            self._revoke_locked()

    def _revoke_locked(self) -> None:
        bundle = self._current_unlocked()
        if bundle is None or bundle.state not in {"active", "rotation_pending"}:
            raise EnrollmentConflict("An active enrollment is required")
        if bundle.state == "rotation_pending":
            # A revocation must target the generation that actually exists on
            # the remote.  First converge the idempotent rotation, preserving
            # rotation_pending on any recovery failure; only then prepare the
            # revocation for the resulting active generation.
            bundle = self._resume_rotation_locked(bundle)
        pending = replace(
            bundle,
            state="revocation_pending",
            rotation_id=None,
            pending_private_key_pkcs8_b64=None,
            pending_access_token=None,
            rotation_prepared=False,
            revocation_pending=True,
            revocation_id=(
                "revocation_" + secrets.token_urlsafe(18)
                if bundle.revocation_id is None
                else bundle.revocation_id
            ),
        )
        self._save(pending)
        try:
            self._resume_revocation_locked(pending)
        except EnrollmentRequestNotDispatched:
            # Only an explicit transport guarantee that no request was sent
            # permits rolling back.  `bundle` is the freshly converged active
            # generation, never the stale rotation generation.
            self._save(bundle)
            raise

    def resume_revocation(self) -> None:
        with self._mutation_lock:
            bundle = self._current_unlocked()
            if bundle is None or bundle.state != "revocation_pending":
                raise EnrollmentConflict("No pending revocation exists")
            self._resume_revocation_locked(bundle)

    def _resume_rotation_locked(
        self,
        bundle: HostedEnrollmentBundle,
    ) -> HostedEnrollmentBundle:
        assert bundle.rotation_id is not None
        assert bundle.pending_private_key_pkcs8_b64 is not None
        assert bundle.pending_access_token is not None
        pending_key = _load_private_key(bundle.pending_private_key_pkcs8_b64)
        pending_jwk = _public_jwk(pending_key)
        pending_key_id = _jwk_thumbprint(pending_jwk)
        pending_digest = _sha256_b64(bundle.pending_access_token.encode("ascii"))
        next_epoch = bundle.credential_epoch + 1
        common = {
            "rotation_id": bundle.rotation_id,
            "tenant_id": bundle.tenant_id,
            "node_id": bundle.node_id,
            "wallet_binding_id": bundle.wallet_binding_id,
            "expected_epoch": bundle.credential_epoch,
            "next_epoch": next_epoch,
            "public_jwk": pending_jwk,
            "device_key_id": pending_key_id,
            "access_token_digest": pending_digest,
        }
        if not bundle.rotation_prepared:
            prepared = self._transport.prepare_rotation(
                common,
                authentication=bundle._rotation_prepare_authentication(),
            )
            _validate_rotation_response(
                prepared,
                common,
                status="prepared",
            )
            bundle = replace(bundle, rotation_prepared=True)
            self._save(bundle)
        committed = self._transport.commit_rotation(
            common,
            authentication=bundle._pending_commit_authentication(),
        )
        _validate_rotation_response(
            committed,
            common,
            status="active",
        )
        _expect_equal(committed, "credential_epoch", next_epoch)
        active = replace(
            bundle,
            state="active",
            credential_epoch=next_epoch,
            private_key_pkcs8_b64=bundle.pending_private_key_pkcs8_b64,
            access_token=bundle.pending_access_token,
            rotation_id=None,
            pending_private_key_pkcs8_b64=None,
            pending_access_token=None,
            rotation_prepared=False,
            revocation_pending=False,
            revocation_id=None,
        )
        self._save(active)
        return active

    def _resume_revocation_locked(self, bundle: HostedEnrollmentBundle) -> None:
        assert bundle.state == "revocation_pending"
        assert bundle.revocation_id is not None
        expected_epoch = bundle.credential_epoch
        next_epoch = expected_epoch + 1
        request = {
            "revocation_id": bundle.revocation_id,
            "tenant_id": bundle.tenant_id,
            "node_id": bundle.node_id,
            "wallet_binding_id": bundle.wallet_binding_id,
            "credential_epoch": expected_epoch,
            "expected_epoch": expected_epoch,
            "next_epoch": next_epoch,
            "device_key_id": bundle.device_key_id,
            "access_token_digest": bundle.access_token_digest,
            "status": "revoking",
        }
        response = self._transport.revoke(
            request,
            authentication=bundle._revocation_authentication(),
        )
        _validate_revocation_response(
            response,
            request=request,
            next_epoch=next_epoch,
        )
        self._store.delete(_SECRET_NAME)

    def _save(self, bundle: HostedEnrollmentBundle) -> None:
        self._store.set(_SECRET_NAME, _encode_bundle(bundle))


def _validate_rotation_response(
    response: dict[str, object],
    expected: dict[str, object],
    *,
    status: str,
) -> None:
    if not isinstance(response, dict):
        raise EnrollmentConflict("Enrollment response is invalid")
    for key in (
        "rotation_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
        "device_key_id",
        "access_token_digest",
    ):
        _expect_equal(response, key, expected[key])
    _expect_equal(response, "expected_epoch", expected["expected_epoch"])
    _expect_equal(response, "next_epoch", expected["next_epoch"])
    _expect_equal(response, "status", status)


def _validate_enrollment_response(
    response: dict[str, object],
    *,
    bundle: HostedEnrollmentBundle,
    expected_epoch: int,
    next_epoch: int,
) -> None:
    if not isinstance(response, dict):
        raise EnrollmentConflict("Enrollment response is invalid")
    _expect_equal(response, "wallet_binding_id", bundle.wallet_binding_id)
    _expect_equal(response, "device_key_id", bundle.device_key_id)
    _expect_equal(response, "access_token_digest", bundle.access_token_digest)
    _expect_equal(response, "expected_epoch", expected_epoch)
    _expect_equal(response, "next_epoch", next_epoch)
    _expect_equal(response, "status", "active")
    _response_identifier(response, "tenant_id")
    _response_identifier(response, "node_id")


def _validate_revocation_response(
    response: dict[str, object],
    *,
    request: dict[str, object],
    next_epoch: int,
) -> None:
    if not isinstance(response, dict):
        raise EnrollmentConflict("Revocation response is invalid")
    for key in (
        "revocation_id",
        "tenant_id",
        "node_id",
        "wallet_binding_id",
    ):
        _expect_equal(response, key, request[key])
    _expect_equal(response, "expected_epoch", request["expected_epoch"])
    _expect_equal(response, "next_epoch", next_epoch)
    _expect_equal(response, "device_key_id", request["device_key_id"])
    _expect_equal(response, "access_token_digest", request["access_token_digest"])
    _expect_equal(response, "status", "revoked")
    _expect_equal(response, "credential_epoch", next_epoch)


def _encode_bundle(bundle: HostedEnrollmentBundle) -> bytes:
    payload = {
        "schema_version": 1,
        "state": bundle.state,
        "wallet_binding_id": bundle.wallet_binding_id,
        "tenant_id": bundle.tenant_id,
        "node_id": bundle.node_id,
        "credential_epoch": bundle.credential_epoch,
        "private_key_pkcs8_b64": bundle.private_key_pkcs8_b64,
        "access_token": bundle.access_token,
        "trust_fingerprint": bundle.trust_fingerprint,
        "invite_digest": bundle.invite_digest,
        "rotation_id": bundle.rotation_id,
        "pending_private_key_pkcs8_b64": bundle.pending_private_key_pkcs8_b64,
        "pending_access_token": bundle.pending_access_token,
        "rotation_prepared": bundle.rotation_prepared,
        "revocation_pending": bundle.revocation_pending,
        "revocation_id": bundle.revocation_id,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _decode_bundle(encoded: bytes) -> HostedEnrollmentBundle:
    if type(encoded) is not bytes or len(encoded) > 64 * 1024:
        raise ValueError("Hosted enrollment bundle is invalid")
    try:
        payload = json.loads(
            encoded.decode("ascii"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("Hosted enrollment bundle is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != _BUNDLE_KEYS:
        raise ValueError("Hosted enrollment bundle is invalid")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ValueError("Hosted enrollment bundle version is unsupported")
    payload = {
        key: value for key, value in payload.items() if key != "schema_version"
    }
    try:
        return HostedEnrollmentBundle(**payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("Hosted enrollment bundle is invalid") from exc


def _reject_duplicate_json_keys(
    pairs: list[tuple[object, object]],
) -> dict[object, object]:
    result: dict[object, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _serialize_private_key(private_key: ec.EllipticCurvePrivateKey) -> str:
    encoded = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return _b64url(encoded)


def _load_private_key(encoded: object) -> ec.EllipticCurvePrivateKey:
    if type(encoded) is not str or not encoded:
        raise ValueError("device private key is invalid")
    try:
        key = serialization.load_der_private_key(_b64url_decode(encoded), password=None)
    except (TypeError, ValueError) as exc:
        raise ValueError("device private key is invalid") from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise ValueError("device private key must use P-256")
    return key


def _public_jwk(private_key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    public = private_key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(public.x.to_bytes(32, "big")),
        "y": _b64url(public.y.to_bytes(32, "big")),
    }


def _validate_public_jwk(value: object) -> tuple[dict[str, str], str]:
    if not isinstance(value, Mapping) or set(value) != {"kty", "crv", "x", "y"}:
        raise ValueError("response public JWK is invalid")
    if (
        type(value.get("kty")) is not str
        or type(value.get("crv")) is not str
        or value.get("kty") != "EC"
        or value.get("crv") != "P-256"
    ):
        raise ValueError("response public JWK must use P-256")
    if any(type(value.get(key)) is not str for key in ("x", "y")):
        raise ValueError("response public JWK is invalid")
    try:
        x = int.from_bytes(_b64url_decode(value["x"]), "big")
        y = int.from_bytes(_b64url_decode(value["y"]), "big")
        if len(_b64url_decode(value["x"])) != 32 or len(_b64url_decode(value["y"])) != 32:
            raise ValueError
        ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("response public JWK is invalid") from exc
    normalized = {key: value[key] for key in ("kty", "crv", "x", "y")}
    return normalized, _jwk_thumbprint(normalized)


def _jwk_thumbprint(jwk: dict[str, str]) -> str:
    canonical = json.dumps(
        {key: jwk[key] for key in ("crv", "kty", "x", "y")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return _sha256_b64(canonical)


def _trust_fingerprint(trust: EnrollmentTrust) -> str:
    canonical = json.dumps(
        {
            "enrollment_endpoint": _canonical_https_url(
                trust.enrollment_endpoint,
                origin=False,
            ),
            "targets": [
                {
                    "chain_id": chain_id,
                    "endpoint": _canonical_https_url(
                        trust.targets[chain_id].endpoint,
                        origin=True,
                    ),
                    "executor_contract": trust.targets[chain_id].executor_contract,
                    "response_key_id": trust.targets[chain_id].response_key_id,
                }
                for chain_id in (8453, 137)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_enrollment_endpoint(value: object) -> str:
    if type(value) is not str or not value or _contains_non_ascii(value):
        raise ValueError("Hosted enrollment endpoint must be canonical HTTPS")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Hosted enrollment endpoint must be canonical HTTPS") from exc
    if (
        parsed.scheme.lower() != "https"
        or "%" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1/enrollments"
        or not parsed.hostname
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("Hosted enrollment endpoint must be canonical HTTPS")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port in (None, 443) else f"{hostname}:{port}"
    normalized = urlunsplit(("https", netloc, "/v1/enrollments", "", ""))
    if normalized != value:
        raise ValueError("Hosted enrollment endpoint must be canonical HTTPS")
    return normalized


def _canonical_https_origin(value: object) -> str:
    if type(value) is not str or not value or _contains_non_ascii(value):
        raise ValueError("Hosted target endpoint must be canonical HTTPS origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("Hosted target endpoint must be canonical HTTPS origin") from exc
    if (
        parsed.scheme.lower() != "https"
        or "%" in parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
        or port is not None and not 1 <= port <= 65535
    ):
        raise ValueError("Hosted target endpoint must be canonical HTTPS origin")
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port in (None, 443) else f"{hostname}:{port}"
    normalized = urlunsplit(("https", netloc, "", "", ""))
    if normalized != value:
        raise ValueError("Hosted target endpoint must be canonical HTTPS origin")
    return normalized


def _canonical_https_url(value: str, *, origin: bool) -> str:
    return _canonical_https_origin(value) if origin else _canonical_enrollment_endpoint(value)


def _contains_non_ascii(value: str) -> bool:
    return any(
        ord(character) > 0x7F
        or ord(character) < 0x20
        or ord(character) == 0x7F
        for character in value
    )


def _require_identifier(value: object, field_name: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _validate_token(value: object, field_name: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _response_identifier(response: dict[str, object], key: str) -> str:
    return _require_identifier(response.get(key), key)


def _response_epoch(response: dict[str, object], key: str) -> int:
    value = response.get(key)
    if type(value) is not int or value <= 0:
        raise EnrollmentConflict(f"Enrollment response {key} is invalid")
    return value


def _expect_equal(response: dict[str, object], key: str, expected: object) -> None:
    actual = response.get(key) if isinstance(response, dict) else None
    if type(actual) is not type(expected) or actual != expected:
        raise EnrollmentConflict(f"Enrollment response {key} does not match")


def _expect_if_present(
    response: dict[str, object],
    key: str,
    expected: object,
) -> None:
    if key in response:
        _expect_equal(response, key, expected)


def _is_sha256_hex(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _sha256_b64(value: bytes) -> str:
    return _b64url(hashlib.sha256(value).digest())


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: object) -> bytes:
    if type(value) is not str or not value:
        raise ValueError("base64url value is invalid")
    if re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise ValueError("base64url value is invalid")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except ValueError as exc:
        raise ValueError("base64url value is invalid") from exc
    if _b64url(decoded) != value:
        raise ValueError("base64url value is not canonical")
    return decoded
