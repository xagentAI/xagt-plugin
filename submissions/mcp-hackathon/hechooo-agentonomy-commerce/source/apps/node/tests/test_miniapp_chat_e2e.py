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
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import quote, urlencode

from fastapi.testclient import TestClient

from apps.node.clink_node.adapters.core import AccountProxyResponse
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.hermes import (
    HermesConflict,
    HermesConversationMessage,
    HermesMessage,
    HermesMessagesPage,
    HermesNotFound,
    HermesRun,
    HermesSession,
    HermesSseEvent,
)
from apps.node.clink_node.interactions import InteractionService
from apps.node.clink_node.miniapp.service import MiniAppChatService
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


NOW = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)
ORIGIN = "https://www.agentonomy.xyz"
BOT_TOKEN = b"123456:test-only-telegram-token"
COOKIE_SECRET = b"c" * 32
HERMES_SECRET = b"h" * 32
SESSION_COOKIE = "agentonomy_miniapp_session"


async def _disconnect_after_first_sse_chunk(
    app: Any,
    *,
    path: str,
    session_cookie: str,
) -> tuple[int, bytes]:
    request_delivered = False
    first_body = asyncio.Event()
    status_code: int | None = None
    body_parts: list[bytes] = []

    async def receive() -> dict[str, object]:
        nonlocal request_delivered
        if not request_delivered:
            request_delivered = True
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        await first_body.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            return
        if message["type"] != "http.response.body":
            return
        body = message.get("body", b"")
        if isinstance(body, bytes) and body:
            body_parts.append(body)
            first_body.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"www.agentonomy.xyz"),
            (
                b"cookie",
                f"{SESSION_COOKIE}={session_cookie}".encode("ascii"),
            ),
        ],
        "client": ("127.0.0.1", 4242),
        "server": ("www.agentonomy.xyz", 443),
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=3.0)
    assert status_code is not None
    return status_code, b"".join(body_parts)


def _client_nonce(marker: bytes) -> str:
    return base64.urlsafe_b64encode(marker * 16).decode("ascii").rstrip("=")


def _signed_init_data(user_id: int, username: str) -> str:
    fields = {
        "auth_date": str(int(NOW.timestamp())),
        "query_id": f"query-{user_id}",
        "user": json.dumps(
            {"id": user_id, "username": username},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret = hmac.new(b"WebAppData", BOT_TOKEN, hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret,
        check.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return urlencode(fields)


class _CoreBoundary:
    def __init__(self) -> None:
        self.account_calls: list[str] = []
        self.failure: Exception | None = None

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def account_readiness(self, user_id: str) -> dict[str, object]:
        return {"user_id": user_id, "ready": False}

    def create_account_session(self, user_id: str) -> dict[str, str]:
        self.account_calls.append(user_id)
        if self.failure is not None:
            raise self.failure
        subject = quote(user_id, safe="")
        return {
            "account_url": f"{ORIGIN}/account/session/{subject}",
        }

    def proxy_account_request(self, **_: Any) -> AccountProxyResponse:
        return AccountProxyResponse(200, b"account", ())

    def audit_summary(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        return []


class _BusinessBoundary:
    def __init__(self, name: str) -> None:
        self.name = name

    def health(self) -> dict[str, str]:
        return {"status": "ok"}

    def capabilities(self) -> list[dict[str, Any]]:
        return []

    def list_services(self, limit: int = 20) -> dict[str, Any]:
        return {"count": 0, "services": []}

    def account_status(self, user_id: str) -> dict[str, object]:
        return {"user_id": user_id, "status": "unavailable"}

    def proxy_public_request(self, **_: Any) -> AccountProxyResponse:
        return AccountProxyResponse(200, self.name.encode("ascii"), ())


class _HermesState:
    """Persistent fake Hermes server state shared across client restarts."""

    def __init__(self) -> None:
        self.sessions: dict[str, list[HermesMessage]] = {}
        self.session_by_key: dict[str, str] = {}
        self.runs: dict[str, HermesRun] = {}
        self.bound_keys: list[str] = []
        self.start_calls: list[tuple[str, str, str]] = []
        self.stream_calls: list[tuple[str, str]] = []
        self.stream_close_calls: list[tuple[str, str]] = []
        self.get_run_calls: list[tuple[str, str, str]] = []
        self.create_session_calls: list[str] = []

    def snapshot(self) -> dict[str, object]:
        return {
            "version": 1,
            "session_by_key": dict(self.session_by_key),
            "sessions": {
                session_id: [
                    {
                        "id": message.id,
                        "session_id": message.session_id,
                        "role": message.role,
                        "content": message.content,
                        "timestamp": message.timestamp,
                        "finish_reason": message.finish_reason,
                    }
                    for message in messages
                ]
                for session_id, messages in self.sessions.items()
            },
            "runs": {
                run_id: {
                    "run_id": run.run_id,
                    "status": run.status,
                    "session_id": run.session_id,
                    "output": run.output,
                }
                for run_id, run in self.runs.items()
            },
        }

    @classmethod
    def from_snapshot(cls, payload: dict[str, object]) -> _HermesState:
        assert payload.get("version") == 1
        raw_owners = payload.get("session_by_key")
        raw_sessions = payload.get("sessions")
        raw_runs = payload.get("runs")
        assert isinstance(raw_owners, dict)
        assert isinstance(raw_sessions, dict)
        assert isinstance(raw_runs, dict)

        state = cls()
        state.session_by_key = {
            str(session_key): str(session_id)
            for session_key, session_id in raw_owners.items()
        }
        for session_id, raw_messages in raw_sessions.items():
            assert isinstance(raw_messages, list)
            messages: list[HermesMessage] = []
            for raw_message in raw_messages:
                assert isinstance(raw_message, dict)
                messages.append(
                    HermesMessage(
                        id=raw_message.get("id"),
                        session_id=str(raw_message["session_id"]),
                        role=str(raw_message["role"]),
                        content=str(raw_message["content"]),
                        timestamp=raw_message.get("timestamp"),
                        finish_reason=raw_message.get("finish_reason"),
                    )
                )
            state.sessions[str(session_id)] = messages
        for run_id, raw_run in raw_runs.items():
            assert isinstance(raw_run, dict)
            raw_session_id = raw_run.get("session_id")
            raw_output = raw_run.get("output")
            state.runs[str(run_id)] = HermesRun(
                run_id=str(raw_run["run_id"]),
                status=str(raw_run["status"]),
                session_id=(
                    None
                    if raw_session_id is None
                    else str(raw_session_id)
                ),
                output=None if raw_output is None else str(raw_output),
            )
        assert set(state.session_by_key.values()) == set(state.sessions)
        return state

    def complete(self, run_id: str, answer: str) -> None:
        current = self.runs[run_id]
        assert current.session_id is not None
        messages = self.sessions[current.session_id]
        messages.append(
            HermesMessage(
                id=len(messages) + 1,
                session_id=current.session_id,
                role="assistant",
                content=answer,
                timestamp=NOW.timestamp() + len(messages),
            )
        )
        self.runs[run_id] = HermesRun(
            run_id=run_id,
            status="completed",
            session_id=current.session_id,
            output=answer,
        )


class _BlockingHermesStream:
    """One event followed by an open stream that ends only when closed."""

    def __init__(
        self,
        state: _HermesState,
        *,
        session_key: str,
        run_id: str,
    ) -> None:
        self._state = state
        self._session_key = session_key
        self._run_id = run_id
        self._yielded = False
        self._released = threading.Event()

    def __iter__(self) -> _BlockingHermesStream:
        return self

    def __next__(self) -> HermesSseEvent:
        if not self._yielded:
            self._yielded = True
            return HermesSseEvent(
                event="message.delta",
                id="temporary-1",
                data={"delta": "partial"},
            )
        self._released.wait(timeout=3.0)
        raise StopIteration

    def close(self) -> None:
        self._state.stream_close_calls.append(
            (self._session_key, self._run_id)
        )
        self._released.set()


class _HermesBoundary:
    def __init__(self, state: _HermesState) -> None:
        self.state = state

    def for_session(self, session_key: str) -> _HermesSessionBoundary:
        self.state.bound_keys.append(session_key)
        return _HermesSessionBoundary(self.state, session_key)


class _HermesSessionBoundary:
    def __init__(self, state: _HermesState, session_key: str) -> None:
        self.state = state
        self.session_key = session_key

    def _require_owned_session(self, session_id: str) -> None:
        if (
            self.state.session_by_key.get(self.session_key) != session_id
            or session_id not in self.state.sessions
        ):
            raise HermesNotFound()

    def _require_owned_run(self, run_id: str) -> HermesRun:
        run = self.state.runs.get(run_id)
        if run is None or run.session_id is None:
            raise HermesNotFound()
        self._require_owned_session(run.session_id)
        return run

    def get_session(self, session_id: str) -> HermesSession:
        self._require_owned_session(session_id)
        return HermesSession(id=session_id)

    def create_session(self, session_id: str | None = None) -> HermesSession:
        assert session_id is not None
        owner = next(
            (
                key
                for key, owned_session_id in self.state.session_by_key.items()
                if owned_session_id == session_id
            ),
            None,
        )
        if owner is not None and owner != self.session_key:
            raise HermesNotFound()
        existing = self.state.session_by_key.get(self.session_key)
        if existing is not None and existing != session_id:
            raise HermesConflict()
        if session_id in self.state.sessions:
            raise HermesConflict()
        self.state.sessions[session_id] = []
        self.state.session_by_key[self.session_key] = session_id
        self.state.create_session_calls.append(session_id)
        return HermesSession(id=session_id)

    def get_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        order: str = "oldest",
    ) -> HermesMessagesPage:
        self._require_owned_session(session_id)
        messages = list(self.state.sessions[session_id])
        if order == "latest":
            messages = messages[-limit:]
        else:
            messages = messages[offset : offset + limit]
        return HermesMessagesPage(
            session_id=session_id,
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
        conversation_history: Sequence[HermesConversationMessage],
    ) -> HermesRun:
        self._require_owned_session(session_id)
        run_id = f"run-{len(self.state.runs) + 1}"
        self.state.start_calls.append(
            (self.session_key, session_id, user_input)
        )
        messages = self.state.sessions[session_id]
        messages.append(
            HermesMessage(
                id=len(messages) + 1,
                session_id=session_id,
                role="user",
                content=user_input,
                timestamp=NOW.timestamp() + len(messages),
            )
        )
        self.state.runs[run_id] = HermesRun(
            run_id=run_id,
            status="running",
            session_id=session_id,
        )
        return HermesRun(
            run_id=run_id,
            status="started",
            session_id=session_id,
        )

    def get_run(self, run_id: str, *, session_id: str) -> HermesRun:
        self.state.get_run_calls.append(
            (self.session_key, run_id, session_id)
        )
        self._require_owned_session(session_id)
        run = self._require_owned_run(run_id)
        if run.session_id != session_id:
            raise HermesNotFound()
        return run

    def stream_run_events(self, run_id: str) -> Iterator[HermesSseEvent]:
        self._require_owned_run(run_id)
        self.state.stream_calls.append((self.session_key, run_id))
        return _BlockingHermesStream(
            self.state,
            session_key=self.session_key,
            run_id=run_id,
        )

    def stop_run(self, run_id: str) -> HermesRun:
        run = self._require_owned_run(run_id)
        stopped = HermesRun(
            run_id=run_id,
            status="cancelled",
            session_id=run.session_id,
        )
        self.state.runs[run_id] = stopped
        return stopped


class _FailClosedTrafficGuard:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.calls = 0

    def consume(self, action: str, scope: str) -> bool:
        self.calls += 1
        raise RuntimeError(self.marker)

    def acquire_sse(self, scope: str) -> str | None:
        raise RuntimeError(self.marker)

    def release_sse(self, scope: str, token: str) -> bool:
        raise RuntimeError(self.marker)


class MiniAppChatEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = NodePaths.from_home(root / ".clink")
        self.database = root / "node.db"
        defaults = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=self.paths,
        )
        self.settings = replace(
            defaults,
            miniapp=replace(defaults.miniapp, enabled=True),
        )
        self.repository = self._repository()
        self.hermes_state = _HermesState()
        self.core = _CoreBoundary()
        self.service = self._service(self.repository)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _repository(self) -> SQLiteNodeRepository:
        repository = SQLiteNodeRepository(self.database)
        repository.migrate()
        return repository

    def _service(
        self,
        repository: SQLiteNodeRepository,
        *,
        traffic_guard: object | None = None,
    ) -> MiniAppChatService:
        return MiniAppChatService(
            repository=repository,
            hermes_client=_HermesBoundary(self.hermes_state),
            account_link_factory=self.core.create_account_session,
            telegram_bot_token=BOT_TOKEN,
            cookie_secret=COOKIE_SECRET,
            hermes_session_secret=HERMES_SECRET,
            allowed_origin=ORIGIN,
            now=lambda: NOW,
            auth_max_age_seconds=300,
            session_ttl_seconds=3_600,
            traffic_guard=traffic_guard,
        )

    def _client(
        self,
        *,
        repository: SQLiteNodeRepository | None = None,
        service: MiniAppChatService | None | object = ...,
        settings: NodeSettings | None = None,
    ) -> TestClient:
        selected_repository = repository or self.repository
        selected_service = self.service if service is ... else service
        selected_settings = settings or self.settings
        context = NodeApiContext(
            settings=selected_settings,
            repository=selected_repository,
            interaction_service=InteractionService(
                selected_repository,
                base_url=ORIGIN,
            ),
            session_token="node-test-session",
            core=self.core,
            marketplace=_BusinessBoundary("marketplace"),
            prediction_markets=_BusinessBoundary("prediction-markets"),
            miniapp_service=selected_service,
        )
        return TestClient(create_app(context), base_url=ORIGIN)

    def _login(
        self,
        client: TestClient,
        *,
        user_id: int,
        username: str,
        nonce_marker: bytes,
    ) -> str:
        response = client.post(
            "/miniapp/api/session",
            headers={"Origin": ORIGIN},
            json={
                "init_data": _signed_init_data(user_id, username),
                "client_nonce": _client_nonce(nonce_marker),
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["csrf_token"]

    def _send(
        self,
        client: TestClient,
        csrf: str,
        message_id: str,
        text: str,
    ):
        return client.post(
            "/miniapp/api/chat/messages",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": csrf,
            },
            json={"client_message_id": message_id, "text": text},
        )

    def test_two_users_are_isolated_and_duplicate_message_starts_once(
        self,
    ) -> None:
        alice = self._client()
        bob = self._client()
        alice_csrf = self._login(
            alice,
            user_id=101,
            username="alice",
            nonce_marker=b"a",
        )
        bob_csrf = self._login(
            bob,
            user_id=202,
            username="bob",
            nonce_marker=b"b",
        )
        message_id = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))
        bob_message_id = str(
            uuid.UUID("12121212-1212-4212-8212-121212121212")
        )

        forged = alice.post(
            "/miniapp/api/chat/messages",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": alice_csrf,
            },
            json={
                "client_message_id": message_id,
                "text": "hello",
                "run_id": "browser-chosen-run",
                "session_id": "browser-chosen-session",
            },
        )
        first = self._send(alice, alice_csrf, message_id, "hello")
        duplicate = self._send(alice, alice_csrf, message_id, "hello")
        conflict = self._send(
            alice,
            alice_csrf,
            message_id,
            "changed browser payload",
        )
        bob_first = self._send(
            bob,
            bob_csrf,
            bob_message_id,
            "bob private message",
        )
        bob_run = bob.get(
            f"/miniapp/api/chat/messages/{message_id}/run"
        )
        bob_stop = bob.post(
            f"/miniapp/api/chat/messages/{message_id}/stop",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": bob_csrf,
            },
        )
        alice_chat = alice.get("/miniapp/api/chat")
        bob_chat = bob.get("/miniapp/api/chat")

        self.assertEqual(forged.status_code, 400)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(first.json(), duplicate.json())
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json(), {"detail": "miniapp_conflict"})
        self.assertEqual(bob_first.status_code, 202)
        self.assertEqual(
            sum(
                user_input == "hello"
                for _, _, user_input in self.hermes_state.start_calls
            ),
            1,
        )
        self.assertEqual(len(self.hermes_state.start_calls), 2)
        self.assertEqual(bob_run.status_code, 404)
        self.assertEqual(bob_stop.status_code, 404)
        self.assertEqual(alice_chat.status_code, 200)
        self.assertEqual(bob_chat.status_code, 200)
        self.assertEqual(
            [
                message["content"]
                for message in alice_chat.json()["messages"]
            ],
            ["hello"],
        )
        self.assertEqual(
            [message["content"] for message in bob_chat.json()["messages"]],
            ["bob private message"],
        )
        self.assertNotIn("run_id", first.json())
        self.assertNotIn("session_id", first.json())
        self.assertGreaterEqual(len(set(self.hermes_state.bound_keys)), 2)

        alice_key, alice_session_id, _ = self.hermes_state.start_calls[0]
        alice_run_id = next(
            run_id
            for run_id, run in self.hermes_state.runs.items()
            if run.session_id == alice_session_id
        )
        wrong = _HermesBoundary(self.hermes_state).for_session(
            "browser-forged-session-key"
        )
        with self.assertRaises(HermesNotFound):
            wrong.get_session(alice_session_id)
        with self.assertRaises(HermesNotFound):
            wrong.create_session(alice_session_id)
        with self.assertRaises(HermesNotFound):
            wrong.get_messages(alice_session_id)
        with self.assertRaises(HermesNotFound):
            wrong.start_run(
                alice_session_id,
                "forged",
                conversation_history=(),
            )
        with self.assertRaises(HermesNotFound):
            wrong.get_run(alice_run_id, session_id=alice_session_id)
        with self.assertRaises(HermesNotFound):
            wrong.stream_run_events(alice_run_id)
        with self.assertRaises(HermesNotFound):
            wrong.stop_run(alice_run_id)
        self.assertNotEqual(alice_key, "browser-forged-session-key")
        owned_pairs = {
            (session_key, session_id)
            for session_key, session_id, _ in self.hermes_state.start_calls
        }
        self.assertEqual(len({key for key, _ in owned_pairs}), 2)
        self.assertEqual(len({session for _, session in owned_pairs}), 2)
        self.assertEqual(self.hermes_state.session_by_key, dict(owned_pairs))

    def test_stream_end_recovers_by_polling_original_run_and_history(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(
            client,
            user_id=303,
            username="recovering-user",
            nonce_marker=b"r",
        )
        message_id = str(uuid.UUID("22222222-2222-4222-8222-222222222222"))
        accepted = self._send(client, csrf, message_id, "recover this")
        self.assertEqual(accepted.status_code, 202)

        cookie = client.cookies.get(SESSION_COOKIE)
        self.assertIsNotNone(cookie)
        status_code, raw_body = asyncio.run(
            _disconnect_after_first_sse_chunk(
                client.app,
                path=f"/miniapp/api/chat/messages/{message_id}/events",
                session_cookie=cookie,
            )
        )
        body = raw_body.decode("utf-8")
        self.assertEqual(status_code, 200)
        self.assertIn("event: message.delta", body)
        self.assertIn('"delta":"partial"', body)
        self.assertEqual(len(self.hermes_state.stream_calls), 1)
        self.assertEqual(
            self.hermes_state.stream_close_calls,
            [self.hermes_state.stream_calls[0]],
        )

        # The browser never receives the run id; the fake server resolves its
        # own original run before the browser polls by client_message_id.
        run_id = next(reversed(self.hermes_state.runs))
        self.hermes_state.complete(run_id, "authoritative final answer")
        polled = client.get(
            f"/miniapp/api/chat/messages/{message_id}/run"
        )
        history = client.get("/miniapp/api/chat")

        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["status"], "completed")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            [item["content"] for item in history.json()["messages"]],
            ["recover this", "authoritative final answer"],
        )
        self.assertEqual(len(self.hermes_state.start_calls), 1)
        self.assertEqual(len(self.hermes_state.stream_calls), 1)
        self.assertEqual(len(self.hermes_state.get_run_calls), 2)

    def test_node_and_hermes_client_reassembly_recovers_binding_claim_and_lease(
        self,
    ) -> None:
        first_client = self._client()
        csrf = self._login(
            first_client,
            user_id=404,
            username="restart-user",
            nonce_marker=b"s",
        )
        first_id = str(uuid.UUID("33333333-3333-4333-8333-333333333333"))
        second_id = str(uuid.UUID("44444444-4444-4444-8444-444444444444"))
        accepted = self._send(first_client, csrf, first_id, "before restart")
        self.assertEqual(accepted.status_code, 202)
        cookie = first_client.cookies.get(SESSION_COOKIE)
        self.assertIsNotNone(cookie)
        original_session_ids = set(self.hermes_state.sessions)
        original_owners = dict(self.hermes_state.session_by_key)
        snapshot = self.hermes_state.snapshot()
        self.hermes_state = _HermesState.from_snapshot(
            json.loads(json.dumps(snapshot))
        )

        restarted_repository = self._repository()
        restarted_service = self._service(restarted_repository)
        restarted_client = self._client(
            repository=restarted_repository,
            service=restarted_service,
        )
        restarted_client.cookies.set(
            SESSION_COOKIE,
            cookie,
            path="/miniapp",
        )

        duplicate = self._send(
            restarted_client,
            csrf,
            first_id,
            "before restart",
        )
        blocked = self._send(
            restarted_client,
            csrf,
            second_id,
            "while original run is active",
        )
        history = restarted_client.get("/miniapp/api/chat")

        self.assertEqual(duplicate.status_code, 202)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json(),
            {"detail": "miniapp_run_active"},
        )
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            [message["content"] for message in history.json()["messages"]],
            ["before restart"],
        )
        self.assertEqual(set(self.hermes_state.sessions), original_session_ids)
        self.assertEqual(self.hermes_state.session_by_key, original_owners)
        self.assertEqual(len(self.hermes_state.start_calls), 0)

        first_run_id = next(reversed(self.hermes_state.runs))
        self.hermes_state.complete(first_run_id, "survived restart")
        terminal = restarted_client.get(
            f"/miniapp/api/chat/messages/{first_id}/run"
        )
        final_history = restarted_client.get("/miniapp/api/chat")
        retried = self._send(
            restarted_client,
            csrf,
            second_id,
            "after terminal recovery",
        )

        self.assertEqual(terminal.status_code, 200)
        self.assertEqual(final_history.status_code, 200)
        self.assertEqual(
            [
                message["content"]
                for message in final_history.json()["messages"]
            ],
            ["before restart", "survived restart"],
        )
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(len(self.hermes_state.start_calls), 1)
        self.assertEqual(set(self.hermes_state.sessions), original_session_ids)
        self.assertEqual(self.hermes_state.session_by_key, original_owners)

    def test_account_operation_is_subject_bound_and_core_fails_closed(
        self,
    ) -> None:
        client = self._client()
        csrf = self._login(
            client,
            user_id=505,
            username="wallet-user",
            nonce_marker=b"w",
        )

        linked = client.post(
            "/miniapp/api/operations/account",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": csrf,
            },
            json={},
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(
            linked.json(),
            {"url": f"{ORIGIN}/account/session/telegram%3A505"},
        )
        self.assertEqual(self.core.account_calls, ["telegram:505"])

        marker = "core-secret-marker must-not-leak"
        self.core.failure = RuntimeError(marker)
        failed = client.post(
            "/miniapp/api/operations/account",
            headers={
                "Origin": ORIGIN,
                "X-Agentonomy-CSRF": csrf,
            },
            json={},
        )
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn(marker, failed.text)

    def test_disabled_feature_hides_page_api_and_assets_without_readiness_change(
        self,
    ) -> None:
        disabled_settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=self.paths,
        )
        client = self._client(service=None, settings=disabled_settings)
        before = client.get("/readyz")

        page = client.get("/miniapp/")
        api = client.get("/miniapp/api/chat")
        script = client.get("/static/miniapp.js")
        after = client.get("/readyz")

        self.assertEqual(page.status_code, 404)
        self.assertEqual(api.status_code, 404)
        self.assertEqual(script.status_code, 404)
        self.assertEqual(before.status_code, 200)
        self.assertEqual(after.status_code, 200)
        self.assertEqual(before.json(), after.json())
        self.assertEqual(self.hermes_state.bound_keys, [])
        self.assertEqual(self.hermes_state.start_calls, [])

    def test_traffic_backend_failure_is_fixed_503_and_never_bypasses(
        self,
    ) -> None:
        marker = "redis://user:password@cache.internal telegram:606"
        guard = _FailClosedTrafficGuard(marker)
        service = self._service(self.repository, traffic_guard=guard)
        client = self._client(service=service)

        response = client.post(
            "/miniapp/api/session",
            headers={"Origin": ORIGIN},
            json={
                "init_data": _signed_init_data(606, "traffic-user"),
                "client_nonce": _client_nonce(b"t"),
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "miniapp_unavailable"})
        self.assertNotIn(marker, response.text)
        self.assertEqual(guard.calls, 1)
        self.assertEqual(self.hermes_state.bound_keys, [])
        self.assertEqual(self.hermes_state.start_calls, [])


if __name__ == "__main__":
    unittest.main()
