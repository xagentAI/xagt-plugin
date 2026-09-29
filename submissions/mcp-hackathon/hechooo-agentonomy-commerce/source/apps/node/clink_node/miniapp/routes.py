from __future__ import annotations

import ipaddress
import json
import threading
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any, Awaitable, Callable

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .service import (
    MiniAppChatService,
    MiniAppOrderSigningOutcomeUnknown,
    MiniAppSseLease,
)
from .session_service import MiniAppServiceError
from .traffic import (
    IP_GENERAL,
    IP_SESSION_EXCHANGE,
    MESSAGE_SUBMIT,
    OPERATION_LINK,
    STOP,
    SUBJECT_GENERAL,
)


_MAX_SESSION_BODY_BYTES = 20 * 1024
_MAX_MESSAGE_BODY_BYTES = 128 * 1024
_MAX_OPERATION_BODY_BYTES = 2 * 1024
_MAX_RUN_OUTPUT_BYTES = 128 * 1024
_MAX_SSE_DELTA_BYTES = 16 * 1024
_MAX_SSE_TOOL_LABEL_BYTES = 128
_SESSION_COOKIE = "agentonomy_miniapp_session"
_NO_STORE_HEADERS = {"Cache-Control": "no-store"}
_EVENTS_DONE = object()


class _AsyncFlight:
    def __init__(self) -> None:
        self.event = anyio.Event()
        self.result: dict[str, object] | None = None
        self.error: BaseException | None = None


class _KeyedAsyncSingleFlight:
    def __init__(self, *, cache_success: bool) -> None:
        self._gate = threading.Lock()
        self._cache_success = cache_success
        self._cache: dict[tuple[str, str], dict[str, object]] = {}
        self._flights: dict[tuple[str, str], _AsyncFlight] = {}

    async def run(
        self,
        key: tuple[str, str],
        operation: Callable[[], Awaitable[dict[str, object]]],
    ) -> dict[str, object]:
        with self._gate:
            cached = self._cache.get(key)
            if cached is not None:
                return dict(cached)
            flight = self._flights.get(key)
            owner = flight is None
            if flight is None:
                flight = _AsyncFlight()
                self._flights[key] = flight
        if not owner:
            await flight.event.wait()
            if flight.error is not None:
                raise flight.error
            assert flight.result is not None
            return dict(flight.result)
        try:
            result = dict(await operation())
        except BaseException as exc:
            with self._gate:
                flight.error = exc
                self._flights.pop(key, None)
                flight.event.set()
            raise
        with self._gate:
            flight.result = result
            if self._cache_success:
                self._cache[key] = result
            self._flights.pop(key, None)
            flight.event.set()
        return dict(result)


def attach_miniapp_routes(
    app: FastAPI,
    service: MiniAppChatService | None,
) -> None:
    # Personal MVP guards live only for this Node process. Durable operation
    # authority and recovery remain with Prediction Markets.
    funding_continue_flights = _KeyedAsyncSingleFlight(
        cache_success=False
    )
    signing_create_flights = _KeyedAsyncSingleFlight(cache_success=True)

    @app.post("/miniapp/api/session", include_in_schema=False)
    async def create_miniapp_session(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            client_ip = _client_ip_scope(request)
            await _require_traffic(service, IP_GENERAL, client_ip)
            await _require_traffic(service, IP_SESSION_EXCHANGE, client_ip)
            service.sessions.require_origin(_raw_headers(request, b"origin"))
            payload = await _strict_json_object(
                request,
                expected={"init_data", "client_nonce"},
                max_bytes=_MAX_SESSION_BODY_BYTES,
            )
            if not all(isinstance(payload[name], str) for name in payload):
                raise MiniAppServiceError("miniapp_invalid_request", 400)
            exchange = await run_in_threadpool(
                service.sessions.exchange_session,
                init_data=payload["init_data"],
                client_nonce=payload["client_nonce"],
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        response = JSONResponse(
            {
                "authenticated": True,
                "user": {
                    "id": exchange.identity.user_id,
                    "username": exchange.identity.username,
                },
                "expires_at": exchange.session.expires_at.isoformat(),
                "csrf_token": exchange.csrf_token,
                "storage_scope": exchange.storage_scope,
            },
            status_code=201,
            headers=_NO_STORE_HEADERS,
        )
        response.set_cookie(
            _SESSION_COOKIE,
            exchange.session_token,
            max_age=exchange.max_age_seconds,
            path="/miniapp",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.delete("/miniapp/api/session", include_in_schema=False)
    async def delete_miniapp_session(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            service.sessions.require_origin(_raw_headers(request, b"origin"))
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            service.sessions.require_csrf(
                session,
                _raw_headers(request, b"x-agentonomy-csrf"),
            )
            await run_in_threadpool(service.sessions.revoke_session, session)
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        response = Response(status_code=204, headers=_NO_STORE_HEADERS)
        response.delete_cookie(
            _SESSION_COOKIE,
            path="/miniapp",
            secure=True,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/miniapp/api/chat", include_in_schema=False)
    async def get_miniapp_chat(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            snapshot = await run_in_threadpool(service.get_chat, session)
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(
            {
                "messages": [
                    {
                        "id": item.id,
                        "role": item.role,
                        "content": item.content,
                        "timestamp": item.timestamp,
                    }
                    for item in snapshot.messages
                ],
                "latest": (
                    {
                        "client_message_id": snapshot.latest_client_message_id,
                        "status": snapshot.latest_submission_status,
                    }
                    if snapshot.latest_client_message_id is not None
                    else None
                ),
            },
            headers=_NO_STORE_HEADERS,
        )

    async def create_subject_operation(
        request: Request,
        active_service: MiniAppChatService,
        operation: Callable[[Any], str],
    ) -> Response:
        try:
            await _require_traffic(
                active_service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            active_service.sessions.require_origin(
                _raw_headers(request, b"origin")
            )
            session = await run_in_threadpool(
                active_service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                active_service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            await _require_traffic(
                active_service,
                OPERATION_LINK,
                session.subject_id,
            )
            active_service.sessions.require_csrf(
                session,
                _raw_headers(request, b"x-agentonomy-csrf"),
            )
            await _strict_json_object(
                request,
                expected=set(),
                max_bytes=_MAX_OPERATION_BODY_BYTES,
            )
            url = await run_in_threadpool(operation, session)
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse({"url": url}, headers=_NO_STORE_HEADERS)

    @app.post("/miniapp/api/operations/account", include_in_schema=False)
    async def create_miniapp_account_operation(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        return await create_subject_operation(
            request,
            service,
            service.create_account_operation_link,
        )

    @app.post("/miniapp/api/operations/polymarket", include_in_schema=False)
    async def create_miniapp_polymarket_operation(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        return await create_subject_operation(
            request,
            service,
            service.create_polymarket_operation_link,
        )

    async def live_operation_session(
        request: Request,
        active_service: MiniAppChatService,
        *,
        mutation: bool,
    ) -> Any:
        await _require_traffic(
            active_service,
            IP_GENERAL,
            _client_ip_scope(request),
        )
        if mutation:
            active_service.sessions.require_origin(
                _raw_headers(request, b"origin")
            )
        session = await run_in_threadpool(
            active_service.sessions.authenticate_session,
            _session_cookie(request),
        )
        await _require_traffic(
            active_service,
            SUBJECT_GENERAL,
            session.subject_id,
        )
        await _require_traffic(
            active_service,
            OPERATION_LINK,
            session.subject_id,
        )
        if mutation:
            active_service.sessions.require_csrf(
                session,
                _raw_headers(request, b"x-agentonomy-csrf"),
            )
        return session

    def require_no_operation_query(request: Request) -> None:
        if request.url.query:
            raise MiniAppServiceError("miniapp_invalid_request", 400)

    def live_operations_available(
        active_service: MiniAppChatService | None,
    ) -> bool:
        return bool(
            active_service is not None
            and active_service.polymarket_live_operations_enabled
        )

    @app.post(
        "/miniapp/api/operations/polymarket/funding",
        include_in_schema=False,
    )
    async def create_polymarket_funding_operation(
        request: Request,
    ) -> Response:
        if not live_operations_available(service):
            return _error(404, "miniapp_not_found")
        assert service is not None
        try:
            require_no_operation_query(request)
            session = await live_operation_session(
                request,
                service,
                mutation=True,
            )
            payload = await _strict_json_object(
                request,
                expected={"amount_usdc", "idempotency_key"},
                max_bytes=_MAX_OPERATION_BODY_BYTES,
            )
            result = await run_in_threadpool(
                service.create_polymarket_funding_operation,
                session,
                amount_usdc=payload["amount_usdc"],
                idempotency_key=payload["idempotency_key"],
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(result, status_code=201, headers=_NO_STORE_HEADERS)

    @app.get(
        "/miniapp/api/operations/polymarket/funding/{operation_id}",
        include_in_schema=False,
    )
    async def get_polymarket_funding_operation(
        request: Request,
        operation_id: str,
    ) -> Response:
        if not live_operations_available(service):
            return _error(404, "miniapp_not_found")
        assert service is not None
        try:
            require_no_operation_query(request)
            session = await live_operation_session(
                request,
                service,
                mutation=False,
            )
            result = await run_in_threadpool(
                service.get_polymarket_funding_operation,
                session,
                operation_id,
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(result, headers=_NO_STORE_HEADERS)

    @app.post(
        "/miniapp/api/operations/polymarket/funding/{operation_id}/continue",
        include_in_schema=False,
    )
    async def continue_polymarket_funding_operation(
        request: Request,
        operation_id: str,
    ) -> Response:
        if not live_operations_available(service):
            return _error(404, "miniapp_not_found")
        assert service is not None
        try:
            require_no_operation_query(request)
            session = await live_operation_session(
                request,
                service,
                mutation=True,
            )
            await _strict_json_object(
                request,
                expected=set(),
                max_bytes=_MAX_OPERATION_BODY_BYTES,
            )
            result = await funding_continue_flights.run(
                (session.subject_id, operation_id),
                lambda: run_in_threadpool(
                    service.continue_polymarket_funding_operation,
                    session,
                    operation_id,
                ),
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(result, headers=_NO_STORE_HEADERS)

    @app.post(
        "/miniapp/api/operations/polymarket/order-signing",
        include_in_schema=False,
    )
    async def create_polymarket_order_signing_session(
        request: Request,
    ) -> Response:
        if not live_operations_available(service):
            return _error(404, "miniapp_not_found")
        assert service is not None
        try:
            require_no_operation_query(request)
            session = await live_operation_session(
                request,
                service,
                mutation=True,
            )
            payload = await _strict_json_object(
                request,
                expected={"preview_id"},
                max_bytes=_MAX_OPERATION_BODY_BYTES,
            )
            result = await signing_create_flights.run(
                (session.subject_id, str(payload["preview_id"])),
                lambda: run_in_threadpool(
                    service.create_polymarket_order_signing_session,
                    session,
                    preview_id=payload["preview_id"],
                ),
            )
        except MiniAppOrderSigningOutcomeUnknown as exc:
            return JSONResponse(
                {
                    "detail": exc.reason,
                    "next_action": exc.next_action,
                },
                status_code=exc.status_code,
                headers=_NO_STORE_HEADERS,
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(result, status_code=201, headers=_NO_STORE_HEADERS)

    @app.get(
        "/miniapp/api/operations/polymarket/order-signing/{session_id}",
        include_in_schema=False,
    )
    async def get_polymarket_order_signing_session(
        request: Request,
        session_id: str,
    ) -> Response:
        if not live_operations_available(service):
            return _error(404, "miniapp_not_found")
        assert service is not None
        try:
            require_no_operation_query(request)
            session = await live_operation_session(
                request,
                service,
                mutation=False,
            )
            result = await run_in_threadpool(
                service.get_polymarket_order_signing_session,
                session,
                session_id,
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(result, headers=_NO_STORE_HEADERS)

    @app.post("/miniapp/api/chat/messages", include_in_schema=False)
    async def post_miniapp_message(request: Request) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            service.sessions.require_origin(_raw_headers(request, b"origin"))
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            await _require_traffic(
                service,
                MESSAGE_SUBMIT,
                session.subject_id,
            )
            service.sessions.require_csrf(
                session,
                _raw_headers(request, b"x-agentonomy-csrf"),
            )
            payload = await _strict_json_object(
                request,
                expected={"client_message_id", "text"},
                max_bytes=_MAX_MESSAGE_BODY_BYTES,
            )
            if not all(isinstance(payload[name], str) for name in payload):
                raise MiniAppServiceError("miniapp_invalid_request", 400)
            submission = await run_in_threadpool(
                service.submit_message,
                session,
                client_message_id=payload["client_message_id"],
                text=payload["text"],
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(
            {
                "client_message_id": submission.client_message_id,
                "status": submission.status,
            },
            status_code=202,
            headers=_NO_STORE_HEADERS,
        )

    @app.get(
        "/miniapp/api/chat/messages/{client_message_id}/run",
        include_in_schema=False,
    )
    async def get_miniapp_run(
        request: Request,
        client_message_id: str,
    ) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            run = await run_in_threadpool(
                service.get_message_run,
                session,
                client_message_id,
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        output = (
            _bounded_text(run.output, _MAX_RUN_OUTPUT_BYTES)
            if run.status == "completed"
            else None
        )
        return JSONResponse(
            {
                "client_message_id": client_message_id,
                "status": run.status,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
                "has_output": output is not None,
                "has_error": run.error is not None,
                "output": output,
            },
            headers=_NO_STORE_HEADERS,
        )

    @app.get(
        "/miniapp/api/chat/messages/{client_message_id}/events",
        include_in_schema=False,
    )
    async def get_miniapp_events(
        request: Request,
        client_message_id: str,
    ) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        lease: MiniAppSseLease | None = None
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            lease = await run_in_threadpool(
                service.acquire_sse_lease,
                session,
            )
            events = await run_in_threadpool(
                service.stream_message_events,
                session,
                client_message_id,
            )
        except MiniAppServiceError as exc:
            if lease is not None:
                await _release_sse_lease_safely(service, lease)
            return _error(exc.status_code, exc.reason)
        except Exception:
            if lease is not None:
                await _release_sse_lease_safely(service, lease)
            return _error(503, "miniapp_unavailable")
        assert lease is not None
        return StreamingResponse(
            _serialize_events(
                events,
                on_close=lambda: service.release_sse_lease(lease),
            ),
            media_type="text/event-stream",
            headers=_NO_STORE_HEADERS,
        )

    @app.post(
        "/miniapp/api/chat/messages/{client_message_id}/stop",
        include_in_schema=False,
    )
    async def stop_miniapp_run(
        request: Request,
        client_message_id: str,
    ) -> Response:
        if service is None:
            return _error(404, "miniapp_not_found")
        try:
            await _require_traffic(
                service,
                IP_GENERAL,
                _client_ip_scope(request),
            )
            service.sessions.require_origin(_raw_headers(request, b"origin"))
            session = await run_in_threadpool(
                service.sessions.authenticate_session,
                _session_cookie(request),
            )
            await _require_traffic(
                service,
                SUBJECT_GENERAL,
                session.subject_id,
            )
            await _require_traffic(
                service,
                STOP,
                session.subject_id,
            )
            service.sessions.require_csrf(
                session,
                _raw_headers(request, b"x-agentonomy-csrf"),
            )
            run = await run_in_threadpool(
                service.stop_message_run,
                session,
                client_message_id,
            )
        except MiniAppServiceError as exc:
            return _error(exc.status_code, exc.reason)
        return JSONResponse(
            {"client_message_id": client_message_id, "status": run.status},
            headers=_NO_STORE_HEADERS,
        )


def _error(status_code: int, reason: str) -> JSONResponse:
    return JSONResponse(
        {"detail": reason},
        status_code=status_code,
        headers=_NO_STORE_HEADERS,
    )


async def _require_traffic(
    service: MiniAppChatService,
    action: str,
    scope: str,
) -> None:
    await run_in_threadpool(service.require_traffic, action, scope)


async def _release_sse_lease_safely(
    service: MiniAppChatService,
    lease: MiniAppSseLease,
) -> None:
    try:
        await run_in_threadpool(service.release_sse_lease, lease)
    except Exception:
        pass


def _raw_headers(request: Request, name: bytes) -> list[str]:
    values: list[str] = []
    for raw_name, raw_value in request.scope.get("headers", []):
        if raw_name.lower() != name:
            continue
        try:
            values.append(raw_value.decode("ascii"))
        except UnicodeDecodeError:
            values.append("")
    return values


def _client_ip_scope(request: Request) -> str:
    peer_host = getattr(request.client, "host", None)
    peer = _canonical_ip(peer_host)
    if peer is None:
        return "invalid-peer"
    try:
        is_loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return "invalid-peer"
    if not is_loopback:
        return peer
    forwarded = _raw_headers(request, b"x-agentonomy-client-ip")
    if len(forwarded) == 1:
        candidate = _canonical_ip(forwarded[0])
        if candidate is not None:
            return candidate
    return peer


def _canonical_ip(value: object) -> str | None:
    if not isinstance(value, str) or not value or "%" in value:
        return None
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    canonical = parsed.compressed
    if value != canonical:
        return None
    return canonical


def _session_cookie(request: Request) -> str:
    found: list[str] = []
    for header in _raw_headers(request, b"cookie"):
        for item in header.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name == _SESSION_COOKIE:
                found.append(value)
    if len(found) != 1:
        raise MiniAppServiceError("miniapp_unauthorized", 401)
    return found[0]


async def _strict_json_object(
    request: Request,
    *,
    expected: set[str],
    max_bytes: int,
) -> dict[str, Any]:
    media_type = request.headers.get("content-type", "").split(";", 1)[0]
    if media_type.strip().lower() != "application/json":
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    _require_bounded_content_length(request, max_bytes=max_bytes)
    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(chunk) > max_bytes - len(body):
                raise MiniAppServiceError("miniapp_invalid_request", 400)
            body.extend(chunk)
    except MiniAppServiceError:
        raise
    except Exception:
        raise MiniAppServiceError("miniapp_invalid_request", 400) from None
    if not body:
        raise MiniAppServiceError("miniapp_invalid_request", 400)

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=pairs_hook,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, RecursionError):
        raise MiniAppServiceError("miniapp_invalid_request", 400) from None
    if not isinstance(payload, dict) or set(payload) != expected:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    return payload


def _require_bounded_content_length(request: Request, *, max_bytes: int) -> None:
    values = _raw_headers(request, b"content-length")
    if not values:
        return
    if len(values) != 1:
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    value = values[0]
    if not value or any(
        character < "0" or character > "9" for character in value
    ):
        raise MiniAppServiceError("miniapp_invalid_request", 400)
    normalized = value.lstrip("0") or "0"
    maximum = str(max_bytes)
    if len(normalized) > len(maximum) or (
        len(normalized) == len(maximum) and normalized > maximum
    ):
        raise MiniAppServiceError("miniapp_invalid_request", 400)


async def _serialize_events(
    events: Iterator[Any],
    *,
    on_close: Callable[[], None] | None = None,
) -> AsyncIterator[bytes]:
    try:
        try:
            iterator = iter(events)
            while True:
                item = await anyio.to_thread.run_sync(
                    _next_event,
                    iterator,
                    abandon_on_cancel=True,
                )
                if item is _EVENTS_DONE:
                    return
                projected = _project_event(item)
                if projected is None:
                    continue
                event_name, event_data = projected
                lines = [f"event: {event_name}"]
                lines.append(
                    "data: "
                    + json.dumps(
                        event_data,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                yield ("\n".join(lines) + "\n\n").encode("utf-8")
        except Exception:
            yield (
                'event: error\ndata: {"event":"error",'
                '"reason":"miniapp_stream_unavailable"}\n\n'
            ).encode("ascii")
    finally:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(
                _close_events,
                events,
                abandon_on_cancel=True,
            )
            if on_close is not None:
                await anyio.to_thread.run_sync(
                    _run_close_callback,
                    on_close,
                    abandon_on_cancel=True,
                )


def _next_event(iterator: Iterator[Any]) -> object:
    try:
        return next(iterator)
    except StopIteration:
        return _EVENTS_DONE


def _close_events(events: object) -> None:
    close = getattr(events, "close", None)
    if not callable(close):
        return
    try:
        close()
    except Exception:
        pass


def _run_close_callback(callback: Callable[[], None]) -> None:
    try:
        callback()
    except Exception:
        pass


def _project_event(item: object) -> tuple[str, dict[str, str]] | None:
    event_name = getattr(item, "event", None)
    data = getattr(item, "data", None)
    if not isinstance(data, Mapping):
        return None
    if event_name == "message.delta":
        delta = _bounded_text(data.get("delta"), _MAX_SSE_DELTA_BYTES)
        if delta is None or not delta.strip():
            return None
        return event_name, {"delta": delta}
    if event_name in {"tool.started", "tool.completed"}:
        return event_name, {
            "tool": _safe_tool_label(data.get("tool")),
        }
    return None


def _bounded_text(value: object, max_bytes: int) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return None
    if len(encoded) > max_bytes:
        return None
    return value


def _safe_tool_label(value: object) -> str:
    label = _bounded_text(value, _MAX_SSE_TOOL_LABEL_BYTES)
    if label is None or not label or label != label.strip():
        return "tool"
    if any(
        not character.isascii()
        or not (character.isalnum() or character in " ._:/-")
        for character in label
    ):
        return "tool"
    return label
