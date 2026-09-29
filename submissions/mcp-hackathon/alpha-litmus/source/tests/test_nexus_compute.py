"""Synthetic/documentation-derived fixtures only; never real trading evidence."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app import nexus
from app import nexus_compute as compute

KEY = "nxk_" + "synthetic_compute_only"


@pytest.fixture(autouse=True)
def no_nexus_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(**kwargs: Any) -> None:
        raise AssertionError("No real network allowed")
    monkeypatch.setattr(httpx, "AsyncClient", deny)
    # Also block saved client aliases and synchronous clients at the transport.
    async def deny_async_transport(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("No real network allowed")

    def deny_sync_transport(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("No real network allowed")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_async_transport)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_sync_transport)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", raising=False)
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)


REAL_CLIENT = httpx.AsyncClient


def install(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", "true")
    monkeypatch.setenv("NEXUS_API_KEY", KEY)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert all(0 < getattr(kwargs["timeout"], x) <= 15 for x in ("connect", "read", "write", "pool"))
        return REAL_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)


def request(**kwargs: Any) -> compute.WindowExperimentRequest:
    return compute.WindowExperimentRequest(confirm_compute=True, **kwargs)


class Fixture:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.run_id = ""
        self.bars = 0
        self.overrides: dict[str, dict[str, Any]] = {}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert str(req.url) == nexus.BASE + "/tools/call"
        assert req.method == "POST"
        assert req.headers["X-API-KEY"] == KEY
        call = json.loads(req.content)
        self.calls.append(call)
        name, args = call["name"], call["arguments"]
        if name == "run_backtest":
            assert set(args) == {"n_bars"}
            self.bars = args["n_bars"]
            self.run_id = f"bt-{self.bars}"
            data = {"run_id": self.run_id, "status": "queued", "poll": "https://evil.invalid", "hint": KEY}
        elif name == "get_backtest_job":
            assert args == {"run_id": self.run_id}
            data = {"run_id": self.run_id, "status": "completed", "equity": 9999, "arbitrary": KEY}
        else:
            assert args == ({"symbol": "BTC/USDT"} if name == "get_strategy_signal" else {})
            data = {
                "get_strategy_metrics": {"total_return_pct": 10 if self.bars == 500 else -1,
                    "profit_factor": 1.5 if self.bars == 500 else 1, "max_drawdown": "2.5%",
                    "status": "QUALIFIED_FOR_OKX_LISTING" if self.bars == 500 else "NOT_QUALIFIED",
                    "run_id": self.run_id, "reasoning_log": KEY},
                "get_strategy_equity": {"run_id": self.run_id, "points": [
                    {"t": 1, "equity": 100}, {"t": 2, "equity": 120}, {"t": 3, "equity": 90}]},
                "get_strategy_trades": {"run_id": self.run_id, "trades": [{"symbol": "BTC/USDT", "pnl": -10}]},
                "get_strategy_signal": {"symbol": "BTC/USDT", "trade_intent": "HOLD", "timestamp": 123},
            }[name]
        data = self.overrides.get(name, data)
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(data)}]})


def fast_poll(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    intervals: list[float] = []
    sleep = asyncio.sleep

    async def fake(seconds: float) -> None:
        intervals.append(seconds)
        await sleep(0)

    monkeypatch.setattr(compute.asyncio, "sleep", fake)
    return intervals


@pytest.mark.parametrize("value", [False, 1, 1.0, "true", None])
def test_strict_confirmation(value: Any) -> None:
    with pytest.raises(ValidationError):
        compute.WindowExperimentRequest(confirm_compute=value)


def test_confirmation_required() -> None:
    with pytest.raises(ValidationError):
        compute.WindowExperimentRequest.model_validate({})


@pytest.mark.parametrize("windows", [[], [19], [501], [20, 20], [500, 100], [20, 30, 40, 50], [True], [20.0], ["20"]])
def test_window_boundaries(windows: Any) -> None:
    with pytest.raises(ValidationError):
        request(windows=windows)


@pytest.mark.parametrize("timeout", [4, 61, True, 5.0, "30"])
def test_timeout_boundaries(timeout: Any) -> None:
    with pytest.raises(ValidationError):
        request(timeout_seconds=timeout)


def test_defaults_and_valid_bounds() -> None:
    assert request().windows == [100, 250, 500]
    assert request().timeout_seconds == 30
    assert request(windows=[20, 500], timeout_seconds=60).windows == [20, 500]
    with pytest.raises(ValidationError):
        request(poll_interval=0)


@pytest.mark.parametrize("read,backtest,key", [(None, None, None), ("true", None, KEY),
    (None, "true", KEY), ("TRUE", "true", KEY), ("true", "1", KEY),
    ("true", "true", None), ("true", "true", "bad\nkey")])
def test_disabled_no_call(monkeypatch: pytest.MonkeyPatch, read: str | None, backtest: str | None, key: str | None) -> None:
    for name, value in [("ALPHALITMUS_ENABLE_NEXUS", read), ("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", backtest), ("NEXUS_API_KEY", key)]:
        if value is not None:
            monkeypatch.setenv(name, value)
    with pytest.raises(compute.NexusComputeError) as exc:
        asyncio.run(compute.run_window_experiment(request()))
    assert exc.value.code in ("NEXUS_COMPUTE_DISABLED", "NEXUS_NOT_CONFIGURED")


def test_bypassed_model_revalidated() -> None:
    forged = compute.WindowExperimentRequest.model_construct(confirm_compute=1)
    with pytest.raises(compute.NexusComputeError, match="^NEXUS_INVALID_REQUEST$"):
        asyncio.run(compute.run_window_experiment(forged))
    mutated = request()
    mutated.windows.append(501)
    with pytest.raises(compute.NexusComputeError, match="^NEXUS_INVALID_REQUEST$"):
        asyncio.run(compute.run_window_experiment(mutated))


def test_three_sequential_windows_unproven(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    install(monkeypatch, fixture)
    intervals = fast_poll(monkeypatch)
    monkeypatch.setenv("NEXUS_BASE_URL", "https://evil.invalid")
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.status == "UNPROVEN"
    assert [w.n_bars for w in report.windows] == [500, 250, 100]
    assert [w.run_id for w in report.windows] == ["bt-500", "bt-250", "bt-100"]
    assert report.baseline_n_bars == 500
    assert report.smallest_observed_failing_n_bars == 100
    assert report.definitive_boundary_n_bars is None
    assert report.baseline_survived is None
    assert report.confirmed_counterexample is False
    assert len(fixture.calls) == 18
    assert [c["name"] for c in fixture.calls] == ["run_backtest", "get_backtest_job", "get_strategy_metrics",
        "get_strategy_equity", "get_strategy_trades", "get_strategy_signal"] * 3
    assert intervals == [1, 1, 1]
    for window in report.windows:
        assert window.equity.binding == window.trades.binding == "matched"
        assert window.equity.observed_return_pct == pytest.approx(-10)
        assert window.equity.observed_max_drawdown_pct == pytest.approx(25)
        assert window.metrics.binding == window.signal.binding == "unavailable"
    encoded = report.model_dump_json()
    assert KEY not in encoded and "reasoning_log" not in encoded and "arbitrary" not in encoded
    assert len(encoded) < 12000
    assert compute.WindowExperimentReport.model_validate_json(encoded) == report


@pytest.mark.parametrize("tool", ["get_backtest_job", "get_strategy_equity", "get_strategy_trades"])
def test_mismatch_inconsistent(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    fixture = Fixture()
    fixture.overrides[tool] = {"run_id": "bt-other", "status": "completed", "points": [], "trades": []}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.status == "INCONSISTENT"
    assert report.windows[0].run_id == "bt-500"
    assert report.windows[1].job_status == "not_started"
    assert report.definitive_boundary_n_bars is None
    assert sum(c["name"] == "run_backtest" for c in fixture.calls) == 1


@pytest.mark.parametrize("identifier", [None, 123, "", KEY, "bt-secret", "bt-\n", "x" * 65, "<script>"])
@pytest.mark.parametrize("tool", ["run_backtest", "get_backtest_job", "get_strategy_equity", "get_strategy_trades"])
def test_corrupt_ids(monkeypatch: pytest.MonkeyPatch, identifier: Any, tool: str) -> None:
    fixture = Fixture()
    fixture.overrides[tool] = {"run_id": identifier, "status": "completed"}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.status == "UNPROVEN"
    window = report.windows[0]
    assert "NEXUS_SCHEMA_ERROR" in [window.reason, *window.errors]
    assert KEY not in report.model_dump_json()


@pytest.mark.parametrize("state", [None, "done", "failed", "cancelled", "canceled", "incomplete", "COMPLETED", KEY, 1])
@pytest.mark.parametrize("tool", ["run_backtest", "get_backtest_job"])
def test_unknown_state_closed(monkeypatch: pytest.MonkeyPatch, state: Any, tool: str) -> None:
    fixture = Fixture()
    fixture.overrides[tool] = {"run_id": "bt-500", "status": state}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason == "NEXUS_UNKNOWN_JOB_STATE"
    assert report.windows[0].run_id == "bt-500"
    assert not any(c["name"].startswith("get_strategy") for c in fixture.calls)


def test_poll_running_then_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    polls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal polls
        if json.loads(req.content)["name"] == "get_backtest_job":
            polls += 1
            fixture.overrides["get_backtest_job"] = {"run_id": "bt-20", "status": "running" if polls < 3 else "completed"}
        return fixture(req)

    install(monkeypatch, handler)
    intervals = fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.windows[0].job_status == "completed"
    assert polls == 3 and intervals == [1, 1, 1]


@pytest.mark.parametrize("status", [301, 307, 401, 404, 429, 502])
def test_http_no_retry(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(status, text=KEY, headers={"Location": "https://evil.invalid"})

    install(monkeypatch, handler)
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason == "NEXUS_HTTP_ERROR"
    assert len(calls) == 1 and KEY not in report.model_dump_json()


@pytest.mark.parametrize("exception", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError])
def test_transport_sanitized(monkeypatch: pytest.MonkeyPatch, exception: Any) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise exception(KEY)
    install(monkeypatch, handler)
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason in ("NEXUS_TIMEOUT", "NEXUS_TRANSPORT_ERROR")
    assert KEY not in report.model_dump_json()
    assert not compute._PROCESS_LOCK.locked()


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"isError":true}', b'{"run_id":"a","run_id":"b"}',
    b'{"data":{"x":NaN}}', b'[' * 40 + b'0' + b']' * 40])
def test_malformed_envelopes(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    install(monkeypatch, lambda req: httpx.Response(200, content=body))
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason == "NEXUS_SCHEMA_ERROR"


def test_stream_byte_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    consumed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for i in range(100):
                consumed.append(i)
                yield b" " * 65536

    install(monkeypatch, lambda req: httpx.Response(200, stream=Stream()))
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason == "NEXUS_RESPONSE_TOO_LARGE"
    assert max(consumed) == 30


@pytest.mark.parametrize("headers", [{"Content-Length": "2000001"}, {"Content-Length": "-1"},
    {"Content-Length": "9" * 100}, {"Content-Encoding": "gzip"}])
def test_bad_headers(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str]) -> None:
    install(monkeypatch, lambda req: httpx.Response(200, headers=headers, content=b""))
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.windows[0].reason in ("NEXUS_RESPONSE_TOO_LARGE", "NEXUS_SCHEMA_ERROR")


def test_missing_metrics_never_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    fixture.overrides["get_strategy_metrics"] = {"total_return_pct": KEY, "profit_factor": None, "status": KEY}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.status == "UNPROVEN"
    assert report.windows[0].metrics.return_nonpositive is None
    assert report.windows[0].metrics.profit_factor_at_most_one is None
    assert report.windows[0].metrics.not_qualified is None
    assert report.smallest_observed_failing_n_bars is None


@pytest.mark.parametrize("points", [[], [{"t": 1, "equity": 100}], [{"t": 2, "equity": 100}, {"t": 1, "equity": 90}],
    [{"t": 1, "equity": 0}, {"t": 2, "equity": 90}], [{"t": 1}, {"t": 2, "equity": 90}]])
def test_equity_descriptive_unavailable(monkeypatch: pytest.MonkeyPatch, points: Any) -> None:
    fixture = Fixture()
    fixture.overrides["get_strategy_equity"] = {"run_id": "bt-20", "points": points}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.windows[0].equity.observed_return_pct is None
    assert report.windows[0].equity.observed_max_drawdown_pct is None


def test_concurrent_and_cancel_release(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        entered = asyncio.Event()

        async def handler(req: httpx.Request) -> httpx.Response:
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError

        install(monkeypatch, handler)
        first = asyncio.create_task(compute.run_window_experiment(request()))
        await entered.wait()
        with pytest.raises(compute.NexusComputeError, match="^NEXUS_COMPUTE_BUSY$"):
            await compute.run_window_experiment(request())
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not compute._PROCESS_LOCK.locked()
        install(monkeypatch, lambda req: httpx.Response(502))
        assert (await compute.run_window_experiment(request())).status == "UNPROVEN"

    asyncio.run(scenario())


@pytest.mark.parametrize("state", ["queued", "running"])
def test_total_timeout_preserves_submission(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    fixture = Fixture()
    fixture.overrides["get_backtest_job"] = {"run_id": "bt-500", "status": state}
    install(monkeypatch, fixture)
    report = asyncio.run(compute.run_window_experiment(request(timeout_seconds=5)))
    assert report.windows[0].reason == "NEXUS_TIMEOUT"
    assert report.windows[0].run_id == "bt-500"
    assert report.windows[1].job_status == "not_started"
    assert 1 <= sum(c["name"] == "get_backtest_job" for c in fixture.calls) <= 4
    assert sum(c["name"] == "run_backtest" for c in fixture.calls) == 1
    assert not compute._PROCESS_LOCK.locked()


def test_duplicate_submission_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    fixture.overrides["run_backtest"] = {"run_id": "bt-500", "status": "queued"}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request()))
    assert report.status == "INCONSISTENT"
    assert report.windows[1].reason == "NEXUS_RUN_ID_MISMATCH"
    assert sum(c["name"] == "run_backtest" for c in fixture.calls) == 2


def test_positive_unbound_never_survived(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[500])))
    assert report.status == "UNPROVEN"
    assert report.smallest_observed_failing_n_bars is None
    assert report.baseline_survived is None


def test_partial_evidence_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()

    def handler(req: httpx.Request) -> httpx.Response:
        if json.loads(req.content)["name"] == "get_strategy_equity":
            raise httpx.ReadTimeout(KEY)
        return fixture(req)

    install(monkeypatch, handler)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    window = report.windows[0]
    assert window.errors == ["NEXUS_TIMEOUT"]
    assert window.metrics.total_return_pct == -1
    assert window.trades.binding == "matched"
    assert window.signal.trade_intent == "HOLD"
    assert window.equity.binding == "unavailable"


def test_mismatch_not_hidden_by_malformed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    fixture.overrides["get_strategy_equity"] = {"run_id": "bt-other", "points": "invalid"}
    install(monkeypatch, fixture)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.status == "INCONSISTENT"


@pytest.mark.parametrize("envelope", ["result", "data", "structuredContent", "plain"])
def test_envelopes_and_immediate_completion(monkeypatch: pytest.MonkeyPatch, envelope: str) -> None:
    fixture = Fixture()
    fixture.overrides["run_backtest"] = {"run_id": "bt-20", "status": "completed"}

    def handler(req: httpx.Request) -> httpx.Response:
        response = fixture(req)
        data = json.loads(response.json()["content"][0]["text"])
        return httpx.Response(200, json=data if envelope == "plain" else {envelope: data})

    install(monkeypatch, handler)
    fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(windows=[20])))
    assert report.windows[0].job_status == "completed"
    assert [c["name"] for c in fixture.calls][:2] == ["run_backtest", "get_backtest_job"]


def test_private_transport_run_cap_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = Fixture()
    install(monkeypatch, fixture)

    async def scenario() -> None:
        async with REAL_CLIENT(transport=httpx.MockTransport(fixture)) as http:
            client = compute._NexusComputeClient(http, KEY)
            for invalid in [19, 501, True, 20.0]:
                with pytest.raises(compute.NexusComputeError, match="^NEXUS_INVALID_REQUEST$"):
                    await client.run_backtest(invalid)
            for bars in [500, 250, 20]:
                await client.run_backtest(bars)
            with pytest.raises(compute.NexusComputeError, match="^NEXUS_RUN_LIMIT$"):
                await client.run_backtest(20)

    asyncio.run(scenario())
    assert len(fixture.calls) == 3


def test_network_guard_blocks_saved_clients() -> None:
    async def scenario() -> None:
        async with REAL_CLIENT(trust_env=False) as client:
            with pytest.raises(AssertionError, match="No real network allowed"):
                await client.get(nexus.BASE)

    asyncio.run(scenario())
    with httpx.Client(trust_env=False) as client:
        with pytest.raises(AssertionError, match="No real network allowed"):
            client.get(nexus.BASE)


@pytest.mark.parametrize("seconds,cap", [(5, 20), (30, 45), (60, 75)])
def test_hard_call_budget(monkeypatch: pytest.MonkeyPatch, seconds: int, cap: int) -> None:
    fixture = Fixture()
    fixture.overrides["get_backtest_job"] = {"run_id": "bt-500", "status": "running"}
    install(monkeypatch, fixture)
    intervals = fast_poll(monkeypatch)
    report = asyncio.run(compute.run_window_experiment(request(timeout_seconds=seconds)))
    assert len(fixture.calls) == cap
    assert all(interval == 1 for interval in intervals)
    assert report.status == "UNPROVEN"
    assert report.windows[0].reason == "NEXUS_CALL_LIMIT"
    assert report.windows[0].run_id == "bt-500"
    assert report.windows[1].job_status == "not_started"
    assert report.definitive_boundary_n_bars is None
    assert not compute._PROCESS_LOCK.locked()


def test_enabled_but_unconfirmed_never_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", "true")
    monkeypatch.setenv("NEXUS_API_KEY", KEY)
    forged = compute.WindowExperimentRequest.model_construct(confirm_compute=False)
    with pytest.raises(compute.NexusComputeError, match="^NEXUS_INVALID_REQUEST$"):
        asyncio.run(compute.run_window_experiment(forged))
