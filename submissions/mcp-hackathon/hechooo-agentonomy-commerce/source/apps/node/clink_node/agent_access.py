from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Callable

from .storage.agent_access import (
    AgentAccessRepository,
    AgentBindingRecord,
    RuntimeCredentialRecord,
    _AgentAccessRepositoryConflict,
    _AgentAccessRepositoryNotFound,
)


_MAX_IDENTIFIER_LENGTH = 256
_MAX_USER_ID_LENGTH = 96
_TOKEN_PREFIX = "clink_rt_v1_"
_OPC_TOKEN_PREFIX = "agentonomy_opc_v1_"
_TOKEN_DOMAIN = b"clink-agent-runtime-token:v1\x00"
_ALLOWED_SCOPES = frozenset({"read", "payments"})


class AgentAccessError(ValueError):
    """A stable, coded Agent access failure."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class AgentAccessUnauthorizedError(AgentAccessError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__("unauthorized", message)


class AgentAccessNotFoundError(AgentAccessError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__("not_found", message)


class AgentAccessConflictError(AgentAccessError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__("conflict", message)


@dataclass(frozen=True, slots=True)
class AgentBinding:
    agent_id: str
    user_id: str
    issuer: str
    subject_id: str
    external_agent_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedRuntimeCredential:
    credential_id: str
    agent_id: str
    runtime_id: str
    scope: str
    expires_at: datetime
    access_token: str = field(repr=False)
    issued_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimePrincipal:
    user_id: str
    agent_id: str
    runtime_id: str
    credential_id: str
    issuer: str
    scope: str
    expires_at: datetime
    # Set only for an OPC credential.  It is never accepted from a public
    # tool argument; the Core-backed authenticator supplies it.
    opc_installation_id: str | None = None


class CompositeRuntimeAuthenticator:
    """Route C and OPC runtime bearers by their exact versioned prefix.

    A recognized prefix selects exactly one backend.  Backend failures are
    propagated and never retried through the other backend, which prevents a
    malformed/failed credential from becoming an identity confusion fallback.
    """

    def __init__(self, c_authenticator=None, opc_authenticator=None) -> None:
        self.c_authenticator = c_authenticator
        self.opc_authenticator = opc_authenticator

    def authenticate(self, token: str) -> RuntimePrincipal:
        if not isinstance(token, str):
            raise AgentAccessUnauthorizedError()
        if token.startswith(_TOKEN_PREFIX):
            if self.c_authenticator is None:
                raise AgentAccessUnauthorizedError()
            return self.c_authenticator.authenticate(token)
        if token.startswith(_OPC_TOKEN_PREFIX):
            if self.opc_authenticator is None:
                raise AgentAccessUnauthorizedError()
            return self.opc_authenticator.authenticate(token)
        raise AgentAccessUnauthorizedError()


class AgentAccessService:
    def __init__(
        self,
        repository: AgentAccessRepository,
        *,
        issuer: str,
        token_key: bytes,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.issuer = _validate_identifier(issuer)
        if not isinstance(token_key, (bytes, bytearray, memoryview)):
            raise AgentAccessError("invalid_input")
        self._token_key = bytes(token_key)
        if len(self._token_key) < 32:
            raise AgentAccessError("invalid_input")
        if clock is not None and not callable(clock):
            raise AgentAccessError("invalid_input")
        self._clock = clock or (lambda: datetime.now(UTC))

    def __repr__(self) -> str:
        return (
            f"AgentAccessService(repository={self.repository!r}, "
            f"issuer={self.issuer!r})"
        )

    def register(
        self,
        *,
        subject_id: str,
        external_agent_id: str,
    ) -> AgentBinding:
        subject_id = _validate_identifier(subject_id)
        external_agent_id = _validate_identifier(external_agent_id)
        try:
            record = self.repository.register(
                agent_id=_new_identifier("agent"),
                user_id=_core_user_id(self.issuer, subject_id),
                issuer=self.issuer,
                subject_id=subject_id,
                external_agent_id=external_agent_id,
                created_at=self._now(),
            )
        except _AgentAccessRepositoryConflict as exc:
            raise AgentAccessConflictError() from exc
        return _binding_from_record(record)

    def get_agent(self, agent_id: str) -> AgentBinding:
        agent_id = _validate_identifier(agent_id)
        record = self.repository.get_agent(agent_id, issuer=self.issuer)
        if record is None:
            raise AgentAccessNotFoundError()
        return _binding_from_record(record)

    def get_runtime_status(self, agent_id: str) -> dict[str, object]:
        """Return the current runtime state without exposing credential secrets."""

        agent_id = _validate_identifier(agent_id)
        current = self.repository.get_runtime_status(
            agent_id,
            issuer=self.issuer,
        )
        if current is None:
            raise AgentAccessNotFoundError()
        binding, credential = current
        runtime: dict[str, object] | None = None
        if credential is not None:
            now = self._now()
            if credential.revoked_at is not None:
                status = "revoked"
            elif credential.expires_at <= now:
                status = "expired"
            else:
                status = "active"
            runtime = {
                "credential_id": credential.credential_id,
                "runtime_id": credential.runtime_id,
                "scope": credential.scope,
                "issued_at": credential.issued_at,
                "expires_at": credential.expires_at,
                "status": status,
            }
        return {"agent_id": binding.agent_id, "runtime": runtime}

    def issue_credential(
        self,
        *,
        agent_id: str,
        runtime_id: str,
        request_id: str,
        scope: str = "payments",
        ttl_seconds: int = 300,
        replaces_credential_id: str | None = None,
    ) -> IssuedRuntimeCredential:
        agent_id = _validate_identifier(agent_id)
        runtime_id = _validate_identifier(runtime_id)
        request_id = _validate_identifier(request_id)
        if type(scope) is not str or scope not in _ALLOWED_SCOPES:
            raise AgentAccessError("invalid_input")
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 900:
            raise AgentAccessError("invalid_input")
        if replaces_credential_id is not None:
            replaces_credential_id = _validate_identifier(
                replaces_credential_id
            )

        request_fingerprint = _request_fingerprint(
            agent_id=agent_id,
            runtime_id=runtime_id,
            request_id=request_id,
            scope=scope,
            ttl_seconds=ttl_seconds,
            replaces_credential_id=replaces_credential_id,
        )
        credential_id = _new_identifier("credential")
        issued_at = self._now()
        expires_at = issued_at + timedelta(seconds=ttl_seconds)
        try:
            record = self.repository.issue_credential(
                issuer=self.issuer,
                agent_id=agent_id,
                runtime_id=runtime_id,
                request_id=request_id,
                scope=scope,
                request_fingerprint=request_fingerprint,
                credential_id=credential_id,
                secret_digest=_secret_digest(
                    _derive_access_token(self._token_key, credential_id)
                ),
                issued_at=issued_at,
                expires_at=expires_at,
                replaces_credential_id=replaces_credential_id,
            )
        except _AgentAccessRepositoryNotFound as exc:
            raise AgentAccessNotFoundError() from exc
        except _AgentAccessRepositoryConflict as exc:
            raise AgentAccessConflictError() from exc

        access_token = _derive_access_token(
            self._token_key,
            record.credential_id,
        )
        if not hmac.compare_digest(
            record.secret_digest,
            _secret_digest(access_token),
        ):
            raise AgentAccessUnauthorizedError()
        return IssuedRuntimeCredential(
            credential_id=record.credential_id,
            agent_id=record.agent_id,
            runtime_id=record.runtime_id,
            scope=record.scope,
            expires_at=record.expires_at,
            access_token=access_token,
            issued_at=record.issued_at,
        )

    def authenticate(self, token: str) -> RuntimePrincipal:
        if (
            not isinstance(token, str)
            or not token.startswith(_TOKEN_PREFIX)
            or not token.isascii()
            or len(token) > 256
        ):
            raise AgentAccessUnauthorizedError()
        digest = _secret_digest(token)
        pair = self.repository.authenticate(secret_digest=digest)
        if pair is None:
            raise AgentAccessUnauthorizedError()
        binding, credential = pair
        expected_token = _derive_access_token(
            self._token_key,
            credential.credential_id,
        )
        if not hmac.compare_digest(token, expected_token):
            raise AgentAccessUnauthorizedError()
        if not hmac.compare_digest(digest, credential.secret_digest):
            raise AgentAccessUnauthorizedError()
        if binding.issuer != self.issuer:
            raise AgentAccessUnauthorizedError()
        now = self._now()
        if (
            credential.revoked_at is not None
            or credential.expires_at <= now
        ):
            raise AgentAccessUnauthorizedError()
        return RuntimePrincipal(
            user_id=binding.user_id,
            agent_id=binding.agent_id,
            runtime_id=credential.runtime_id,
            credential_id=credential.credential_id,
            issuer=binding.issuer,
            scope=credential.scope,
            expires_at=credential.expires_at,
        )

    def revoke_runtime(self, *, agent_id: str, runtime_id: str) -> None:
        agent_id = _validate_identifier(agent_id)
        runtime_id = _validate_identifier(runtime_id)
        try:
            self.repository.revoke_runtime(
                issuer=self.issuer,
                agent_id=agent_id,
                runtime_id=runtime_id,
                revoked_at=self._now(),
            )
        except _AgentAccessRepositoryNotFound as exc:
            raise AgentAccessNotFoundError() from exc
        except _AgentAccessRepositoryConflict as exc:
            raise AgentAccessConflictError() from exc

    def _now(self) -> datetime:
        value = self._clock()
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise AgentAccessError("invalid_clock")
        return value.astimezone(UTC)


def _validate_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise AgentAccessError("invalid_input")
    return value


def _new_identifier(kind: str) -> str:
    return f"{kind}_{uuid.uuid4().hex}"


def _core_user_id(issuer: str, subject_id: str) -> str:
    # Core treats user IDs as opaque canonical identifiers.  Do not expose a
    # Java subject (which may contain punctuation or Unicode) in a downstream
    # ID or allow a delimiter to alter the namespace.  The binding retains the
    # original issuer/subject for exact replay and audit lookup.
    canonical = json.dumps(
        {"issuer": issuer, "subject_id": subject_id},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"clink-agent-user:v1\x00" + canonical
    ).hexdigest()
    return f"agent:v1:{digest}"


def _request_fingerprint(
    *,
    agent_id: str,
    runtime_id: str,
    request_id: str,
    scope: str,
    ttl_seconds: int,
    replaces_credential_id: str | None,
) -> str:
    payload = {
        "agent_id": agent_id,
        "request_id": request_id,
        "replaces_credential_id": replaces_credential_id,
        "runtime_id": runtime_id,
        "scope": scope,
        "ttl_seconds": ttl_seconds,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _derive_access_token(token_key: bytes, credential_id: str) -> str:
    digest = hmac.new(
        token_key,
        _TOKEN_DOMAIN + credential_id.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{_TOKEN_PREFIX}{encoded}"


def _secret_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _binding_from_record(record: AgentBindingRecord) -> AgentBinding:
    return AgentBinding(
        agent_id=record.agent_id,
        user_id=record.user_id,
        issuer=record.issuer,
        subject_id=record.subject_id,
        external_agent_id=record.external_agent_id,
        created_at=record.created_at,
    )


__all__ = [
    "AgentAccessConflictError",
    "AgentAccessError",
    "AgentAccessNotFoundError",
    "AgentAccessService",
    "AgentAccessUnauthorizedError",
    "AgentBinding",
    "CompositeRuntimeAuthenticator",
    "IssuedRuntimeCredential",
    "RuntimePrincipal",
]
