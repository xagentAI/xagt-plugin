"""Offline transport coverage for the explicitly opted-in compute surface."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from app.main import app
from app.mcp_server import mcp
from app import transport
from app.nexus_compute import NexusComputeError, WindowExperimentReport, WindowExperimentRequest


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ALPHALITMUS_ENV", "test")
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", raising=False)
    with TestClient(app, raise_server_exceptions=False) as result:
        yield result


@pytest.mark.parametrize("payload", [
    {}, {"confirm_compute": False}, {"confirm_compute": "true"},
    {"confirm_compute": 1}, {"confirm_compute": True, "secret": "never-echo"},
    {"confirm_compute": True, "windows": [19]},
    {"confirm_compute": True, "windows": [501]},
    {"confirm_compute": True, "windows": [20, 30, 40, 50]},
    {"confirm_compute": True, "windows": [100, 20]},
    {"confirm_compute": True, "windows": [100, 100]},
    {"confirm_compute": True, "timeout_seconds": "30"},
])
def test_compute_rejects_invalid_requests(client: TestClient, payload: dict[str, object]) -> None:
    response = client.post("/v1/nexus/window-stability", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "INVALID_REQUEST"}

    async def check() -> None:
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("run_nexus_window_stability", {"request": payload})

    asyncio.run(check())


@pytest.mark.parametrize("arguments", [
    {}, {"confirm_compute": True}, {"request": {}, "secret": "never-echo"},
])
def test_compute_mcp_requires_strict_wrapper(arguments: dict[str, object]) -> None:
    async def check() -> None:
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("run_nexus_window_stability", arguments)

    asyncio.run(check())


def test_compute_json_boundary(client: TestClient) -> None:
    response = client.post(
        "/v1/nexus/window-stability",
        content='{"confirm_compute":true,"confirm_compute":false}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "INVALID_JSON"}


def test_disabled_compute_is_normal_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_API_KEY", "never-echo")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")
    response = client.post("/v1/nexus/window-stability", json={"confirm_compute": True})
    assert response.status_code == 200
    report = WindowExperimentReport.model_validate(response.json())
    assert report.status == "UNPROVEN"
    assert all(w.reason == "NEXUS_COMPUTE_DISABLED" and w.run_id is None for w in report.windows)
    assert "never-echo" not in response.text

    async def check() -> None:
        result = await mcp.call_tool("run_nexus_window_stability", {"request": {"confirm_compute": True}})
        assert "NEXUS_COMPUTE_DISABLED" in str(result)
        assert "never-echo" not in str(result)

    asyncio.run(check())


def test_both_transports_call_same_core(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[WindowExperimentRequest] = []
    expected = WindowExperimentReport.model_validate({
        "baseline_n_bars": 100, "windows": [{"n_bars": 100}],
    })

    async def core(request: WindowExperimentRequest) -> WindowExperimentReport:
        calls.append(request)
        return expected

    monkeypatch.setattr(transport, "run_window_experiment", core)
    payload = {"confirm_compute": True, "windows": [100]}
    response = client.post("/v1/nexus/window-stability", json=payload)
    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")
    asyncio.run(mcp.call_tool("run_nexus_window_stability", {"request": payload}))
    assert calls == [WindowExperimentRequest.model_validate(payload)] * 2


def test_missing_key_is_normal_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "true")
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS_BACKTEST", "true")
    response = client.post("/v1/nexus/window-stability", json={"confirm_compute": True})
    assert response.status_code == 200
    report = WindowExperimentReport.model_validate(response.json())
    assert report.status == "UNPROVEN"
    assert all(w.reason == "NEXUS_NOT_CONFIGURED" and w.run_id is None for w in report.windows)


@pytest.mark.parametrize("failure,status,code", [
    (NexusComputeError("NEXUS_COMPUTE_BUSY"), 429, "NEXUS_COMPUTE_BUSY"),
    (NexusComputeError("NEXUS_INVALID_REQUEST"), 422, "NEXUS_INVALID_REQUEST"),
    (NexusComputeError("NEXUS_TIMEOUT"), 504, "NEXUS_TIMEOUT"),
    (RuntimeError("never-echo"), 500, "INTERNAL_ERROR"),
])
def test_compute_errors_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failure: Exception, status: int, code: str,
) -> None:
    async def core(request: WindowExperimentRequest) -> WindowExperimentReport:
        raise failure

    monkeypatch.setattr(transport, "run_window_experiment", core)
    response = client.post("/v1/nexus/window-stability", json={"confirm_compute": True})
    assert response.status_code == status
    assert response.json() == {"detail": code}

    async def check() -> None:
        public = "TOOL_FAILED" if status == 500 else code
        with pytest.raises(ToolError, match=f"^{public}$"):
            await mcp.call_tool("run_nexus_window_stability", {"request": {"confirm_compute": True}})

    asyncio.run(check())


def test_compute_uses_shared_admission(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = transport.Admission(1)
    monkeypatch.setattr(transport, "admission", gate)

    async def check() -> None:
        async with gate.slot():
            response = client.post("/v1/nexus/window-stability", json={"confirm_compute": True})
            assert response.status_code == 429
            assert response.json() == {"detail": "CAPACITY_EXCEEDED"}
            with pytest.raises(ToolError, match="^CAPACITY_EXCEEDED$"):
                await mcp.call_tool("run_nexus_window_stability", {"request": {"confirm_compute": True}})

    asyncio.run(check())
