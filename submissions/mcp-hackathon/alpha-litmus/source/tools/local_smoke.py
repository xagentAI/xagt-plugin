"""Offline REST, verifier, MCP stdio, and loopback TCP smoke checks."""

import asyncio
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import anyio
import httpx
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app import main as rest, mcp_server, provenance
from app.certificates import content_hash, verify_report
from app.contracts import Report, Verification

ROOT = Path(__file__).resolve().parents[1]


def offline_environment(temporary: Path) -> dict[str, str]:
    """Allow only OS essentials, never inherited service credentials or proxies."""
    allowed = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        ALPHALITMUS_ENABLE_NEXUS="false", ALPHALITMUS_ENABLE_LIVE_NEXUS="false",
        ALPHALITMUS_ENV="test",
        ALPHALITMUS_ENABLE_NEXUS_BACKTEST="false",
        ALPHALITMUS_COMMIT="local-dev", PYTHONDONTWRITEBYTECODE="1",
        TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary),
        HOME=str(temporary), USERPROFILE=str(temporary),
    )
    return env


def tamper_report(report: Report) -> Report:
    damaged = report.model_copy(deep=True)
    assert damaged.test_matrix
    damaged.test_matrix[0].reason += " [local smoke tamper]"
    return damaged


async def check_mcp(report: Report, env: dict[str, str], temporary: Path) -> dict[str, object]:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-B", "-m", "app.mcp_server"],
        cwd=str(ROOT), env=env,
    )
    with (temporary / "mcp-stderr.txt").open("w", encoding="utf-8") as errors:
        with anyio.fail_after(60):
            async with stdio_client(parameters, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = sorted(tool.name for tool in tools.tools)
                    assert len(names) == 8
                    assert set(names) == set(mcp_server.ARGUMENTS)
                    assert "evaluate_strategy_release" in names
                    assert "replay_recorded_nexus_evidence" in names
                    assert "evaluate_live_nexus_candidate" in names
                    for tool in tools.tools:
                        assert tool.annotations is not None
                        assert tool.annotations.readOnlyHint == (tool.name != "run_nexus_window_stability")
                        assert tool.annotations.destructiveHint is False
                        if tool.name == "run_nexus_window_stability":
                            assert tool.annotations.idempotentHint is False
                            assert tool.annotations.openWorldHint is True
                        if tool.name == "replay_recorded_nexus_evidence":
                            assert tool.annotations.readOnlyHint is True
                            assert tool.annotations.idempotentHint is True
                            assert tool.annotations.openWorldHint is False
                    result = await session.call_tool("get_demo_fixture", {"scenario": "mixed"})
                    assert not result.isError and result.structuredContent is not None
                    actual = Report.model_validate(result.structuredContent)
                    assert verify_report(actual).valid
                    assert content_hash(actual) == content_hash(report)
                    assert actual.canonical_report_hash == report.canonical_report_hash
                    assert actual.evidence_classification == "synthetic_reference"
                    assert actual.verdict == report.verdict
                    assert actual.no_execution and not actual.nexus_validated
                    return {
                        "tools": names, "canonical_report_hash": actual.canonical_report_hash,
                        "hash_equivalent": True, "classification": actual.evidence_classification,
                        "verdict": actual.verdict,
                    }


def check_tcp(env: dict[str, str]) -> dict[str, object]:
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
    except OSError:
        return {"status": "skipped", "reason": "LOOPBACK_BIND_UNAVAILABLE"}
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--no-access-log", "--log-level", "critical"],
        cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        with httpx.Client(trust_env=False, timeout=1) as client:
            while time.monotonic() < deadline:
                assert process.poll() is None, "TCP_STARTUP_FAILED"
                try:
                    response = client.get(f"http://127.0.0.1:{port}/health")
                except httpx.TransportError:
                    time.sleep(0.1)
                    continue
                assert response.status_code == 200
                health = rest.Health.model_validate(response.json())
                assert health.status == "ok" and health.service == "alpha-litmus"
                assert health.no_execution
                assert health.commit == provenance.commit_state()["commit"]
                return {"status": "passed", "http_status": 200, "service": health.service}
        raise AssertionError("TCP_STARTUP_TIMEOUT")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_smoke() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix=".local-smoke-", dir=ROOT) as directory:
        temporary = Path(directory)
        env = offline_environment(temporary)
        with patch.dict(os.environ, env, clear=True):
            provenance._snapshot.cache_clear()
            try:
                with TestClient(rest.app) as client:
                    health_response = client.get("/health")
                    capabilities_response = client.get("/v1/capabilities")
                    proof_response = client.get("/.well-known/xagent-verification.json")
                    assert all(response.status_code == 200 for response in (
                        health_response, capabilities_response, proof_response,
                    ))
                    health = rest.Health.model_validate(health_response.json())
                    capabilities = rest.Capabilities.model_validate(capabilities_response.json())
                    proof = rest.Proof.model_validate(proof_response.json())
                    assert health.service == proof.slug == "alpha-litmus"
                    assert capabilities.name == "AlphaLitmus"
                    assert health.commit == proof.commit
                    assert health.commit_reviewable == proof.commit_reviewable
                    assert health.provenance_basis == proof.provenance_basis
                    assert health.no_execution and not capabilities.nexus_enabled
                    assert capabilities.execution == "paper_only"
                    assert capabilities.side_effects == ["opt_in_nexus_backtest_compute"]
                    assert set(capabilities.tools) == set(mcp_server.ARGUMENTS)
                    response = client.get("/v1/demo/mixed")
                    assert response.status_code == 200
                    report = Report.model_validate(response.json())
                    assert report.analysis is not None and report.mode == "reference"
                    assert report.evidence_classification == "synthetic_reference"
                    assert report.no_execution and not report.nexus_validated
                    assert report.provenance.commit == health.commit
                    checked = client.post("/v1/verify-report", json=report.model_dump(mode="json"))
                    assert checked.status_code == 200
                    assert Verification.model_validate(checked.json()).valid

                cli: dict[str, object] = {}
                for label, value, expected in (
                    ("synthetic", report, 0), ("tampered", tamper_report(report), 1),
                ):
                    # Smoke-only artifacts stay under the temporary directory so a
                    # fresh clone with no ignored reports/ directory still passes.
                    path = temporary / f"alphalitmus-{label}-report.json"
                    path.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, "-B", "-m", "app.verify", str(path)],
                        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60, check=False,
                    )
                    assert result.returncode == expected, "UNEXPECTED_VERIFIER_EXIT"
                    assert not result.stderr, "UNEXPECTED_VERIFIER_STDERR"
                    verification = Verification.model_validate_json(result.stdout)
                    assert verification.valid == (expected == 0)
                    assert not verification.authenticity_verified
                    if expected:
                        assert "CONTENT_HASH_MISMATCH" in verification.errors
                    cli[label] = {"exit": result.returncode, "stdout": result.stdout}

                return {
                    "python": platform.python_version(), "imports": ["app.main", "app.mcp_server"],
                    "rest": {"lifespan": "passed", "service": health.service,
                             "proof_slug": proof.slug, "commit_consistent": True,
                             "nexus_enabled": capabilities.nexus_enabled, "execution": capabilities.execution},
                    "report": {"canonical_report_hash": report.canonical_report_hash,
                               "classification": report.evidence_classification, "verdict": report.verdict},
                    "cli": cli, "mcp": asyncio.run(check_mcp(report, env, temporary)),
                    "tcp": check_tcp(env), "live_requests": False,
                }
            finally:
                provenance._snapshot.cache_clear()


def main() -> int:
    try:
        result = run_smoke()
    except Exception:
        # Do not leak subprocess diagnostics, environment values, or local paths.
        print(json.dumps({"status": "failed", "error": "LOCAL_SMOKE_FAILED"}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
