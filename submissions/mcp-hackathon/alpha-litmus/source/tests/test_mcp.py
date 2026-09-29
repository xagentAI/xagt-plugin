import asyncio
import os
import subprocess
import sys
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

from app import provenance, transport
from app.certificates import content_hash, verify_report
from app.contracts import ChallengeRequest, Report
from app.demo import fixture
from app.mcp_server import ARGUMENTS, mcp
from app.main import app


def test_real_mcp_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS", raising=False)

    async def check() -> None:
        tools = await mcp.list_tools()
        assert {tool.name for tool in tools} == set(ARGUMENTS)
        assert len(tools) == 8
        assert "evaluate_strategy_release" in {tool.name for tool in tools}
        assert "replay_recorded_nexus_evidence" in {tool.name for tool in tools}
        assert "evaluate_live_nexus_candidate" in {tool.name for tool in tools}
        for tool in tools:
            assert tool.inputSchema["additionalProperties"] is False
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint == (tool.name != "run_nexus_window_stability")
            assert tool.annotations.destructiveHint is False
            if tool.name == "run_nexus_window_stability":
                assert tool.annotations.idempotentHint is False
                assert tool.annotations.openWorldHint is True
            if tool.name == "evaluate_strategy_release":
                assert tool.annotations.idempotentHint is True
                assert tool.annotations.openWorldHint is True
            if tool.name == "replay_recorded_nexus_evidence":
                assert tool.annotations.idempotentHint is True
                assert tool.annotations.openWorldHint is False
        result = await mcp.call_tool("get_demo_fixture", {"scenario": "shock"})
        assert "synthetic" in str(result)
        for name in ("challenge_nexus_strategy", "find_failure_boundary"):
            result = await mcp.call_tool(name, {"request": {"mode": "nexus"}})
            assert "nexus_validated" in str(result)
        report = await transport.run_challenge(ChallengeRequest(mode="nexus"))
        result = await mcp.call_tool("verify_failure_certificate", {"report": report.model_dump(mode="json")})
        assert "authenticity_verified" in str(result)

    asyncio.run(check())


@pytest.mark.parametrize("arguments", [
    {"scenario": "mixed", "secret": "never-echo"},
    {"scenario": 1}, {"scenario": "fragile"},
])
def test_strict_mcp_arguments(arguments: dict[str, object]) -> None:
    async def check() -> None:
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("get_demo_fixture", arguments)
    asyncio.run(check())


def test_mcp_nested_unknowns_and_no_coercion() -> None:
    async def check() -> None:
        for request in ({"mode": "nexus", "unknown": 1}, {"mode": "nexus", "bootstrap_iterations": "50"}):
            with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
                await mcp.call_tool("challenge_nexus_strategy", {"request": request})
    asyncio.run(check())


def test_mcp_reference_mode() -> None:
    async def check() -> None:
        result = await mcp.call_tool("challenge_nexus_strategy", {"request": {
            "research": fixture("shock").model_dump(mode="json"),
            "bootstrap_iterations": 50, "additional_cost_max_bps": 0,
        }})
        assert "synthetic_reference" in str(result)
    asyncio.run(check())


def test_mcp_capacity_and_size(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = transport.Admission(1)
    monkeypatch.setattr(transport, "admission", gate)

    async def check() -> None:
        async with gate.slot():
            with pytest.raises(ToolError, match="^CAPACITY_EXCEEDED$"):
                await mcp.call_tool("get_demo_fixture", {})
        with pytest.raises(ToolError, match="^BODY_TOO_LARGE$"):
            await mcp.call_tool("get_demo_fixture", {"scenario": "x" * transport.MAX_BODY_BYTES})
    asyncio.run(check())


@pytest.mark.parametrize("frame", [
    b'{"jsonrpc":"2.0","id":1,"method":"initialize","method":"never-echo"}\n',
    b'{"jsonrpc":"2.0","id":NaN,"method":"never-echo"}\n',
    b'{"never-echo":',
])
def test_stdio_rejects_malformed_frames(frame: bytes) -> None:
    env = dict(os.environ)
    env["ALPHALITMUS_ENV"] = "test"
    result = subprocess.run(
        [sys.executable, "-m", "app.mcp_server"], input=frame,
        capture_output=True, timeout=15, check=False, env=env,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.returncode == 0
    assert b"never-echo" not in result.stdout + result.stderr
    assert result.stdout == b""


def test_mcp_exception_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: object) -> None:
        raise RuntimeError("secret-never-echo")
    monkeypatch.setattr(transport, "challenge", broken)

    async def check() -> None:
        with pytest.raises(ToolError, match="^TOOL_FAILED$"):
            await mcp.call_tool("challenge_nexus_strategy", {"request": {"mode": "nexus"}})
    asyncio.run(check())


def test_stdio_subprocess_discovery_and_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENV", "test")
    async def check() -> None:
        env = {key: value for key, value in os.environ.items()
               if key not in ("NEXUS_API_KEY", "ALPHALITMUS_ENABLE_NEXUS", "ALPHALITMUS_ENV")}
        env["ALPHALITMUS_ENABLE_NEXUS"] = "false"
        env["ALPHALITMUS_ENABLE_NEXUS_BACKTEST"] = "false"
        env["ALPHALITMUS_COMMIT"] = provenance.commit_state()["commit"]
        parameters = StdioServerParameters(
            command=sys.executable, args=["-m", "app.mcp_server"], env=env,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        with anyio.fail_after(30):
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {tool.name for tool in tools.tools} == set(ARGUMENTS)
                    for scenario in ("mixed", "shock"):
                        result = await session.call_tool("get_demo_fixture", {"scenario": scenario})
                        assert not result.isError
                        assert result.structuredContent is not None
                        report = Report.model_validate(result.structuredContent)
                        assert verify_report(report).valid
                        assert report.request.research == fixture(scenario)
                        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
                            response = await client.get("/v1/demo/" + scenario)
                        assert response.status_code == 200
                        rest_report = Report.model_validate(response.json())
                        assert content_hash(report) == content_hash(rest_report)
                        assert report.canonical_report_hash == rest_report.canonical_report_hash
                    rejected = await session.call_tool("get_demo_fixture", {"secret": "never-echo"})
                    assert rejected.isError
                    assert "never-echo" not in str(rejected)
    asyncio.run(check())


@pytest.mark.parametrize("commit", ["", "0" * 40, "A" * 40, "a" * 40])
def test_production_stdio_startup(commit: str) -> None:
    env = dict(os.environ)
    env.update(ALPHALITMUS_ENV="production", ALPHALITMUS_COMMIT=commit,
               TRADEPROOF_COMMIT="b" * 40)
    result = subprocess.run(
        [sys.executable, "-m", "app.mcp_server"], input=b"", capture_output=True,
        timeout=15, check=False, env=env, cwd=Path(__file__).resolve().parents[1],
    )
    assert (result.returncode == 0) == (commit == "a" * 40)
    assert result.stdout == b""


def test_programmatic_stdio_validates_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENV", "production")
    monkeypatch.delenv("ALPHALITMUS_COMMIT", raising=False)
    provenance._snapshot.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Production requires"):
            asyncio.run(mcp.run_stdio_async())
    finally:
        provenance._snapshot.cache_clear()
