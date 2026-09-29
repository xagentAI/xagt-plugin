from __future__ import annotations

import json
import math
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

import httpx

from clink_node.hermes.models import (
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
    _utf8_size,
)


_RESOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SESSION_ALLOWED_FIELDS = {
    "id",
    "source",
    "user_id",
    "model",
    "title",
    "started_at",
    "ended_at",
    "end_reason",
    "message_count",
    "tool_call_count",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "estimated_cost_usd",
    "actual_cost_usd",
    "api_call_count",
    "parent_session_id",
    "last_active",
    "preview",
    "_lineage_root_id",
    "pinned",
    "archived",
    "hidden",
    "has_system_prompt",
    "has_model_config",
}
_MESSAGE_ALLOWED_FIELDS = {
    "id",
    "session_id",
    "role",
    "content",
    "tool_call_id",
    "tool_calls",
    "tool_name",
    "timestamp",
    "token_count",
    "finish_reason",
    "reasoning",
    "reasoning_content",
}
_RUN_ALLOWED_FIELDS = {
    "object",
    "run_id",
    "status",
    "created_at",
    "updated_at",
    "session_id",
    "model",
    "last_event",
    "output",
    "error",
    "usage",
    "pending_steer",
}
_RUN_STATUSES = {
    "started",
    "queued",
    "running",
    "waiting_for_approval",
    "stopping",
    "completed",
    "failed",
    "cancelled",
}


class _InvalidJson(ValueError):
    """Private sentinel used to keep remote payloads out of public errors."""


def _protocol_error() -> HermesProtocolError:
    return HermesProtocolError()


def _failure_kind_for_status(status_code: int) -> str:
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code >= 500:
        return "unavailable"
    return "protocol"


def _raise_redacted_failure(kind: str) -> None:
    if kind == "not_found":
        raise HermesNotFound()
    if kind == "conflict":
        raise HermesConflict()
    if kind == "unavailable":
        raise HermesUnavailable()
    raise _protocol_error()


def _raise_for_unexpected_status(status_code: int) -> None:
    _raise_redacted_failure(_failure_kind_for_status(status_code))


def _validate_resource_id(value: object) -> str:
    if not isinstance(value, str) or not _RESOURCE_ID_RE.fullmatch(value):
        raise ValueError("invalid Hermes resource identifier")
    return value


def _require_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise _protocol_error()
    return value


def _strict_keys(
    value: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
) -> None:
    if set(value) - allowed or required - set(value):
        raise _protocol_error()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _protocol_error()
    return value


def _optional_number(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float}:
        raise _protocol_error()
    parsed: float | None = None
    try:
        parsed = float(value)
    except (OverflowError, ValueError):
        pass
    if parsed is None or not math.isfinite(parsed):
        raise _protocol_error()
    return parsed


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _protocol_error()
    return value


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise _protocol_error()
    return value


def _contains_secret(value: object, secrets: Sequence[str]) -> bool:
    if isinstance(value, str):
        return any(secret and secret in value for secret in secrets)
    if isinstance(value, Mapping):
        return any(
            _contains_secret(key, secrets) or _contains_secret(item, secrets)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item, secrets) for item in value)
    return False


def _valid_json_tree(value: object) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if item is None or isinstance(item, (bool, int)):
            continue
        if isinstance(item, float):
            if not math.isfinite(item):
                return False
            continue
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return False
            continue
        if isinstance(item, list):
            pending.extend(item)
            continue
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str):
                    return False
                try:
                    key.encode("utf-8")
                except UnicodeEncodeError:
                    return False
                pending.append(nested)
            continue
        return False
    return True


def _decode_json_strict(content: bytes) -> object:
    malformed = False
    payload: object = None

    def reject_constant(_: str) -> object:
        raise _InvalidJson()

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _InvalidJson()
            result[key] = value
        return result

    try:
        payload = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (
        ValueError,
        RecursionError,
    ):
        malformed = True
    if malformed or not _valid_json_tree(payload):
        raise _protocol_error()
    return payload


def _parse_session(payload: object, *, expected_id: str | None) -> HermesSession:
    root = _require_object(payload)
    _strict_keys(root, allowed={"object", "session"}, required={"object", "session"})
    if root["object"] != "hermes.session":
        raise _protocol_error()
    session = _require_object(root["session"])
    _strict_keys(
        session,
        allowed=_SESSION_ALLOWED_FIELDS,
        required={"id", "has_system_prompt", "has_model_config"},
    )
    session_id: str | None = None
    try:
        session_id = _validate_resource_id(session["id"])
    except ValueError:
        pass
    if session_id is None:
        raise _protocol_error()
    if expected_id is not None and session_id != expected_id:
        raise _protocol_error()

    string_fields = {
        "source",
        "user_id",
        "model",
        "title",
        "end_reason",
        "parent_session_id",
        "preview",
        "_lineage_root_id",
    }
    number_fields = {
        "started_at",
        "ended_at",
        "estimated_cost_usd",
        "actual_cost_usd",
        "last_active",
    }
    integer_fields = {
        "message_count",
        "tool_call_count",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "api_call_count",
    }
    bool_fields = {
        "pinned",
        "archived",
        "hidden",
        "has_system_prompt",
        "has_model_config",
    }
    for name in string_fields & set(session):
        _optional_string(session[name])
    for name in number_fields & set(session):
        _optional_number(session[name])
    for name in integer_fields & set(session):
        _optional_nonnegative_int(session[name])
    for name in bool_fields & set(session):
        if name.startswith("has_") and type(session[name]) is not bool:
            raise _protocol_error()
        _optional_bool(session[name])

    return HermesSession(
        id=session_id,
        source=_optional_string(session.get("source")),
        title=_optional_string(session.get("title")),
        model=_optional_string(session.get("model")),
        started_at=_optional_number(session.get("started_at")),
        ended_at=_optional_number(session.get("ended_at")),
        message_count=_optional_nonnegative_int(session.get("message_count")),
        last_active=_optional_number(session.get("last_active")),
        preview=_optional_string(session.get("preview")),
        pinned=_optional_bool(session.get("pinned")),
        archived=_optional_bool(session.get("archived")),
        hidden=_optional_bool(session.get("hidden")),
        has_system_prompt=bool(session["has_system_prompt"]),
        has_model_config=bool(session["has_model_config"]),
    )


def _parse_messages(payload: object) -> HermesMessagesPage:
    root = _require_object(payload)
    _strict_keys(
        root,
        allowed={"object", "session_id", "data", "pagination"},
        required={"object", "session_id", "data", "pagination"},
    )
    if root["object"] != "list":
        raise _protocol_error()
    effective_session_id: str | None = None
    try:
        effective_session_id = _validate_resource_id(root["session_id"])
    except ValueError:
        pass
    if effective_session_id is None:
        raise _protocol_error()
    if not isinstance(root["data"], list):
        raise _protocol_error()
    pagination = _require_object(root["pagination"])
    _strict_keys(
        pagination,
        allowed={"limit", "offset", "order", "returned"},
        required={"limit", "offset", "order", "returned"},
    )
    limit = _optional_nonnegative_int(pagination["limit"])
    offset = _optional_nonnegative_int(pagination["offset"])
    returned = _optional_nonnegative_int(pagination["returned"])
    order = pagination["order"]
    if limit is None or offset is None or returned is None or order not in {
        "oldest",
        "latest",
    }:
        raise _protocol_error()

    messages: list[HermesMessage] = []
    for raw_message in root["data"]:
        item = _require_object(raw_message)
        _strict_keys(
            item,
            allowed=_MESSAGE_ALLOWED_FIELDS,
            required={"session_id", "role", "content"},
        )
        if item["session_id"] != effective_session_id:
            raise _protocol_error()
        role = item["role"]
        content = item["content"]
        if role not in {"system", "user", "assistant", "tool"} or not isinstance(
            content, str
        ):
            raise _protocol_error()
        message_id = item.get("id")
        if message_id is not None and (
            isinstance(message_id, bool) or not isinstance(message_id, (int, str))
        ):
            raise _protocol_error()
        if "timestamp" in item:
            _optional_number(item["timestamp"])
        if "token_count" in item:
            _optional_nonnegative_int(item["token_count"])
        for name in (
            "tool_call_id",
            "tool_name",
            "finish_reason",
            "reasoning",
            "reasoning_content",
        ):
            if name in item:
                _optional_string(item[name])
        if "tool_calls" in item and item["tool_calls"] is not None and not isinstance(
            item["tool_calls"], list
        ):
            raise _protocol_error()
        messages.append(
            HermesMessage(
                id=message_id,
                session_id=effective_session_id,
                role=role,
                content=content,
                timestamp=_optional_number(item.get("timestamp")),
                finish_reason=_optional_string(item.get("finish_reason")),
            )
        )
    if returned != len(messages):
        raise _protocol_error()
    return HermesMessagesPage(
        session_id=effective_session_id,
        messages=tuple(messages),
        limit=limit,
        offset=offset,
        order=order,
        returned=returned,
    )


def _parse_run_start(
    payload: object,
    *,
    expected_session_id: str,
) -> HermesRun:
    root = _require_object(payload)
    _strict_keys(
        root,
        allowed={"run_id", "status"},
        required={"run_id", "status"},
    )
    run_id: str | None = None
    try:
        run_id = _validate_resource_id(root["run_id"])
    except ValueError:
        pass
    if run_id is None:
        raise _protocol_error()
    if root["status"] != "started":
        raise _protocol_error()
    return HermesRun(
        run_id=run_id,
        status="started",
        session_id=expected_session_id,
    )


def _parse_run_status(
    payload: object,
    *,
    expected_run_id: str,
    expected_session_id: str,
) -> HermesRun:
    root = _require_object(payload)
    _strict_keys(
        root,
        allowed=_RUN_ALLOWED_FIELDS,
        required={
            "object",
            "run_id",
            "status",
            "created_at",
            "updated_at",
            "session_id",
        },
    )
    if (
        root["object"] != "hermes.run"
        or root["run_id"] != expected_run_id
        or root["session_id"] != expected_session_id
        or root["status"] not in _RUN_STATUSES
    ):
        raise _protocol_error()
    created_at = _optional_number(root["created_at"])
    updated_at = _optional_number(root["updated_at"])
    if created_at is None or updated_at is None:
        raise _protocol_error()
    for name in (
        "model",
        "last_event",
        "output",
        "error",
        "pending_steer",
    ):
        if name in root:
            _optional_string(root[name])
    usage: dict[str, int] | None = None
    if root.get("usage") is not None:
        usage_payload = _require_object(root["usage"])
        _strict_keys(
            usage_payload,
            allowed={"input_tokens", "output_tokens", "total_tokens"},
            required={"input_tokens", "output_tokens", "total_tokens"},
        )
        usage = {}
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            parsed = _optional_nonnegative_int(usage_payload[name])
            if parsed is None:
                raise _protocol_error()
            usage[name] = parsed
    return HermesRun(
        run_id=expected_run_id,
        status=root["status"],
        session_id=expected_session_id,
        created_at=created_at,
        updated_at=updated_at,
        model=_optional_string(root.get("model")),
        last_event=_optional_string(root.get("last_event")),
        output=_optional_string(root.get("output")),
        error=_optional_string(root.get("error")),
        usage=usage,
        pending_steer=_optional_string(root.get("pending_steer")),
    )


def _parse_run_stop(payload: object, *, expected_run_id: str) -> HermesRun:
    root = _require_object(payload)
    _strict_keys(
        root,
        allowed={"run_id", "status"},
        required={"run_id", "status"},
    )
    if root["run_id"] != expected_run_id or root["status"] != "stopping":
        raise _protocol_error()
    return HermesRun(run_id=expected_run_id, status="stopping")


class _HermesEventStreamControl:
    """Thread-safe ownership of one SSE transport and its worker threads."""

    def __init__(self) -> None:
        self.signals: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=4)
        self.stop_event = threading.Event()
        self.deadline_expired = threading.Event()
        self.cancelled = threading.Event()
        self._response_lock = threading.Lock()
        self._response: httpx.Response | None = None
        self._threads_lock = threading.Lock()
        self._threads: tuple[threading.Thread, ...] = ()

    def set_response(self, response: httpx.Response) -> None:
        with self._response_lock:
            self._response = response

    def clear_response(self, response: httpx.Response) -> None:
        with self._response_lock:
            if self._response is response:
                self._response = None

    def close_active_response(self) -> None:
        with self._response_lock:
            response = self._response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def put_signal(self, kind: str, value: object = None) -> bool:
        while not self.stop_event.is_set():
            try:
                self.signals.put_nowait((kind, value))
                return True
            except queue.Full:
                self.stop_event.wait(timeout=0.005)
        return False

    def start_threads(self, *threads: threading.Thread) -> bool:
        with self._threads_lock:
            if self.stop_event.is_set():
                return False
            self._threads = tuple(threads)
            for thread in threads:
                thread.start()
        return True

    def _wake_consumer(self) -> None:
        try:
            self.signals.put_nowait(("cancelled", None))
        except queue.Full:
            pass

    def expire_deadline(self) -> None:
        self.deadline_expired.set()
        self.stop_event.set()
        self.close_active_response()
        self._wake_consumer()

    def cancel(self) -> None:
        self.cancelled.set()
        self.stop_event.set()
        self.close_active_response()
        self._wake_consumer()
        self.join_threads(timeout=0.1)

    def shutdown(self) -> None:
        self.stop_event.set()
        self.close_active_response()
        self._wake_consumer()
        self.join_threads(timeout=0.1)

    def join_threads(self, *, timeout: float) -> None:
        current = threading.current_thread()
        with self._threads_lock:
            threads = self._threads
        joinable = sorted(
            (thread for thread in threads if thread is not current),
            key=lambda thread: thread.name == "hermes-sse-reader",
        )
        deadline = time.perf_counter() + timeout
        for thread in joinable:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            thread.join(timeout=remaining)


class HermesEventStream(Iterator[HermesSseEvent]):
    """Closable SSE iterator whose cancellation is safe across threads."""

    def __init__(
        self,
        iterator: Iterator[HermesSseEvent],
        control: _HermesEventStreamControl,
    ) -> None:
        self._iterator = iterator
        self._control = control
        self._state_lock = threading.Lock()
        self._closed = False
        self._exhausted = False

    def __iter__(self) -> HermesEventStream:
        return self

    def __next__(self) -> HermesSseEvent:
        with self._state_lock:
            if self._closed or self._exhausted:
                raise StopIteration
        try:
            event = next(self._iterator)
        except StopIteration:
            with self._state_lock:
                self._exhausted = True
            raise
        if self._control.cancelled.is_set():
            raise HermesUnavailable()
        return event

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._control.cancel()

    def __repr__(self) -> str:
        return "HermesEventStream()"


class HermesClient:
    """Loopback-only owner of the Hermes API transport and bearer secret."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | bytes,
        client: httpx.Client | None = None,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 60.0,
        max_response_bytes: int = 256 * 1024,
        max_sse_event_bytes: int = 64 * 1024,
        max_sse_total_bytes: int = 2 * 1024 * 1024,
        max_sse_events: int = 2_000,
        max_stream_seconds: float = 15 * 60.0,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        self._api_key = self._validate_api_key(api_key)
        self._connect_timeout_seconds = self._positive_number(
            connect_timeout_seconds
        )
        self._read_timeout_seconds = self._positive_number(read_timeout_seconds)
        self._max_response_bytes = self._positive_int(max_response_bytes)
        self._max_sse_event_bytes = self._positive_int(max_sse_event_bytes)
        self._max_sse_total_bytes = self._positive_int(max_sse_total_bytes)
        self._max_sse_events = self._positive_int(max_sse_events)
        self._max_stream_seconds = self._positive_number(max_stream_seconds)
        self._timeout = httpx.Timeout(
            connect=self._connect_timeout_seconds,
            read=self._read_timeout_seconds,
            write=self._connect_timeout_seconds,
            pool=self._connect_timeout_seconds,
        )
        self._sse_timeout = httpx.Timeout(
            connect=self._connect_timeout_seconds,
            read=min(
                self._read_timeout_seconds,
                self._max_stream_seconds,
            ),
            write=self._connect_timeout_seconds,
            pool=self._connect_timeout_seconds,
        )
        self._owns_client = client is None
        if client is not None and (
            client.follow_redirects
            or bool(getattr(client, "_trust_env", True))
            or getattr(client, "_mounts", None) != {}
        ):
            raise ValueError(
                "injected Hermes client must disable redirects and environment"
            )
        self._client = client or httpx.Client(
            timeout=self._timeout,
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def _positive_number(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Hermes limit must be positive")
        parsed = float(value)
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError("Hermes limit must be positive")
        return parsed

    @staticmethod
    def _positive_int(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("Hermes limit must be a positive integer")
        return value

    @staticmethod
    def _validate_base_url(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Hermes base URL must be loopback HTTP")
        parsed: httpx.URL | None = None
        try:
            parsed = httpx.URL(value)
        except Exception:
            pass
        if (
            parsed is None
            or parsed.scheme != "http"
            or parsed.host not in {"127.0.0.1", "localhost", "::1"}
            or bool(parsed.username)
            or bool(parsed.password)
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("Hermes base URL must be loopback HTTP")
        return str(parsed).rstrip("/")

    @staticmethod
    def _validate_api_key(value: object) -> str:
        decoded: str | None = None
        if isinstance(value, bytes):
            try:
                decoded = value.decode("ascii")
            except UnicodeDecodeError:
                pass
            if decoded is None:
                raise ValueError("invalid Hermes API credential")
            value = decoded
        ascii_safe = False
        if isinstance(value, str):
            try:
                value.encode("ascii")
            except UnicodeEncodeError:
                pass
            else:
                ascii_safe = True
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 4096
            or not ascii_safe
            or re.fullmatch(r"[\x21-\x7e]+", value) is None
        ):
            raise ValueError("invalid Hermes API credential")
        return value

    def for_session(self, session_key: str) -> HermesSessionClient:
        ascii_safe = False
        if isinstance(session_key, str):
            try:
                session_key.encode("ascii")
            except UnicodeEncodeError:
                pass
            else:
                ascii_safe = True
        if (
            not isinstance(session_key, str)
            or not session_key
            or session_key != session_key.strip()
            or len(session_key) > 256
            or not ascii_safe
            or re.fullmatch(r"[\x21-\x7e]+", session_key) is None
        ):
            raise ValueError("invalid Hermes session key")
        return HermesSessionClient(self, session_key)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _headers(self, session_key: str, *, sse: bool = False) -> dict[str, str]:
        return {
            "Accept": "text/event-stream" if sse else "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Hermes-Session-Key": session_key,
        }

    def _request_json(
        self,
        *,
        session_key: str,
        method: str,
        path: str,
        expected_status: int,
        json_body: dict[str, Any] | None = None,
        params: dict[str, object] | None = None,
    ) -> object:
        transport_failed = False
        content: bytes | None = None
        try:
            stream_context = self._client.stream(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(session_key),
                json=json_body,
                params=params,
                timeout=self._timeout,
                follow_redirects=False,
            )
            with stream_context as response:
                if response.status_code != expected_status:
                    _raise_for_unexpected_status(response.status_code)
                media_type = response.headers.get("content-type", "").split(
                    ";", 1
                )[0].strip().lower()
                if media_type != "application/json":
                    raise _protocol_error()
                buffer = bytearray()
                for chunk in response.iter_raw():
                    if len(chunk) > self._max_response_bytes - len(buffer):
                        raise HermesResponseTooLarge() from None
                    buffer.extend(chunk)
                content = bytes(buffer)
        except (httpx.HTTPError, httpx.StreamError):
            transport_failed = True
        if transport_failed:
            raise HermesUnavailable()
        if content is None:
            raise HermesUnavailable()
        payload = _decode_json_strict(content)
        if _contains_secret(payload, (self._api_key, session_key)):
            raise _protocol_error()
        return payload

    def _stream_events(
        self,
        *,
        session_key: str,
        run_id: str,
    ) -> HermesEventStream:
        control = _HermesEventStreamControl()
        iterator = self._iterate_stream_events(
            session_key=session_key,
            run_id=run_id,
            control=control,
        )
        return HermesEventStream(iterator, control)

    def _iterate_stream_events(
        self,
        *,
        session_key: str,
        run_id: str,
        control: _HermesEventStreamControl,
    ) -> Iterator[HermesSseEvent]:
        signals = control.signals
        stop_event = control.stop_event
        deadline_expired = control.deadline_expired
        cancelled = control.cancelled

        def produce() -> None:
            response: httpx.Response | None = None
            try:
                if stop_event.is_set():
                    return
                stream_context = self._client.stream(
                    "GET",
                    f"{self._base_url}/v1/runs/{run_id}/events",
                    headers=self._headers(session_key, sse=True),
                    timeout=self._sse_timeout,
                    follow_redirects=False,
                )
                with stream_context as response:
                    control.set_response(response)
                    if stop_event.is_set():
                        return
                    if response.status_code != 200:
                        control.put_signal(
                            "error",
                            _failure_kind_for_status(response.status_code),
                        )
                        return
                    media_type = response.headers.get(
                        "content-type", ""
                    ).split(";", 1)[0].strip().lower()
                    if media_type != "text/event-stream":
                        control.put_signal("error", "protocol")
                        return
                    producer_bytes = 0
                    for chunk in response.iter_raw():
                        if stop_event.is_set():
                            return
                        producer_bytes += len(chunk)
                        if producer_bytes > self._max_sse_total_bytes:
                            control.put_signal("error", "protocol")
                            return
                        if not control.put_signal("chunk", chunk):
                            return
                    control.put_signal("end")
            except (httpx.HTTPError, httpx.StreamError):
                control.put_signal("error", "unavailable")
            except Exception:
                control.put_signal("error", "unavailable")
            finally:
                if response is not None:
                    control.clear_response(response)

        started_at = time.monotonic()
        deadline = started_at + self._max_stream_seconds
        watchdog_delay = max(0.0, deadline - time.monotonic())

        def enforce_deadline() -> None:
            if stop_event.wait(timeout=watchdog_delay):
                return
            control.expire_deadline()

        producer = threading.Thread(
            target=produce,
            name="hermes-sse-reader",
            daemon=True,
        )
        watchdog = threading.Thread(
            target=enforce_deadline,
            name="hermes-sse-deadline",
            daemon=True,
        )
        control.start_threads(watchdog, producer)

        total_bytes = 0
        event_bytes = 0
        event_name: str | None = None
        event_id: str | None = None
        data_lines: list[str] = []
        event_count = 0
        buffer = b""

        def finish_event() -> HermesSseEvent | None:
            nonlocal event_bytes, event_name, event_id, data_lines
            if not data_lines:
                event_bytes = 0
                event_name = None
                event_id = None
                return None
            raw_data = "\n".join(data_lines)
            encoded_data: bytes | None = None
            try:
                encoded_data = raw_data.encode("utf-8")
            except UnicodeEncodeError:
                pass
            if encoded_data is None:
                raise _protocol_error()
            decoded = _decode_json_strict(encoded_data)
            data = _require_object(decoded)
            data_event = data.get("event")
            if not isinstance(data_event, str) or not data_event:
                raise _protocol_error()
            if event_name is not None and event_name != data_event:
                raise _protocol_error()
            normalized_event = event_name or data_event
            if (
                len(normalized_event) > 128
                or re.search(r"[\r\n\x00]", normalized_event)
                or data.get("run_id") != run_id
            ):
                raise _protocol_error()
            if event_id is not None and (
                len(event_id) > 256
                or re.search(r"[\r\n\x00]", event_id)
            ):
                raise _protocol_error()
            if _contains_secret(data, (self._api_key, session_key)):
                raise _protocol_error()
            result = HermesSseEvent(
                event=normalized_event,
                id=event_id,
                data=dict(data),
            )
            event_bytes = 0
            event_name = None
            event_id = None
            data_lines = []
            return result

        def process_line(line: bytes) -> HermesSseEvent | None:
            nonlocal event_bytes, event_name, event_id, data_lines
            event_bytes += len(line) + 1
            if event_bytes > self._max_sse_event_bytes:
                raise _protocol_error()
            if line.endswith(b"\r"):
                line = line[:-1]
            if not line:
                return finish_event()
            if line.startswith(b":"):
                return None
            decoded_line: str | None = None
            try:
                decoded_line = line.decode("utf-8")
            except UnicodeDecodeError:
                pass
            if decoded_line is None:
                raise _protocol_error()
            field, separator, value = decoded_line.partition(":")
            if not separator:
                value = ""
            elif value.startswith(" "):
                value = value[1:]
            if field == "event":
                event_name = value
            elif field == "id":
                event_id = value
            elif field == "data":
                data_lines.append(value)
            return None

        def require_live_stream() -> None:
            if (
                cancelled.is_set()
                or deadline_expired.is_set()
                or time.monotonic() >= deadline
            ):
                raise HermesUnavailable()

        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HermesUnavailable()
                timed_out = False
                signal: tuple[str, object] | None = None
                try:
                    signal = signals.get(timeout=remaining)
                except queue.Empty:
                    timed_out = True
                if timed_out or signal is None:
                    raise HermesUnavailable()
                kind, value = signal
                require_live_stream()
                if kind == "error":
                    if not isinstance(value, str):
                        raise HermesUnavailable()
                    _raise_redacted_failure(value)
                if kind == "end":
                    break
                if kind != "chunk" or not isinstance(value, bytes):
                    raise HermesUnavailable()
                chunk = value
                total_bytes += len(chunk)
                if total_bytes > self._max_sse_total_bytes:
                    raise _protocol_error()
                buffer += chunk
                if len(buffer) > self._max_sse_event_bytes and b"\n" not in buffer:
                    raise _protocol_error()
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    parsed = process_line(line)
                    if parsed is not None:
                        event_count += 1
                        if event_count > self._max_sse_events:
                            raise _protocol_error()
                        require_live_stream()
                        yield parsed
                        require_live_stream()
            if buffer:
                parsed = process_line(buffer)
                if parsed is not None:
                    event_count += 1
                    if event_count > self._max_sse_events:
                        raise _protocol_error()
                    require_live_stream()
                    yield parsed
                    require_live_stream()
            parsed = finish_event()
            if parsed is not None:
                event_count += 1
                if event_count > self._max_sse_events:
                    raise _protocol_error()
                require_live_stream()
                yield parsed
                require_live_stream()
        finally:
            control.shutdown()


@dataclass(frozen=True, slots=True)
class HermesSessionClient:
    _owner: HermesClient
    _session_key: str = field(repr=False)

    def create_session(self, session_id: str | None = None) -> HermesSession:
        body = {"source": "agentonomy_miniapp"}
        expected_id: str | None = None
        if session_id is not None:
            expected_id = _validate_resource_id(session_id)
            body["id"] = expected_id
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="POST",
            path="/api/sessions",
            expected_status=201,
            json_body=body,
        )
        return _parse_session(payload, expected_id=expected_id)

    def get_session(self, session_id: str) -> HermesSession:
        expected_id = _validate_resource_id(session_id)
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="GET",
            path=f"/api/sessions/{expected_id}",
            expected_status=200,
        )
        return _parse_session(payload, expected_id=expected_id)

    def get_messages(
        self,
        session_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        order: str = "oldest",
    ) -> HermesMessagesPage:
        expected_id = _validate_resource_id(session_id)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
            or isinstance(offset, bool)
            or not isinstance(offset, int)
            or offset < 0
            or order not in {"oldest", "latest"}
        ):
            raise ValueError("invalid Hermes message pagination")
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="GET",
            path=f"/api/sessions/{expected_id}/messages",
            expected_status=200,
            params={"limit": limit, "offset": offset, "order": order},
        )
        return _parse_messages(payload)

    def start_run(
        self,
        session_id: str,
        user_input: str,
        *,
        conversation_history: Sequence[HermesConversationMessage],
    ) -> HermesRun:
        expected_session_id = _validate_resource_id(session_id)
        if (
            not isinstance(user_input, str)
            or not user_input.strip()
            or _utf8_size(user_input) > 16 * 1024
        ):
            raise ValueError("invalid Hermes run input")
        if len(conversation_history) > 200 or any(
            not isinstance(item, HermesConversationMessage)
            for item in conversation_history
        ):
            raise ValueError("invalid Hermes conversation history")
        history_bytes = sum(
            _utf8_size(item.role) + _utf8_size(item.content)
            for item in conversation_history
        )
        if history_bytes > 256 * 1024:
            raise ValueError("Hermes conversation history is too large")
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="POST",
            path="/v1/runs",
            expected_status=202,
            json_body={
                "input": user_input,
                "session_id": expected_session_id,
                "conversation_history": [
                    {"role": item.role, "content": item.content}
                    for item in conversation_history
                ],
            },
        )
        return _parse_run_start(
            payload,
            expected_session_id=expected_session_id,
        )

    def get_run(self, run_id: str, *, session_id: str) -> HermesRun:
        expected_run_id = _validate_resource_id(run_id)
        expected_session_id = _validate_resource_id(session_id)
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="GET",
            path=f"/v1/runs/{expected_run_id}",
            expected_status=200,
        )
        return _parse_run_status(
            payload,
            expected_run_id=expected_run_id,
            expected_session_id=expected_session_id,
        )

    def stream_run_events(self, run_id: str) -> HermesEventStream:
        expected_run_id = _validate_resource_id(run_id)
        return self._owner._stream_events(
            session_key=self._session_key,
            run_id=expected_run_id,
        )

    def stop_run(self, run_id: str) -> HermesRun:
        expected_run_id = _validate_resource_id(run_id)
        payload = self._owner._request_json(
            session_key=self._session_key,
            method="POST",
            path=f"/v1/runs/{expected_run_id}/stop",
            expected_status=200,
        )
        return _parse_run_stop(payload, expected_run_id=expected_run_id)
