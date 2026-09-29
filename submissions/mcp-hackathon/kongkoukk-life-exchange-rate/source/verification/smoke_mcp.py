"""Exercise the deployed ASGI mount using the real MCP v2 HTTP client.

Run from the repository root: uv run python verification/smoke_mcp.py --live-fx
Without --live-fx, the deterministic chain is offline and positive FX/RSS calls
are explicitly reported as skipped. The server is stopped on every exit path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import version

import httpx
from mcp import Client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "source"))

from life_exchange_rate.providers.fixtures import demo_profile

EXPECTED_TOOLS = {
    "get_macro_events", "get_official_macro_headlines", "get_live_fx_event",
    "get_policy_rate_event", "get_energy_event", "rank_events_for_user",
    "translate_event_to_life", "convert_to_life_units", "compare_event_scenarios",
}


def diagnostic(exc: BaseException) -> str:
    detail = "".join(traceback.format_exception(exc))
    return re.sub(r"(?i)(api[_-]?key|access[_-]?token|password)=([^&\s]+)", r"\1=[redacted]", detail)


def unpack(result):
    if result.is_error:
        raise AssertionError(f"MCP tool returned an error: {result.content}")
    if result.structured_content is None:
        raise AssertionError("Expected structured MCP output")
    value = result.structured_content
    return value["result"] if set(value) == {"result"} else value


async def exercise(endpoint: str, live_fx: bool):
    profile = demo_profile().model_dump(mode="json")
    modes = []
    evidence = None
    for mode, expected_protocol in (("auto", "2026-07-28"), ("legacy", "2025-11-25")):
        calls = []
        negative_checks = []
        async with Client(endpoint, mode=mode, read_timeout_seconds=45) as client:
            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert names == EXPECTED_TOOLS, names
            assert client.protocol_version == expected_protocol

            async def call(name, arguments):
                print(f"MCP smoke [{mode}]: {name}", flush=True)
                result = unpack(await client.call_tool(name, arguments))
                calls.append({"tool": name, "status": "passed"})
                return result

            events = await call("get_macro_events", {"mode": "demo"})
            policy = await call("get_policy_rate_event", {"mode": "fixture"})
            energy = await call("get_energy_event", {"mode": "fixture"})
            assert policy["provenance"]["source_type"] == "synthetic_fixture"
            assert energy["provenance"]["source_type"] == "synthetic_fixture"
            fixture_radar = await call("rank_events_for_user", {"events": events, "profile": profile})
            fixture_impact = await call("translate_event_to_life", {"event": events[0], "profile": profile})
            assert fixture_impact["direct_effect_home"] == 1739.13
            assert fixture_impact["work_hours_equivalent"] == 8.7
            assert fixture_impact["calculation_trace"]
            conversion = await call("convert_to_life_units", {
                "amount": fixture_impact["direct_effect_home"], "currency": "SEK", "profile": profile,
            })
            assert conversion["work_hours_equivalent"] == 8.7
            scenarios = await call("compare_event_scenarios", {
                "event": events[2], "profile": profile,
                "assumptions": {"interest_rate_pass_through": 0, "oil_to_fuel_pass_through": 0},
            })
            assert len(scenarios) == 3
            assert all(item["result"]["direct_effect_home"] == 0 for item in scenarios)

            headline = {"headline_id": "unquantified-smoke-input", "title": "A headline without observations", "requires_quantification": True}
            current_evidence = {
                "event_mode": "synthetic_fixture",
                "profile_origin": "Explicit synthetic judging profile; prices and income are inputs, not claimed market observations.",
                "profile": profile,
                "event": events[0],
                "ranked_radar": fixture_radar,
                "impact": fixture_impact,
                "life_unit_conversion": conversion,
            }
            if live_fx:
                headlines = await call("get_official_macro_headlines", {"source": "fed", "limit": 1})
                assert headlines and all(item["requires_quantification"] for item in headlines)
                headline = headlines[0]
                observed = await call("get_live_fx_event", {"base_currency": "SEK", "quote_currency": "JPY", "lookback_days": 7})
                assert observed["confidence"] == "observed"
                assert observed["provenance"]["source_url"]
                assert observed["window_start"] <= observed["window_end"]
                radar = await call("rank_events_for_user", {"events": [observed, policy, energy], "profile": profile})
                impact = await call("translate_event_to_life", {"event": observed, "profile": profile})
                expected_money = round(profile["travel_budget_home"] * (observed["old_value"] / observed["new_value"] - 1), 2)
                assert impact["direct_effect_home"] == expected_money
                assert impact["calculation_trace"]
                assert impact["event_provenance"] == observed["provenance"]
                units = await call("convert_to_life_units", {"amount": impact["direct_effect_home"], "currency": "SEK", "profile": profile})
                current_evidence.update({
                    "event_mode": "live_official_observations",
                    "separately_fetched_official_headline": headline,
                    "headline_relationship": "Shown to test the headline boundary; no causal link to the FX move is asserted. Only the numeric FX observations drive this calculation.",
                    "event": observed, "ranked_radar": radar, "impact": impact, "life_unit_conversion": units,
                })
            else:
                for name in ("get_official_macro_headlines", "get_live_fx_event"):
                    calls.append({"tool": name, "status": "skipped", "reason": "Pass --live-fx to exercise live positive calls."})

            invalid = [
                ("get_macro_events", {"mode": "invent"}, "unsupported event mode"),
                ("get_official_macro_headlines", {"source": "untrusted"}, "unknown headline source"),
                ("get_live_fx_event", {"base_currency": "SEK", "quote_currency": "SEK"}, "identical FX currencies"),
                ("get_energy_event", {"lookback_days": 366}, "out-of-range lookback"),
                ("translate_event_to_life", {"event": headline, "profile": profile}, "headline lacks numeric event values"),
                ("convert_to_life_units", {"amount": 100, "currency": "USD", "profile": profile}, "conversion currency mismatch"),
                ("compare_event_scenarios", {"event": events[0], "profile": profile, "mild_multiplier": 0}, "invalid scenario multiplier"),
            ]
            for name, arguments, label in invalid:
                result = await client.call_tool(name, arguments)
                assert result.is_error, label
                negative_checks.append({"check": label, "status": "rejected_as_expected"})
            modes.append({
                "mode": mode,
                "protocol_version": client.protocol_version,
                "server_info": client.server_info.model_dump(mode="json") if client.server_info else None,
                "tool_names": sorted(names),
                "calls": calls,
                "negative_checks": negative_checks,
            })
            if evidence is None:
                evidence = current_evidence
    return modes, evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-fx", action="store_true", help="Exercise live official RSS and ECB-filtered FX and save the observed end-to-end chain")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "verification")
    args = parser.parse_args()
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.update({"PUBLIC_BASE_URL": base_url, "PYTHONDONTWRITEBYTECODE": "1"})
    output = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "sdk_version": version("mcp"),
        "transport": "Streamable HTTP over a real Uvicorn subprocess on loopback",
        "endpoint": base_url + "/mcp/",
        "live_positive_calls": args.live_fx,
    }
    evidence = None
    failure = None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as server_log:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "life_exchange_rate.main:app", "--app-dir", "source", "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
            cwd=PROJECT_ROOT, env=environment, stdout=server_log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(base_url=base_url, timeout=2, trust_env=False) as http:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Uvicorn exited before startup completed")
                    try:
                        health = http.get("/health")
                        if health.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Uvicorn startup timed out")
                proof = http.get("/.well-known/xagent-verification.json").json()
                assert health.json()["commit"] == proof["commit"]
                assert health.json()["version"] == proof["version"]
                assert proof["mcp"] == base_url + "/mcp/"
                output.update({"health": health.json(), "verification": proof})
            output["modes"], evidence = asyncio.run(exercise(base_url + "/mcp/", args.live_fx))
            output["status"] = "passed" if args.live_fx else "passed_fixture_flow_live_calls_skipped"
        except Exception as exc:
            details = diagnostic(exc)
            output.update({"status": "failed", "error": str(exc), "error_traceback": details})
            print(details, file=sys.stderr, flush=True)
            failure = exc
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            output["server_stopped"] = process.poll() is not None
    (args.output_dir / "mcp-smoke.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if evidence is not None:
        evidence.update({"recorded_at": output["recorded_at"], "review_commit": output["health"]["commit"]})
    else:
        evidence = {"status": "not_generated", "recorded_at": output["recorded_at"], "reason": "The smoke run failed before completing the end-to-end chain; no live result is claimed."}
    (args.output_dir / "end-to-end-demo.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "sdk_version": output["sdk_version"], "output_dir": str(args.output_dir.resolve())}))
    if failure is not None:
        raise SystemExit(f"MCP smoke failed: {failure}")


if __name__ == "__main__":
    main()
