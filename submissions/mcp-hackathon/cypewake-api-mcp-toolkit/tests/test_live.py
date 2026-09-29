"""
test_live.py · smoke tests that need real internet access

Not collected by default (the pytest configuration runs offline tests only). To run them:

    pytest -m live -v

Intent: isolate the "depends on an external network" part explicitly, so a check that decays with upstream
never pretends to be a full pass the way v1 did.
"""

from __future__ import annotations

import asyncio

import pytest

import core

pytestmark = pytest.mark.live

PETSTORE = "https://petstore3.swagger.io/api/v3/openapi.json"
OPEN_METEO = "https://api.open-meteo.com"
FX = "https://api.frankfurter.app"


def test_petstore_spec_parses_with_auth_and_relative_base():
    d = core.parse_openapi_spec(PETSTORE)
    assert d["operation_count"] >= 15
    assert d["base_url"] == "https://petstore3.swagger.io/api/v3"
    assert {s["name"] for s in d["auth_schemes"]} >= {"api_key"}


def test_weather_api_returns_200_and_temperature():
    res = core.call_rest_api(
        OPEN_METEO, "/v1/forecast", "GET",
        {"latitude": 31.23, "longitude": 121.47, "current": "temperature_2m"},
    )
    assert res["status_code"] == 200
    assert "temperature_2m" in res["body_preview"]


def test_fx_api_returns_200_and_cny_rate():
    res = core.call_rest_api(FX, "/latest", "GET", {"from": "USD", "to": "CNY"})
    assert res["status_code"] == 200
    assert "CNY" in res["body_preview"]


def test_verify_api_reports_real_pass_fail_not_always_true():
    v = core.verify_api(PETSTORE, max_ops=8, timeout=8)
    assert v["verified"] == 8
    # Key point: the verdict must not be a tautological "everything reachable"
    assert v["passed"] < v["verified"], "Petstore's /pet endpoints require auth, so not everything should pass"
    statuses = {r["status"] for r in v["results"]}
    assert statuses & {"passed", "auth_required", "bad_request", "not_found"}


def test_registered_call_end_to_end(tmp_path):
    reg = core.Registry(tmp_path / "registry.json")
    reg.register("petstore", PETSTORE)
    res = reg.call("petstore", "findPetsByStatus", {"status": "available"})
    assert res["status_code"] == 200
    # body_preview is a truncated preview and may be partial JSON, so assert only on content traits
    assert '"id"' in res["body_preview"]


def test_generated_bundle_server_runs(tmp_path, monkeypatch):
    """The output is not merely code that looks right — FastMCP can actually load it."""
    from fastmcp import Client

    monkeypatch.chdir(tmp_path)
    core.generate_bundle(PETSTORE, "live-check")

    import importlib.util
    import sys

    path = tmp_path / "generated" / "live-check" / "server.py"
    spec = importlib.util.spec_from_file_location("live_check_server", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_check_server"] = mod
    spec.loader.exec_module(mod)

    async def names() -> list[str]:
        async with Client(mod.mcp) as c:
            return [t.name for t in await c.list_tools()]

    tool_names = asyncio.run(names())
    assert "getPetById" in tool_names
