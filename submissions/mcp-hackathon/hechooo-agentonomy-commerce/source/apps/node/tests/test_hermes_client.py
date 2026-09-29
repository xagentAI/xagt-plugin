from __future__ import annotations

import dataclasses
import json
import queue
import threading
import time
import unittest
from unittest import mock

import httpx

import clink_node.hermes as hermes_api
from clink_node.hermes import (
    HermesClient,
    HermesConversationMessage,
    HermesProtocolError,
    HermesSseEvent,
    HermesUnavailable,
)


API_KEY = "api-key-secret"
SESSION_KEY = "telegram-subject-secret"


def _session_payload(session_id: str = "session_1") -> dict[str, object]:
    return {
        "object": "hermes.session",
        "session": {
            "id": session_id,
            "source": "agentonomy_miniapp",
            "started_at": 1_786_979_200.0,
            "message_count": 2,
            "has_system_prompt": False,
            "has_model_config": False,
        },
    }


def _messages_payload(session_id: str = "session_1") -> dict[str, object]:
    return {
        "object": "list",
        "session_id": session_id,
        "data": [
            {
                "id": 1,
                "session_id": session_id,
                "role": "user",
                "content": "hello",
                "timestamp": 1_786_979_201.0,
            },
            {
                "id": 2,
                "session_id": session_id,
                "role": "assistant",
                "content": "hi",
                "timestamp": 1_786_979_202.0,
            },
        ],
        "pagination": {
            "limit": 50,
            "offset": 0,
            "order": "oldest",
            "returned": 2,
        },
    }


def _run_payload(
    run_id: str = "run_1",
    session_id: str = "session_1",
) -> dict[str, object]:
    return {
        "object": "hermes.run",
        "run_id": run_id,
        "status": "running",
        "created_at": 1_786_979_203.0,
        "updated_at": 1_786_979_204.0,
        "session_id": session_id,
        "model": "hermes-agent",
    }


def _make_client(
    handler,
    **overrides: object,
):
    def streaming_handler(request: httpx.Request) -> httpx.Response:
        response = handler(request)
        if not response.is_stream_consumed:
            return response
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=httpx.ByteStream(response.content),
            extensions=response.extensions,
        )

    raw_client = httpx.Client(
        transport=httpx.MockTransport(streaming_handler),
        follow_redirects=False,
        trust_env=False,
    )
    settings: dict[str, object] = {
        "base_url": "http://127.0.0.1:8642",
        "api_key": API_KEY,
        "client": raw_client,
        "connect_timeout_seconds": 1.0,
        "read_timeout_seconds": 2.0,
        "max_response_bytes": 64 * 1024,
        "max_sse_event_bytes": 16 * 1024,
        "max_sse_total_bytes": 128 * 1024,
        "max_sse_events": 100,
        "max_stream_seconds": 60.0,
    }
    settings.update(overrides)
    return HermesClient(**settings), raw_client


class HermesClientWireContractTests(unittest.TestCase):
    def test_official_v0204_paths_headers_bodies_and_models(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            route = (request.method, request.url.path)
            if route == ("POST", "/api/sessions"):
                return httpx.Response(201, json=_session_payload())
            if route == ("GET", "/api/sessions/session_1"):
                return httpx.Response(200, json=_session_payload())
            if route == ("GET", "/api/sessions/session_1/messages"):
                return httpx.Response(200, json=_messages_payload())
            if route == ("POST", "/v1/runs"):
                return httpx.Response(
                    202,
                    json={"run_id": "run_1", "status": "started"},
                )
            if route == ("GET", "/v1/runs/run_1"):
                return httpx.Response(200, json=_run_payload())
            if route == ("GET", "/v1/runs/run_1/events"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=_RecordingStream(
                        [
                            b": keepalive\n\n",
                            b"data: {\"event\":\"message.delta\","
                            b"\"run_id\":\"run_1\",\"delta\":\"ok\"}\n\n",
                        ]
                    ),
                )
            if route == ("POST", "/v1/runs/run_1/stop"):
                return httpx.Response(
                    200,
                    json={"run_id": "run_1", "status": "stopping"},
                )
            return httpx.Response(404, json={"error": "unexpected"})

        client, raw_client = _make_client(handler)
        self.addCleanup(raw_client.close)
        bound = client.for_session(SESSION_KEY)

        created = bound.create_session()
        fetched = bound.get_session("session_1")
        messages = bound.get_messages(
            "session_1", limit=50, offset=0, order="oldest"
        )
        started = bound.start_run(
            "session_1",
            "new message",
            conversation_history=(
                HermesConversationMessage(role="user", content="hello"),
                HermesConversationMessage(role="assistant", content="hi"),
            ),
        )
        running = bound.get_run("run_1", session_id="session_1")
        events = list(bound.stream_run_events("run_1"))
        stopped = bound.stop_run("run_1")

        self.assertEqual(created.id, "session_1")
        self.assertEqual(fetched.id, "session_1")
        self.assertEqual([item.content for item in messages.messages], ["hello", "hi"])
        self.assertEqual(started.run_id, "run_1")
        self.assertEqual(started.session_id, "session_1")
        self.assertEqual(running.status, "running")
        self.assertEqual(events[0].event, "message.delta")
        self.assertEqual(events[0].data["delta"], "ok")
        self.assertEqual(stopped.status, "stopping")

        self.assertEqual(
            [(request.method, request.url.path) for request in requests],
            [
                ("POST", "/api/sessions"),
                ("GET", "/api/sessions/session_1"),
                ("GET", "/api/sessions/session_1/messages"),
                ("POST", "/v1/runs"),
                ("GET", "/v1/runs/run_1"),
                ("GET", "/v1/runs/run_1/events"),
                ("POST", "/v1/runs/run_1/stop"),
            ],
        )
        for request in requests:
            self.assertEqual(
                request.headers["authorization"], f"Bearer {API_KEY}"
            )
            self.assertEqual(
                request.headers["x-hermes-session-key"], SESSION_KEY
            )
        self.assertEqual(
            json.loads(requests[0].content),
            {"source": "agentonomy_miniapp"},
        )
        self.assertEqual(
            dict(requests[2].url.params),
            {"limit": "50", "offset": "0", "order": "oldest"},
        )
        self.assertEqual(
            json.loads(requests[3].content),
            {
                "input": "new message",
                "session_id": "session_1",
                "conversation_history": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ],
            },
        )
        self.assertEqual(requests[5].headers["accept"], "text/event-stream")
        self.assertEqual(requests[6].content, b"")

        browser_facing = repr(
            (created, fetched, messages, started, running, events, stopped)
        )
        self.assertNotIn(API_KEY, browser_facing)
        self.assertNotIn(SESSION_KEY, browser_facing)

    def test_bound_client_does_not_offer_header_or_session_key_overrides(self) -> None:
        client, raw_client = _make_client(
            lambda request: httpx.Response(200, json=_session_payload())
        )
        self.addCleanup(raw_client.close)

        with self.assertRaises(ValueError):
            client.for_session("")
        with self.assertRaises(ValueError):
            client.for_session("x\r\nforged: value")
        with self.assertRaises(TypeError):
            client.for_session(SESSION_KEY).get_session(
                "session_1", headers={"X-Hermes-Session-Key": "other"}
            )
        self.assertNotIn(SESSION_KEY, repr(client.for_session(SESSION_KEY)))

    def test_get_messages_returns_valid_effective_descendant_session(self) -> None:
        client, raw_client = _make_client(
            lambda request: httpx.Response(
                200, json=_messages_payload("session_child")
            )
        )
        self.addCleanup(raw_client.close)

        page = client.for_session(SESSION_KEY).get_messages("session_root")

        self.assertEqual(page.session_id, "session_child")
        self.assertEqual(
            {message.session_id for message in page.messages},
            {"session_child"},
        )

    def test_response_and_request_models_are_frozen_and_strict(self) -> None:
        message = HermesConversationMessage(role="user", content="hello")
        event = HermesSseEvent(
            event="message.delta",
            id=None,
            data={"event": "message.delta", "run_id": "run_1"},
        )
        self.assertTrue(message.__dataclass_params__.frozen)
        self.assertTrue(event.__dataclass_params__.frozen)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            message.role = "assistant"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            HermesConversationMessage(  # type: ignore[call-arg]
                role="user", content="hello", model="browser-choice"
            )
        with self.assertRaises(TypeError):
            event.data["run_id"] = "other"  # type: ignore[index]

        nested = HermesSseEvent(
            event="tool.completed",
            id=None,
            data={
                "event": "tool.completed",
                "run_id": "run_1",
                "result": {"items": ["one"]},
            },
        )
        with self.assertRaises(TypeError):
            nested.data["result"]["items"] += ("two",)  # type: ignore[index,operator]


class HermesClientSafetyTests(unittest.TestCase):
    def test_fixed_status_exceptions_are_exported_and_redacted(self) -> None:
        not_found = hermes_api.HermesNotFound()
        conflict = hermes_api.HermesConflict()

        self.assertIsInstance(not_found, hermes_api.HermesError)
        self.assertIsInstance(conflict, hermes_api.HermesError)
        self.assertEqual(str(not_found), "hermes_not_found")
        self.assertEqual(str(conflict), "hermes_conflict")
        self.assertIsNone(not_found.__cause__)
        self.assertIsNone(not_found.__context__)
        self.assertIsNone(conflict.__cause__)
        self.assertIsNone(conflict.__context__)
        with self.assertRaises(TypeError):
            hermes_api.HermesNotFound("private-response-marker")
        with self.assertRaises(TypeError):
            hermes_api.HermesConflict("private-response-marker")

    def test_every_method_classifies_status_without_leaking_response(self) -> None:
        operations = (
            ("create_session", lambda bound: bound.create_session("session_1")),
            ("get_session", lambda bound: bound.get_session("session_1")),
            ("get_messages", lambda bound: bound.get_messages("session_1")),
            (
                "start_run",
                lambda bound: bound.start_run(
                    "session_1", "hello", conversation_history=()
                ),
            ),
            (
                "get_run",
                lambda bound: bound.get_run("run_1", session_id="session_1"),
            ),
            (
                "stream_run_events",
                lambda bound: list(bound.stream_run_events("run_1")),
            ),
            ("stop_run", lambda bound: bound.stop_run("run_1")),
        )
        classifications = (
            (400, HermesProtocolError, "hermes_protocol_error"),
            (404, hermes_api.HermesNotFound, "hermes_not_found"),
            (409, hermes_api.HermesConflict, "hermes_conflict"),
            (500, HermesUnavailable, "hermes_unavailable"),
        )
        response_marker = (
            f"remote-private-marker {API_KEY} {SESSION_KEY} "
            "http://remote.invalid/private?token=secret"
        )

        for name, operation in operations:
            for status, expected_type, expected_message in classifications:
                with self.subTest(method=name, status=status):
                    calls = 0

                    def handler(request: httpx.Request) -> httpx.Response:
                        nonlocal calls
                        calls += 1
                        return httpx.Response(
                            status,
                            json={"error": response_marker},
                            headers={"x-remote-private": response_marker},
                        )

                    client, raw_client = _make_client(handler)
                    try:
                        with self.assertRaises(expected_type) as caught:
                            operation(client.for_session(SESSION_KEY))
                        self.assertEqual(str(caught.exception), expected_message)
                        rendered = repr(caught.exception)
                        for secret in (
                            API_KEY,
                            SESSION_KEY,
                            "remote-private-marker",
                            "remote.invalid",
                            "token=secret",
                        ):
                            self.assertNotIn(secret, rendered)
                        self.assertIsNone(caught.exception.__cause__)
                        self.assertIsNone(caught.exception.__context__)
                        self.assertEqual(calls, 1)
                    finally:
                        raw_client.close()

    def test_injected_client_must_disable_environment_and_redirects(self) -> None:
        unsafe_environment = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            )
        )
        self.addCleanup(unsafe_environment.close)
        with self.assertRaises(ValueError):
            HermesClient(
                base_url="http://127.0.0.1:8642",
                api_key=API_KEY,
                client=unsafe_environment,
            )

        unsafe_redirects = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={})
            ),
            trust_env=False,
            follow_redirects=True,
        )
        self.addCleanup(unsafe_redirects.close)
        with self.assertRaises(ValueError):
            HermesClient(
                base_url="http://127.0.0.1:8642",
                api_key=API_KEY,
                client=unsafe_redirects,
            )

        unsafe_proxy = httpx.Client(
            proxy="http://127.0.0.1:9999",
            trust_env=False,
            follow_redirects=False,
        )
        self.addCleanup(unsafe_proxy.close)
        with self.assertRaises(ValueError):
            HermesClient(
                base_url="http://127.0.0.1:8642",
                api_key=API_KEY,
                client=unsafe_proxy,
            )

    def test_header_credentials_reject_invalid_unicode_without_echo(self) -> None:
        marker = "private\ud800marker"
        with self.assertRaises(ValueError) as caught_api:
            HermesClient(
                base_url="http://127.0.0.1:8642",
                api_key=marker,
            )
        self.assertEqual(str(caught_api.exception), "invalid Hermes API credential")
        self.assertNotIn("private", repr(caught_api.exception))
        self.assertIsNone(caught_api.exception.__context__)

        client = HermesClient(
            base_url="http://127.0.0.1:8642",
            api_key=API_KEY,
        )
        self.addCleanup(client.close)
        with self.assertRaises(ValueError) as caught_session:
            client.for_session(marker)
        self.assertEqual(str(caught_session.exception), "invalid Hermes session key")
        self.assertNotIn("private", repr(caught_session.exception))
        self.assertIsNone(caught_session.exception.__context__)

        for control in ("embedded\ttab", "embedded\x7fdelete"):
            with self.subTest(control=repr(control)):
                with self.assertRaises(ValueError):
                    HermesClient(
                        base_url="http://127.0.0.1:8642",
                        api_key=control,
                    )
                with self.assertRaises(ValueError):
                    client.for_session(control)

    def test_only_literal_loopback_http_base_urls_are_accepted(self) -> None:
        invalid = (
            "https://127.0.0.1:8642",
            "http://0.0.0.0:8642",
            "http://192.168.1.10:8642",
            "http://hermes.internal:8642",
            "http://127.0.0.1:8642/path",
            "http://127.0.0.1:8642?key=secret",
            "http://user:pass@127.0.0.1:8642",
        )
        for base_url in invalid:
            with self.subTest(base_url=base_url), self.assertRaises(ValueError):
                HermesClient(base_url=base_url, api_key=API_KEY)

        for base_url in (
            "http://127.0.0.1:8642",
            "http://localhost:8642",
            "http://[::1]:8642",
        ):
            with self.subTest(base_url=base_url):
                client = HermesClient(base_url=base_url, api_key=API_KEY)
                client.close()

    def test_redirects_are_never_followed(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                307,
                headers={"location": "http://127.0.0.1:9999/stolen"},
            )

        client, raw_client = _make_client(handler)
        self.addCleanup(raw_client.close)
        with self.assertRaises(HermesProtocolError):
            client.for_session(SESSION_KEY).create_session()
        self.assertEqual(calls, 1)

    def test_json_content_type_size_and_unknown_fields_fail_closed(self) -> None:
        cases = (
            httpx.Response(200, text=json.dumps(_session_payload())),
            httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"{not-json",
            ),
            httpx.Response(
                200,
                json={
                    **_session_payload(),
                    "credential_echo": API_KEY,
                },
            ),
            httpx.Response(
                200,
                json={
                    "object": "hermes.session",
                    "session": {
                        **_session_payload()["session"],  # type: ignore[arg-type]
                        "unknown": "remote-marker",
                    },
                },
            ),
        )
        for response in cases:
            with self.subTest(response=response):
                client, raw_client = _make_client(lambda request, r=response: r)
                try:
                    with self.assertRaises(HermesProtocolError) as caught:
                        client.for_session(SESSION_KEY).create_session()
                    rendered = repr(caught.exception)
                    self.assertNotIn(API_KEY, rendered)
                    self.assertNotIn("remote-marker", rendered)
                    self.assertIsNone(caught.exception.__cause__)
                finally:
                    raw_client.close()

        oversized, raw_client = _make_client(
            lambda request: httpx.Response(
                201,
                json={
                    "object": "hermes.session",
                    "session": {
                        "id": "session_1",
                        "preview": "response-body-marker" * 128,
                        "has_system_prompt": False,
                        "has_model_config": False,
                    },
                },
            ),
            max_response_bytes=128,
        )
        try:
            with self.assertRaises(hermes_api.HermesError) as caught:
                oversized.for_session(SESSION_KEY).create_session()
            self.assertEqual(
                caught.exception.__class__.__name__,
                "HermesResponseTooLarge",
            )
            self.assertIs(
                getattr(hermes_api, "HermesResponseTooLarge", None),
                caught.exception.__class__,
            )
            self.assertEqual(
                str(caught.exception),
                "hermes_response_too_large",
            )
            self.assertNotIn("response-body-marker", repr(caught.exception))
            self.assertNotIn("session_1", repr(caught.exception))
            self.assertNotIn("128", repr(caught.exception))
            self.assertIsNone(caught.exception.__cause__)
            self.assertIsNone(caught.exception.__context__)
        finally:
            raw_client.close()

    def test_json_response_is_bounded_while_streaming(self) -> None:
        stream = _RecordingStream([b"12345678", b"abcdefgh", b"not-read"])
        client, raw_client = _make_client(
            lambda request: httpx.Response(
                201,
                headers={"content-type": "application/json"},
                stream=stream,
            ),
            max_response_bytes=12,
        )
        self.addCleanup(raw_client.close)

        with self.assertRaises(hermes_api.HermesError) as caught:
            client.for_session(SESSION_KEY).create_session()

        self.assertEqual(
            caught.exception.__class__.__name__,
            "HermesResponseTooLarge",
        )
        self.assertEqual(str(caught.exception), "hermes_response_too_large")
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(stream.iterations, 2)
        self.assertTrue(stream.closed)

    def test_json_duplicate_keys_and_invalid_unicode_are_rejected(self) -> None:
        payloads = (
            (
                b'{"object":"hermes.session","object":"hermes.session",'
                b'"session":{"id":"session_1","has_system_prompt":false,'
                b'"has_model_config":false}}'
            ),
            (
                b'{"object":"hermes.session","session":{"id":"session_1",'
                b'"preview":"\\ud800","has_system_prompt":false,'
                b'"has_model_config":false}}'
            ),
            (
                b'{"object":"hermes.session","session":{"id":"session_1",'
                + b'"started_at":'
                + b"9" * 1024
                + b',"has_system_prompt":false,"has_model_config":false}}'
            ),
            (
                b'{"object":"hermes.session","session":{"id":"session_1",'
                + b'"started_at":'
                + b"9" * 5000
                + b',"has_system_prompt":false,"has_model_config":false}}'
            ),
        )
        for body in payloads:
            with self.subTest(body=body):
                client, raw_client = _make_client(
                    lambda request, content=body: httpx.Response(
                        201,
                        headers={"content-type": "application/json"},
                        content=content,
                    )
                )
                try:
                    with self.assertRaises(HermesProtocolError):
                        client.for_session(SESSION_KEY).create_session()
                finally:
                    raw_client.close()

    def test_get_session_and_run_mismatches_fail_closed(self) -> None:
        responses = iter(
            (
                httpx.Response(200, json=_session_payload("other_session")),
                httpx.Response(
                    200,
                    json=_run_payload("other_run", "session_1"),
                ),
                httpx.Response(
                    200,
                    json=_run_payload("run_1", "other_session"),
                ),
            )
        )
        client, raw_client = _make_client(lambda request: next(responses))
        self.addCleanup(raw_client.close)
        bound = client.for_session(SESSION_KEY)

        with self.assertRaises(HermesProtocolError):
            bound.get_session("session_1")
        with self.assertRaises(HermesProtocolError):
            bound.get_run("run_1", session_id="session_1")
        with self.assertRaises(HermesProtocolError):
            bound.get_run("run_1", session_id="session_1")

    def test_get_messages_rejects_invalid_effective_or_message_session_id(
        self,
    ) -> None:
        invalid_effective = _messages_payload("../session_child")
        mismatched_message = _messages_payload("session_child")
        mismatched_message["data"][0]["session_id"] = "session_other"  # type: ignore[index]

        for payload in (invalid_effective, mismatched_message):
            with self.subTest(payload=payload):
                client, raw_client = _make_client(
                    lambda request, body=payload: httpx.Response(200, json=body)
                )
                try:
                    with self.assertRaises(HermesProtocolError):
                        client.for_session(SESSION_KEY).get_messages(
                            "session_root"
                        )
                finally:
                    raw_client.close()

    def test_mutation_timeout_is_not_retried_and_exception_is_redacted(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout(
                f"remote-marker {API_KEY} {SESSION_KEY} ?query=private",
                request=request,
            )

        client, raw_client = _make_client(handler)
        self.addCleanup(raw_client.close)
        with self.assertRaises(HermesUnavailable) as caught:
            client.for_session(SESSION_KEY).start_run(
                "session_1",
                "private-body-marker",
                conversation_history=(),
            )

        self.assertEqual(calls, 1)
        self.assertEqual(str(caught.exception), "hermes_unavailable")
        rendered = repr(caught.exception)
        for secret in (
            API_KEY,
            SESSION_KEY,
            "private-body-marker",
            "remote-marker",
            "?query=private",
        ):
            self.assertNotIn(secret, rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_start_run_rejects_unbounded_or_browser_shaped_history(self) -> None:
        client, raw_client = _make_client(
            lambda request: httpx.Response(
                202, json={"run_id": "run_1", "status": "started"}
            )
        )
        self.addCleanup(raw_client.close)
        bound = client.for_session(SESSION_KEY)

        with self.assertRaises(ValueError):
            bound.start_run(
                "session_1",
                "hello",
                conversation_history=(
                    {"role": "user", "content": "hello", "model": "x"},
                ),
            )
        with self.assertRaises(ValueError):
            bound.start_run(
                "session_1",
                "x" * (16 * 1024 + 1),
                conversation_history=(),
            )
        with self.assertRaises(ValueError):
            bound.start_run(
                "session_1",
                "hello",
                conversation_history=tuple(
                    HermesConversationMessage(role="user", content=str(i))
                    for i in range(201)
                ),
            )

    def test_invalid_unicode_fails_closed_without_input_or_chain(self) -> None:
        marker = "private\ud800marker"
        with self.assertRaises(ValueError) as caught_message:
            HermesConversationMessage(role="user", content=marker)
        self.assertEqual(str(caught_message.exception), "invalid Hermes text")
        self.assertNotIn("private", repr(caught_message.exception))
        self.assertIsNone(caught_message.exception.__cause__)
        self.assertIsNone(caught_message.exception.__context__)

        client, raw_client = _make_client(
            lambda request: httpx.Response(
                202, json={"run_id": "run_1", "status": "started"}
            )
        )
        self.addCleanup(raw_client.close)
        with self.assertRaises(ValueError) as caught_input:
            client.for_session(SESSION_KEY).start_run(
                "session_1",
                marker,
                conversation_history=(),
            )
        self.assertEqual(str(caught_input.exception), "invalid Hermes text")
        self.assertNotIn("private", repr(caught_input.exception))
        self.assertIsNone(caught_input.exception.__cause__)
        self.assertIsNone(caught_input.exception.__context__)


class _RecordingStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False
        self.iterations = 0

    def __iter__(self):
        for chunk in self._chunks:
            self.iterations += 1
            yield chunk

    def close(self) -> None:
        self.closed = True


class _TimeoutStream(httpx.SyncByteStream):
    def __init__(self, marker: str) -> None:
        self._marker = marker
        self.closed = False
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        raise httpx.ReadTimeout(self._marker)
        yield b""  # pragma: no cover

    def close(self) -> None:
        self.closed = True


class _BlockingStream(httpx.SyncByteStream):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        first_chunk_delay_seconds: float = 0.0,
    ) -> None:
        self._chunks = chunks
        self._first_chunk_delay_seconds = first_chunk_delay_seconds
        self._release = threading.Event()
        self.blocked = threading.Event()
        self.finished = threading.Event()
        self.closed = False
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        try:
            for index, chunk in enumerate(self._chunks):
                if index == 0 and self._first_chunk_delay_seconds:
                    time.sleep(self._first_chunk_delay_seconds)
                if self._release.is_set():
                    return
                yield chunk
            self.blocked.set()
            self._release.wait(timeout=2.0)
        finally:
            self.finished.set()

    def close(self) -> None:
        self.closed = True
        self._release.set()


class _ObservedSignalQueue(queue.Queue[tuple[str, object]]):
    def __init__(self, *, hold_blocking_put: bool) -> None:
        super().__init__(maxsize=4)
        self.hold_blocking_put = hold_blocking_put
        self.full_put_attempted = threading.Event()
        self.release_blocking_put = threading.Event()

    def put(
        self,
        item: tuple[str, object],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        if self.full():
            self.full_put_attempted.set()
            if block and self.hold_blocking_put:
                self.release_blocking_put.wait(timeout=1.0)
        super().put(item, block=block, timeout=timeout)


def _live_hermes_stream_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if thread.name in {"hermes-sse-reader", "hermes-sse-deadline"}
        and thread.is_alive()
    ]


class HermesSseSafetyTests(unittest.TestCase):
    def _bound_for_stream(
        self,
        chunks: list[bytes],
        **overrides: object,
    ):
        stream = _RecordingStream(chunks)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream; charset=utf-8"},
                stream=stream,
            )

        client, raw_client = _make_client(handler, **overrides)
        return client.for_session(SESSION_KEY), raw_client, stream

    def test_keepalive_multiline_and_explicit_sse_fields_are_normalized(self) -> None:
        bound, raw_client, stream = self._bound_for_stream(
            [
                b": keepalive\n\n",
                b"id: event-1\n",
                b"event: tool.started\n",
                b'data: {"event":"tool.started",\n',
                b'data: "run_id":"run_1","tool":"search"}\n\n',
                b": stream closed\n\n",
            ]
        )
        self.addCleanup(raw_client.close)

        events = list(bound.stream_run_events("run_1"))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event, "tool.started")
        self.assertEqual(events[0].id, "event-1")
        self.assertEqual(events[0].data["tool"], "search")
        self.assertTrue(stream.closed)

    def test_stream_content_type_json_and_run_id_are_strict(self) -> None:
        cases = (
            ({"content-type": "application/json"}, b"{}"),
            (
                {"content-type": "text/event-stream"},
                b"data: not-json\n\n",
            ),
            (
                {"content-type": "text/event-stream"},
                b"data: \xff\n\n",
            ),
            (
                {"content-type": "text/event-stream"},
                b'data: {"event":"message.delta","run_id":"other"}\n\n',
            ),
            (
                {"content-type": "text/event-stream"},
                b'event: one\ndata: {"event":"two","run_id":"run_1"}\n\n',
            ),
            (
                {"content-type": "text/event-stream"},
                (
                    b'data: {"event":"message.delta","run_id":"run_1",'
                    + f'"delta":"{API_KEY}"'.encode()
                    + b"}\n\n"
                ),
            ),
            (
                {"content-type": "text/event-stream"},
                b'data: {"event":"message.delta","run_id":"run_1",'
                b'"delta":"\\ud800"}\n\n',
            ),
            (
                {"content-type": "text/event-stream"},
                b'data: {"event":"message.delta","run_id":"run_1",'
                b'"delta":NaN}\n\n',
            ),
        )
        for headers, body in cases:
            with self.subTest(headers=headers, body=body):
                stream = _RecordingStream([body])
                client, raw_client = _make_client(
                    lambda request, h=headers, s=stream: httpx.Response(
                        200, headers=h, stream=s
                    )
                )
                try:
                    with self.assertRaises(HermesProtocolError) as caught:
                        list(
                            client.for_session(SESSION_KEY).stream_run_events(
                                "run_1"
                            )
                        )
                    self.assertNotIn(API_KEY, repr(caught.exception))
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertIsNone(caught.exception.__context__)
                    self.assertTrue(stream.closed)
                finally:
                    raw_client.close()

    def test_event_total_and_count_caps_fail_closed(self) -> None:
        event = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}\n\n'
        )
        cases = (
            ({"max_sse_event_bytes": 48}, [event]),
            ({"max_sse_total_bytes": len(event) + 8}, [b":123456789\n\n", event]),
            ({"max_sse_events": 1}, [event, event]),
        )
        for settings, chunks in cases:
            with self.subTest(settings=settings):
                bound, raw_client, stream = self._bound_for_stream(
                    chunks, **settings
                )
                try:
                    with self.assertRaises(HermesProtocolError):
                        list(bound.stream_run_events("run_1"))
                    self.assertTrue(stream.closed)
                finally:
                    raw_client.close()

    def test_total_byte_cap_exits_when_signal_queue_is_saturated(self) -> None:
        chunk = b"x" * 16
        bound, raw_client, stream = self._bound_for_stream(
            [chunk] * 100,
            max_sse_event_bytes=1024,
            max_sse_total_bytes=64,
        )
        self.addCleanup(raw_client.close)

        with self.assertRaises(HermesProtocolError) as caught:
            list(bound.stream_run_events("run_1"))

        self.assertEqual(str(caught.exception), "hermes_protocol_error")
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(stream.iterations, 5)
        self.assertTrue(stream.closed)
        self.assertFalse(
            any(
                thread.name == "hermes-sse-reader" and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_monotonic_stream_deadline_is_enforced(self) -> None:
        event = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"ok"}\n\n'
        )
        bound, raw_client, stream = self._bound_for_stream(
            [b": keepalive\n\n", event], max_stream_seconds=1.0
        )
        self.addCleanup(raw_client.close)

        with mock.patch(
            "clink_node.hermes.client.time.monotonic",
            side_effect=(0.0, 0.5, 1.1),
        ):
            with self.assertRaises(HermesUnavailable):
                list(bound.stream_run_events("run_1"))
        self.assertTrue(stream.closed)

    def test_silent_stream_uses_hard_deadline_and_is_not_retried(self) -> None:
        marker = (
            f"remote-private-marker {API_KEY} {SESSION_KEY} "
            "http://remote.invalid/private?token=secret"
        )
        stream = _TimeoutStream(marker)
        calls = 0
        timeout_extension: dict[str, float] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls, timeout_extension
            calls += 1
            timeout_extension = dict(request.extensions["timeout"])
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            connect_timeout_seconds=3.0,
            read_timeout_seconds=30.0,
            max_stream_seconds=5.0,
        )
        self.addCleanup(raw_client.close)

        with self.assertRaises(HermesUnavailable) as caught:
            list(client.for_session(SESSION_KEY).stream_run_events("run_1"))

        self.assertEqual(
            timeout_extension,
            {"connect": 3.0, "read": 5.0, "write": 3.0, "pool": 3.0},
        )
        self.assertEqual(calls, 1)
        self.assertEqual(stream.iterations, 1)
        self.assertTrue(stream.closed)
        self.assertEqual(str(caught.exception), "hermes_unavailable")
        rendered = repr(caught.exception)
        for secret in (
            API_KEY,
            SESSION_KEY,
            "remote-private-marker",
            "remote.invalid",
            "token=secret",
        ):
            self.assertNotIn(secret, rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_hard_deadline_interrupts_stream_silent_from_start(self) -> None:
        stream = _BlockingStream([])
        calls = 0
        outcome: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            read_timeout_seconds=30.0,
            max_stream_seconds=0.05,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        def consume() -> None:
            try:
                outcome["value"] = list(iterator)
            except Exception as exc:  # fixed boundary exception asserted below
                outcome["error"] = exc

        caller = threading.Thread(target=consume, daemon=True)
        started_at = time.monotonic()
        caller.start()
        self.assertTrue(stream.blocked.wait(timeout=0.2))
        caller.join(timeout=0.25)
        completed_before_cleanup = not caller.is_alive()
        elapsed_before_cleanup = time.monotonic() - started_at
        if not completed_before_cleanup:
            stream.close()
            caller.join(timeout=1.0)

        self.assertTrue(completed_before_cleanup)
        self.assertLess(elapsed_before_cleanup, 0.25)
        self.assertIsInstance(outcome.get("error"), HermesUnavailable)
        error = outcome["error"]
        self.assertEqual(str(error), "hermes_unavailable")
        self.assertIsNone(error.__cause__)  # type: ignore[union-attr]
        self.assertIsNone(error.__context__)  # type: ignore[union-attr]
        self.assertEqual(calls, 1)
        self.assertTrue(stream.closed)
        self.assertTrue(stream.finished.wait(timeout=0.2))
        self.assertFalse(
            any(
                thread.name == "hermes-sse-reader" and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_hard_deadline_is_total_after_slow_drip_then_block(self) -> None:
        first = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        stream = _BlockingStream(
            [first],
            first_chunk_delay_seconds=0.04,
        )
        calls = 0
        outcome: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            read_timeout_seconds=30.0,
            max_stream_seconds=0.08,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")
        started_at = time.monotonic()
        self.assertEqual(next(iterator).data["delta"], "first")

        def consume_next() -> None:
            try:
                outcome["value"] = next(iterator)
            except Exception as exc:  # fixed boundary exception asserted below
                outcome["error"] = exc

        caller = threading.Thread(target=consume_next, daemon=True)
        caller.start()
        self.assertTrue(stream.blocked.wait(timeout=0.2))
        caller.join(timeout=0.25)
        completed_before_cleanup = not caller.is_alive()
        elapsed_before_cleanup = time.monotonic() - started_at
        if not completed_before_cleanup:
            stream.close()
            caller.join(timeout=1.0)

        self.assertTrue(completed_before_cleanup)
        self.assertLess(elapsed_before_cleanup, 0.25)
        self.assertIsInstance(outcome.get("error"), HermesUnavailable)
        error = outcome["error"]
        self.assertEqual(str(error), "hermes_unavailable")
        self.assertIsNone(error.__cause__)  # type: ignore[union-attr]
        self.assertIsNone(error.__context__)  # type: ignore[union-attr]
        self.assertEqual(calls, 1)
        self.assertTrue(stream.closed)
        self.assertTrue(stream.finished.wait(timeout=0.2))
        self.assertFalse(
            any(
                thread.name == "hermes-sse-reader" and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_deadline_closes_stream_while_consumer_is_paused_after_yield(
        self,
    ) -> None:
        first = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        stream = _BlockingStream([first])
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            read_timeout_seconds=30.0,
            max_stream_seconds=0.05,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        self.assertEqual(next(iterator).data["delta"], "first")
        self.assertTrue(stream.blocked.wait(timeout=0.2))
        finished_without_resuming = stream.finished.wait(timeout=0.25)
        closed_without_resuming = stream.closed
        live_before_resuming = _live_hermes_stream_threads()

        with self.assertRaises(HermesUnavailable) as caught:
            next(iterator)

        self.assertTrue(finished_without_resuming)
        self.assertTrue(closed_without_resuming)
        self.assertEqual(live_before_resuming, [])
        self.assertEqual(calls, 1)
        self.assertEqual(str(caught.exception), "hermes_unavailable")
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(_live_hermes_stream_threads(), [])

    def test_deadline_rejects_buffered_event_after_consumer_pause(self) -> None:
        first = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        second = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"second"}\n\n'
        )
        stream = _BlockingStream([first + second])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            max_stream_seconds=0.05,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        self.assertEqual(next(iterator).data["delta"], "first")
        self.assertTrue(stream.finished.wait(timeout=0.25))
        with self.assertRaises(HermesUnavailable) as caught:
            next(iterator)

        self.assertEqual(str(caught.exception), "hermes_unavailable")
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertEqual(_live_hermes_stream_threads(), [])

    def test_deadline_watchdog_stops_after_normal_eof(self) -> None:
        event = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"done"}\n\n'
        )
        bound, raw_client, stream = self._bound_for_stream(
            [event],
            max_stream_seconds=0.2,
        )
        self.addCleanup(raw_client.close)

        self.assertEqual(
            [item.data["delta"] for item in bound.stream_run_events("run_1")],
            ["done"],
        )

        self.assertTrue(stream.closed)
        self.assertEqual(_live_hermes_stream_threads(), [])

    def test_deadline_watchdog_stops_when_iterator_closes_early(self) -> None:
        first = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        stream = _BlockingStream([first])

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            max_stream_seconds=0.5,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        self.assertEqual(next(iterator).data["delta"], "first")
        self.assertTrue(stream.blocked.wait(timeout=0.2))
        watchdog_was_running = any(
            thread.name == "hermes-sse-deadline"
            for thread in _live_hermes_stream_threads()
        )
        iterator.close()

        self.assertTrue(watchdog_was_running)
        self.assertTrue(stream.closed)
        self.assertTrue(stream.finished.wait(timeout=0.2))
        self.assertEqual(_live_hermes_stream_threads(), [])

    def test_closing_iterator_closes_upstream_stream(self) -> None:
        first = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        stream = _BlockingStream([first])
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(handler)
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        self.assertEqual(next(iterator).data["delta"], "first")
        self.assertTrue(stream.blocked.wait(timeout=0.2))
        iterator.close()

        self.assertEqual(calls, 1)
        self.assertTrue(stream.closed)
        self.assertTrue(stream.finished.wait(timeout=0.2))
        self.assertFalse(
            any(
                thread.name == "hermes-sse-reader" and thread.is_alive()
                for thread in threading.enumerate()
            )
        )

    def test_closing_iterator_is_safe_while_another_thread_blocks_in_next(
        self,
    ) -> None:
        stream = _BlockingStream([])
        outcome: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=stream,
            )

        client, raw_client = _make_client(
            handler,
            read_timeout_seconds=30.0,
            max_stream_seconds=5.0,
        )
        self.addCleanup(raw_client.close)
        iterator = client.for_session(SESSION_KEY).stream_run_events("run_1")

        def consume_next() -> None:
            try:
                outcome["value"] = next(iterator)
            except Exception as exc:  # fixed boundary exception asserted below
                outcome["error"] = exc

        caller = threading.Thread(target=consume_next, daemon=True)
        caller.start()
        self.assertTrue(stream.blocked.wait(timeout=0.2))

        started_at = time.monotonic()
        iterator.close()
        iterator.close()
        close_elapsed = time.monotonic() - started_at
        caller.join(timeout=0.25)

        self.assertFalse(caller.is_alive())
        self.assertLess(close_elapsed, 0.2)
        self.assertIsInstance(outcome.get("error"), HermesUnavailable)
        error = outcome["error"]
        self.assertEqual(str(error), "hermes_unavailable")
        self.assertIsNone(error.__cause__)  # type: ignore[union-attr]
        self.assertIsNone(error.__context__)  # type: ignore[union-attr]
        self.assertNotIn("generator already executing", repr(error))
        self.assertTrue(stream.closed)
        self.assertTrue(stream.finished.wait(timeout=0.2))
        self.assertEqual(_live_hermes_stream_threads(), [])

    def test_closing_iterator_releases_queue_backpressure(self) -> None:
        event = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )
        bound, raw_client, stream = self._bound_for_stream([event] * 100)
        self.addCleanup(raw_client.close)
        iterator = bound.stream_run_events("run_1")
        signals = _ObservedSignalQueue(hold_blocking_put=True)
        iterator._control.signals = signals

        try:
            self.assertEqual(next(iterator).data["delta"], "first")
            self.assertTrue(signals.full_put_attempted.wait(timeout=0.2))

            started_at = time.monotonic()
            iterator.close()
            close_elapsed = time.monotonic() - started_at

            self.assertLess(close_elapsed, 0.2)
            self.assertTrue(stream.closed)
            self.assertEqual(_live_hermes_stream_threads(), [])
        finally:
            signals.release_blocking_put.set()
            stream.close()

    def test_closing_backpressured_streams_is_stable_across_100_runs(self) -> None:
        event = (
            b'data: {"event":"message.delta","run_id":"run_1",'
            b'"delta":"first"}\n\n'
        )

        for iteration in range(100):
            with self.subTest(iteration=iteration):
                bound, raw_client, stream = self._bound_for_stream([event] * 100)
                iterator = bound.stream_run_events("run_1")
                signals = _ObservedSignalQueue(hold_blocking_put=False)
                iterator._control.signals = signals
                try:
                    self.assertEqual(next(iterator).data["delta"], "first")
                    self.assertTrue(signals.full_put_attempted.wait(timeout=0.2))
                    iterator.close()

                    self.assertTrue(stream.closed)
                    self.assertEqual(_live_hermes_stream_threads(), [])
                finally:
                    iterator.close()
                    stream.close()
                    raw_client.close()


if __name__ == "__main__":
    unittest.main()
