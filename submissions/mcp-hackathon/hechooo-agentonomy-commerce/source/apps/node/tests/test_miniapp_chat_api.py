from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode

import httpx
from fastapi.testclient import TestClient

from apps.node.clink_node.adapters.core import AccountProxyResponse
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.interactions import InteractionService
from apps.node.clink_node.miniapp.service import MiniAppChatService
from apps.node.clink_node.miniapp.session_service import MiniAppServiceError
from apps.node.clink_node.miniapp.routes import (
    _MAX_SESSION_BODY_BYTES,
    _serialize_events,
)
from apps.node.clink_node.miniapp.traffic import (
    IP_GENERAL,
    IP_SESSION_EXCHANGE,
    MESSAGE_SUBMIT,
    OPERATION_LINK,
    STOP,
    SUBJECT_GENERAL,
    MemoryMiniAppTrafficGuard,
)
from apps.node.clink_node.hermes import (
    HermesConflict,
    HermesConversationMessage,
    HermesMessage,
    HermesMessagesPage,
    HermesNotFound,
    HermesProtocolError,
    HermesResponseTooLarge,
    HermesRun,
    HermesSession,
    HermesSseEvent,
    HermesUnavailable,
)
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository
from apps.node.clink_node.miniapp.auth import hash_browser_token


NOW = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)
ORIGIN = "https://www.agentonomy.xyz"
BOT_TOKEN = b"123456:test-only-telegram-token"
COOKIE_SECRET = b"c" * 32
HERMES_SECRET = b"h" * 32
CLIENT_NONCE = base64.urlsafe_b64encode(b"n" * 16).decode().rstrip("=")


def _raw_asgi_request(
    app: Any,
    *,
    path: str,
    headers: list[tuple[bytes, bytes]],
    request_messages: list[dict[str, Any]],
    client: tuple[str, int] = ("127.0.0.1", 12345),
) -> tuple[int, dict[str, Any], int]:
    async def invoke() -> tuple[int, dict[str, Any], int]:
        sent: list[dict[str, Any]] = []
        receive_calls = 0

        async def receive() -> dict[str, Any]:
            nonlocal receive_calls
            if receive_calls >= len(request_messages):
                raise AssertionError("ASGI receive called after the request boundary")
            message = request_messages[receive_calls]
            receive_calls += 1
            return message

        async def send(message: dict[str, Any]) -> None:
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "https",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": headers,
                "client": client,
                "server": ("www.agentonomy.xyz", 443),
            },
            receive,
            send,
        )
        start = next(item for item in sent if item["type"] == "http.response.start")
        body = b"".join(
            item.get("body", b"")
            for item in sent
            if item["type"] == "http.response.body"
        )
        return start["status"], json.loads(body), receive_calls

    return asyncio.run(invoke())


def _signed_init_data(
    *,
    user_id: int = 101,
    username: str = "alice",
    auth_date: datetime = NOW,
) -> str:
    fields = {
        "auth_date": str(int(auth_date.timestamp())),
        "query_id": f"query-{user_id}",
        "user": json.dumps(
            {"id": user_id, "username": username},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN, hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        check.encode(),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


class _Core:
    def __init__(self) -> None:
        self.account_session_calls: list[str] = []
        self.account_session_result: object = {
            "account_url": (
                f"{ORIGIN}/account/session/test-link"
                "?return=%2Fminiapp%2F#complete"
            ),
        }
        self.account_session_error: Exception | None = None

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def account_readiness(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "ready": False}

    def create_account_session(self, user_id: str) -> dict[str, Any]:
        self.account_session_calls.append(user_id)
        if self.account_session_error is not None:
            raise self.account_session_error
        if not isinstance(self.account_session_result, dict):
            return self.account_session_result  # type: ignore[return-value]
        return dict(self.account_session_result)

    def proxy_account_request(self, **kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(200, b"account", ())

    def audit_summary(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        return []


class _Business:
    def __init__(self, name: str) -> None:
        self.name = name
        self.binding_session_calls: list[str] = []
        self.binding_session_result: object = (
            f"{ORIGIN}/polymarket/binding-console/"
            "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
        )
        self.binding_session_error: Exception | None = None

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def capabilities(self) -> list[dict[str, Any]]:
        return []

    def list_services(self, limit: int = 20) -> dict[str, Any]:
        return {"count": 0, "services": []}

    def account_status(self, user_id: str) -> dict[str, Any]:
        return {"user_id": user_id, "status": "unavailable"}

    def create_binding_session(self, user_id: str) -> str:
        self.binding_session_calls.append(user_id)
        if self.binding_session_error is not None:
            raise self.binding_session_error
        return self.binding_session_result  # type: ignore[return-value]

    def proxy_public_request(self, **kwargs: Any) -> AccountProxyResponse:
        return AccountProxyResponse(200, self.name.encode(), ())


class _CloseableEvents:
    def __init__(self, events: list[HermesSseEvent]) -> None:
        self._events = iter(events)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._events)

    def close(self) -> None:
        self.closed = True


class _FailingEvents:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        raise RuntimeError(self.marker)

    def close(self) -> None:
        self.closed = True


class _BrokenIterableEvents:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    def __iter__(self):
        raise RuntimeError(self.marker)

    def close(self) -> None:
        self.closed = True


class _RecordingTrafficGuard:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.deny_action: str | None = None
        self.error_action: str | None = None
        self.error_marker = ""
        self.acquire_calls: list[str] = []
        self.release_calls: list[tuple[str, str]] = []
        self.sse_available = True

    def consume(self, action: str, scope: str) -> bool:
        self.calls.append((action, scope))
        if action == self.error_action:
            raise RuntimeError(self.error_marker)
        return action != self.deny_action

    def acquire_sse(self, scope: str) -> str | None:
        self.acquire_calls.append(scope)
        if not self.sse_available:
            return None
        return "recording-sse-lease"

    def release_sse(self, scope: str, token: str) -> bool:
        self.release_calls.append((scope, token))
        return token == "recording-sse-lease"


class _FakeHermesBound:
    def __init__(self, owner: _FakeHermes, session_key: str) -> None:
        self.owner = owner
        self.session_key = session_key

    def get_session(self, session_id: str) -> HermesSession:
        self.owner.get_session_calls.append((self.session_key, session_id))
        self.owner.get_session_entered.set()
        if self.owner.get_session_release is not None:
            self.owner.get_session_release.wait(timeout=3)
        if session_id not in self.owner.sessions:
            raise HermesNotFound()
        return HermesSession(id=session_id)

    def create_session(self, session_id: str | None = None) -> HermesSession:
        assert session_id is not None
        self.owner.create_session_calls.append((self.session_key, session_id))
        mode = self.owner.create_mode
        if mode in {"conflict_after_create", "unavailable_after_create"}:
            self.owner.sessions.add(session_id)
            self.owner.create_mode = "normal"
            if mode == "conflict_after_create":
                raise HermesConflict()
            raise HermesUnavailable()
        if mode == "unavailable_without_create":
            raise HermesUnavailable()
        if session_id in self.owner.sessions:
            raise HermesConflict()
        self.owner.sessions.add(session_id)
        return HermesSession(id=session_id)

    def get_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        order: str = "oldest",
    ) -> HermesMessagesPage:
        self.owner.get_messages_calls.append(
            (self.session_key, session_id, limit, offset, order)
        )
        if self.owner.get_messages_barrier is not None:
            self.owner.get_messages_barrier.wait(timeout=3)
        configured_error = self.owner.get_messages_errors.get(limit)
        if configured_error is not None:
            raise configured_error
        if session_id not in self.owner.sessions:
            raise HermesNotFound()
        effective = self.owner.descendants.get(session_id, session_id)
        messages = list(self.owner.messages.get(effective, []))
        if order == "latest":
            # Hermes returns the newest bounded window in chronological order.
            messages = messages[-limit:]
        else:
            messages = messages[offset : offset + limit]
        return HermesMessagesPage(
            session_id=effective,
            messages=tuple(messages),
            limit=limit,
            offset=offset,
            order=order,
            returned=len(messages),
        )

    def start_run(
        self,
        session_id: str,
        user_input: str,
        *,
        conversation_history: list[HermesConversationMessage]
        | tuple[HermesConversationMessage, ...],
    ) -> HermesRun:
        history = tuple(conversation_history)
        if sum(
            len(item.role.encode("utf-8")) + len(item.content.encode("utf-8"))
            for item in history
        ) > 256 * 1024:
            raise ValueError("Hermes conversation history is too large")
        self.owner.start_run_calls.append(
            (
                self.session_key,
                session_id,
                user_input,
                history,
            )
        )
        self.owner.start_entered.set()
        if self.owner.start_release is not None:
            self.owner.start_release.wait(timeout=3)
        if self.owner.start_mode == "unavailable":
            raise HermesUnavailable()
        run_id = f"run_{len(self.owner.start_run_calls)}"
        run = HermesRun(run_id=run_id, status="running", session_id=session_id)
        self.owner.runs[run_id] = run
        return HermesRun(run_id=run_id, status="started", session_id=session_id)

    def get_run(self, run_id: str, *, session_id: str) -> HermesRun:
        self.owner.get_run_calls.append((self.session_key, run_id, session_id))
        if self.owner.get_run_mode == "unavailable":
            raise HermesUnavailable()
        run = self.owner.runs.get(run_id)
        if run is None:
            raise HermesNotFound()
        if run.session_id != session_id:
            raise RuntimeError("test session mismatch")
        return run

    def stream_run_events(self, run_id: str):
        self.owner.stream_calls.append((self.session_key, run_id))
        if self.owner.stream_error_marker is not None:
            stream = _FailingEvents(self.owner.stream_error_marker)
        else:
            stream = _CloseableEvents(self.owner.events.get(run_id, []))
        self.owner.streams.append(stream)
        return stream

    def stop_run(self, run_id: str) -> HermesRun:
        self.owner.stop_calls.append((self.session_key, run_id))
        if run_id not in self.owner.runs:
            raise HermesNotFound()
        existing = self.owner.runs[run_id]
        stopped = HermesRun(
            run_id=run_id,
            status=self.owner.stop_status,
            session_id=existing.session_id,
        )
        self.owner.runs[run_id] = stopped
        return stopped


class _FakeHermes:
    def __init__(self) -> None:
        self.bound_keys: list[str] = []
        self.sessions: set[str] = set()
        self.messages: dict[str, list[HermesMessage]] = {}
        self.descendants: dict[str, str] = {}
        self.runs: dict[str, HermesRun] = {}
        self.events: dict[str, list[HermesSseEvent]] = {}
        self.streams: list[_CloseableEvents | _FailingEvents] = []
        self.stream_error_marker: str | None = None
        self.create_mode = "normal"
        self.start_mode = "normal"
        self.get_run_mode = "normal"
        self.stop_status = "stopping"
        self.get_session_calls: list[tuple[str, str]] = []
        self.get_session_entered = threading.Event()
        self.get_session_release: threading.Event | None = None
        self.create_session_calls: list[tuple[str, str]] = []
        self.get_messages_calls: list[tuple[str, str, int, int, str]] = []
        self.get_messages_errors: dict[int, Exception] = {}
        self.get_messages_barrier: threading.Barrier | None = None
        self.start_run_calls: list[tuple] = []
        self.get_run_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str]] = []
        self.stop_calls: list[tuple[str, str]] = []
        self.start_entered = threading.Event()
        self.start_release: threading.Event | None = None

    def for_session(self, session_key: str) -> _FakeHermesBound:
        self.bound_keys.append(session_key)
        return _FakeHermesBound(self, session_key)


class MiniAppChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        paths = NodePaths.from_home(root / ".clink")
        self.settings = NodeSettings.defaults(Profile.PERSONAL, paths=paths)
        self.repository = SQLiteNodeRepository(root / "node.db")
        self.repository.migrate()
        self.hermes = _FakeHermes()
        self.core = _Core()
        self.prediction = _Business("prediction-markets")
        self.now = NOW
        self.service = MiniAppChatService(
            repository=self.repository,
            hermes_client=self.hermes,
            account_link_factory=self.core.create_account_session,
            polymarket_link_factory=self.prediction.create_binding_session,
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: self.now,
            auth_max_age_seconds=300,
            session_ttl_seconds=3600,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _client(
        self,
        *,
        service: MiniAppChatService | None | object = ...,
    ) -> TestClient:
        selected = self.service if service is ... else service
        context = NodeApiContext(
            settings=self.settings,
            repository=self.repository,
            interaction_service=InteractionService(
                self.repository,
                base_url=ORIGIN,
            ),
            session_token="node-test-session",
            core=self.core,
            marketplace=_Business("marketplace"),
            prediction_markets=self.prediction,
            miniapp_service=selected,
        )
        return TestClient(create_app(context), base_url=ORIGIN)

    def _service_with_traffic_guard(
        self,
        traffic_guard: object,
    ) -> MiniAppChatService:
        return MiniAppChatService(
            repository=self.repository,
            hermes_client=self.hermes,
            account_link_factory=self.core.create_account_session,
            polymarket_link_factory=self.prediction.create_binding_session,
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: self.now,
            auth_max_age_seconds=300,
            session_ttl_seconds=3600,
            traffic_guard=traffic_guard,
        )

    def _exchange(
        self,
        client: TestClient,
        *,
        init_data: str | None = None,
        client_nonce: str = CLIENT_NONCE,
    ):
        return client.post(
            "/miniapp/api/session",
            headers={"Origin": ORIGIN},
            json={
                "init_data": init_data or _signed_init_data(),
                "client_nonce": client_nonce,
            },
        )

    def _login(self, client: TestClient) -> str:
        response = self._exchange(client)
        self.assertEqual(response.status_code, 201)
        return response.json()["csrf_token"]

    def _send(
        self,
        client: TestClient,
        csrf: str,
        *,
        client_message_id: str,
        text: str,
        extra: dict[str, object] | None = None,
        origin: str = ORIGIN,
    ):
        return client.post(
            "/miniapp/api/chat/messages",
            headers={"Origin": origin, "X-Agentonomy-CSRF": csrf},
            json={
                "client_message_id": client_message_id,
                "text": text,
                **(extra or {}),
            },
        )

    def test_disabled_routes_are_404_without_side_effects(self) -> None:
        client = self._client(service=None)

        session = self._exchange(client)
        chat = client.get("/miniapp/api/chat")
        health = client.get("/healthz")
        landing = client.get("/")

        self.assertEqual(session.status_code, 404)
        self.assertEqual(chat.status_code, 404)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(landing.status_code, 200)
        self.assertEqual(self.hermes.bound_keys, [])

    def test_all_disabled_routes_are_404_without_cors_or_side_effects(self) -> None:
        client = self._client(service=None)
        message_id = "01010101-0101-4101-8101-010101010101"
        routes = (
            ("delete", "/miniapp/api/session"),
            ("post", "/miniapp/api/operations/account"),
            ("post", "/miniapp/api/operations/polymarket"),
            ("post", "/miniapp/api/chat/messages"),
            ("get", f"/miniapp/api/chat/messages/{message_id}/run"),
            ("get", f"/miniapp/api/chat/messages/{message_id}/events"),
            ("post", f"/miniapp/api/chat/messages/{message_id}/stop"),
        )

        for method, path in routes:
            with self.subTest(method=method, path=path):
                response = getattr(client, method)(path)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("access-control-allow-origin", response.headers)

        self.assertEqual(self.hermes.bound_keys, [])
        self.assertEqual(self.hermes.start_run_calls, [])

    def test_all_public_routes_share_ip_general_before_auth_or_body(self) -> None:
        message_id = "02020202-0202-4202-8202-020202020202"
        routes = (
            ("post", "/miniapp/api/session"),
            ("delete", "/miniapp/api/session"),
            ("get", "/miniapp/api/chat"),
            ("post", "/miniapp/api/operations/account"),
            ("post", "/miniapp/api/operations/polymarket"),
            ("post", "/miniapp/api/chat/messages"),
            ("get", f"/miniapp/api/chat/messages/{message_id}/run"),
            ("get", f"/miniapp/api/chat/messages/{message_id}/events"),
            ("post", f"/miniapp/api/chat/messages/{message_id}/stop"),
        )

        for method, path in routes:
            with self.subTest(method=method, path=path):
                guard = _RecordingTrafficGuard()
                guard.deny_action = IP_GENERAL
                client = self._client(
                    service=self._service_with_traffic_guard(guard)
                )

                response = getattr(client, method)(path)

                self.assertEqual(response.status_code, 429)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_rate_limited"},
                )
                self.assertEqual(
                    [action for action, _ in guard.calls],
                    [IP_GENERAL],
                )
        self.assertEqual(self.hermes.bound_keys, [])

    def test_session_exchange_extra_ip_limit_precedes_body_and_hmac(self) -> None:
        guard = _RecordingTrafficGuard()
        guard.deny_action = IP_SESSION_EXCHANGE
        client = self._client(service=self._service_with_traffic_guard(guard))

        status, payload, receive_calls = _raw_asgi_request(
            client.app,
            path="/miniapp/api/session",
            headers=[],
            request_messages=[],
        )

        self.assertEqual(status, 429)
        self.assertEqual(payload, {"detail": "miniapp_rate_limited"})
        self.assertEqual(receive_calls, 0)
        self.assertEqual(
            guard.calls,
            [
                (IP_GENERAL, "127.0.0.1"),
                (IP_SESSION_EXCHANGE, "127.0.0.1"),
            ],
        )

    def test_proxy_client_ip_is_strict_loopback_only_and_stable_on_errors(
        self,
    ) -> None:
        cases = (
            (
                [(b"x-agentonomy-client-ip", b"203.0.113.8")],
                ("127.0.0.1", 12345),
                "203.0.113.8",
            ),
            (
                [
                    (b"x-agentonomy-client-ip", b"203.0.113.8"),
                    (b"x-agentonomy-client-ip", b"203.0.113.9"),
                ],
                ("127.0.0.1", 12345),
                "127.0.0.1",
            ),
            (
                [(b"x-agentonomy-client-ip", b"invalid-random-one")],
                ("127.0.0.1", 12345),
                "127.0.0.1",
            ),
            (
                [(b"x-agentonomy-client-ip", b"invalid-random-two")],
                ("127.0.0.1", 12345),
                "127.0.0.1",
            ),
            (
                [(b"x-agentonomy-client-ip", b"2001:0db8::1")],
                ("::1", 12345),
                "::1",
            ),
            (
                [(b"x-forwarded-for", b"203.0.113.10")],
                ("127.0.0.1", 12345),
                "127.0.0.1",
            ),
            (
                [(b"x-agentonomy-client-ip", b"203.0.113.11")],
                ("198.51.100.4", 12345),
                "198.51.100.4",
            ),
        )

        for headers, peer, expected_scope in cases:
            with self.subTest(headers=headers, peer=peer):
                guard = _RecordingTrafficGuard()
                guard.deny_action = IP_GENERAL
                client = self._client(
                    service=self._service_with_traffic_guard(guard)
                )

                status, payload, receive_calls = _raw_asgi_request(
                    client.app,
                    path="/miniapp/api/session",
                    headers=headers,
                    request_messages=[],
                    client=peer,
                )

                self.assertEqual(status, 429)
                self.assertEqual(
                    payload,
                    {"detail": "miniapp_rate_limited"},
                )
                self.assertEqual(receive_calls, 0)
                self.assertEqual(guard.calls, [(IP_GENERAL, expected_scope)])

    def test_traffic_backend_failure_is_redacted_503_before_body(self) -> None:
        marker = (
            "redis://user:password@cache.internal/0 "
            "telegram:101 203.0.113.8"
        )
        guard = _RecordingTrafficGuard()
        guard.error_action = IP_GENERAL
        guard.error_marker = marker
        client = self._client(service=self._service_with_traffic_guard(guard))

        status, payload, receive_calls = _raw_asgi_request(
            client.app,
            path="/miniapp/api/session",
            headers=[(b"x-agentonomy-client-ip", b"203.0.113.8")],
            request_messages=[],
        )

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"detail": "miniapp_unavailable"})
        self.assertNotIn(marker, json.dumps(payload))
        self.assertEqual(receive_calls, 0)

    def test_authenticated_routes_apply_subject_general_then_action(self) -> None:
        guard = _RecordingTrafficGuard()
        service = self._service_with_traffic_guard(guard)
        client = self._client(service=service)
        csrf = self._login(client)

        guard.calls.clear()
        chat = client.get("/miniapp/api/chat")
        self.assertEqual(chat.status_code, 200)
        self.assertEqual(
            [action for action, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL],
        )
        self.assertEqual(guard.calls[-1][1], "telegram:101")

        guard.calls.clear()
        operation = client.post(
            "/miniapp/api/operations/account",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )
        self.assertEqual(operation.status_code, 200)
        self.assertEqual(
            [action for action, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL, OPERATION_LINK],
        )

        guard.calls.clear()
        polymarket_operation = client.post(
            "/miniapp/api/operations/polymarket",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )
        self.assertEqual(polymarket_operation.status_code, 200)
        self.assertEqual(
            [action for action, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL, OPERATION_LINK],
        )

        guard.calls.clear()
        message_id = "04040404-0404-4404-8404-040404040404"
        message = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="rate protected",
        )
        self.assertEqual(message.status_code, 202)
        self.assertEqual(
            [action for action, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL, MESSAGE_SUBMIT],
        )

        guard.calls.clear()
        stop = client.post(
            f"/miniapp/api/chat/messages/{message_id}/stop",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
        )
        self.assertEqual(stop.status_code, 200)
        self.assertEqual(
            [action for action, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL, STOP],
        )

    def test_subject_or_action_limit_blocks_before_hermes(self) -> None:
        guard = _RecordingTrafficGuard()
        service = self._service_with_traffic_guard(guard)
        client = self._client(service=service)
        csrf = self._login(client)

        guard.calls.clear()
        guard.deny_action = SUBJECT_GENERAL
        general = client.get("/miniapp/api/chat")
        self.assertEqual(general.status_code, 429)
        self.assertEqual(
            general.json(),
            {"detail": "miniapp_rate_limited"},
        )
        self.assertEqual(self.hermes.bound_keys, [])

        guard.calls.clear()
        guard.deny_action = MESSAGE_SUBMIT
        action = self._send(
            client,
            csrf,
            client_message_id="05050505-0505-4505-8505-050505050505",
            text="do not send",
        )
        self.assertEqual(action.status_code, 429)
        self.assertEqual(
            [name for name, _ in guard.calls],
            [IP_GENERAL, SUBJECT_GENERAL, MESSAGE_SUBMIT],
        )
        self.assertEqual(self.hermes.start_run_calls, [])

    def test_session_exchange_sets_exact_cookie_and_safe_response(self) -> None:
        client = self._client()
        init_data = _signed_init_data()

        response = self._exchange(client, init_data=init_data)

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["authenticated"], True)
        self.assertEqual(body["user"], {"id": 101, "username": "alice"})
        self.assertEqual(body["expires_at"], "2026-08-18T04:00:00+00:00")
        self.assertRegex(body["csrf_token"], r"^[A-Za-z0-9_-]{43}$")
        storage_scope_domain = (
            b"clink-miniapp-storage-scope-v1\x00"
            + b"local-storage"
            + b"\x00"
            + b"telegram:101"
        )
        expected_storage_scope = base64.urlsafe_b64encode(
            hmac.new(
                COOKIE_SECRET,
                storage_scope_domain,
                hashlib.sha256,
            ).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(body["storage_scope"], expected_storage_scope)
        self.assertRegex(body["storage_scope"], r"^[A-Za-z0-9_-]{43}$")
        self.assertNotIn(init_data, response.text)
        self.assertNotIn(BOT_TOKEN.decode(), response.text)
        cookie = response.headers["set-cookie"]
        self.assertIn("agentonomy_miniapp_session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Path=/miniapp", cookie)
        self.assertIn("Max-Age=3600", cookie)

    def test_storage_scope_is_stable_across_sessions_for_one_subject_only(
        self,
    ) -> None:
        first_client = self._client()
        second_client = self._client()
        other_client = self._client()
        second_nonce = base64.urlsafe_b64encode(b"m" * 16).decode().rstrip("=")
        other_nonce = base64.urlsafe_b64encode(b"o" * 16).decode().rstrip("=")

        first = self._exchange(first_client)
        second = self._exchange(
            second_client,
            init_data=_signed_init_data(username="alice-renewed"),
            client_nonce=second_nonce,
        )
        other = self._exchange(
            other_client,
            init_data=_signed_init_data(user_id=202, username="bob"),
            client_nonce=other_nonce,
        )

        self.assertEqual(
            [first.status_code, second.status_code, other.status_code],
            [201] * 3,
        )
        self.assertNotEqual(first.json()["csrf_token"], second.json()["csrf_token"])
        self.assertEqual(first.json()["storage_scope"], second.json()["storage_scope"])
        self.assertNotEqual(first.json()["storage_scope"], other.json()["storage_scope"])
        self.assertNotIn("telegram", first.json()["storage_scope"])
        self.assertNotIn("101", first.json()["storage_scope"])
        self.assertNotEqual(
            first_client.cookies.get("agentonomy_miniapp_session"),
            second_client.cookies.get("agentonomy_miniapp_session"),
        )

    def test_authenticated_responses_are_not_cacheable(self) -> None:
        client = self._client()
        login = self._exchange(client)
        self.assertEqual(login.status_code, 201)
        csrf = login.json()["csrf_token"]
        chat = client.get("/miniapp/api/chat")
        message_id = "04040404-0404-4404-8404-040404040404"
        accepted = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="hello",
        )
        run = client.get(
            f"/miniapp/api/chat/messages/{message_id}/run"
        )

        for response in (login, chat, accepted, run):
            with self.subTest(path=response.request.url.path):
                self.assertEqual(
                    response.headers.get("cache-control"),
                    "no-store",
                )

    def test_lost_response_exchange_is_idempotent_and_nonce_change_conflicts(
        self,
    ) -> None:
        client = self._client()
        init_data = _signed_init_data()

        first = self._exchange(client, init_data=init_data)
        replay = self._exchange(client, init_data=init_data)
        other_nonce = base64.urlsafe_b64encode(b"x" * 16).decode().rstrip("=")
        conflict = self._exchange(
            client,
            init_data=init_data,
            client_nonce=other_nonce,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(
            first.json()["csrf_token"],
            replay.json()["csrf_token"],
        )
        self.assertEqual(
            first.headers["set-cookie"],
            replay.headers["set-cookie"],
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json(), {"detail": "miniapp_conflict"})

    def test_invalid_telegram_inputs_share_one_redacted_401(self) -> None:
        client = self._client()
        secret_marker = "do-not-reflect-this-init-data"
        cases = (
            "not-a-query",
            f"user={secret_marker}&auth_date=1&hash={'0' * 64}",
            _signed_init_data(auth_date=datetime(2026, 8, 17, tzinfo=UTC)),
        )

        for init_data in cases:
            with self.subTest(init_data=init_data[:20]):
                response = self._exchange(client, init_data=init_data)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_unauthorized"},
                )
                self.assertNotIn(secret_marker, response.text)
                self.assertNotIn(BOT_TOKEN.decode(), response.text)

    def test_session_cookie_authentication_expiry_and_revocation_are_redacted(
        self,
    ) -> None:
        client = self._client()

        missing = client.get("/miniapp/api/chat")
        self._login(client)
        token = client.cookies.get("agentonomy_miniapp_session")
        self.assertIsNotNone(token)
        revoked = self.repository.revoke_miniapp_session(
            hash_browser_token(token),
            NOW,
        )
        after_revoke = client.get("/miniapp/api/chat")
        client.cookies.set(
            "agentonomy_miniapp_session",
            "malformed-cookie",
            path="/miniapp",
        )
        malformed = client.get("/miniapp/api/chat")

        self.assertTrue(revoked)
        for response in (missing, after_revoke, malformed):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(
                response.json(),
                {"detail": "miniapp_unauthorized"},
            )

    def test_expired_session_cookie_is_the_same_redacted_401(self) -> None:
        client = self._client()
        self._login(client)

        self.now += timedelta(seconds=3601)
        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "miniapp_unauthorized"})
        self.assertEqual(self.hermes.bound_keys, [])

    def test_duplicate_origin_csrf_and_cookie_headers_fail_closed(self) -> None:
        client = self._client()
        csrf = self._login(client)
        token = client.cookies.get("agentonomy_miniapp_session")
        self.assertIsNotNone(token)
        message_id = "02020202-0202-4202-8202-020202020202"
        body = {"client_message_id": message_id, "text": "hello"}

        duplicate_origin = client.post(
            "/miniapp/api/chat/messages",
            headers=[
                ("Origin", ORIGIN),
                ("Origin", ORIGIN),
                ("X-Agentonomy-CSRF", csrf),
            ],
            json=body,
        )
        duplicate_csrf = client.post(
            "/miniapp/api/chat/messages",
            headers=[
                ("Origin", ORIGIN),
                ("X-Agentonomy-CSRF", csrf),
                ("X-Agentonomy-CSRF", csrf),
            ],
            json=body,
        )
        duplicate_cookie = client.get(
            "/miniapp/api/chat",
            headers={
                "Cookie": (
                    f"agentonomy_miniapp_session={token}; "
                    f"agentonomy_miniapp_session={token}"
                )
            },
        )

        self.assertEqual(duplicate_origin.status_code, 403)
        self.assertEqual(duplicate_csrf.status_code, 403)
        self.assertEqual(duplicate_cookie.status_code, 401)
        self.assertEqual(self.hermes.start_run_calls, [])

    def test_logout_requires_origin_and_csrf_then_revokes_and_clears_cookie(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        endpoint = "/miniapp/api/session"

        missing_origin = client.delete(
            endpoint,
            headers={"X-Agentonomy-CSRF": csrf},
        )
        wrong_origin = client.delete(
            endpoint,
            headers={
                "Origin": "https://www.agentonomy.xyz:444",
                "X-Agentonomy-CSRF": csrf,
            },
        )
        missing_csrf = client.delete(endpoint, headers={"Origin": ORIGIN})
        wrong_csrf = client.delete(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": "x" * 43},
        )

        for response in (
            missing_origin,
            wrong_origin,
            missing_csrf,
            wrong_csrf,
        ):
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json(), {"detail": "miniapp_forbidden"})

        accepted = client.delete(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
        )
        after = client.get("/miniapp/api/chat")

        self.assertEqual(accepted.status_code, 204)
        clear_cookie = accepted.headers["set-cookie"]
        self.assertIn("agentonomy_miniapp_session=", clear_cookie)
        self.assertIn("Max-Age=0", clear_cookie)
        self.assertIn("Path=/miniapp", clear_cookie)
        self.assertIn("HttpOnly", clear_cookie)
        self.assertIn("Secure", clear_cookie)
        self.assertIn("SameSite=lax", clear_cookie)
        self.assertEqual(after.status_code, 401)

    def test_account_operation_link_uses_only_authenticated_subject(self) -> None:
        alice = self._client()
        bob = self._client()
        alice_csrf = self._login(alice)
        bob_login = self._exchange(
            bob,
            init_data=_signed_init_data(user_id=202, username="bob"),
        )
        self.assertEqual(bob_login.status_code, 201)
        endpoint = "/miniapp/api/operations/account"
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf}

        browser_override = alice.post(
            endpoint,
            headers=headers,
            json={"user_id": "telegram:202"},
        )
        alice_link = alice.post(endpoint, headers=headers, json={})
        self.core.account_session_result = {"account_url": f"{ORIGIN}/account"}
        bob_link = bob.post(
            endpoint,
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": bob_login.json()["csrf_token"],
            },
            json={},
        )

        self.assertEqual(browser_override.status_code, 400)
        self.assertEqual(
            browser_override.json(),
            {"detail": "miniapp_invalid_request"},
        )
        self.assertEqual(alice_link.status_code, 200)
        self.assertEqual(
            alice_link.json(),
            {
                "url": (
                    f"{ORIGIN}/account/session/test-link"
                    "?return=%2Fminiapp%2F#complete"
                )
            },
        )
        self.assertEqual(bob_link.status_code, 200)
        self.assertEqual(bob_link.json(), {"url": f"{ORIGIN}/account"})
        self.assertEqual(
            self.core.account_session_calls,
            ["telegram:101", "telegram:202"],
        )

    def test_account_operation_link_requires_auth_origin_csrf_and_empty_body(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        endpoint = "/miniapp/api/operations/account"
        cases = (
            ({"X-Agentonomy-CSRF": csrf}, {}, 403),
            (
                {
                    "Origin": "https://www.agentonomy.xyz:444",
                    "X-Agentonomy-CSRF": csrf,
                },
                {},
                403,
            ),
            ({"Origin": ORIGIN}, {}, 403),
            (
                {"Origin": ORIGIN, "X-Agentonomy-CSRF": "x" * 43},
                {},
                403,
            ),
            (
                {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
                {"subject_id": "telegram:202"},
                400,
            ),
        )

        for headers, body, expected_status in cases:
            with self.subTest(headers=headers, body=body):
                response = client.post(endpoint, headers=headers, json=body)
                self.assertEqual(response.status_code, expected_status)

        unauthenticated = self._client().post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.core.account_session_calls, [])

    def test_account_operation_link_rejects_unsafe_factory_urls(self) -> None:
        client = self._client()
        csrf = self._login(client)
        endpoint = "/miniapp/api/operations/account"
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        unsafe_results: tuple[object, ...] = (
            {"account_url": "https://attacker.invalid/account"},
            {"account_url": "https://www.agentonomy.xyz.evil/account"},
            {"account_url": "https://user@www.agentonomy.xyz/account"},
            {"account_url": "//www.agentonomy.xyz/account"},
            {"account_url": "ftp://www.agentonomy.xyz/account"},
            {"account_url": "https://www.agentonomy.xyz:444/account"},
            {"account_url": f"{ORIGIN}/admin"},
            {"account_url": f"{ORIGIN}/account.evil"},
            {"account_url": f"{ORIGIN}/account/../admin"},
            {"account_url": f"{ORIGIN}/account/\ud800"},
            {"account_url": "javascript:alert(1)"},
            {"account_url": 123},
            {},
            "not-a-mapping",
        )

        for result in unsafe_results:
            with self.subTest(result=result):
                self.service.traffic_guard = MemoryMiniAppTrafficGuard()
                self.core.account_session_result = result
                response = client.post(endpoint, headers=headers, json={})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_unavailable"},
                )
                self.assertNotIn("attacker", response.text)

        self.assertEqual(
            len(self.core.account_session_calls),
            len(unsafe_results),
        )

    def test_account_operation_factory_exception_is_redacted_and_not_retried(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.core.account_session_error = RuntimeError(
            "PRIVATE_CORE_ACCOUNT_MARKER"
        )
        session_token = client.cookies.get("agentonomy_miniapp_session")
        session = self.service.sessions.authenticate_session(session_token)

        with self.assertRaises(MiniAppServiceError) as caught:
            self.service.create_account_operation_link(session)

        self.assertEqual(str(caught.exception), "miniapp_unavailable")
        self.assertNotIn("PRIVATE_CORE_ACCOUNT_MARKER", repr(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(self.core.account_session_calls, ["telegram:101"])
        self.core.account_session_calls.clear()

        response = client.post(
            "/miniapp/api/operations/account",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn("PRIVATE_CORE_ACCOUNT_MARKER", response.text)
        self.assertEqual(self.core.account_session_calls, ["telegram:101"])

    def test_polymarket_operation_link_uses_only_authenticated_subject(
        self,
    ) -> None:
        alice = self._client()
        bob = self._client()
        alice_csrf = self._login(alice)
        bob_login = self._exchange(
            bob,
            init_data=_signed_init_data(user_id=202, username="bob"),
        )
        self.assertEqual(bob_login.status_code, 201)
        endpoint = "/miniapp/api/operations/polymarket"

        browser_override = alice.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf},
            json={
                "user_id": "telegram:202",
                "return_url": "https://evil.invalid",
            },
        )
        alice_link = alice.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf},
            json={},
        )
        self.prediction.binding_session_result = (
            f"{ORIGIN}/polymarket/binding-console/"
            "pm_bind_sess_0f1e2d3c4b5a?access_token=bob-console-token"
        )
        bob_link = bob.post(
            endpoint,
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": bob_login.json()["csrf_token"],
            },
            json={},
        )

        self.assertEqual(browser_override.status_code, 400)
        self.assertEqual(
            browser_override.json(),
            {"detail": "miniapp_invalid_request"},
        )
        self.assertEqual(alice_link.status_code, 200)
        self.assertEqual(
            alice_link.json(),
            {
                "url": (
                    f"{ORIGIN}/polymarket/binding-console/"
                    "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
                )
            },
        )
        self.assertEqual(bob_link.status_code, 200)
        self.assertEqual(
            self.prediction.binding_session_calls,
            ["telegram:101", "telegram:202"],
        )

    def test_polymarket_operation_link_requires_auth_origin_csrf_and_empty_body(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        endpoint = "/miniapp/api/operations/polymarket"
        cases = (
            ({"X-Agentonomy-CSRF": csrf}, {}, 403),
            (
                {
                    "Origin": "https://www.agentonomy.xyz:444",
                    "X-Agentonomy-CSRF": csrf,
                },
                {},
                403,
            ),
            ({"Origin": ORIGIN}, {}, 403),
            (
                {"Origin": ORIGIN, "X-Agentonomy-CSRF": "x" * 43},
                {},
                403,
            ),
            (
                {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
                {"wallet": "0x123", "session": "other", "run": "live"},
                400,
            ),
        )

        for headers, body, expected_status in cases:
            with self.subTest(headers=headers, body=body):
                response = client.post(endpoint, headers=headers, json=body)
                self.assertEqual(response.status_code, expected_status)

        unauthenticated = self._client().post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.prediction.binding_session_calls, [])

    def test_polymarket_operation_link_rejects_unsafe_factory_urls(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        endpoint = "/miniapp/api/operations/polymarket"
        headers = {"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf}
        unsafe_results: tuple[object, ...] = (
            (
                "https://attacker.invalid/polymarket/binding-console/"
                "pm_bind_sess_a1"
            ),
            (
                "https://www.agentonomy.xyz.evil/polymarket/"
                "binding-console/pm_bind_sess_a1"
            ),
            f"{ORIGIN}/polymarket/binding-console/not-a-session",
            f"{ORIGIN}/polymarket/binding-console/pm_bind_sess_a1/extra",
            f"{ORIGIN}/polymarket/binding-console/pm_bind_sess_a1?bad=1",
            f"{ORIGIN}/polymarket/binding-console/../admin",
            f"{ORIGIN}/admin",
            123,
            None,
        )

        for result in unsafe_results:
            with self.subTest(result=result):
                self.service.traffic_guard = MemoryMiniAppTrafficGuard()
                self.prediction.binding_session_result = result
                response = client.post(endpoint, headers=headers, json={})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_unavailable"},
                )
                self.assertNotIn("attacker", response.text)

        self.assertEqual(
            len(self.prediction.binding_session_calls),
            len(unsafe_results),
        )

    def test_polymarket_operation_factory_exception_is_redacted_and_not_retried(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.prediction.binding_session_error = RuntimeError(
            "PRIVATE_POLYMARKET_LINK_MARKER"
        )
        session_token = client.cookies.get("agentonomy_miniapp_session")
        session = self.service.sessions.authenticate_session(session_token)

        with self.assertRaises(MiniAppServiceError) as caught:
            self.service.create_polymarket_operation_link(session)

        self.assertEqual(str(caught.exception), "miniapp_unavailable")
        self.assertNotIn(
            "PRIVATE_POLYMARKET_LINK_MARKER",
            repr(caught.exception),
        )
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(
            self.prediction.binding_session_calls,
            ["telegram:101"],
        )
        self.prediction.binding_session_calls.clear()

        response = client.post(
            "/miniapp/api/operations/polymarket",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            json={},
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn("PRIVATE_POLYMARKET_LINK_MARKER", response.text)
        self.assertEqual(
            self.prediction.binding_session_calls,
            ["telegram:101"],
        )

    def test_session_exchange_rejects_origin_and_body_shape_before_storage(
        self,
    ) -> None:
        client = self._client()
        payload = {
            "init_data": _signed_init_data(),
            "client_nonce": CLIENT_NONCE,
        }
        cases = (
            ({}, json.dumps(payload)),
            ({"Origin": "http://www.agentonomy.xyz"}, json.dumps(payload)),
            ({"Origin": "https://user@www.agentonomy.xyz"}, json.dumps(payload)),
            ({"Origin": ORIGIN}, json.dumps({**payload, "user_id": 101})),
            (
                {"Origin": ORIGIN},
                '{"init_data":"x","init_data":"y","client_nonce":"z"}',
            ),
        )

        for headers, body in cases:
            with self.subTest(headers=headers, body=body[:40]):
                response = client.post(
                    "/miniapp/api/session",
                    headers={"Content-Type": "application/json", **headers},
                    content=body,
                )
                self.assertIn(response.status_code, {400, 403})

        self.assertIsNone(
            self.repository.get_miniapp_session("0" * 64, NOW)
        )

    def test_chat_gets_or_creates_one_deterministic_private_hermes_session(
        self,
    ) -> None:
        client = self._client()
        self._login(client)

        first = client.get("/miniapp/api/chat")
        second = client.get("/miniapp/api/chat")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["messages"], [])
        self.assertEqual(len(self.hermes.create_session_calls), 1)
        self.assertGreaterEqual(len(self.hermes.get_session_calls), 2)
        session_id = self.hermes.create_session_calls[0][1]
        self.assertNotIn("101", session_id)
        self.assertNotIn(session_id, first.text)
        self.assertNotIn(self.hermes.bound_keys[0], first.text)

    def test_short_history_uses_one_latest_window_for_chat_and_submit(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)

        chat = client.get("/miniapp/api/chat")

        self.assertEqual(chat.status_code, 200)
        self.assertEqual(
            [call[2:] for call in self.hermes.get_messages_calls],
            [(40, 0, "latest")],
        )

        self.hermes.get_messages_calls.clear()
        submitted = self._send(
            client,
            csrf,
            client_message_id="47474747-4747-4747-8747-474747474747",
            text="one start only",
        )

        self.assertEqual(submitted.status_code, 202)
        self.assertEqual(
            [call[2:] for call in self.hermes.get_messages_calls],
            [(40, 0, "latest")],
        )
        self.assertEqual(len(self.hermes.start_run_calls), 1)

    def test_chat_retries_only_oversized_latest_windows_chronologically(
        self,
    ) -> None:
        client = self._client()
        self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        session_id = self.hermes.create_session_calls[0][1]
        self.hermes.messages[session_id] = [
            HermesMessage(index, session_id, "user", f"message-{index}", float(index))
            for index in range(1, 7)
        ]
        self.hermes.get_messages_errors = {
            limit: HermesResponseTooLarge() for limit in (40, 20, 10)
        }
        self.hermes.get_messages_calls.clear()

        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [call[2:] for call in self.hermes.get_messages_calls],
            [
                (40, 0, "latest"),
                (20, 0, "latest"),
                (10, 0, "latest"),
                (5, 0, "latest"),
            ],
        )
        self.assertEqual(
            [item["content"] for item in response.json()["messages"]],
            [f"message-{index}" for index in range(2, 7)],
        )

    def test_submit_retries_only_oversized_latest_windows_before_one_start(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        session_id = self.hermes.create_session_calls[0][1]
        self.hermes.messages[session_id] = [
            HermesMessage(index, session_id, "user", f"message-{index}", float(index))
            for index in range(1, 13)
        ]
        self.hermes.get_messages_errors = {
            limit: HermesResponseTooLarge() for limit in (40, 20)
        }
        self.hermes.get_messages_calls.clear()

        response = self._send(
            client,
            csrf,
            client_message_id="48484848-4848-4848-8848-484848484848",
            text="submit after bounded history",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(
            [call[2:] for call in self.hermes.get_messages_calls],
            [
                (40, 0, "latest"),
                (20, 0, "latest"),
                (10, 0, "latest"),
            ],
        )
        self.assertEqual(len(self.hermes.start_run_calls), 1)
        history = self.hermes.start_run_calls[0][3]
        self.assertEqual(
            [item.content for item in history],
            [f"message-{index}" for index in range(3, 13)],
        )

    def test_oversized_one_message_window_fails_closed_without_start(
        self,
    ) -> None:
        for operation in ("chat", "submit"):
            with self.subTest(operation=operation):
                self.tearDown()
                self.setUp()
                client = self._client()
                csrf = self._login(client)
                self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
                self.hermes.get_messages_errors = {
                    limit: HermesResponseTooLarge()
                    for limit in (40, 20, 10, 5, 1)
                }
                self.hermes.get_messages_calls.clear()

                if operation == "chat":
                    response = client.get("/miniapp/api/chat")
                else:
                    response = self._send(
                        client,
                        csrf,
                        client_message_id=(
                            "49494949-4949-4949-8949-494949494949"
                        ),
                        text="must not start",
                    )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_unavailable"},
                )
                self.assertEqual(
                    [call[2] for call in self.hermes.get_messages_calls],
                    [40, 20, 10, 5, 1],
                )
                self.assertEqual(self.hermes.start_run_calls, [])

    def test_non_oversize_history_failure_is_never_retried(self) -> None:
        for failure_type in (HermesProtocolError, HermesUnavailable):
            for operation in ("chat", "submit"):
                with self.subTest(
                    failure_type=failure_type.__name__,
                    operation=operation,
                ):
                    self.tearDown()
                    self.setUp()
                    client = self._client()
                    csrf = self._login(client)
                    self.assertEqual(
                        client.get("/miniapp/api/chat").status_code,
                        200,
                    )
                    self.hermes.get_messages_errors = {40: failure_type()}
                    self.hermes.get_messages_calls.clear()

                    if operation == "chat":
                        response = client.get("/miniapp/api/chat")
                    else:
                        response = self._send(
                            client,
                            csrf,
                            client_message_id=(
                                "50505050-5050-4050-8050-505050505050"
                            ),
                            text="do not retry history",
                        )

                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(
                        response.json(),
                        {"detail": "miniapp_unavailable"},
                    )
                    self.assertEqual(
                        [call[2] for call in self.hermes.get_messages_calls],
                        [40],
                    )
                    self.assertEqual(self.hermes.start_run_calls, [])

    def test_blocking_hermes_call_does_not_block_api_event_loop(self) -> None:
        test_client = self._client()
        app = test_client.app
        test_client.close()
        self.hermes.get_session_release = threading.Event()
        health_done = threading.Event()
        health_seen_before_release: list[bool] = []

        def release_after_health() -> None:
            health_seen_before_release.append(health_done.wait(timeout=0.5))
            self.hermes.get_session_release.set()

        async def scenario() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=ORIGIN,
            ) as client:
                login = await client.post(
                    "/miniapp/api/session",
                    headers={"Origin": ORIGIN},
                    json={
                        "init_data": _signed_init_data(),
                        "client_nonce": CLIENT_NONCE,
                    },
                )
                self.assertEqual(login.status_code, 201)

                async def health() -> httpx.Response:
                    response = await client.get("/healthz")
                    health_done.set()
                    return response

                releaser = threading.Thread(target=release_after_health)
                releaser.start()
                chat_task = asyncio.create_task(client.get("/miniapp/api/chat"))
                health_task = asyncio.create_task(health())
                chat_response, health_response = await asyncio.gather(
                    chat_task,
                    health_task,
                )
                releaser.join(timeout=2)
                self.assertFalse(releaser.is_alive())
                return chat_response, health_response

        chat_response, health_response = asyncio.run(scenario())

        self.assertEqual(health_seen_before_release, [True])
        self.assertEqual(chat_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)

    def test_session_create_conflict_or_lost_response_probes_get_once(self) -> None:
        for mode in ("conflict_after_create", "unavailable_after_create"):
            with self.subTest(mode=mode):
                self.tearDown()
                self.setUp()
                self.hermes.create_mode = mode
                client = self._client()
                self._login(client)

                response = client.get("/miniapp/api/chat")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(self.hermes.create_session_calls), 1)
                self.assertEqual(len(self.hermes.get_session_calls), 2)

    def test_session_create_failure_probes_once_without_second_post(self) -> None:
        self.hermes.create_mode = "unavailable_without_create"
        client = self._client()
        self._login(client)

        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertEqual(len(self.hermes.create_session_calls), 1)
        self.assertEqual(len(self.hermes.get_session_calls), 2)

    def test_two_users_receive_distinct_private_hermes_scopes(self) -> None:
        alice = self._client()
        bob = self._client()
        self._login(alice)
        bob_login = self._exchange(
            bob,
            init_data=_signed_init_data(user_id=202, username="bob"),
        )
        self.assertEqual(bob_login.status_code, 201)

        self.assertEqual(alice.get("/miniapp/api/chat").status_code, 200)
        self.assertEqual(bob.get("/miniapp/api/chat").status_code, 200)

        self.assertEqual(len(set(self.hermes.bound_keys)), 2)
        session_ids = [item[1] for item in self.hermes.create_session_calls]
        self.assertEqual(len(set(session_ids)), 2)
        for session_id in session_ids:
            self.assertNotIn("101", session_id)
            self.assertNotIn("202", session_id)

    def test_chat_projects_descendant_messages_without_exposing_session_id(
        self,
    ) -> None:
        client = self._client()
        self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root_session = self.hermes.create_session_calls[0][1]
        child_session = "compacted_child_session"
        self.hermes.descendants[root_session] = child_session
        self.hermes.messages[child_session] = [
            HermesMessage(
                id=1,
                session_id=child_session,
                role="user",
                content="first",
                timestamp=1.0,
            ),
            HermesMessage(
                id=2,
                session_id=child_session,
                role="assistant",
                content="second",
                timestamp=2.0,
            ),
        ]

        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["content"] for item in response.json()["messages"]],
            ["first", "second"],
        )
        self.assertNotIn(root_session, response.text)
        self.assertNotIn(child_session, response.text)

    def test_chat_hides_system_and_tool_messages_but_keeps_server_history(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        session_id = self.hermes.create_session_calls[0][1]
        self.hermes.messages[session_id] = [
            HermesMessage(1, session_id, "system", "SYSTEM_SECRET_MARKER", 1.0),
            HermesMessage(2, session_id, "user", "visible question", 2.0),
            HermesMessage(3, session_id, "tool", "TOOL_RESULT_MARKER", 3.0),
            HermesMessage(4, session_id, "assistant", "visible answer", 4.0),
        ]

        projected = client.get("/miniapp/api/chat")
        submitted = self._send(
            client,
            csrf,
            client_message_id="41414141-4141-4141-8141-414141414141",
            text="continue",
        )

        self.assertEqual(projected.status_code, 200)
        self.assertEqual(
            [
                (item["role"], item["content"])
                for item in projected.json()["messages"]
            ],
            [
                ("user", "visible question"),
                ("assistant", "visible answer"),
            ],
        )
        self.assertNotIn("SYSTEM_SECRET_MARKER", projected.text)
        self.assertNotIn("TOOL_RESULT_MARKER", projected.text)
        self.assertEqual(submitted.status_code, 202)
        history = self.hermes.start_run_calls[-1][3]
        self.assertEqual(
            [(item.role, item.content) for item in history],
            [
                ("system", "SYSTEM_SECRET_MARKER"),
                ("user", "visible question"),
                ("tool", "TOOL_RESULT_MARKER"),
                ("assistant", "visible answer"),
            ],
        )

    def test_chat_hides_blank_assistant_messages_but_keeps_run_history(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        session_id = self.hermes.create_session_calls[0][1]
        self.hermes.messages[session_id] = [
            HermesMessage(1, session_id, "user", "visible question", 1.0),
            HermesMessage(2, session_id, "assistant", "", 2.0),
            HermesMessage(3, session_id, "assistant", "   ", 3.0),
            HermesMessage(4, session_id, "assistant", "visible answer", 4.0),
        ]

        projected = client.get("/miniapp/api/chat")
        submitted = self._send(
            client,
            csrf,
            client_message_id="46464646-4646-4646-8646-464646464646",
            text="continue",
        )

        self.assertEqual(projected.status_code, 200)
        self.assertEqual(
            [
                (item["role"], item["content"])
                for item in projected.json()["messages"]
            ],
            [
                ("user", "visible question"),
                ("assistant", "visible answer"),
            ],
        )
        self.assertEqual(submitted.status_code, 202)
        history = self.hermes.start_run_calls[-1][3]
        self.assertEqual(
            [(item.role, item.content) for item in history],
            [
                ("user", "visible question"),
                ("assistant", ""),
                ("assistant", "   "),
                ("assistant", "visible answer"),
            ],
        )

    def test_chat_latest_ignores_accepted_claim_without_active_lease(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "56565656-5656-4656-8656-565656565656"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="historical accepted message",
            ).status_code,
            202,
        )
        self.assertTrue(
            self.repository.release_miniapp_active_run_lease(
                "telegram:101",
                message_id,
            )
        )

        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["latest"])

    def test_inconsistent_effective_message_session_fails_closed(self) -> None:
        client = self._client()
        self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root_session = self.hermes.create_session_calls[0][1]
        self.hermes.messages[root_session] = [
            HermesMessage(
                id=1,
                session_id="unrelated_session",
                role="assistant",
                content="must not cross scopes",
                timestamp=1.0,
            )
        ]

        response = client.get("/miniapp/api/chat")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn("must not cross scopes", response.text)

    def test_message_request_is_strict_bounded_and_preserves_exact_text(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "11111111-1111-4111-8111-111111111111"
        cases = (
            {"client_message_id": message_id, "text": "", "extra": None},
            {"client_message_id": message_id, "text": "   ", "extra": None},
            {
                "client_message_id": "NOT-A-UUID",
                "text": "hello",
                "extra": None,
            },
            {
                "client_message_id": message_id,
                "text": "é" * 8193,
                "extra": None,
            },
            *(
                {
                    "client_message_id": message_id,
                    "text": "hello",
                    "extra": {field: "override"},
                }
                for field in (
                    "user_id",
                    "subject_id",
                    "session_id",
                    "run_id",
                    "run_owner",
                    "model",
                    "provider",
                    "system",
                    "tools",
                )
            ),
        )
        for item in cases:
            with self.subTest(item=str(item)[:80]):
                self.service.traffic_guard = MemoryMiniAppTrafficGuard()
                response = self._send(
                    client,
                    csrf,
                    client_message_id=item["client_message_id"],
                    text=item["text"],
                    extra=item["extra"],
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {"detail": "miniapp_invalid_request"},
                )

        raw_surrogate = json.dumps(
            {"client_message_id": message_id, "text": "\ud800"},
            ensure_ascii=True,
        )
        self.service.traffic_guard = MemoryMiniAppTrafficGuard()
        surrogate = client.post(
            "/miniapp/api/chat/messages",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": csrf,
                "Content-Type": "application/json",
            },
            content=raw_surrogate,
        )
        self.assertEqual(surrogate.status_code, 400)
        self.assertEqual(self.hermes.start_run_calls, [])

        valid_id = "22222222-2222-4222-8222-222222222222"
        self.service.traffic_guard = MemoryMiniAppTrafficGuard()
        accepted = self._send(
            client,
            csrf,
            client_message_id=valid_id,
            text="  preserve me exactly  ",
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(
            self.hermes.start_run_calls[-1][2],
            "  preserve me exactly  ",
        )

    def test_request_body_cap_stops_before_next_asgi_chunk(self) -> None:
        client = self._client()
        first = b"x" * 12_000
        second = b"y" * (_MAX_SESSION_BODY_BYTES - len(first) + 1)

        status, payload, receive_calls = _raw_asgi_request(
            client.app,
            path="/miniapp/api/session",
            headers=[
                (b"content-type", b"application/json"),
                (b"content-length", str(_MAX_SESSION_BODY_BYTES).encode()),
                (b"origin", ORIGIN.encode()),
            ],
            request_messages=[
                {"type": "http.request", "body": first, "more_body": True},
                {"type": "http.request", "body": second, "more_body": True},
                {
                    "type": "http.request",
                    "body": b"must-not-be-read",
                    "more_body": False,
                },
            ],
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"detail": "miniapp_invalid_request"})
        self.assertEqual(receive_calls, 2)

    def test_request_body_cap_is_enforced_without_content_length(self) -> None:
        client = self._client()

        status, payload, receive_calls = _raw_asgi_request(
            client.app,
            path="/miniapp/api/session",
            headers=[
                (b"content-type", b"application/json"),
                (b"origin", ORIGIN.encode()),
            ],
            request_messages=[
                {
                    "type": "http.request",
                    "body": b"x" * _MAX_SESSION_BODY_BYTES,
                    "more_body": True,
                },
                {"type": "http.request", "body": b"x", "more_body": False},
            ],
        )

        self.assertEqual(status, 400)
        self.assertEqual(payload, {"detail": "miniapp_invalid_request"})
        self.assertEqual(receive_calls, 2)

    def test_content_length_is_unique_ascii_decimal_and_early_bounded(self) -> None:
        client = self._client()
        cases = (
            [b"1", b"1"],
            [b""],
            [b"+1"],
            [b"-1"],
            [b"1, 1"],
            [b"1 "],
            [b"not-a-number"],
            [str(_MAX_SESSION_BODY_BYTES + 1).encode()],
        )

        for values in cases:
            with self.subTest(values=values):
                status, payload, receive_calls = _raw_asgi_request(
                    client.app,
                    path="/miniapp/api/session",
                    headers=[
                        (b"content-type", b"application/json"),
                        *((b"content-length", value) for value in values),
                        (b"origin", ORIGIN.encode()),
                    ],
                    request_messages=[],
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload, {"detail": "miniapp_invalid_request"})
                self.assertEqual(receive_calls, 0)

    def test_sse_failure_is_redacted_and_closes_upstream(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "03030303-0303-4303-8303-030303030303"
        accepted = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="hello",
        )
        self.assertEqual(accepted.status_code, 202)
        marker = "do-not-reflect-upstream-session-key"
        self.hermes.stream_error_marker = marker

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("miniapp_stream_unavailable", response.text)
        self.assertNotIn(marker, response.text)
        self.assertTrue(self.hermes.streams[-1].closed)

    def test_sse_downstream_close_closes_upstream_early(self) -> None:
        events = _CloseableEvents(
            [
                HermesSseEvent("message.delta", "1", {"delta": "one"}),
                HermesSseEvent("message.delta", "2", {"delta": "two"}),
            ]
        )
        guard = MemoryMiniAppTrafficGuard()
        lease = guard.acquire_sse("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        releases: list[bool] = []

        def release() -> None:
            releases.append(guard.release_sse("telegram:101", lease))

        async def consume_one_then_close() -> bytes:
            stream = _serialize_events(events, on_close=release)
            first = await anext(stream)
            await stream.aclose()
            return first

        first = asyncio.run(consume_one_then_close())

        self.assertIn(b"one", first)
        self.assertTrue(events.closed)
        self.assertEqual(releases, [True])
        self.assertIsNotNone(guard.acquire_sse("telegram:101"))

    def test_sse_iterator_setup_failure_is_redacted_and_releases_once(
        self,
    ) -> None:
        marker = "PRIVATE_BROKEN_ITERATOR_MARKER"
        events = _BrokenIterableEvents(marker)
        releases: list[str] = []

        async def consume_error() -> bytes:
            stream = _serialize_events(
                events,
                on_close=lambda: releases.append("released"),
            )
            item = await anext(stream)
            await stream.aclose()
            return item

        item = asyncio.run(consume_error())

        self.assertIn(b"miniapp_stream_unavailable", item)
        self.assertNotIn(marker.encode(), item)
        self.assertTrue(events.closed)
        self.assertEqual(releases, ["released"])

    def test_shared_guard_allows_only_one_cross_service_sse_and_releases(
        self,
    ) -> None:
        guard = MemoryMiniAppTrafficGuard()
        first_service = self._service_with_traffic_guard(guard)
        second_service = self._service_with_traffic_guard(guard)
        first_client = self._client(service=first_service)
        second_client = self._client(service=second_service)
        first_csrf = self._login(first_client)
        second_csrf = self._login(second_client)
        self.assertEqual(first_csrf, second_csrf)
        message_id = "06060606-0606-4606-8606-060606060606"
        accepted = self._send(
            first_client,
            first_csrf,
            client_message_id=message_id,
            text="one stream",
        )
        self.assertEqual(accepted.status_code, 202)
        session_token = first_client.cookies.get(
            "agentonomy_miniapp_session"
        )
        self.assertIsNotNone(session_token)
        session = first_service.sessions.authenticate_session(session_token)

        lease = first_service.acquire_sse_lease(session)
        upstream = first_service.stream_message_events(session, message_id)
        self.assertEqual(len(self.hermes.stream_calls), 1)

        blocked = second_client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(
            blocked.json(),
            {"detail": "miniapp_rate_limited"},
        )
        self.assertEqual(len(self.hermes.stream_calls), 1)

        upstream.close()
        first_service.release_sse_lease(lease)
        resumed = second_client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(len(self.hermes.stream_calls), 2)
        self.assertIsNotNone(guard.acquire_sse("telegram:101"))

    def test_sse_lease_is_acquired_before_any_hermes_stream_call(self) -> None:
        guard = _RecordingTrafficGuard()
        guard.sse_available = False
        service = self._service_with_traffic_guard(guard)
        client = self._client(service=service)
        csrf = self._login(client)
        message_id = "07070707-0707-4707-8707-070707070707"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="blocked stream",
            ).status_code,
            202,
        )

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(guard.acquire_calls, ["telegram:101"])
        self.assertEqual(self.hermes.stream_calls, [])

    def test_sse_setup_exception_releases_lease_for_recovery(self) -> None:
        guard = MemoryMiniAppTrafficGuard()
        service = self._service_with_traffic_guard(guard)
        client = self._client(service=service)
        csrf = self._login(client)
        message_id = "08080808-0808-4808-8808-080808080808"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="setup failure",
            ).status_code,
            202,
        )
        self.hermes.get_run_mode = "unavailable"

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertIsNotNone(guard.acquire_sse("telegram:101"))

    def test_unexpected_sse_setup_exception_is_redacted_and_releases(
        self,
    ) -> None:
        marker = "redis://secret-cache/0 PRIVATE_SSE_SETUP_MARKER"
        guard = MemoryMiniAppTrafficGuard()
        service = self._service_with_traffic_guard(guard)
        client = self._client(service=service)
        csrf = self._login(client)
        message_id = "09090909-0909-4909-8909-090909090909"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="unexpected setup failure",
            ).status_code,
            202,
        )

        def fail_stream(*args: object, **kwargs: object):
            raise RuntimeError(marker)

        service.stream_message_events = fail_stream  # type: ignore[method-assign]

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn(marker, response.text)
        self.assertIsNotNone(guard.acquire_sse("telegram:101"))

    def test_message_claim_is_at_most_once_with_replay_and_payload_conflict(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "33333333-3333-4333-8333-333333333333"

        first = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="hello",
        )
        replay = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="hello",
        )
        changed = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="changed",
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(first.json()["status"], "accepted")
        self.assertNotIn("run_", first.text)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json(), {"detail": "miniapp_conflict"})
        self.assertEqual(len(self.hermes.start_run_calls), 1)

    def test_same_message_replay_keeps_original_provenance_after_rotation(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root = self.hermes.create_session_calls[0][1]
        self.hermes.descendants[root] = "child_a"
        message_id = "31313131-3131-4131-8131-313131313131"

        first = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="same payload",
        )
        self.assertEqual(first.status_code, 202)
        claim = self.repository.get_miniapp_message_claim(
            "telegram:101",
            message_id,
        )
        self.assertIsNotNone(claim)
        assert claim is not None
        self.assertEqual(claim.hermes_run_session_id, "child_a")
        self.assertFalse(claim.legacy_unreconciled)
        message_calls = len(self.hermes.get_messages_calls)
        start_calls = len(self.hermes.start_run_calls)

        self.hermes.descendants[root] = "child_b"
        replay = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="same payload",
        )
        changed = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="different payload",
        )

        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json(), {"detail": "miniapp_conflict"})
        self.assertEqual(len(self.hermes.get_messages_calls), message_calls)
        self.assertEqual(len(self.hermes.start_run_calls), start_calls)
        stored = self.repository.get_miniapp_message_claim(
            "telegram:101",
            message_id,
        )
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.hermes_run_session_id, "child_a")

    def test_old_run_routes_use_claim_provenance_after_rotation(self) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root = self.hermes.create_session_calls[0][1]
        self.hermes.descendants[root] = "child_a"
        message_id = "32323232-3232-4232-8232-323232323232"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="run on a",
            ).status_code,
            202,
        )
        self.hermes.events["run_1"] = [
            HermesSseEvent(
                event="message.delta",
                id="event-a",
                data={
                    "event": "message.delta",
                    "run_id": "run_1",
                    "delta": "from a",
                },
            )
        ]
        self.hermes.descendants[root] = "child_b"
        message_calls = len(self.hermes.get_messages_calls)
        base = f"/miniapp/api/chat/messages/{message_id}"

        status = client.get(f"{base}/run")
        events = client.get(f"{base}/events")
        stopped = client.post(
            f"{base}/stop",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
        )

        self.assertEqual(status.status_code, 200)
        self.assertEqual(events.status_code, 200)
        self.assertIn("from a", events.text)
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(len(self.hermes.get_messages_calls), message_calls)
        self.assertEqual(
            [session_id for _, _, session_id in self.hermes.get_run_calls],
            ["child_a", "child_a", "child_a"],
        )

    def test_active_run_uses_old_provenance_then_new_run_uses_rotated_child(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root = self.hermes.create_session_calls[0][1]
        self.hermes.descendants[root] = "child_a"
        first_id = "34343434-3434-4434-8434-343434343434"
        second_id = "35353535-3535-4535-8535-353535353535"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=first_id,
                text="first",
            ).status_code,
            202,
        )
        self.hermes.descendants[root] = "child_b"

        blocked = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="second",
        )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json(), {"detail": "miniapp_run_active"})
        self.assertEqual(self.hermes.get_run_calls[-1][2], "child_a")
        self.assertEqual(len(self.hermes.start_run_calls), 1)

        self.hermes.runs["run_1"] = HermesRun(
            run_id="run_1",
            status="completed",
            session_id="child_a",
        )
        accepted = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="second",
        )

        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(self.hermes.get_run_calls[-1][2], "child_a")
        self.assertEqual(self.hermes.start_run_calls[-1][1], "child_b")
        second_claim = self.repository.get_miniapp_message_claim(
            "telegram:101",
            second_id,
        )
        self.assertIsNotNone(second_claim)
        assert second_claim is not None
        self.assertEqual(second_claim.hermes_run_session_id, "child_b")

    def test_legacy_unreconciled_claim_fails_closed_before_hermes(self) -> None:
        client = self._client()
        csrf = self._login(client)
        legacy_id = "36363636-3636-4636-8636-363636363636"
        payload_hash = hashlib.sha256(
            b"agentonomy-miniapp-message-v1\x00legacy"
        ).hexdigest()
        with self.repository.transaction() as connection:
            connection.execute(
                """
                INSERT INTO miniapp_message_claim(
                    subject_id, client_message_id, payload_hash,
                    status, hermes_run_id, hermes_run_session_id,
                    legacy_unreconciled, created_at, updated_at
                ) VALUES (?, ?, ?, 'unknown', NULL, NULL, 1, ?, ?)
                """,
                (
                    "telegram:101",
                    legacy_id,
                    payload_hash,
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO miniapp_active_run_lease(
                    subject_id, client_message_id, acquired_at, updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "telegram:101",
                    legacy_id,
                    NOW.isoformat(),
                    NOW.isoformat(),
                ),
            )

        replay = self._send(
            client,
            csrf,
            client_message_id=legacy_id,
            text="legacy",
        )
        run = client.get(f"/miniapp/api/chat/messages/{legacy_id}/run")
        fresh = self._send(
            client,
            csrf,
            client_message_id="37373737-3737-4737-8737-373737373737",
            text="must stay blocked",
        )

        self.assertEqual(replay.status_code, 503)
        self.assertEqual(replay.json(), {"detail": "miniapp_message_unknown"})
        self.assertEqual(run.status_code, 409)
        self.assertEqual(run.json(), {"detail": "miniapp_message_unknown"})
        self.assertEqual(fresh.status_code, 409)
        self.assertEqual(fresh.json(), {"detail": "miniapp_message_unknown"})
        self.assertEqual(self.hermes.bound_keys, [])
        self.assertEqual(self.hermes.get_run_calls, [])
        self.assertEqual(self.hermes.start_run_calls, [])

    def test_message_uses_bounded_chronological_descendant_history(self) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        root = self.hermes.create_session_calls[0][1]
        child = "resumed_child"
        self.hermes.descendants[root] = child
        self.hermes.messages[child] = [
            HermesMessage(1, child, "user", "one", 1.0),
            HermesMessage(2, child, "assistant", "two", 2.0),
        ]

        response = self._send(
            client,
            csrf,
            client_message_id="44444444-4444-4444-8444-444444444444",
            text="three",
        )

        self.assertEqual(response.status_code, 202)
        _, effective, _, history = self.hermes.start_run_calls[-1]
        self.assertEqual(effective, child)
        self.assertEqual(
            [(item.role, item.content) for item in history],
            [("user", "one"), ("assistant", "two")],
        )

    def test_message_trims_long_history_to_deterministic_utf8_budget(self) -> None:
        client = self._client()
        csrf = self._login(client)
        self.assertEqual(client.get("/miniapp/api/chat").status_code, 200)
        session_id = self.hermes.create_session_calls[0][1]
        oversized_old_message = "old-oversized|" + ("é" * (35 * 1024))
        bounded_messages = [
            HermesMessage(
                index + 2,
                session_id,
                "user",
                f"{index:03d}|" + ("é" * 4096),
                float(index + 2),
            )
            for index in range(150)
        ]
        self.hermes.messages[session_id] = [
            HermesMessage(
                1,
                session_id,
                "user",
                oversized_old_message,
                1.0,
            ),
            *bounded_messages,
        ]
        source_bytes = sum(
            len(item.role.encode("utf-8")) + len(item.content.encode("utf-8"))
            for item in self.hermes.messages[session_id]
        )
        self.assertGreater(source_bytes, 256 * 1024)

        response = self._send(
            client,
            csrf,
            client_message_id="45454545-4545-4545-8545-454545454545",
            text="current input stays separate",
        )

        self.assertEqual(response.status_code, 202)
        _, _, user_input, history = self.hermes.start_run_calls[-1]
        history_bytes = sum(
            len(item.role.encode("utf-8")) + len(item.content.encode("utf-8"))
            for item in history
        )
        self.assertLessEqual(history_bytes, 240 * 1024)
        self.assertEqual(user_input, "current input stays separate")
        self.assertEqual(
            [item.content for item in history],
            [item.content for item in bounded_messages[-29:]],
        )
        self.assertNotIn(oversized_old_message, [item.content for item in history])

    def test_ambiguous_start_is_unknown_and_never_replayed(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "55555555-5555-4555-8555-555555555555"
        self.hermes.start_mode = "unavailable"

        first = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="maybe sent",
        )
        replay = self._send(
            client,
            csrf,
            client_message_id=message_id,
            text="maybe sent",
        )
        fresh = self._send(
            client,
            csrf,
            client_message_id="52525252-5252-4252-8252-525252525252",
            text="must remain blocked",
        )

        self.assertEqual(first.status_code, 503)
        self.assertEqual(
            first.json(),
            {"detail": "miniapp_message_unknown"},
        )
        self.assertEqual(replay.status_code, 503)
        self.assertEqual(fresh.status_code, 503)
        self.assertEqual(
            fresh.json(),
            {"detail": "miniapp_message_unknown"},
        )
        self.assertEqual(len(self.hermes.start_run_calls), 1)
        lease = self.repository.get_miniapp_active_run_lease("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.client_message_id, message_id)

    def test_active_run_blocks_new_message_until_hermes_reports_terminal(self) -> None:
        client = self._client()
        csrf = self._login(client)
        first_id = "66666666-6666-4666-8666-666666666666"
        second_id = "77777777-7777-4777-8777-777777777777"
        self.assertEqual(
            self._send(client, csrf, client_message_id=first_id, text="one").status_code,
            202,
        )

        blocked = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json(), {"detail": "miniapp_run_active"})
        self.assertEqual(len(self.hermes.start_run_calls), 1)

        running = self.hermes.runs["run_1"]
        self.hermes.runs["run_1"] = HermesRun(
            run_id="run_1",
            status="completed",
            session_id=running.session_id,
        )
        accepted = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(len(self.hermes.start_run_calls), 2)

    def test_concurrent_same_message_claim_starts_one_run(self) -> None:
        first_client = self._client()
        second_client = self._client()
        first_csrf = self._login(first_client)
        second_csrf = self._login(second_client)
        self.assertEqual(first_csrf, second_csrf)
        self.hermes.start_release = threading.Event()
        message_id = "88888888-8888-4888-8888-888888888888"
        responses: list = []

        def send(client: TestClient, csrf: str) -> None:
            responses.append(
                self._send(
                    client,
                    csrf,
                    client_message_id=message_id,
                    text="once",
                )
            )

        one = threading.Thread(target=send, args=(first_client, first_csrf))
        two = threading.Thread(target=send, args=(second_client, second_csrf))
        one.start()
        self.assertTrue(self.hermes.start_entered.wait(timeout=2))
        two.start()
        self.hermes.start_release.set()
        one.join(timeout=3)
        two.join(timeout=3)

        self.assertFalse(one.is_alive())
        self.assertFalse(two.is_alive())
        self.assertEqual([item.status_code for item in responses], [202, 202])
        self.assertEqual(len(self.hermes.start_run_calls), 1)

    def test_two_service_instances_share_one_subject_run_lease(self) -> None:
        second_service = MiniAppChatService(
            repository=self.repository,
            hermes_client=self.hermes,
            account_link_factory=self.core.create_account_session,
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: self.now,
            auth_max_age_seconds=300,
            session_ttl_seconds=3600,
        )
        first_client = self._client()
        second_client = self._client(service=second_service)
        first_csrf = self._login(first_client)
        second_csrf = self._login(second_client)
        self.assertEqual(first_client.get("/miniapp/api/chat").status_code, 200)
        self.hermes.get_messages_barrier = threading.Barrier(2)
        self.hermes.start_release = threading.Event()
        responses: list = []

        def send(
            client: TestClient,
            csrf: str,
            client_message_id: str,
        ) -> None:
            responses.append(
                self._send(
                    client,
                    csrf,
                    client_message_id=client_message_id,
                    text=client_message_id,
                )
            )

        one = threading.Thread(
            target=send,
            args=(
                first_client,
                first_csrf,
                "43434343-4343-4343-8343-434343434343",
            ),
        )
        two = threading.Thread(
            target=send,
            args=(
                second_client,
                second_csrf,
                "44444444-5555-4666-8777-888888888888",
            ),
        )
        one.start()
        two.start()
        self.assertTrue(self.hermes.start_entered.wait(timeout=2))
        self.hermes.start_release.set()
        one.join(timeout=3)
        two.join(timeout=3)

        self.assertFalse(one.is_alive())
        self.assertFalse(two.is_alive())
        self.assertEqual(sorted(item.status_code for item in responses), [202, 409])
        blocked = next(item for item in responses if item.status_code == 409)
        self.assertEqual(blocked.json(), {"detail": "miniapp_run_active"})
        self.assertEqual(len(self.hermes.start_run_calls), 1)
        lease = self.repository.get_miniapp_active_run_lease("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        accepted_ids = {
            item.json()["client_message_id"]
            for item in responses
            if item.status_code == 202
        }
        self.assertEqual({lease.client_message_id}, accepted_ids)

    def test_terminal_status_releases_exact_lease_for_next_message(self) -> None:
        client = self._client()
        csrf = self._login(client)
        first_id = "45454545-4545-4545-8545-454545454545"
        second_id = "46464646-4646-4646-8646-464646464646"
        self.assertEqual(
            self._send(client, csrf, client_message_id=first_id, text="one").status_code,
            202,
        )
        running = self.hermes.runs["run_1"]
        self.hermes.runs["run_1"] = HermesRun(
            run_id="run_1",
            status="completed",
            session_id=running.session_id,
        )

        status = client.get(f"/miniapp/api/chat/messages/{first_id}/run")
        accepted = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")
        self.assertEqual(accepted.status_code, 202)
        self.assertEqual(len(self.hermes.start_run_calls), 2)
        replayed_status = client.get(
            f"/miniapp/api/chat/messages/{first_id}/run"
        )
        current_lease = self.repository.get_miniapp_active_run_lease(
            "telegram:101"
        )
        self.assertEqual(replayed_status.status_code, 404)
        self.assertEqual(
            replayed_status.json(),
            {"detail": "miniapp_not_found"},
        )
        self.assertIsNotNone(current_lease)
        assert current_lease is not None
        self.assertEqual(current_lease.client_message_id, second_id)

    def test_accepted_claim_without_lease_is_not_recoverable_or_stoppable(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "57575757-5757-4757-8757-575757575757"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="lease owner only",
            ).status_code,
            202,
        )
        self.assertTrue(
            self.repository.release_miniapp_active_run_lease(
                "telegram:101",
                message_id,
            )
        )
        hermes_call_counts = (
            len(self.hermes.bound_keys),
            len(self.hermes.get_run_calls),
            len(self.hermes.stream_calls),
            len(self.hermes.stop_calls),
        )
        base = f"/miniapp/api/chat/messages/{message_id}"

        responses = (
            client.get(f"{base}/run"),
            client.get(f"{base}/events"),
            client.post(
                f"{base}/stop",
                headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            ),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"detail": "miniapp_not_found"})
        self.assertEqual(
            (
                len(self.hermes.bound_keys),
                len(self.hermes.get_run_calls),
                len(self.hermes.stream_calls),
                len(self.hermes.stop_calls),
            ),
            hermes_call_counts,
        )

    def test_active_lease_with_missing_hermes_run_fails_closed(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "58585858-5858-4858-8858-585858585858"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="fail closed",
            ).status_code,
            202,
        )
        self.hermes.runs.clear()
        base = f"/miniapp/api/chat/messages/{message_id}"

        responses = (
            client.get(f"{base}/run"),
            client.get(f"{base}/events"),
            client.post(
                f"{base}/stop",
                headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
            ),
        )

        for response in responses:
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        lease = self.repository.get_miniapp_active_run_lease("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.client_message_id, message_id)
        self.assertEqual(self.hermes.stream_calls, [])
        self.assertEqual(self.hermes.stop_calls, [])

    def test_run_routes_map_claim_lookup_failure_to_fixed_503_without_hermes(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "59595959-5959-4959-8959-595959595959"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="storage failure stays unavailable",
            ).status_code,
            202,
        )
        hermes_call_counts = (
            len(self.hermes.bound_keys),
            len(self.hermes.get_run_calls),
            len(self.hermes.stream_calls),
            len(self.hermes.stop_calls),
        )
        base = f"/miniapp/api/chat/messages/{message_id}"
        cases = (
            ("status", lambda: client.get(f"{base}/run")),
            ("events", lambda: client.get(f"{base}/events")),
            (
                "stop",
                lambda: client.post(
                    f"{base}/stop",
                    headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
                ),
            ),
        )

        with mock.patch.object(
            self.repository,
            "get_miniapp_message_claim",
            side_effect=RuntimeError("STORAGE_EXCEPTION_MARKER"),
        ):
            responses = tuple((name, request()) for name, request in cases)

        self.assertEqual(
            [
                (name, response.status_code, response.json())
                for name, response in responses
            ],
            [
                ("status", 503, {"detail": "miniapp_unavailable"}),
                ("events", 503, {"detail": "miniapp_unavailable"}),
                ("stop", 503, {"detail": "miniapp_unavailable"}),
            ],
        )
        for _, response in responses:
            self.assertNotIn("STORAGE_EXCEPTION_MARKER", response.text)
        self.assertEqual(
            (
                len(self.hermes.bound_keys),
                len(self.hermes.get_run_calls),
                len(self.hermes.stream_calls),
                len(self.hermes.stop_calls),
            ),
            hermes_call_counts,
        )
        lease = self.repository.get_miniapp_active_run_lease("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.client_message_id, message_id)

    def test_terminal_stop_releases_lease_but_stopping_does_not(self) -> None:
        client = self._client()
        csrf = self._login(client)
        first_id = "47474747-4747-4747-8747-474747474747"
        second_id = "48484848-4848-4848-8848-484848484848"
        self.assertEqual(
            self._send(client, csrf, client_message_id=first_id, text="one").status_code,
            202,
        )
        endpoint = f"/miniapp/api/chat/messages/{first_id}/stop"
        stopping = client.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
        )
        blocked = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )
        self.hermes.stop_status = "cancelled"
        cancelled = client.post(
            endpoint,
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": csrf},
        )
        accepted = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )

        self.assertEqual(stopping.json()["status"], "stopping")
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertEqual(accepted.status_code, 202)

    def test_events_release_only_after_authoritative_terminal_status(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "49494949-4949-4949-8949-494949494949"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="one",
            ).status_code,
            202,
        )
        endpoint = f"/miniapp/api/chat/messages/{message_id}/events"

        running = client.get(endpoint)
        lease_while_running = self.repository.get_miniapp_active_run_lease(
            "telegram:101"
        )
        current = self.hermes.runs["run_1"]
        self.hermes.runs["run_1"] = HermesRun(
            run_id="run_1",
            status="failed",
            session_id=current.session_id,
        )
        terminal = client.get(endpoint)

        self.assertEqual(running.status_code, 200)
        self.assertIsNotNone(lease_while_running)
        self.assertEqual(terminal.status_code, 200)
        self.assertIsNone(
            self.repository.get_miniapp_active_run_lease("telegram:101")
        )

    def test_transport_ambiguity_keeps_accepted_owner_lease(self) -> None:
        client = self._client()
        csrf = self._login(client)
        first_id = "50505050-5050-4050-8050-505050505050"
        second_id = "51515151-5151-4151-8151-515151515151"
        self.assertEqual(
            self._send(client, csrf, client_message_id=first_id, text="one").status_code,
            202,
        )
        self.hermes.get_run_mode = "unavailable"

        blocked = self._send(
            client,
            csrf,
            client_message_id=second_id,
            text="two",
        )

        self.assertEqual(blocked.status_code, 503)
        self.assertEqual(blocked.json(), {"detail": "miniapp_unavailable"})
        lease = self.repository.get_miniapp_active_run_lease("telegram:101")
        self.assertIsNotNone(lease)
        assert lease is not None
        self.assertEqual(lease.client_message_id, first_id)
        self.assertEqual(len(self.hermes.start_run_calls), 1)

    def test_run_status_events_and_stop_are_subject_bound_by_message_claim(
        self,
    ) -> None:
        alice = self._client()
        bob = self._client()
        alice_csrf = self._login(alice)
        bob_login = self._exchange(
            bob,
            init_data=_signed_init_data(user_id=202, username="bob"),
        )
        self.assertEqual(bob_login.status_code, 201)
        bob_csrf = bob_login.json()["csrf_token"]
        message_id = "99999999-9999-4999-8999-999999999999"
        self.assertEqual(
            self._send(
                alice,
                alice_csrf,
                client_message_id=message_id,
                text="hello",
            ).status_code,
            202,
        )
        run = self.hermes.runs["run_1"]
        self.hermes.events["run_1"] = [
            HermesSseEvent(
                event="message.delta",
                id="event-1",
                data={
                    "event": "message.delta",
                    "run_id": "run_1",
                    "delta": "safe text",
                },
            )
        ]
        base = f"/miniapp/api/chat/messages/{message_id}"

        bob_status = bob.get(f"{base}/run")
        bob_events = bob.get(f"{base}/events")
        bob_stop = bob.post(
            f"{base}/stop",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": bob_csrf},
        )
        self.assertEqual(bob_status.status_code, 404)
        self.assertEqual(bob_events.status_code, 404)
        self.assertEqual(bob_stop.status_code, 404)
        self.assertEqual(self.hermes.stop_calls, [])

        status = alice.get(f"{base}/run")
        events = alice.get(f"{base}/events")
        missing_csrf = alice.post(f"{base}/stop", headers={"Origin": ORIGIN})
        stopped = alice.post(
            f"{base}/stop",
            headers={"Origin": ORIGIN, "X-Agentonomy-CSRF": alice_csrf},
        )

        self.assertEqual(status.status_code, 200)
        self.assertEqual(
            status.json(),
            {
                "client_message_id": message_id,
                "status": "running",
                "created_at": None,
                "updated_at": None,
                "has_output": False,
                "has_error": False,
                "output": None,
            },
        )
        self.assertNotIn(run.session_id, status.text)
        self.assertNotIn(self.hermes.bound_keys[0], status.text)
        self.assertEqual(events.status_code, 200)
        self.assertIn("event: message.delta", events.text)
        self.assertIn("safe text", events.text)
        self.assertNotIn("id: event-1", events.text)
        self.assertNotIn("run_1", events.text)
        self.assertTrue(self.hermes.streams[-1].closed)
        self.assertEqual(missing_csrf.status_code, 403)
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.json()["status"], "stopping")
        self.assertEqual(len(self.hermes.stop_calls), 1)

    def test_completed_run_returns_the_exact_bounded_output_only(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "89898989-8989-4989-8989-898989898989"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="fund 1 USDC",
            ).status_code,
            202,
        )
        current = self.hermes.runs["run_1"]
        output = (
            "已确认：https://www.agentonomy.xyz/miniapp/#funding=1.000000"
        )
        self.hermes.runs["run_1"] = HermesRun(
            run_id="must-not-leak-run-id",
            status="completed",
            session_id=current.session_id,
            output=output,
            error="must-not-leak-error",
        )

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/run"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "client_message_id": message_id,
                "status": "completed",
                "created_at": None,
                "updated_at": None,
                "has_output": True,
                "has_error": True,
                "output": output,
            },
        )
        self.assertNotIn("must-not-leak-run-id", response.text)
        self.assertNotIn("must-not-leak-error", response.text)
        self.assertNotIn(str(current.session_id), response.text)

    def test_run_hides_unsafe_output_even_when_hermes_reports_it(self) -> None:
        cases = (
            ("running", "must-not-leak-running-output"),
            ("completed", "x" * (128 * 1024 + 1)),
            ("completed", b"must-not-leak-non-string-output"),
        )
        for index, (status, output) in enumerate(cases):
            with self.subTest(status=status, output_type=type(output).__name__):
                client = self._client()
                csrf = self._login(client)
                message_id = (
                    f"77777777-7777-4777-8777-{index:012d}"
                )
                self.assertEqual(
                    self._send(
                        client,
                        csrf,
                        client_message_id=message_id,
                        text="hello",
                    ).status_code,
                    202,
                )
                current = self.hermes.runs[f"run_{index + 1}"]
                self.hermes.runs[f"run_{index + 1}"] = HermesRun(
                    run_id=f"run_{index + 1}",
                    status=status,
                    session_id=current.session_id,
                    output=output,  # type: ignore[arg-type]
                )

                response = client.get(
                    f"/miniapp/api/chat/messages/{message_id}/run"
                )

                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["has_output"])
                self.assertIsNone(response.json()["output"])
                if status == "running":
                    self.hermes.runs[f"run_{index + 1}"] = HermesRun(
                        run_id=f"run_{index + 1}",
                        status="completed",
                        session_id=current.session_id,
                    )
                    client.get(
                        f"/miniapp/api/chat/messages/{message_id}/run"
                    )

    def test_sse_projects_only_safe_delta_and_tool_labels(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "42424242-4242-4242-8242-424242424242"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="stream safely",
            ).status_code,
            202,
        )
        self.hermes.events["run_1"] = [
            HermesSseEvent(
                "message.delta",
                "RUN_ID_MARKER",
                {
                    "event": "message.delta",
                    "run_id": "RUN_ID_MARKER",
                    "delta": "safe delta",
                    "args": {"token": "NESTED_ARG_MARKER"},
                },
            ),
            HermesSseEvent(
                "tool.started",
                "SESSION_MARKER",
                {
                    "event": "tool.started",
                    "run_id": "RUN_ID_MARKER",
                    "tool": "web_search",
                    "args": {"query": "NESTED_ARG_MARKER"},
                },
            ),
            HermesSseEvent(
                "tool.completed",
                None,
                {
                    "event": "tool.completed",
                    "tool": "web_search",
                    "result": {"value": "NESTED_RESULT_MARKER"},
                },
            ),
            HermesSseEvent(
                "message.delta",
                None,
                {
                    "event": "message.delta",
                    "delta": "x" * (20 * 1024),
                },
            ),
            HermesSseEvent(
                "tool.started",
                None,
                {
                    "event": "tool.started",
                    "tool": "UNSAFE_LABEL_MARKER\nInjected",
                },
            ),
            HermesSseEvent(
                "unknown.remote",
                None,
                {
                    "event": "unknown.remote",
                    "secret": "UNKNOWN_EVENT_MARKER",
                },
            ),
        ]

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 200)
        data_lines = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(
            data_lines,
            [
                {"delta": "safe delta"},
                {"tool": "web_search"},
                {"tool": "web_search"},
                {"tool": "tool"},
            ],
        )
        for marker in (
            "RUN_ID_MARKER",
            "SESSION_MARKER",
            "NESTED_ARG_MARKER",
            "NESTED_RESULT_MARKER",
            "UNSAFE_LABEL_MARKER",
            "UNKNOWN_EVENT_MARKER",
        ):
            self.assertNotIn(marker, response.text)
        self.assertLess(len(response.content), 4096)
        self.assertTrue(self.hermes.streams[-1].closed)

    def test_sse_drops_blank_message_deltas(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "47474747-4747-4747-8747-474747474747"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=message_id,
                text="stream only visible text",
            ).status_code,
            202,
        )
        self.hermes.events["run_1"] = [
            HermesSseEvent(
                "message.delta",
                None,
                {"event": "message.delta", "delta": ""},
            ),
            HermesSseEvent(
                "message.delta",
                None,
                {"event": "message.delta", "delta": "   \n\t"},
            ),
            HermesSseEvent(
                "message.delta",
                None,
                {"event": "message.delta", "delta": "visible"},
            ),
        ]

        response = client.get(
            f"/miniapp/api/chat/messages/{message_id}/events"
        )

        self.assertEqual(response.status_code, 200)
        data_lines = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        self.assertEqual(data_lines, [{"delta": "visible"}])

    def test_run_routes_reject_unknown_or_nonaccepted_claim_without_hermes(self) -> None:
        client = self._client()
        csrf = self._login(client)
        missing_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        malformed = client.get(
            "/miniapp/api/chat/messages/not-a-uuid/run"
        )
        missing = client.get(
            f"/miniapp/api/chat/messages/{missing_id}/run"
        )
        self.hermes.start_mode = "unavailable"
        unknown_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        self.assertEqual(
            self._send(
                client,
                csrf,
                client_message_id=unknown_id,
                text="unknown",
            ).status_code,
            503,
        )
        unknown = client.get(
            f"/miniapp/api/chat/messages/{unknown_id}/run"
        )

        self.assertEqual(malformed.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unknown.status_code, 409)
        self.assertEqual(
            unknown.json(),
            {"detail": "miniapp_message_unknown"},
        )

    def test_message_and_stop_mutations_require_strict_origin_and_csrf(self) -> None:
        client = self._client()
        csrf = self._login(client)
        message_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        request_body = {"client_message_id": message_id, "text": "hello"}
        cases = (
            ({"X-Agentonomy-CSRF": csrf}, 403),
            (
                {
                    "Origin": "https://www.agentonomy.xyz:444",
                    "X-Agentonomy-CSRF": csrf,
                },
                403,
            ),
            ({"Origin": ORIGIN}, 403),
            (
                {"Origin": ORIGIN, "X-Agentonomy-CSRF": "z" * 43},
                403,
            ),
        )
        for headers, expected in cases:
            with self.subTest(headers=headers):
                response = client.post(
                    "/miniapp/api/chat/messages",
                    headers=headers,
                    json=request_body,
                )
                self.assertEqual(response.status_code, expected)
        self.assertEqual(self.hermes.start_run_calls, [])


if __name__ == "__main__":
    unittest.main()
