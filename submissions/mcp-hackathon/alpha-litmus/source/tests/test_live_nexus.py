"""Fixed Candidate v1 live Nexus security, cache, and transport tests."""

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import app.live_nexus as live
from app.main import app
from app.mcp_server import ARGUMENTS, LiveNexusArguments, mcp
from app.nexus import nexus_api_key
from app.transport import nexus_evidence


class Clock:
    def __init__(self) -> None:
        self.mono = 100.0
        self.wall = datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc)

    def tick(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


def evidence(clock: Clock) -> dict[str, dict]:
    fetched = clock.wall.isoformat()
    surfaces = {
        "signal": {"symbol": "BTC/USDT", "trade_intent": "HOLD", "timestamp": clock.wall.timestamp()},
        "metrics": {
            "sharpe_ratio": 0.4897,
            "trading_period_days": 90,
            "estimated_aum_usdt": 100000,
            "profit_factor": 1.0178,
            "max_drawdown": "3.50%",
            "total_return_pct": 1.0221,
            "win_rate_pct": 41.43,
            "trade_count": 70,
            "status": "NOT_QUALIFIED",
        },
        "equity": {
            "run_id": "bt-7544746ff32d",
            "points": [{"t": 1, "equity": 100.0}, {"t": 2, "equity": 101.022085}],
        },
        "trades": {
            "run_id": "bt-7544746ff32d",
            "trades": [
                {"symbol": "BTC/USDT", "pnl": 5.0},
                {"symbol": "ETH/USDT", "pnl": -2.0},
            ],
        },
    }
    return {
        label: {"status": "received", "tool": f"get_strategy_{label}", "fetched_at": fetched, "data": data}
        for label, data in surfaces.items()
    }


@pytest.fixture(autouse=True)
def live_state(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    live.reset_live_nexus_state()
    monkeypatch.setenv("ALPHALITMUS_ENABLE_LIVE_NEXUS", "true")
    monkeypatch.setenv("NEXUS_API_KEY", "nxk_" + "a" * 24)
    monkeypatch.delenv("NEXUS_API_KEY_FILE", raising=False)
    monkeypatch.setattr(live, "_monotonic", lambda: clock.mono)
    monkeypatch.setattr(live, "_utc_now", lambda: clock.wall)
    return clock


def test_live_success_fixed_identity_and_verified_gate(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    calls: list[str] = []

    async def fake_read(symbol: str) -> dict:
        calls.append(symbol)
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    result = asyncio.run(live.run_live_nexus_candidate())
    assert calls == ["BTC/USDT"]
    assert result.live is True and result.historical is False
    assert result.no_execution is True and result.recorded_fallback_used is False
    assert result.cache_status == "miss"
    assert result.strategy_id == "str_b840280ce037"
    assert result.release_gate.source_report_verified is True
    assert result.release_gate.source_verdict == "INCONSISTENT"
    assert result.release_gate.decision == "BLOCK_DEPLOYMENT"
    checks = {item.code: item.status for item in result.release_gate.report.reconciliation.result.results}  # type: ignore[union-attr]
    assert checks["TRADE_SYMBOLS"] == "MISMATCH"


def test_cache_hit_is_disclosed_and_zero_network(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    calls = 0

    async def fake_read(symbol: str) -> dict:
        nonlocal calls
        calls += 1
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    first = asyncio.run(live.run_live_nexus_candidate())
    live_state.tick(9)
    second = asyncio.run(live.run_live_nexus_candidate())
    assert calls == 1
    assert first.cache_status == "miss"
    assert second.cache_status == "hit"
    assert second.cache_age_seconds == 9
    assert second.release_gate.model_dump(mode="json") == first.release_gate.model_dump(mode="json")


def test_cache_expiry_refreshes(monkeypatch: pytest.MonkeyPatch, live_state: Clock) -> None:
    calls = 0

    async def fake_read(symbol: str) -> dict:
        nonlocal calls
        calls += 1
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    asyncio.run(live.run_live_nexus_candidate())
    live_state.tick(61)
    refreshed = asyncio.run(live.run_live_nexus_candidate())
    assert calls == 2
    assert refreshed.cache_status == "miss"


def test_disabled_fails_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_LIVE_NEXUS", "false")

    async def forbidden(symbol: str) -> dict:
        raise AssertionError("network attempted")

    monkeypatch.setattr(live, "read_nexus", forbidden)
    with pytest.raises(live.LiveNexusError, match="^LIVE_NEXUS_DISABLED$"):
        asyncio.run(live.run_live_nexus_candidate())


def test_partial_upstream_never_uses_recorded_fallback(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    partial = evidence(live_state)
    partial["metrics"] = {"status": "unavailable", "reason": "NEXUS_TIMEOUT"}

    async def fake_read(symbol: str) -> dict:
        return partial

    monkeypatch.setattr(live, "read_nexus", fake_read)
    with pytest.raises(live.LiveNexusError, match="^LIVE_NEXUS_UNAVAILABLE$"):
        asyncio.run(live.run_live_nexus_candidate())


def test_circuit_opens_after_three_failures(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    calls = 0

    async def fail(symbol: str) -> dict:
        nonlocal calls
        calls += 1
        return {label: {"status": "unavailable"} for label in live.SURFACES}

    monkeypatch.setattr(live, "read_nexus", fail)
    for _ in range(3):
        with pytest.raises(live.LiveNexusError, match="^LIVE_NEXUS_UNAVAILABLE$"):
            asyncio.run(live.run_live_nexus_candidate())
        live_state.tick(11)
    with pytest.raises(live.LiveNexusError, match="^LIVE_NEXUS_CIRCUIT_OPEN$"):
        asyncio.run(live.run_live_nexus_candidate())
    assert calls == 3


def test_global_request_limit_bounds_cache_hits(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    async def fake_read(symbol: str) -> dict:
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    asyncio.run(live.run_live_nexus_candidate())
    for _ in range(29):
        asyncio.run(live.run_live_nexus_candidate())
    with pytest.raises(live.LiveNexusError, match="^LIVE_NEXUS_RATE_LIMITED$"):
        asyncio.run(live.run_live_nexus_candidate())


def test_cancelled_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled(symbol: str) -> dict:
        raise asyncio.CancelledError

    monkeypatch.setattr(live, "read_nexus", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(live.run_live_nexus_candidate())


def test_key_file_is_bounded_and_not_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = "nxk_" + "b" * 24
    path = tmp_path / "nexus-key"
    path.write_text(key + "\n", encoding="utf-8")
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    monkeypatch.setenv("NEXUS_API_KEY_FILE", str(path))
    assert nexus_api_key() == key
    path.write_text("x" * 513, encoding="utf-8")
    assert nexus_api_key() == ""


def test_rest_disabled_and_strict_no_query_or_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_LIVE_NEXUS", "false")
    with TestClient(app, raise_server_exceptions=False) as client:
        disabled = client.get("/v1/nexus/live/candidate-v1")
        query = client.get("/v1/nexus/live/candidate-v1?symbol=ETH%2FUSDT")
        body = client.request(
            "GET", "/v1/nexus/live/candidate-v1", content=b"{}", headers={"content-type": "application/json"}
        )
    assert disabled.status_code == 503 and disabled.json() == {"detail": "LIVE_NEXUS_DISABLED"}
    assert query.status_code == 400 and query.json() == {"detail": "QUERY_PARAMETERS_NOT_ALLOWED"}
    assert body.status_code == 400 and body.json() == {"detail": "BODY_NOT_ALLOWED"}


def test_rest_mcp_parity(monkeypatch: pytest.MonkeyPatch, live_state: Clock) -> None:
    async def fake_read(symbol: str) -> dict:
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/nexus/live/candidate-v1")
    assert response.status_code == 200
    rest = response.json()

    async def call() -> dict:
        result = await mcp.call_tool("evaluate_live_nexus_candidate", {})
        items = list(result) if isinstance(result, (list, tuple)) else [result]
        for item in items:
            if isinstance(item, dict) and item.get("live_schema_version"):
                return item
            text = getattr(item, "text", None)
            if text:
                decoded = json.loads(text)
                if isinstance(decoded, dict) and decoded.get("live_schema_version"):
                    return decoded
        raise AssertionError("live MCP payload missing")

    mcp_result = asyncio.run(call())
    assert mcp_result["release_gate"] == rest["release_gate"]
    assert mcp_result["upstream_fetched_at"] == rest["upstream_fetched_at"]
    assert mcp_result["cache_status"] == "hit"


def test_mcp_contract_and_annotations() -> None:
    assert ARGUMENTS["evaluate_live_nexus_candidate"] is LiveNexusArguments

    async def check() -> None:
        tools = await mcp.list_tools()
        item = next(tool for tool in tools if tool.name == "evaluate_live_nexus_candidate")
        assert item.annotations is not None
        assert item.annotations.readOnlyHint is True
        assert item.annotations.destructiveHint is False
        assert item.annotations.idempotentHint is False
        assert item.annotations.openWorldHint is True
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("evaluate_live_nexus_candidate", {"symbol": "ETH/USDT"})

    asyncio.run(check())


def test_openapi_has_strict_live_schema() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    route = schema["paths"]["/v1/nexus/live/candidate-v1"]["get"]
    ref = route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/LiveNexusResult")


def test_live_flag_does_not_enable_arbitrary_nexus_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_LIVE_NEXUS", "true")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "false")
    result = asyncio.run(nexus_evidence("ETH/USDT"))
    assert all(item == {"status": "unavailable", "reason": "NEXUS_DISABLED"} for item in result.values())


def test_secret_absent_from_live_serialization(
    monkeypatch: pytest.MonkeyPatch, live_state: Clock,
) -> None:
    secret = "nxk_" + "supersecret123456789012"
    monkeypatch.setenv("NEXUS_API_KEY", secret)

    async def fake_read(symbol: str) -> dict:
        return evidence(live_state)

    monkeypatch.setattr(live, "read_nexus", fake_read)
    result = asyncio.run(live.run_live_nexus_candidate())
    serialized = result.model_dump_json()
    assert secret not in serialized
    assert "NEXUS_API_KEY" not in serialized


def test_dashboard_exposes_fail_closed_live_pulse() -> None:
    html = TestClient(app).get("/").text
    assert 'id="run-live-nexus"' in html
    assert "$('hero-live').addEventListener('click', loadLive)" in html
    assert 'id="live-nexus"' in html
    assert 'id="live-details"' in html
    assert "fetch('/v1/nexus/live/candidate-v1'" in html
    assert "result.recorded_fallback_used !== false" in html
    assert "currentGate.source_report_verified !== true" in html
    assert "if (!liveResult || !object(liveResult.release_gate)" in html
    assert "'READY TO CHECK', 'Not checked yet'" in html
    assert "'CHECKING', 'Pending'" in html
    assert "revealResult('live-nexus')" in html
    assert "Unavailable / awaiting live Nexus check" not in html
    assert ".innerHTML" not in html
