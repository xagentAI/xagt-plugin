from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterator, Mapping, Protocol, Sequence
from urllib.parse import SplitResult, parse_qsl, unquote, urlsplit

from ..adapters.http import DownstreamError
from ..adapters.prediction_markets import OrderSigningCreationAmbiguousError
from .session_service import MiniAppServiceError, MiniAppSessionService
from .traffic import (
    MemoryMiniAppTrafficGuard,
    MiniAppTrafficGuard,
)
from ..hermes import (
    HermesConflict,
    HermesConversationMessage,
    HermesMessage,
    HermesMessagesPage,
    HermesNotFound,
    HermesResponseTooLarge,
    HermesRun,
    HermesSession,
    HermesSseEvent,
    HermesUnavailable,
)
from ..storage.base import (
    MiniAppActiveRunLease,
    MiniAppBrowserSession,
    MiniAppHermesBinding,
    MiniAppMessageClaim,
    MiniAppMessageClaimResult,
    MiniAppStorageConflict,
    NodeRepository,
)


_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
_MAX_CONVERSATION_HISTORY_BYTES = 240 * 1024
_LATEST_MESSAGE_LIMITS = (40, 20, 10, 5, 1)
_LIVE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_FUNDING_IDEMPOTENCY = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
)
_FUNDING_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$")
_FUNDING_PROJECTION_KEYS = frozenset(
    {
        "operation_id",
        "status",
        "amount_usdc",
        "chain_status",
        "bridge_status",
        "buying_power_status",
        "reason",
        "next_action",
    }
)
_SIGNING_PROJECTION_KEYS = frozenset(
    {
        "session_id",
        "status",
        "reason",
        "next_action",
        "execution_id",
    }
)


class MiniAppOrderSigningOutcomeUnknown(MiniAppServiceError):
    next_action = "create_new_preview_or_manual_reconcile"

    def __init__(self) -> None:
        super().__init__("miniapp_order_signing_outcome_unknown", 503)


class HermesSessionBoundary(Protocol):
    def create_session(self, session_id: str | None = None) -> HermesSession: ...

    def get_session(self, session_id: str) -> HermesSession: ...

    def get_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        order: str = "oldest",
    ) -> HermesMessagesPage: ...

    def start_run(
        self,
        session_id: str,
        user_input: str,
        *,
        conversation_history: Sequence[HermesConversationMessage],
    ) -> HermesRun: ...

    def get_run(self, run_id: str, *, session_id: str) -> HermesRun: ...

    def stream_run_events(self, run_id: str) -> Iterator[HermesSseEvent]: ...

    def stop_run(self, run_id: str) -> HermesRun: ...


class HermesClientBoundary(Protocol):
    def for_session(self, session_key: str) -> HermesSessionBoundary: ...


class PolymarketLiveOperationsBoundary(Protocol):
    def create_funding_operation(
        self,
        *,
        user_id: str,
        amount_usdc: str,
        idempotency_key: str,
    ) -> Mapping[str, object]: ...

    def get_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> Mapping[str, object]: ...

    def continue_funding_operation(
        self,
        *,
        user_id: str,
        operation_id: str,
    ) -> Mapping[str, object]: ...

    def create_order_signing_session(
        self,
        *,
        user_id: str,
        preview_id: str,
    ) -> Mapping[str, object]: ...

    def get_order_signing_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class MiniAppChatMessage:
    id: int | str | None
    role: str
    content: str
    timestamp: float | None


@dataclass(frozen=True, slots=True)
class MiniAppChatSnapshot:
    messages: tuple[MiniAppChatMessage, ...]
    latest_client_message_id: str | None
    latest_submission_status: str | None


@dataclass(frozen=True, slots=True)
class MiniAppSubmission:
    client_message_id: str
    status: str


@dataclass(frozen=True, slots=True)
class MiniAppSseLease:
    subject_id: str
    token: str


class MiniAppChatService:
    def __init__(
        self,
        *,
        repository: NodeRepository,
        hermes_client: HermesClientBoundary,
        account_link_factory: Callable[[str], Mapping[str, object]],
        polymarket_link_factory: Callable[[str], str] | None = None,
        polymarket_live_operations: (
            PolymarketLiveOperationsBoundary | None
        ) = None,
        telegram_bot_token: bytes,
        cookie_secret: bytes,
        hermes_session_secret: bytes,
        allowed_origin: str,
        now: Callable[[], datetime] | None = None,
        auth_max_age_seconds: int = 300,
        session_ttl_seconds: int = 86_400,
        traffic_guard: MiniAppTrafficGuard | None = None,
    ) -> None:
        self.repository = repository
        self.hermes_client = hermes_client
        self._account_link_factory = account_link_factory
        self._polymarket_link_factory = polymarket_link_factory
        self._polymarket_live_operations = polymarket_live_operations
        self._hermes_session_secret = _secret_bytes(hermes_session_secret)
        self.sessions = MiniAppSessionService(
            repository=repository,
            telegram_bot_token=telegram_bot_token,
            cookie_secret=cookie_secret,
            allowed_origin=allowed_origin,
            now=now,
            auth_max_age_seconds=auth_max_age_seconds,
            session_ttl_seconds=session_ttl_seconds,
        )
        self.traffic_guard = (
            traffic_guard
            if traffic_guard is not None
            else MemoryMiniAppTrafficGuard()
        )
        self._subject_locks = tuple(threading.Lock() for _ in range(64))

    def require_traffic(self, action: str, scope: str) -> None:
        failed = False
        try:
            allowed = self.traffic_guard.consume(action, scope)
        except Exception:
            failed = True
            allowed = False
        if failed:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        if allowed is not True:
            raise MiniAppServiceError("miniapp_rate_limited", 429)

    def acquire_sse_lease(
        self,
        session: MiniAppBrowserSession,
    ) -> MiniAppSseLease:
        failed = False
        try:
            token = self.traffic_guard.acquire_sse(session.subject_id)
        except Exception:
            failed = True
            token = None
        if failed:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        if token is None:
            raise MiniAppServiceError("miniapp_rate_limited", 429)
        if not isinstance(token, str) or not token:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        return MiniAppSseLease(session.subject_id, token)

    def release_sse_lease(self, lease: MiniAppSseLease) -> None:
        failed = False
        try:
            released = self.traffic_guard.release_sse(
                lease.subject_id,
                lease.token,
            )
        except Exception:
            failed = True
            released = False
        if failed or released is not True:
            raise MiniAppServiceError("miniapp_unavailable", 503)

    def create_account_operation_link(
        self,
        session: MiniAppBrowserSession,
    ) -> str:
        failed = False
        try:
            result = self._account_link_factory(session.subject_id)
        except Exception:
            failed = True
            result = None
        if failed or not isinstance(result, Mapping):
            raise MiniAppServiceError("miniapp_unavailable", 503)
        try:
            candidate = result.get("account_url")
        except Exception:
            candidate = None
        url = _validated_account_operation_url(
            candidate,
            self.sessions.allowed_origin,
        )
        if url is None:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        return url

    def create_polymarket_operation_link(
        self,
        session: MiniAppBrowserSession,
    ) -> str:
        failed = self._polymarket_link_factory is None
        try:
            candidate = (
                self._polymarket_link_factory(session.subject_id)
                if self._polymarket_link_factory is not None
                else None
            )
        except Exception:
            failed = True
            candidate = None
        if failed:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        url = _validated_polymarket_operation_url(
            candidate,
            self.sessions.allowed_origin,
        )
        if url is None:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        return url

    @property
    def polymarket_live_operations_enabled(self) -> bool:
        return self._polymarket_live_operations is not None

    def create_polymarket_funding_operation(
        self,
        session: MiniAppBrowserSession,
        *,
        amount_usdc: object,
        idempotency_key: object,
    ) -> dict[str, object]:
        operations = self._require_polymarket_live_operations()
        amount = _normalize_funding_amount(amount_usdc)
        browser_key = _validate_live_idempotency_key(idempotency_key)
        scoped_key = "miniapp:" + hashlib.sha256(
            b"agentonomy-polymarket-funding-v1\x00"
            + session.subject_id.encode("utf-8")
            + b"\x00"
            + browser_key.encode("ascii")
        ).hexdigest()
        try:
            result = operations.create_funding_operation(
                user_id=session.subject_id,
                amount_usdc=amount,
                idempotency_key=scoped_key,
            )
        except DownstreamError as exc:
            raise _live_operation_error(exc) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return _safe_live_projection(result, _FUNDING_PROJECTION_KEYS)

    def get_polymarket_funding_operation(
        self,
        session: MiniAppBrowserSession,
        operation_id: object,
    ) -> dict[str, object]:
        operations = self._require_polymarket_live_operations()
        normalized_id = _validate_live_id(operation_id)
        try:
            result = operations.get_funding_operation(
                user_id=session.subject_id,
                operation_id=normalized_id,
            )
        except DownstreamError as exc:
            raise _live_operation_error(exc) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return _safe_live_projection(result, _FUNDING_PROJECTION_KEYS)

    def continue_polymarket_funding_operation(
        self,
        session: MiniAppBrowserSession,
        operation_id: object,
    ) -> dict[str, object]:
        operations = self._require_polymarket_live_operations()
        normalized_id = _validate_live_id(operation_id)
        try:
            result = operations.continue_funding_operation(
                user_id=session.subject_id,
                operation_id=normalized_id,
            )
        except DownstreamError as exc:
            raise _live_operation_error(exc) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return _safe_live_projection(result, _FUNDING_PROJECTION_KEYS)

    def create_polymarket_order_signing_session(
        self,
        session: MiniAppBrowserSession,
        *,
        preview_id: object,
    ) -> dict[str, object]:
        operations = self._require_polymarket_live_operations()
        normalized_id = _validate_live_id(preview_id)
        try:
            result = operations.create_order_signing_session(
                user_id=session.subject_id,
                preview_id=normalized_id,
            )
        except OrderSigningCreationAmbiguousError:
            raise MiniAppOrderSigningOutcomeUnknown() from None
        except DownstreamError as exc:
            raise _live_operation_error(exc) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return _safe_live_projection(
            result,
            _SIGNING_PROJECTION_KEYS | {"signing_url"},
        )

    def get_polymarket_order_signing_session(
        self,
        session: MiniAppBrowserSession,
        session_id: object,
    ) -> dict[str, object]:
        operations = self._require_polymarket_live_operations()
        normalized_id = _validate_live_id(session_id)
        try:
            result = operations.get_order_signing_session(
                user_id=session.subject_id,
                session_id=normalized_id,
            )
        except DownstreamError as exc:
            raise _live_operation_error(exc) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return _safe_live_projection(result, _SIGNING_PROJECTION_KEYS)

    def _require_polymarket_live_operations(
        self,
    ) -> PolymarketLiveOperationsBoundary:
        if self._polymarket_live_operations is None:
            raise MiniAppServiceError("miniapp_not_found", 404)
        return self._polymarket_live_operations

    def get_chat(
        self,
        session: MiniAppBrowserSession,
    ) -> MiniAppChatSnapshot:
        try:
            _, bound = self._binding_client(session.subject_id)
            page = self._latest_messages_page(
                bound,
                self._hermes_session_id(session.subject_id),
            )
            page_messages = self._validated_messages(page)
            messages = tuple(
                MiniAppChatMessage(
                    id=item.id,
                    role=item.role,
                    content=item.content,
                    timestamp=item.timestamp,
                )
                for item in page_messages
                if item.role in {"user", "assistant"}
                and (item.role != "assistant" or bool(item.content.strip()))
            )
            lease = self.repository.get_miniapp_active_run_lease(
                session.subject_id
            )
            latest = self._lease_owner_claim(lease) if lease is not None else None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        return MiniAppChatSnapshot(
            messages=messages,
            latest_client_message_id=(
                latest.client_message_id if latest is not None else None
            ),
            latest_submission_status=(latest.status if latest is not None else None),
        )

    def submit_message(
        self,
        session: MiniAppBrowserSession,
        *,
        client_message_id: str,
        text: str,
    ) -> MiniAppSubmission:
        normalized_id, encoded_text = _validate_message_input(
            client_message_id,
            text,
        )
        payload_hash = hashlib.sha256(
            b"agentonomy-miniapp-message-v1\x00" + encoded_text
        ).hexdigest()
        lock = self._subject_lock(session.subject_id)
        with lock:
            existing = self.repository.get_miniapp_message_claim(
                session.subject_id,
                normalized_id,
            )
            if existing is not None:
                return self._existing_submission(existing, payload_hash)

            try:
                self._preflight_nonterminal_lease(session.subject_id)
                _, bound = self._binding_client(session.subject_id)
                page = self._latest_messages_page(
                    bound,
                    self._hermes_session_id(session.subject_id),
                )
                page_messages = self._validated_messages(page)
                history = _bounded_conversation_history(page_messages)
            except MiniAppServiceError:
                raise
            except Exception:
                raise MiniAppServiceError("miniapp_unavailable", 503) from None

            proposed = MiniAppMessageClaim(
                subject_id=session.subject_id,
                client_message_id=normalized_id,
                payload_hash=payload_hash,
                status="starting",
                hermes_run_id=None,
                hermes_run_session_id=page.session_id,
                legacy_unreconciled=False,
                created_at=self.sessions.current_time(),
                updated_at=self.sessions.current_time(),
            )
            try:
                claimed = self._claim_with_active_lease(
                    bound,
                    proposed,
                    payload_hash,
                )
            except MiniAppServiceError:
                raise
            except Exception:
                raise MiniAppServiceError("miniapp_unavailable", 503) from None
            if not claimed.created:
                return self._submission_from_claim(claimed.claim)

            try:
                run = bound.start_run(
                    page.session_id,
                    text,
                    conversation_history=history,
                )
            except Exception:
                try:
                    self.repository.complete_miniapp_message(
                        session.subject_id,
                        normalized_id,
                        status="unknown",
                        hermes_run_id=None,
                        hermes_run_session_id=page.session_id,
                        now=self.sessions.current_time(),
                    )
                except Exception:
                    pass
                raise MiniAppServiceError(
                    "miniapp_message_unknown",
                    503,
                ) from None
            try:
                completed = self.repository.complete_miniapp_message(
                    session.subject_id,
                    normalized_id,
                    status="accepted",
                    hermes_run_id=run.run_id,
                    hermes_run_session_id=page.session_id,
                    now=self.sessions.current_time(),
                )
            except Exception:
                raise MiniAppServiceError("miniapp_unavailable", 503) from None
            return self._submission_from_claim(completed)

    def get_message_run(
        self,
        session: MiniAppBrowserSession,
        client_message_id: str,
    ) -> HermesRun:
        claim = self._accepted_claim(session.subject_id, client_message_id)
        try:
            _, bound = self._binding_client(session.subject_id)
            run = bound.get_run(
                claim.hermes_run_id,
                session_id=self._claim_run_session_id(claim),
            )
            self._release_claim_if_terminal(session.subject_id, claim, run)
            return run
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def stream_message_events(
        self,
        session: MiniAppBrowserSession,
        client_message_id: str,
    ) -> Iterator[HermesSseEvent]:
        claim = self._accepted_claim(session.subject_id, client_message_id)
        try:
            _, bound = self._binding_client(session.subject_id)
            run = bound.get_run(
                claim.hermes_run_id,
                session_id=self._claim_run_session_id(claim),
            )
            self._release_claim_if_terminal(session.subject_id, claim, run)
            return bound.stream_run_events(claim.hermes_run_id)
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def stop_message_run(
        self,
        session: MiniAppBrowserSession,
        client_message_id: str,
    ) -> HermesRun:
        claim = self._accepted_claim(session.subject_id, client_message_id)
        try:
            _, bound = self._binding_client(session.subject_id)
            current = bound.get_run(
                claim.hermes_run_id,
                session_id=self._claim_run_session_id(claim),
            )
            if current.status in _TERMINAL_RUN_STATUSES:
                self._release_claim_if_terminal(
                    session.subject_id,
                    claim,
                    current,
                )
                return current
            stopped = bound.stop_run(claim.hermes_run_id)
            self._release_claim_if_terminal(
                session.subject_id,
                claim,
                stopped,
            )
            return stopped
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def _accepted_claim(
        self,
        subject_id: str,
        client_message_id: str,
    ) -> MiniAppMessageClaim:
        try:
            normalized_id, _ = _validate_message_input(
                client_message_id,
                "lookup",
            )
        except MiniAppServiceError:
            raise MiniAppServiceError("miniapp_not_found", 404) from None
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        try:
            claim = self.repository.get_miniapp_message_claim(
                subject_id,
                normalized_id,
            )
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        if claim is None:
            raise MiniAppServiceError("miniapp_not_found", 404)
        if claim.legacy_unreconciled or claim.hermes_run_session_id is None:
            raise MiniAppServiceError("miniapp_message_unknown", 409)
        if claim.status == "unknown":
            raise MiniAppServiceError("miniapp_message_unknown", 409)
        if claim.status != "accepted" or claim.hermes_run_id is None:
            raise MiniAppServiceError("miniapp_run_active", 409)
        try:
            lease = self.repository.get_miniapp_active_run_lease(subject_id)
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        if lease is None or lease.client_message_id != normalized_id:
            raise MiniAppServiceError("miniapp_not_found", 404)
        return claim

    def _existing_submission(
        self,
        existing: MiniAppMessageClaim,
        payload_hash: str,
    ) -> MiniAppSubmission:
        if not hmac.compare_digest(existing.payload_hash, payload_hash):
            raise MiniAppServiceError("miniapp_conflict", 409)
        return self._submission_from_claim(existing)

    def _submission_from_claim(
        self,
        claim: MiniAppMessageClaim,
    ) -> MiniAppSubmission:
        if claim.status == "unknown":
            raise MiniAppServiceError("miniapp_message_unknown", 503)
        return MiniAppSubmission(
            client_message_id=claim.client_message_id,
            status=claim.status,
        )

    def _claim_with_active_lease(
        self,
        bound: HermesSessionBoundary,
        proposed: MiniAppMessageClaim,
        payload_hash: str,
    ) -> MiniAppMessageClaimResult:
        for attempt in range(2):
            try:
                return self.repository.claim_miniapp_message(proposed)
            except MiniAppStorageConflict:
                existing = self.repository.get_miniapp_message_claim(
                    proposed.subject_id,
                    proposed.client_message_id,
                )
                if existing is not None:
                    self._existing_submission(existing, payload_hash)
                    return MiniAppMessageClaimResult(existing, False)
                self._resolve_active_lease(
                    bound,
                    proposed.subject_id,
                    allow_terminal_release=(attempt == 0),
                )
        raise MiniAppServiceError("miniapp_unavailable", 503)

    def _resolve_active_lease(
        self,
        bound: HermesSessionBoundary,
        subject_id: str,
        *,
        allow_terminal_release: bool,
    ) -> None:
        lease = self.repository.get_miniapp_active_run_lease(subject_id)
        if lease is None:
            if allow_terminal_release:
                return
            raise MiniAppServiceError("miniapp_unavailable", 503)
        owner = self._lease_owner_claim(lease)
        if owner.legacy_unreconciled or owner.hermes_run_session_id is None:
            raise MiniAppServiceError("miniapp_message_unknown", 409)
        if owner.status == "starting":
            raise MiniAppServiceError("miniapp_run_active", 409)
        if owner.status == "unknown":
            raise MiniAppServiceError("miniapp_message_unknown", 503)
        if owner.status != "accepted" or owner.hermes_run_id is None:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        try:
            run = bound.get_run(
                owner.hermes_run_id,
                session_id=self._claim_run_session_id(owner),
            )
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        if run.status not in _TERMINAL_RUN_STATUSES:
            raise MiniAppServiceError("miniapp_run_active", 409)
        if not allow_terminal_release:
            raise MiniAppServiceError("miniapp_run_active", 409)
        try:
            self.repository.release_miniapp_active_run_lease(
                subject_id,
                owner.client_message_id,
            )
        except MiniAppStorageConflict:
            raise MiniAppServiceError("miniapp_run_active", 409) from None
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def _preflight_nonterminal_lease(self, subject_id: str) -> None:
        lease = self.repository.get_miniapp_active_run_lease(subject_id)
        if lease is None:
            return
        owner = self._lease_owner_claim(lease)
        if owner.legacy_unreconciled or owner.hermes_run_session_id is None:
            raise MiniAppServiceError("miniapp_message_unknown", 409)
        if owner.status == "starting":
            raise MiniAppServiceError("miniapp_run_active", 409)
        if owner.status == "unknown":
            raise MiniAppServiceError("miniapp_message_unknown", 503)
        if owner.status != "accepted" or owner.hermes_run_id is None:
            raise MiniAppServiceError("miniapp_unavailable", 503)

    def _lease_owner_claim(
        self,
        lease: MiniAppActiveRunLease,
    ) -> MiniAppMessageClaim:
        owner = self.repository.get_miniapp_message_claim(
            lease.subject_id,
            lease.client_message_id,
        )
        if owner is None:
            raise MiniAppServiceError("miniapp_unavailable", 503)
        return owner

    def _release_claim_if_terminal(
        self,
        subject_id: str,
        claim: MiniAppMessageClaim,
        run: HermesRun,
    ) -> None:
        if run.status not in _TERMINAL_RUN_STATUSES:
            return
        try:
            self.repository.release_miniapp_active_run_lease(
                subject_id,
                claim.client_message_id,
            )
        except MiniAppStorageConflict:
            return

    def _claim_run_session_id(self, claim: MiniAppMessageClaim) -> str:
        if claim.legacy_unreconciled or claim.hermes_run_session_id is None:
            raise MiniAppServiceError("miniapp_message_unknown", 409)
        return claim.hermes_run_session_id

    def _subject_lock(self, subject_id: str) -> threading.Lock:
        index = hashlib.sha256(subject_id.encode("utf-8")).digest()[0] % len(
            self._subject_locks
        )
        return self._subject_locks[index]

    def _validated_messages(
        self,
        page: HermesMessagesPage,
    ) -> tuple[HermesMessage, ...]:
        if any(item.session_id != page.session_id for item in page.messages):
            raise MiniAppServiceError("miniapp_unavailable", 503)
        return page.messages

    def _latest_messages_page(
        self,
        bound: HermesSessionBoundary,
        session_id: str,
    ) -> HermesMessagesPage:
        for limit in _LATEST_MESSAGE_LIMITS:
            try:
                return bound.get_messages(
                    session_id,
                    limit=limit,
                    offset=0,
                    order="latest",
                )
            except HermesResponseTooLarge:
                if limit == _LATEST_MESSAGE_LIMITS[-1]:
                    raise MiniAppServiceError(
                        "miniapp_unavailable",
                        503,
                    ) from None
        raise MiniAppServiceError("miniapp_unavailable", 503)

    def _binding_client(
        self,
        subject_id: str,
    ) -> tuple[MiniAppHermesBinding, HermesSessionBoundary]:
        session_id = self._hermes_session_id(subject_id)
        session_key = self._hermes_session_key(subject_id)
        proposed = MiniAppHermesBinding(
            subject_id=subject_id,
            hermes_session_id=session_id,
            session_key_hash=hashlib.sha256(session_key.encode("ascii")).hexdigest(),
            created_at=self.sessions.current_time(),
            revoked_at=None,
        )
        try:
            binding = self.repository.get_or_create_hermes_binding(proposed)
            bound = self.hermes_client.for_session(session_key)
            self._ensure_hermes_session(bound, binding.hermes_session_id)
            return binding, bound
        except MiniAppStorageConflict:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        except MiniAppServiceError:
            raise
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def _ensure_hermes_session(
        self,
        bound: HermesSessionBoundary,
        session_id: str,
    ) -> None:
        try:
            bound.get_session(session_id)
            return
        except HermesNotFound:
            pass
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        try:
            bound.create_session(session_id)
            return
        except (HermesConflict, HermesUnavailable):
            pass
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        try:
            bound.get_session(session_id)
        except Exception:
            raise MiniAppServiceError("miniapp_unavailable", 503) from None

    def _hermes_session_id(self, subject_id: str) -> str:
        digest = hmac.new(
            self._hermes_session_secret,
            b"agentonomy-miniapp-hermes-v1\x00session-id\x00"
            + subject_id.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"agentonomy-miniapp-{digest}"

    def _hermes_session_key(self, subject_id: str) -> str:
        digest = hmac.new(
            self._hermes_session_secret,
            b"agentonomy-miniapp-hermes-v1\x00memory-key\x00"
            + subject_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _validate_live_id(value: object) -> str:
    if not isinstance(value, str) or _LIVE_ID.fullmatch(value) is None:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    return value


def _validate_live_idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or _FUNDING_IDEMPOTENCY.fullmatch(value) is None
    ):
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    return value


def _normalize_funding_amount(value: object) -> str:
    if not isinstance(value, str) or _FUNDING_AMOUNT.fullmatch(value) is None:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    whole, separator, fraction = value.partition(".")
    if len(whole) + 6 > 78:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    canonical = f"{whole}.{fraction.ljust(6, '0') if separator else '000000'}"
    if canonical == "0.000000":
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    return canonical


def _safe_live_projection(
    value: object,
    expected_keys: frozenset[str] | set[str],
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(expected_keys):
        raise MiniAppServiceError("miniapp_unavailable", 503)
    result = {key: value[key] for key in expected_keys}
    try:
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, UnicodeError, ValueError):
        raise MiniAppServiceError("miniapp_unavailable", 503) from None
    if len(encoded) > 8 * 1024:
        raise MiniAppServiceError("miniapp_unavailable", 503)
    return result


def _live_operation_error(exc: DownstreamError) -> MiniAppServiceError:
    if exc.status_code == 404:
        return MiniAppServiceError("miniapp_not_found", 404)
    if exc.status_code == 409:
        return MiniAppServiceError("miniapp_conflict", 409)
    return MiniAppServiceError("miniapp_unavailable", 503)


def _secret_bytes(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise ValueError("invalid Mini App secret")
    return value


def _validate_message_input(
    client_message_id: object,
    text: object,
) -> tuple[str, bytes]:
    if not isinstance(client_message_id, str):
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    try:
        parsed = uuid.UUID(client_message_id)
    except (ValueError, AttributeError):
        raise MiniAppServiceError("miniapp_invalid_request", 400) from None
    if str(parsed) != client_message_id:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    if not isinstance(text, str) or not text.strip():
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        raise MiniAppServiceError("miniapp_invalid_request", 400) from None
    if len(encoded) > 16 * 1024:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    return client_message_id, encoded


def _bounded_conversation_history(
    messages: Sequence[HermesMessage],
) -> tuple[HermesConversationMessage, ...]:
    selected: list[HermesConversationMessage] = []
    remaining_bytes = _MAX_CONVERSATION_HISTORY_BYTES
    for item in reversed(messages):
        try:
            role_bytes = item.role.encode("utf-8")
            content_bytes = item.content.encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        message_bytes = len(role_bytes) + len(content_bytes)
        if message_bytes > remaining_bytes:
            continue
        try:
            message = HermesConversationMessage(item.role, item.content)
        except ValueError:
            if item.role in {"system", "user", "assistant", "tool"}:
                continue
            raise MiniAppServiceError("miniapp_unavailable", 503) from None
        selected.append(message)
        remaining_bytes -= message_bytes
    selected.reverse()
    return tuple(selected)


def _validated_account_operation_url(
    value: object,
    allowed_origin: str,
) -> str | None:
    parsed_url = _parsed_same_origin_operation_url(value, allowed_origin)
    if parsed_url is None:
        return None
    _, decoded_path = parsed_url
    if decoded_path != "/account" and not decoded_path.startswith("/account/"):
        return None
    assert isinstance(value, str)
    return value


def _parsed_same_origin_operation_url(
    value: object,
    allowed_origin: str,
) -> tuple[SplitResult, str] | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not _has_valid_percent_escapes(value)
    ):
        return None
    try:
        value.encode("utf-8")
        decoded_value = unquote(value, encoding="utf-8", errors="strict")
        parsed = urlsplit(value)
        expected = urlsplit(allowed_origin)
        parsed_port = parsed.port
        expected_port = expected.port
    except (UnicodeError, ValueError):
        return None
    if any(
        ord(character) <= 0x20 or ord(character) == 0x7F
        for character in decoded_value
    ):
        return None
    if "\\" in decoded_value:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.scheme != expected.scheme
        or parsed.hostname.lower() != (expected.hostname or "").lower()
        or _effective_url_port(parsed.scheme, parsed_port)
        != _effective_url_port(expected.scheme, expected_port)
    ):
        return None
    decoded_path = unquote(parsed.path, encoding="utf-8", errors="strict")
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        return None
    return parsed, decoded_path


_POLYMARKET_BINDING_PATH = re.compile(
    r"^/polymarket/binding-console/pm_bind_sess_[0-9a-f]{12}$"
)
_POLYMARKET_CONSOLE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validated_polymarket_operation_url(
    value: object,
    allowed_origin: str,
) -> str | None:
    parsed_url = _parsed_same_origin_operation_url(value, allowed_origin)
    if parsed_url is None:
        return None
    parsed, decoded_path = parsed_url
    try:
        query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError:
        return None
    if parsed.fragment:
        return None
    if _POLYMARKET_BINDING_PATH.fullmatch(decoded_path) is None:
        return None
    if (
        len(query) != 1
        or query[0][0] != "access_token"
        or _POLYMARKET_CONSOLE_TOKEN.fullmatch(query[0][1]) is None
    ):
        return None
    assert isinstance(value, str)
    return value


def _has_valid_percent_escapes(value: str) -> bool:
    hexadecimal = frozenset("0123456789abcdefABCDEF")
    for index, character in enumerate(value):
        if character == "%" and (
            index + 2 >= len(value)
            or value[index + 1] not in hexadecimal
            or value[index + 2] not in hexadecimal
        ):
            return False
    return True


def _effective_url_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None
