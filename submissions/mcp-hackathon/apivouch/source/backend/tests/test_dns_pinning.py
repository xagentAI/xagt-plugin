"""Adversarial DNS with real HTTPX/httpcore and a simulated socket boundary."""

import ipaddress
import socket
import ssl

import httpcore
import httpx
import pytest
from fastapi import HTTPException

from app.core import security
from app.services import http_client

PUBLIC = "93.184.216.34"
PUBLIC6 = "2606:4700:4700::1111"


def answer(*addresses):
    return [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM,
         socket.IPPROTO_TCP, "", (address, 0))
        for address in addresses
    ]


class Wire(httpcore.AsyncNetworkStream):
    def __init__(self, response):
        self.response = response
        self.writes = bytearray()
        self.tls = []
        self.closed = False

    async def read(self, max_bytes, timeout=None):
        result, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return result

    async def write(self, buffer, timeout=None):
        self.writes.extend(buffer)

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self

    async def aclose(self):
        self.closed = True

    def get_extra_info(self, info):
        return None


@pytest.fixture
def network(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK", "false")
    targets, wires, responses = [], [], []

    async def connect(self, host, port, **kwargs):
        # A vulnerable connector resolves the name a second time here. The
        # adversarial resolver then returns a forbidden target.
        try:
            ipaddress.ip_address(host)
            target = host
        except ValueError:
            target = socket.getaddrinfo(host, port)[0][4][0]
        targets.append((target, port))
        wire = Wire(responses.pop(0) if responses else b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        wires.append(wire)
        return wire

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    return targets, wires, responses


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fd00:ec2::254"])
@pytest.mark.parametrize("public", [PUBLIC, PUBLIC6])
async def test_rebinding_never_connects_or_sends_to_second_dns_answer(monkeypatch, network, forbidden, public):
    calls = []

    def dns(host, *args, **kwargs):
        calls.append(host)
        return answer(public if len(calls) == 1 else forbidden)

    monkeypatch.setattr(security.socket, "getaddrinfo", dns)
    targets, wires, _ = network
    response = await http_client.safe_request("GET", "https://rebind.example:8443/path", headers={"Host": "evil.example"})
    assert response.content == b"ok"
    assert calls == ["rebind.example"]
    assert targets == [(public, 8443)]
    assert wires[0].tls == [("rebind.example", True, ssl.CERT_REQUIRED)]
    assert b"Host: rebind.example:8443\r\n" in wires[0].writes
    assert b"evil.example" not in wires[0].writes
    assert wires[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [
    (PUBLIC, "127.0.0.1"), ("10.0.0.1", PUBLIC), (PUBLIC, "169.254.169.254"),
    (PUBLIC, "::1"), (PUBLIC6, "fd00:ec2::254"), (PUBLIC6, "::ffff:127.0.0.1"),
    (PUBLIC, "100.64.0.1"), (PUBLIC6, "ff02::1"), (PUBLIC, "not-an-ip"),
    (PUBLIC, "fe80::1%3"), (),
])
async def test_entire_answer_fails_closed_before_connect(monkeypatch, network, addresses):
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer(*addresses))
    with pytest.raises(HTTPException):
        await http_client.safe_request("GET", "http://mixed.example/")
    assert network[0] == []
    assert network[1] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["/next", "http://other.example/next", "http://[::1]/", "http://169.254.169.254/"])
async def test_every_redirect_revalidates_before_any_second_request(monkeypatch, network, location):
    calls = []

    def dns(host, *args, **kwargs):
        calls.append(host)
        return answer(PUBLIC if len(calls) == 1 else "127.0.0.1")

    monkeypatch.setattr(security.socket, "getaddrinfo", dns)
    targets, wires, responses = network
    responses.append(f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n".encode())
    with pytest.raises(HTTPException):
        await http_client.safe_request("GET", "http://rebind.example/start")
    assert len(calls) == 2
    assert targets == [(PUBLIC, 80)]
    assert len(wires) == 1 and wires[0].closed
    assert b"GET /start " in wires[0].writes


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["/next", "https://other.example/next"])
async def test_redirect_gets_new_pin_pool_host_and_tls(monkeypatch, network, location):
    calls = []

    def dns(host, *args, **kwargs):
        calls.append(host)
        return answer(PUBLIC if len(calls) == 1 else PUBLIC6)

    monkeypatch.setattr(security.socket, "getaddrinfo", dns)
    targets, wires, responses = network
    responses.append(f"HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\n\r\n".encode())
    await http_client.safe_request("GET", "https://rebind.example/start")
    final_host = "other.example" if "other" in location else "rebind.example"
    assert calls == ["rebind.example", final_host]
    assert targets == [(PUBLIC, 443), (PUBLIC6, 443)]
    assert all(wire.closed for wire in wires)
    assert wires[1].tls == [(final_host, True, ssl.CERT_REQUIRED)]
    assert f"Host: {final_host}\r\n".encode() in wires[1].writes


@pytest.mark.asyncio
async def test_environment_cannot_install_proxy_or_tls_override(monkeypatch, network):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9999")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("SSL_CERT_FILE", "nonexistent-ca-file")
    monkeypatch.setenv("SSL_CERT_DIR", "nonexistent-ca-dir")
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer(PUBLIC))
    for scheme in ("http", "https"):
        await http_client.safe_request("GET", f"{scheme}://public.example/")
    assert network[0] == [(PUBLIC, 80), (PUBLIC, 443)]


@pytest.mark.asyncio
async def test_fallback_uses_only_validated_snapshot(monkeypatch, network):
    calls = []

    def dns(*args, **kwargs):
        calls.append(True)
        return answer(PUBLIC, PUBLIC6) if len(calls) == 1 else answer("127.0.0.1")

    monkeypatch.setattr(security.socket, "getaddrinfo", dns)
    original = httpcore.AnyIOBackend.connect_tcp
    attempts = []

    async def connect(self, host, port, **kwargs):
        attempts.append(host)
        if host == PUBLIC:
            raise httpcore.ConnectError("simulated unreachable address")
        return await original(self, host, port, **kwargs)

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    await http_client.safe_request("GET", "https://public.example/")
    assert attempts == [PUBLIC, PUBLIC6]
    assert len(calls) == 1
    assert network[0] == [(PUBLIC6, 443)]


@pytest.mark.asyncio
async def test_transport_rejects_other_origin_even_with_existing_pool(monkeypatch, network):
    async with http_client._PinnedTransport(httpx.URL("http://public.example"), (PUBLIC,)) as transport:
        with pytest.raises(httpx.ConnectError, match="outside pinned origin"):
            await transport.handle_async_request(httpx.Request("GET", "http://127.0.0.1/"))
    assert network[0] == []


@pytest.mark.asyncio
async def test_development_policy_still_pins(monkeypatch, network):
    monkeypatch.setenv("ALLOW_PRIVATE_NETWORK", "true")
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer("::1"))
    await http_client.safe_request("GET", "http://localhost/")
    assert network[0] == [("::1", 80)]


@pytest.mark.asyncio
async def test_response_limit_still_closes_pinned_socket(monkeypatch, network):
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer(PUBLIC))
    monkeypatch.setattr(http_client, "MAX_RESPONSE_BYTES", 1)
    with pytest.raises(ValueError, match="Response exceeds"):
        await http_client.safe_request("GET", "http://public.example/")
    assert network[1][0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [httpcore.ConnectError, httpcore.ConnectTimeout])
async def test_failed_connect_never_falls_back_to_hostname(monkeypatch, network, error):
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer(PUBLIC, PUBLIC6))
    attempts = []

    async def connect(self, host, port, **kwargs):
        attempts.append(host)
        raise error("simulated connection failure")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    with pytest.raises(getattr(httpx, error.__name__)):
        await http_client.safe_request("GET", "https://public.example/")
    assert attempts == [PUBLIC, PUBLIC6]
    assert network[1] == []


@pytest.mark.asyncio
async def test_read_error_keeps_httpx_contract_and_closes_socket(monkeypatch, network):
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda *a, **k: answer(PUBLIC))

    async def read(self, max_bytes, timeout=None):
        raise httpcore.ReadTimeout("simulated read timeout")

    monkeypatch.setattr(Wire, "read", read)
    with pytest.raises(httpx.ReadTimeout):
        await http_client.safe_request("GET", "https://public.example/")
    assert network[1][0].closed
