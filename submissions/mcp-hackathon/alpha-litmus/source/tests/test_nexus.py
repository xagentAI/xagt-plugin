import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from app import nexus

KEY = "nxk_" + "synthetic_dummy_" + "a" * 20
DATA: dict[str, dict[str, Any]] = {
    "signal": {"symbol": "BTC/USDT", "trade_intent": "BUY", "timestamp": 1000},
    "metrics": {"trade_count": 2, "max_drawdown": "3.85%"},
    "equity": {"run_id": "bt-abc123", "points": [{"t": 1, "equity": 100}]},
    "trades": {"run_id": "bt-abc123", "trades": [{"symbol": "BTC/USDT", "pnl": 10}]},
}


def install(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    original = httpx.AsyncClient
    monkeypatch.setenv("NEXUS_API_KEY", KEY)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        timeout = kwargs["timeout"]
        assert all(getattr(timeout, part) > 0 for part in ("connect", "read", "write", "pool"))
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def test_four_documented_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == nexus.BASE + "/tools/call"
        assert request.method == "POST"
        assert request.headers["X-API-KEY"] == KEY
        payload = json.loads(request.content)
        label = payload["name"].removeprefix("get_strategy_")
        calls.append(label)
        assert payload["arguments"] == ({"symbol": "BTC/USDT"} if label == "signal" else {})
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(DATA[label])}]})

    install(monkeypatch, handler)
    monkeypatch.setenv("NEXUS_BASE_URL", "https://attacker.invalid")
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert set(calls) == set(nexus.SURFACES)
    assert all(result[label]["data"] == DATA[label] for label in nexus.SURFACES)
    assert KEY not in json.dumps(result)


def test_current_gateway_object_content_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production gateway compatibility: `content` is the result object."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        label = payload["name"].removeprefix("get_strategy_")
        calls.append(label)
        return httpx.Response(200, json={
            "ok": True,
            "name": payload["name"],
            "strategy_id": "str-safe",
            "content": DATA[label],
        })

    install(monkeypatch, handler)
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert set(calls) == set(nexus.SURFACES)
    assert all(result[label]["status"] == "received" for label in nexus.SURFACES)
    assert all(result[label]["data"] == DATA[label] for label in nexus.SURFACES)
    assert KEY not in json.dumps(result)


def test_missing_key_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert all(item["reason"] == "NEXUS_NOT_CONFIGURED" for item in result.values())


@pytest.mark.parametrize("symbol", ["BTCUSDT", "btc/usdt", "https://evil.invalid", "BTC/USDT\n"])
def test_invalid_symbol_no_network(monkeypatch: pytest.MonkeyPatch, symbol: str) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", KEY)
    assert all(item["reason"] == "NEXUS_INVALID_SYMBOL" for item in asyncio.run(nexus.read_nexus(symbol)).values())


@pytest.mark.parametrize("status", [301, 307, 401, 404, 429, 502])
def test_http_errors_and_redirects(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(status, headers={"Location": "https://attacker.invalid"}, text=KEY)

    install(monkeypatch, handler)
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert len(calls) == 4
    assert all(item["reason"] == "NEXUS_HTTP_ERROR" for item in result.values())
    assert KEY not in json.dumps(result)


@pytest.mark.parametrize("exception", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError])
def test_transport_errors(monkeypatch: pytest.MonkeyPatch, exception: type[httpx.HTTPError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exception(KEY)

    install(monkeypatch, handler)
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert all(item["status"] == "unavailable" for item in result.values())
    assert KEY not in json.dumps(result)


def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    install(monkeypatch, handler)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(nexus.read_nexus("BTC/USDT"))


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"isError":true}', b'{"trade_count":NaN}', b'{"trade_count":1e999}', b"[" * 40 + b"0" + b"]" * 40])
def test_malformed_responses(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    install(monkeypatch, lambda request: httpx.Response(200, content=body))
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert all(item["status"] == "unavailable" for item in result.values())


def test_stream_limit_without_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    consumed: list[int] = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for index in range(100):
                consumed.append(index)
                yield b" " * 65536

    install(monkeypatch, lambda request: httpx.Response(200, stream=Stream()))
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert all(item["status"] == "unavailable" for item in result.values())
    assert max(consumed) == 30


def test_declared_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, lambda request: httpx.Response(200, headers={"Content-Length": "2000001"}, content=b"{}"))
    assert all(item["status"] == "unavailable" for item in asyncio.run(nexus.read_nexus("BTC/USDT")).values())


@pytest.mark.parametrize("payload", [{"result": {"trade_count": 4}}, {"data": {"trade_count": 4}}, {"structuredContent": {"trade_count": 4}}, {"content": {"trade_count": 4}}, {"content": [{"type": "text", "text": '{"trade_count":4}'}]}])
def test_unpack_compatibility(payload: dict[str, Any]) -> None:
    assert nexus.unpack(payload) == {"trade_count": 4}


@pytest.mark.parametrize("payload", [{"content": [None]}, {"content": []}, {"data": []}, {"error": "secret"}])
def test_unpack_rejects_invalid(payload: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        nexus.unpack(payload)


@pytest.mark.parametrize("identifier", [KEY, "bt-nxk_other", "bt-secret", "Bearer-key", "<script>", "x" * 65, "bt-\n"])
def test_sanitize_ids(monkeypatch: pytest.MonkeyPatch, identifier: str) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", KEY)
    assert "run_id" not in nexus.sanitize("equity", {"run_id": identifier})


def test_malicious_echo_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "symbol": KEY, "trade_intent": KEY, "timestamp": KEY, "run_id": KEY,
            "trade_count": KEY, "max_drawdown": KEY, "status": KEY,
            "reasoning_log": KEY, "arbitrary": KEY,
            "points": [{"t": KEY, "equity": KEY}],
            "trades": [{"symbol": KEY, "pnl": KEY}],
        })

    install(monkeypatch, handler)
    report = json.dumps(asyncio.run(nexus.read_nexus("BTC/USDT")))
    assert KEY not in report
    assert "reasoning_log" not in report
    assert "arbitrary" not in report


def test_unprefixed_key_and_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", "private123")
    assert nexus.sanitize("equity", {"run_id": "bt-private123", "unknown": 42}, key="private123") == {}
    assert nexus.sanitize("equity", {"run_id": "bt-private123", "unknown": 42}) == {"run_id": "bt-private123"}
    assert nexus.sanitize("metrics", {"trade_count": True, "win_rate_pct": "50", "run_id": "a"}) == {}
    assert nexus.sanitize("signal", {**DATA["signal"], "reasoning_log": "free text"}) == DATA["signal"]


def test_encoded_response_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, lambda request: httpx.Response(200, headers={"Content-Encoding": "gzip"}, content=b""))
    assert all(item["status"] == "unavailable" for item in asyncio.run(nexus.read_nexus("BTC/USDT")).values())


def test_nested_envelopes_bounded() -> None:
    payload: dict[str, Any] = {"trade_count": 4}
    for _ in range(40):
        payload = {"result": payload}
    with pytest.raises(ValueError):
        nexus.unpack(payload)


def test_partial_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        label = json.loads(request.content)["name"].removeprefix("get_strategy_")
        if label == "signal":
            raise httpx.ReadTimeout(KEY)
        return httpx.Response(200, json=DATA[label])

    install(monkeypatch, handler)
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert result["signal"]["status"] == "unavailable"
    assert all(result[label]["status"] == "received" for label in ("metrics", "equity", "trades"))


@pytest.mark.parametrize("text", [
    '{"trade_count":1,"trade_count":2}',
    '{"data":{"trade_count":1,"trade_count":1}}',
    '{"run_id":"bt-a","run_\\u0069d":"bt-b"}',
    '{"ignored":{"a":1,"a":2}}',
])
@pytest.mark.parametrize("wrapped", [False, True])
def test_duplicate_json_keys_rejected(monkeypatch: pytest.MonkeyPatch, text: str, wrapped: bool) -> None:
    body = json.dumps({"content": [{"type": "text", "text": text}]}) if wrapped else text
    install(monkeypatch, lambda request: httpx.Response(200, content=body))
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert all(item["status"] == "unavailable" for item in result.values())
    with pytest.raises(ValueError, match="^NEXUS_SCHEMA_ERROR$"):
        nexus.unpack({"content": [{"type": "text", "text": text}]})


def test_live_unprefixed_key_echo_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, lambda request: httpx.Response(200, json={"run_id": "bt-private123"}))
    monkeypatch.setenv("NEXUS_API_KEY", "private123")
    result = asyncio.run(nexus.read_nexus("BTC/USDT"))
    assert "private123" not in json.dumps(result)
    assert all(item["status"] == "unavailable" for item in result.values())
