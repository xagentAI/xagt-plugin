"""Offline provenance trust-boundary and public transport regressions."""

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from app import provenance
from app.certificates import content_hash, verify_report
from app.contracts import ChallengeRequest, Provenance
from app.lab import challenge
from app.main import app
from app.mcp_server import mcp

SHA = "0123456789abcdef" * 2 + "01234567"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ALPHALITMUS_ENABLE_NEXUS", "false")
    monkeypatch.setenv("ALPHALITMUS_ENV", "test")
    monkeypatch.delenv("ALPHALITMUS_COMMIT", raising=False)
    provenance._snapshot.cache_clear()
    yield
    provenance._snapshot.cache_clear()


@pytest.mark.parametrize("commit", [SHA, "a" * 40, "0" * 39 + "1"])
def test_valid_reviewable(commit: str) -> None:
    value = Provenance(commit=commit, commit_reviewable=True)
    assert Provenance.model_validate_json(value.model_dump_json()) == value


def test_local_default() -> None:
    assert Provenance().model_dump() == {"commit": "local-dev", "commit_reviewable": False}


@pytest.mark.parametrize("commit", [None, "", "abc123", "0" * 40, "A" * 40,
                                         "g" * 40, "a" * 39, "a" * 41, SHA + "\n", " " + SHA, "local-dev"])
def test_invalid_reviewable(commit: object) -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate({"commit": commit, "commit_reviewable": True})


@pytest.mark.parametrize("commit", [None, "", "abc123", SHA, "0" * 40, "local-dev\n"])
def test_false_requires_sentinel(commit: object) -> None:
    with pytest.raises(ValidationError):
        Provenance.model_validate({"commit": commit, "commit_reviewable": False})


@pytest.mark.parametrize("flag", [0, 1, 0.0, 1.0, "true", "false", "True", "False", "yes", None])
@pytest.mark.parametrize("commit", [SHA, "local-dev"])
def test_boolean_is_strict(flag: object, commit: str) -> None:
    data = {"commit": commit, "commit_reviewable": flag}
    with pytest.raises(ValidationError):
        Provenance.model_validate(data)
    with pytest.raises(ValidationError):
        Provenance.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("commit", ["", "abc123", "0" * 40, "A" * 40, SHA + "\n", SHA])
def test_environment_generation(commit: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_COMMIT", commit)
    report = challenge(ChallengeRequest(mode="nexus"))
    assert report.provenance == Provenance(
        commit=SHA if commit == SHA else "local-dev", commit_reviewable=commit == SHA,
    )
    assert verify_report(report).valid


@pytest.mark.parametrize("constructed", [False, True])
@pytest.mark.parametrize("state", [
    {"commit": "abc123", "commit_reviewable": True},
    {"commit": SHA, "commit_reviewable": False},
    {"commit": None, "commit_reviewable": False},
    {"commit": "local-dev", "commit_reviewable": "false"},
])
def test_generation_revalidates(
    state: dict[str, Any], constructed: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = Provenance.model_construct(**state) if constructed else state
    monkeypatch.setattr(provenance, "commit_state", lambda: value)
    with pytest.raises(ValidationError):
        challenge(ChallengeRequest(mode="nexus"))


def test_rehashed_invalid_claim_rejected_everywhere() -> None:
    data = challenge(ChallengeRequest(mode="nexus")).model_dump(mode="json")
    data["provenance"] = {"commit": "abc123", "commit_reviewable": True}
    data["report_id"] = data["canonical_report_hash"] = content_hash(data)
    for value in (data, json.dumps(data)):
        result = verify_report(value)
        assert not result.valid
        assert result.errors == ["INVALID_CERTIFICATE"]

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            response = await client.post("/v1/verify-report", json=data)
        assert response.status_code == 422
        assert response.json() == {"detail": "INVALID_REQUEST"}
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("verify_failure_certificate", {"report": data})

    asyncio.run(check())


@pytest.mark.parametrize("commit", ["local-dev", SHA])
def test_valid_transport_generation(commit: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHALITMUS_COMMIT", commit)

    async def check() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            for path in ("/v1/challenge", "/v1/find-failure-boundary"):
                response = await client.post(path, json={"mode": "nexus"})
                assert response.status_code == 200
                data = response.json()
                assert data["provenance"] == {"commit": commit, "commit_reviewable": commit == SHA}
                assert verify_report(data).valid
                verified = await client.post("/v1/verify-report", json=data)
                assert verified.status_code == 200
                assert verified.json()["valid"] is True
        for name in ("challenge_nexus_strategy", "find_failure_boundary"):
            result = await mcp.call_tool(name, {"request": {"mode": "nexus"}})
            assert commit in str(result)
        verified_result = await mcp.call_tool("verify_failure_certificate", {"report": data})
        assert "authenticity_verified" in str(verified_result)

    asyncio.run(check())


@pytest.mark.parametrize("constructed", [False, True])
def test_invalid_generation_safe_transport_failures(
    constructed: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "nxk_" + "q" * 24
    monkeypatch.setenv("NEXUS_API_KEY", secret)
    state: dict[str, Any] = {"commit": secret, "commit_reviewable": True}
    value = Provenance.model_construct(**state) if constructed else state
    monkeypatch.setattr(provenance, "commit_state", lambda: value)

    async def check() -> None:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://local") as client:
            for path in ("/v1/challenge", "/v1/find-failure-boundary", "/v1/demo/shock"):
                response = await client.get(path) if "/demo/" in path else await client.post(path, json={"mode": "nexus"})
                assert response.status_code == 500
                assert response.json() == {"detail": "INTERNAL_ERROR"}
                assert secret not in response.text
        for name in ("challenge_nexus_strategy", "find_failure_boundary", "get_demo_fixture"):
            arguments = {"scenario": "shock"} if name == "get_demo_fixture" else {"request": {"mode": "nexus"}}
            with pytest.raises(ToolError, match="^TOOL_FAILED$"):
                await mcp.call_tool(name, arguments)

    asyncio.run(check())
    captured = capsys.readouterr()
    assert secret not in captured.out + captured.err
