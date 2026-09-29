from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Any
from urllib.parse import urljoin

import httpcore
import httpx

from app.core.config import MAX_REDIRECTS, MAX_RESPONSE_BYTES, REQUEST_TIMEOUT
from app.core.security import resolve_url_for_fetch


@contextmanager
def _map_network_errors():
    # Preserve the HTTPX error contract consumed by runtime/probe callers.
    try:
        yield
    except (httpcore.NetworkError, httpcore.TimeoutException, httpcore.ProtocolError,
            httpcore.ProxyError, httpcore.UnsupportedProtocol) as exc:
        error_type = getattr(httpx, type(exc).__name__, httpx.TransportError)
        raise error_type(str(exc)) from exc


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, host: str, port: int, addresses: tuple[str, ...]):
        self.host, self.port, self.addresses = host, port, addresses
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if (host, port) != (self.host, self.port):
            raise httpcore.ConnectError("Connection outside pinned origin")
        deadline = None if timeout is None else monotonic() + timeout
        for index, address in enumerate(self.addresses):
            remaining = None if deadline is None else max(0, deadline - monotonic())
            try:
                # Only numeric addresses cross the socket boundary. TLS still uses
                # httpcore's original origin hostname, never this address.
                return await self.backend.connect_tcp(
                    address, port, timeout=remaining,
                    local_address=local_address, socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout):
                if index == len(self.addresses) - 1:
                    raise
        raise httpcore.ConnectError("No pinned addresses")


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        with _map_network_errors():
            async for chunk in self.stream:
                yield chunk

    async def aclose(self):
        await self.stream.aclose()


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, url: httpx.URL, addresses: tuple[str, ...]):
        self.origin = (url.raw_scheme, url.raw_host, url.port)
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            network_backend=_PinnedBackend(
                url.raw_host.decode("ascii"), url.port or (443 if url.scheme == "https" else 80), addresses,
            ),
            max_connections=1, max_keepalive_connections=0, retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if (url.raw_scheme, url.raw_host, url.port) != self.origin:
            raise httpx.ConnectError("Request outside pinned origin", request=request)
        with _map_network_errors():
            response = await self.pool.handle_async_request(httpcore.Request(
                method=request.method,
                url=httpcore.URL(scheme=url.raw_scheme, host=url.raw_host, port=url.port, target=url.raw_path),
                headers=request.headers.raw, content=request.stream,
                # Do not accept SNI overrides or other caller-supplied core extensions.
                extensions={"timeout": request.extensions.get("timeout", {})},
            ))
        return httpx.Response(
            response.status, headers=response.headers,
            stream=_ResponseStream(response.stream), extensions=response.extensions,
        )

    async def aclose(self):
        await self.pool.aclose()


@dataclass
class SafeResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str

    def json(self) -> Any:
        import json

        return json.loads(self.content.decode("utf-8", errors="strict"))


async def safe_request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
) -> SafeResponse:
    """Make a bounded request while validating every redirect target."""
    current = url
    request_method = method.upper()
    for redirect_number in range(MAX_REDIRECTS + 1):
        addresses = resolve_url_for_fetch(current)
        # A pool belongs to exactly one validation snapshot and one redirect hop.
        transport = _PinnedTransport(httpx.URL(current), addresses)
        request_headers = {key: value for key, value in (headers or {}).items() if key.lower() != "host"}
        async with (
            httpx.AsyncClient(
                timeout=REQUEST_TIMEOUT, follow_redirects=False,
                trust_env=False, transport=transport,
            ) as client,
            client.stream(
                request_method,
                current,
                params=params if redirect_number == 0 else None,
                headers=request_headers,
                json=json_body if redirect_number == 0 else None,
            ) as response,
        ):
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(f"Response exceeds {MAX_RESPONSE_BYTES} bytes")
            response_headers = {key.lower(): value for key, value in response.headers.items()}
            status = response.status_code
        if status not in {301, 302, 303, 307, 308}:
            return SafeResponse(status, response_headers, bytes(body), current)
        location = response_headers.get("location")
        if not location:
            return SafeResponse(status, response_headers, bytes(body), current)
        if redirect_number >= MAX_REDIRECTS:
            raise ValueError("Too many redirects")
        current = urljoin(current, location)
        if status == 303:
            request_method = "GET"
    raise ValueError("Redirect handling failed")
