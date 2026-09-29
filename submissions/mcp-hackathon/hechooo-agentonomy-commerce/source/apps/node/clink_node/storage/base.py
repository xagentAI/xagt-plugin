from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MAX_ID_LENGTH = 256
_INVALID_MESSAGE = "miniapp_storage_invalid"
_CONFLICT_MESSAGE = "miniapp_storage_conflict"


class MiniAppStorageConflict(RuntimeError):
    """A stable, deliberately redacted Mini App storage conflict."""

    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


def _validate_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_ID_LENGTH
    ):
        raise ValueError(_INVALID_MESSAGE)
    return value


def _validate_hash(value: object) -> str:
    if not isinstance(value, str) or not _HASH_PATTERN.fullmatch(value):
        raise ValueError(_INVALID_MESSAGE)
    return value


def _normalize_datetime(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(_INVALID_MESSAGE)
    return value.astimezone(UTC)


@dataclass(frozen=True)
class ModuleRecord:
    name: str
    mode: str
    status: str
    pid: int | None
    endpoint: str | None
    mcp_url: str | None
    detail: str | None
    updated_at: datetime


@dataclass(frozen=True)
class InteractionSession:
    session_id: str
    kind: str
    user_id: str
    token_hash: str
    payload: dict[str, Any]
    status: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


@dataclass(frozen=True)
class MiniAppBrowserSession:
    session_id: str
    telegram_user_id: str
    subject_id: str
    exchange_hash: str
    client_nonce_hash: str
    session_token_hash: str
    csrf_token_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "telegram_user_id",
            "subject_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_id(getattr(self, field_name)),
            )
        for field_name in (
            "exchange_hash",
            "client_nonce_hash",
            "session_token_hash",
            "csrf_token_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _validate_hash(getattr(self, field_name)),
            )
        for field_name in ("created_at", "expires_at"):
            object.__setattr__(
                self,
                field_name,
                _normalize_datetime(getattr(self, field_name)),
            )
        if self.revoked_at is not None:
            object.__setattr__(
                self,
                "revoked_at",
                _normalize_datetime(self.revoked_at),
            )


@dataclass(frozen=True)
class MiniAppHermesBinding:
    subject_id: str
    hermes_session_id: str
    session_key_hash: str
    created_at: datetime
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _validate_id(self.subject_id))
        object.__setattr__(
            self,
            "hermes_session_id",
            _validate_id(self.hermes_session_id),
        )
        object.__setattr__(
            self,
            "session_key_hash",
            _validate_hash(self.session_key_hash),
        )
        object.__setattr__(
            self,
            "created_at",
            _normalize_datetime(self.created_at),
        )
        if self.revoked_at is not None:
            object.__setattr__(
                self,
                "revoked_at",
                _normalize_datetime(self.revoked_at),
            )


@dataclass(frozen=True)
class MiniAppMessageClaim:
    subject_id: str
    client_message_id: str
    payload_hash: str
    status: str
    hermes_run_id: str | None
    hermes_run_session_id: str | None
    legacy_unreconciled: bool
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _validate_id(self.subject_id))
        object.__setattr__(
            self,
            "client_message_id",
            _validate_id(self.client_message_id),
        )
        object.__setattr__(
            self,
            "payload_hash",
            _validate_hash(self.payload_hash),
        )
        if self.status not in ("starting", "accepted", "unknown"):
            raise ValueError(_INVALID_MESSAGE)
        if type(self.legacy_unreconciled) is not bool:
            raise ValueError(_INVALID_MESSAGE)
        if self.legacy_unreconciled:
            if (
                self.status != "unknown"
                or self.hermes_run_id is not None
                or self.hermes_run_session_id is not None
            ):
                raise ValueError(_INVALID_MESSAGE)
        else:
            if self.hermes_run_session_id is None:
                raise ValueError(_INVALID_MESSAGE)
            object.__setattr__(
                self,
                "hermes_run_session_id",
                _validate_id(self.hermes_run_session_id),
            )
        if self.status == "accepted" and not self.legacy_unreconciled:
            if self.hermes_run_id is None:
                raise ValueError(_INVALID_MESSAGE)
            object.__setattr__(
                self,
                "hermes_run_id",
                _validate_id(self.hermes_run_id),
            )
        elif self.hermes_run_id is not None:
            raise ValueError(_INVALID_MESSAGE)
        for field_name in ("created_at", "updated_at"):
            object.__setattr__(
                self,
                field_name,
                _normalize_datetime(getattr(self, field_name)),
            )


@dataclass(frozen=True)
class MiniAppMessageClaimResult:
    claim: MiniAppMessageClaim
    created: bool


@dataclass(frozen=True)
class MiniAppActiveRunLease:
    subject_id: str
    client_message_id: str
    acquired_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _validate_id(self.subject_id))
        object.__setattr__(
            self,
            "client_message_id",
            _validate_id(self.client_message_id),
        )
        for field_name in ("acquired_at", "updated_at"):
            object.__setattr__(
                self,
                field_name,
                _normalize_datetime(getattr(self, field_name)),
            )


class NodeRepository(Protocol):
    def migrate(self) -> None: ...

    def schema_version(self) -> int: ...

    def set_module(self, record: ModuleRecord) -> None: ...

    def get_module(self, name: str) -> ModuleRecord | None: ...

    def list_modules(self) -> list[ModuleRecord]: ...

    def create_interaction(self, session: InteractionSession) -> None: ...

    def get_interaction(
        self,
        session_id: str,
    ) -> InteractionSession | None: ...

    def consume_interaction(
        self,
        session_id: str,
        token_hash: str,
        *,
        now: datetime,
    ) -> InteractionSession | None: ...

    def append_event(
        self,
        event_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> int: ...

    def pending_events(self, limit: int = 100) -> list[dict[str, Any]]: ...

    def mark_event_published(self, event_id: int) -> None: ...

    def put_secret_reference(
        self,
        name: str,
        backend: str,
        reference: str,
    ) -> None: ...

    def get_secret_reference(self, name: str) -> dict[str, str] | None: ...

    def exchange_miniapp_session(
        self,
        proposed: MiniAppBrowserSession,
    ) -> MiniAppBrowserSession: ...

    def get_miniapp_session(
        self,
        session_token_hash: str,
        now: datetime,
    ) -> MiniAppBrowserSession | None: ...

    def revoke_miniapp_session(
        self,
        session_token_hash: str,
        now: datetime,
    ) -> bool: ...

    def get_or_create_hermes_binding(
        self,
        proposed: MiniAppHermesBinding,
    ) -> MiniAppHermesBinding: ...

    def claim_miniapp_message(
        self,
        proposed: MiniAppMessageClaim,
    ) -> MiniAppMessageClaimResult: ...

    def get_miniapp_message_claim(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> MiniAppMessageClaim | None: ...

    def get_latest_miniapp_message_claim(
        self,
        subject_id: str,
    ) -> MiniAppMessageClaim | None: ...

    def get_miniapp_active_run_lease(
        self,
        subject_id: str,
    ) -> MiniAppActiveRunLease | None: ...

    def release_miniapp_active_run_lease(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> bool: ...

    def complete_miniapp_message(
        self,
        subject_id: str,
        client_message_id: str,
        *,
        status: str,
        hermes_run_id: str | None,
        hermes_run_session_id: str | None,
        now: datetime,
    ) -> MiniAppMessageClaim: ...
