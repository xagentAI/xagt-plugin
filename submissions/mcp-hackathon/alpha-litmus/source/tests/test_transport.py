import asyncio
import threading
from collections.abc import AsyncIterator, Iterator

import httpx
import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from app import transport
from app.contracts import ChallengeRequest, Report
from app.lab import challenge
from app.main import app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("ALPHALITMUS_ENV", raising=False)
    with TestClient(app) as result:
        yield result


@pytest.mark.parametrize("body", [
    b'{"mode":"nexus","mode":"nexus"}', b'{"secret":"never-echo",',
    b'{"mode":"nexus","as_of":NaN}', b'{"mode":"nexus","as_of":Infinity}',
    b'{"mode":"nexus","as_of":1e999}', b'\xff',
    b'{"research":{"source":"never-echo","source":"duplicate"}}',
    b'[' * 34 + b'0' + b']' * 34,
])
def test_bad_json_is_safe(client: TestClient, body: bytes) -> None:
    response = client.post("/v1/challenge", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert response.json() == {"detail": "INVALID_JSON"}


def test_depth_exact_boundary() -> None:
    value: object = 0
    for _ in range(32):
        value = [value]
    transport.validate_json(value)
    with pytest.raises(transport.TransportError):
        transport.validate_json([value])


def test_body_limit_and_content_type(client: TestClient) -> None:
    assert client.post("/v1/challenge", content=b" " * (transport.MAX_BODY_BYTES + 1)).status_code == 413
    assert client.post("/v1/challenge", content=b"{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post("/v1/challenge", content=b"{}", headers={"Content-Type": "application/json", "Content-Encoding": "gzip"}).status_code == 415


def test_admission_releases_after_error() -> None:
    async def check() -> None:
        gate = transport.Admission(1)
        with pytest.raises(ValueError):
            async with gate.slot():
                raise ValueError("failure")
        async with gate.slot():
            with pytest.raises(transport.TransportError) as error:
                async with gate.slot():
                    pass
            assert error.value.status == 429
    asyncio.run(check())


def test_chunked_body_bound() -> None:
    async def check() -> None:
        async def chunks() -> AsyncIterator[bytes]:
            yield b" " * 2_000_001
            yield b" " * 2_000_001

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            response = await client.post("/v1/challenge", content=chunks(), headers={"Content-Type": "application/json"})
            assert response.status_code == 413
    asyncio.run(check())


def test_admission_offload_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(transport, "admission", transport.Admission(1))
    loop_thread = threading.get_ident()

    def slow(request: ChallengeRequest, evidence: dict[str, object] | None) -> Report:
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(5)
        return challenge(request, evidence)

    monkeypatch.setattr(transport, "challenge", slow)

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            first = asyncio.create_task(client.post("/v1/challenge", json={"mode": "nexus"}))
            try:
                for _ in range(1000):
                    if started.is_set():
                        break
                    await asyncio.sleep(.001)
                assert started.is_set()
                assert (await client.get("/health")).status_code == 200
                rejected = await client.post("/v1/challenge", json={"mode": "nexus"})
                assert rejected.status_code == 429
            finally:
                release.set()
            assert (await first).status_code == 200
            assert (await client.post("/v1/challenge", json={"mode": "nexus"})).status_code == 200
    asyncio.run(check())


def test_intake_capacity_timeout_and_health(monkeypatch: pytest.MonkeyPatch) -> None:
    assert transport.BODY_TIMEOUT_SECONDS == 10
    assert transport.MAX_INTAKE == 8
    monkeypatch.setattr(transport, "intake_admission", transport.Admission(1))
    monkeypatch.setattr(transport, "BODY_TIMEOUT_SECONDS", .1)

    async def check() -> None:
        started = asyncio.Event()

        async def upload() -> AsyncIterator[bytes]:
            yield b'{"secret":"never-echo'
            started.set()
            await asyncio.sleep(30)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            first = asyncio.create_task(client.post("/v1/challenge", content=upload(), headers={"Content-Type": "application/json"}))
            await started.wait()
            with anyio.fail_after(1):
                assert (await client.get("/health")).status_code == 200
                rejected = await client.post("/v1/challenge", json={"mode": "nexus"})
                assert rejected.status_code == 429
                assert rejected.json() == {"detail": "CAPACITY_EXCEEDED"}
                response = await first
            assert response.status_code == 408
            assert response.json() == {"detail": "BODY_TIMEOUT"}
            assert (await client.post("/v1/challenge", json={"mode": "nexus"})).status_code == 200
    asyncio.run(check())


@pytest.mark.parametrize("headers,status", [
    ([], 200), ([(b"content-length", b"0")], 200),
    ([(b"content-length", b"1")], 400),
    ([(b"transfer-encoding", b"chunked")], 400),
    ([(b"content-length", b"4000001")], 413),
    ([(b"content-length", b"invalid")], 400),
])
def test_health_never_receives_upload(headers: list[tuple[bytes, bytes]], status: int,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    gate = transport.Admission(1)
    monkeypatch.setattr(transport, "intake_admission", gate)

    async def check() -> None:
        scope: Scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                        "method": "GET", "scheme": "http", "path": "/health", "raw_path": b"/health",
                        "query_string": b"", "headers": headers, "server": ("local", 80),
                        "client": ("local", 1234), "root_path": ""}
        messages: list[Message] = []

        async def receive() -> Message:
            raise AssertionError("health waited on an upload")

        async def send(message: Message) -> None:
            messages.append(message)

        async with gate.slot():
            with anyio.fail_after(1):
                await app(scope, receive, send)
        assert messages[0]["status"] == status
    asyncio.run(check())


def test_upload_cancellation_releases_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = transport.Admission(1)
    monkeypatch.setattr(transport, "intake_admission", gate)

    async def check() -> None:
        started = asyncio.Event()

        async def upload() -> AsyncIterator[bytes]:
            started.set()
            await asyncio.sleep(30)
            yield b"{}"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            task = asyncio.create_task(client.post("/v1/challenge", content=upload()))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with gate.slot():
                pass
    asyncio.run(check())
