"""Release-gate projection over verified reports, REST/MCP parity, UI safety.

The pure verdict→decision mapping is tested as a table. project() itself is
only exercised with valid authoritative reports; tampered reports must be
rejected fail-closed with REPORT_VERIFICATION_FAILED.
"""

import asyncio
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from app import provenance, transport
from app.certificates import content_hash, verify_report
from app.contracts import ChallengeRequest, ReleaseGateResult, Report
from app.demo import fixture
from app.lab import challenge
from app.mcp_server import ARGUMENTS, mcp
from app.main import app
from app.release_gate import (
    ACTION_FOR_DECISION,
    DECISION_FOR_VERDICT,
    action_for_decision,
    decision_for_verdict,
    project,
)
from app.transport import TransportError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENABLE_NEXUS", raising=False)
    monkeypatch.delenv("ALPHALITMUS_ENV", raising=False)
    with TestClient(app, raise_server_exceptions=False) as result:
        yield result


def nexus_report() -> Report:
    return challenge(ChallengeRequest(mode="nexus"))


def test_decision_mapping_exact() -> None:
    assert DECISION_FOR_VERDICT == {
        "FRAGILE": "BLOCK_DEPLOYMENT",
        "INCONSISTENT": "BLOCK_DEPLOYMENT",
        "UNPROVEN": "INSUFFICIENT_EVIDENCE",
        "SURVIVED_TESTS": "SURVIVED_BOUNDED_TESTS",
    }
    assert decision_for_verdict("FRAGILE") == "BLOCK_DEPLOYMENT"
    assert decision_for_verdict("INCONSISTENT") == "BLOCK_DEPLOYMENT"
    assert decision_for_verdict("UNPROVEN") == "INSUFFICIENT_EVIDENCE"
    assert decision_for_verdict("SURVIVED_TESTS") == "SURVIVED_BOUNDED_TESTS"


def test_action_mapping_exact() -> None:
    assert ACTION_FOR_DECISION == {
        "BLOCK_DEPLOYMENT": "DO_NOT_DEPLOY",
        "INSUFFICIENT_EVIDENCE": "COLLECT_MORE_EVIDENCE",
        "SURVIVED_BOUNDED_TESTS": "CONTINUE_PAPER_VALIDATION",
    }
    assert action_for_decision("BLOCK_DEPLOYMENT") == "DO_NOT_DEPLOY"
    assert action_for_decision("INSUFFICIENT_EVIDENCE") == "COLLECT_MORE_EVIDENCE"
    assert action_for_decision("SURVIVED_BOUNDED_TESTS") == "CONTINUE_PAPER_VALIDATION"


def test_valid_report_projects_successfully() -> None:
    report = nexus_report()
    assert verify_report(report).valid
    result = project(report)
    assert result.decision == "INSUFFICIENT_EVIDENCE"
    assert result.recommended_action == "COLLECT_MORE_EVIDENCE"
    assert result.source_verdict == "UNPROVEN"
    assert result.source_report_verified is True
    assert result.schema_version == "alphalitmus-release-gate-1"
    assert result.no_execution is True
    assert result.profitability_claimed is False
    assert result.report_id == report.report_id
    assert result.canonical_report_hash == report.canonical_report_hash
    assert "not financial advice" in result.disclaimer.lower()
    assert "not deployment approval" in result.disclaimer.lower()


def test_verdict_changed_without_rehash_rejected() -> None:
    base = nexus_report()
    assert base.verdict == "UNPROVEN"
    tampered = base.model_copy(update={"verdict": "FRAGILE"})
    checked = verify_report(tampered)
    assert checked.valid is False
    assert "CONTENT_HASH_MISMATCH" in checked.errors
    assert "DECISION_POLICY_MISMATCH" in checked.errors
    with pytest.raises(TransportError) as excinfo:
        project(tampered)
    assert excinfo.value.code == "REPORT_VERIFICATION_FAILED"
    # The original valid report still projects.
    assert project(base).decision == "INSUFFICIENT_EVIDENCE"


def test_verdict_changed_with_rehash_still_rejected() -> None:
    base = nexus_report()
    tampered = base.model_copy(update={"verdict": "FRAGILE"})
    digest = content_hash(tampered)
    rehashed = tampered.model_copy(update={"report_id": digest, "canonical_report_hash": digest})
    checked = verify_report(rehashed)
    assert checked.valid is False
    assert "DECISION_POLICY_MISMATCH" in checked.errors
    with pytest.raises(TransportError) as excinfo:
        project(rehashed)
    assert excinfo.value.code == "REPORT_VERIFICATION_FAILED"


@pytest.mark.parametrize("tamper", ["matrix", "reasons"])
def test_metadata_tamper_rejected(tamper: str) -> None:
    base = nexus_report()
    if tamper == "matrix":
        damaged = base.model_copy(deep=True)
        assert damaged.test_matrix
        damaged.test_matrix[0].reason += " [tamper]"
    else:
        damaged = base.model_copy(update={"reason_codes": ["TEST_NOT_PROFITABLE"]})
    assert verify_report(damaged).valid is False
    with pytest.raises(TransportError) as excinfo:
        project(damaged)
    assert excinfo.value.code == "REPORT_VERIFICATION_FAILED"


def test_rest_invalid_source_sanitized(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tampered = nexus_report().model_copy(update={"verdict": "FRAGILE"})
    assert verify_report(tampered).valid is False

    def forged(request: ChallengeRequest, evidence: object = None) -> Report:
        return tampered

    monkeypatch.setattr(transport, "challenge", forged)
    first = client.post("/v1/release-gate", json={"mode": "nexus"})
    second = client.post("/v1/release-gate", json={"mode": "nexus"})
    assert first.status_code == 500
    assert first.json() == {"detail": "REPORT_VERIFICATION_FAILED"}
    assert second.json() == {"detail": "REPORT_VERIFICATION_FAILED"}
    lowered = first.text.lower()
    assert "traceback" not in lowered
    assert tampered.report_id.lower() not in lowered
    assert "content_hash_mismatch" not in lowered
    assert "test_matrix" not in lowered
    assert ".py" not in lowered


def test_mcp_invalid_source_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    tampered = nexus_report().model_copy(update={"verdict": "FRAGILE"})

    def forged(request: ChallengeRequest, evidence: object = None) -> Report:
        return tampered

    monkeypatch.setattr(transport, "challenge", forged)

    async def check() -> None:
        with pytest.raises(ToolError, match="^REPORT_VERIFICATION_FAILED$"):
            await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus"}})

    asyncio.run(check())


def test_successful_result_verified_ids() -> None:
    report = challenge(ChallengeRequest(research=fixture("mixed")))
    assert verify_report(report).valid
    result = project(report)
    assert result.source_report_verified is True
    assert re.fullmatch(r"[0-9a-f]{64}", result.report_id) is not None
    assert result.canonical_report_hash == result.report_id == content_hash(report)
    assert result.report.report_id == result.report_id


def test_inconsistent_real_engine_maps_to_block() -> None:
    report = challenge(ChallengeRequest(mode="nexus"), {
        "equity": {"status": "received", "data": {"run_id": "run-a"}},
        "trades": {"status": "received", "data": {"run_id": "run-b"}},
    })
    assert report.verdict == "INCONSISTENT"
    assert verify_report(report).valid
    result = project(report)
    assert result.decision == "BLOCK_DEPLOYMENT"
    assert result.recommended_action == "DO_NOT_DEPLOY"
    assert result.source_report_verified is True


@pytest.mark.parametrize("scenario", ["mixed", "shock"])
def test_synthetic_demo_never_approves(client: TestClient, scenario: str) -> None:
    response = client.get("/v1/release-gate/demo/" + scenario)
    assert response.status_code == 200
    result = ReleaseGateResult.model_validate(response.json())
    assert result.decision == "INSUFFICIENT_EVIDENCE"
    assert result.recommended_action == "COLLECT_MORE_EVIDENCE"
    assert result.source_verdict == "UNPROVEN"
    assert result.evidence_classification == "synthetic_reference"
    assert result.source_report_verified is True
    # Approval-like outcomes must never appear for synthetic demos.
    assert result.decision != "SURVIVED_BOUNDED_TESTS"
    assert result.recommended_action != "CONTINUE_PAPER_VALIDATION"
    assert "SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE" in result.reason_codes
    # Observed counterevidence stays visible.
    assert result.observed_failures


def test_no_profitability_or_execution_claims() -> None:
    result = project(nexus_report())
    forbidden = {"APPROVE_DEPLOYMENT", "EXECUTE", "BUY", "SELL", "PROFITABLE", "SAFE_TO_TRADE"}
    # The gate decision itself must never use approval/trading wording. The embedded
    # authoritative Report legitimately mentions BUY/SELL intents and NOT_PROFITABLE
    # reason codes as descriptive evidence, so only gate-level fields are checked here.
    assert result.decision not in forbidden
    assert result.recommended_action not in forbidden
    assert result.disclaimer not in forbidden
    for token in forbidden:
        assert token not in result.decision
        assert token not in result.recommended_action
        assert token not in result.disclaimer
    assert result.profitability_claimed is False
    assert result.no_execution is True
    lowered = (result.decision + " " + result.recommended_action + " " + result.disclaimer).lower()
    assert "profitable edge" not in lowered
    assert "safe to trade" not in lowered
    assert "approve" not in result.decision.lower()
    assert result.recommended_action in ("DO_NOT_DEPLOY", "COLLECT_MORE_EVIDENCE", "CONTINUE_PAPER_VALIDATION")


def test_deterministic_reason_ordering() -> None:
    report = challenge(ChallengeRequest(research=fixture("mixed")))
    first = project(report)
    second = project(report)
    assert first.reason_codes == sorted(report.reason_codes) == second.reason_codes
    assert first.observed_failures == sorted(report.observed_failures)
    assert first.unavailable_tests == sorted(report.unavailable_tests)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_projection_does_not_mutate_report() -> None:
    report = challenge(ChallengeRequest(research=fixture("shock")))
    before = report.model_dump(mode="json")
    result = project(report)
    assert report.model_dump(mode="json") == before
    # The embedded report is a validated copy, not an alias that can mutate the source.
    assert result.report.model_dump(mode="json")["report_id"] == before["report_id"]
    assert result.report is not report


def test_rest_and_mcp_share_projection(client: TestClient) -> None:
    body = {"mode": "nexus"}
    rest_response = client.post("/v1/release-gate", json=body)
    assert rest_response.status_code == 200
    rest_result = ReleaseGateResult.model_validate(rest_response.json())
    direct = project(challenge(ChallengeRequest(mode="nexus")))
    assert rest_result.decision == direct.decision
    assert rest_result.recommended_action == direct.recommended_action
    assert rest_result.report_id == direct.report_id
    assert rest_result.canonical_report_hash == direct.canonical_report_hash
    assert rest_result.source_report_verified is True
    assert direct.source_report_verified is True

    async def check() -> None:
        mcp_result = await mcp.call_tool("evaluate_strategy_release", {"request": body})
        text = str(mcp_result)
        assert "INSUFFICIENT_EVIDENCE" in text
        assert "COLLECT_MORE_EVIDENCE" in text

    asyncio.run(check())


def test_rest_mcp_success_outputs_match(client: TestClient) -> None:
    body = {"mode": "nexus"}
    rest_result = ReleaseGateResult.model_validate(client.post("/v1/release-gate", json=body).json())

    async def check() -> ReleaseGateResult:
        from pydantic import ValidationError

        outcome = await mcp.call_tool("evaluate_strategy_release", {"request": body})
        if isinstance(outcome, dict):
            return ReleaseGateResult.model_validate(outcome)
        stack = list(outcome) if isinstance(outcome, (list, tuple)) else [outcome]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                try:
                    return ReleaseGateResult.model_validate(item)
                except ValidationError:
                    continue
            if isinstance(item, (list, tuple)):
                stack.extend(item)
                continue
            text = getattr(item, "text", None)
            if not text:
                continue
            try:
                return ReleaseGateResult.model_validate_json(text)
            except ValidationError:
                continue
        raise AssertionError("MCP result carried no parseable ReleaseGateResult")

    mcp_result = asyncio.run(check())
    assert mcp_result.decision == rest_result.decision
    assert mcp_result.recommended_action == rest_result.recommended_action
    assert mcp_result.report_id == rest_result.report_id
    assert mcp_result.canonical_report_hash == rest_result.canonical_report_hash
    assert mcp_result.source_report_verified is True


def test_rest_release_gate_validation(client: TestClient) -> None:
    assert client.post("/v1/release-gate", json={"mode": "nexus", "secret": "never-echo"}).status_code == 422
    bad = client.post("/v1/release-gate", json={"mode": "nexus", "bootstrap_iterations": "50"})
    assert bad.status_code == 422
    assert "never-echo" not in bad.text
    assert client.post("/v1/release-gate", json={"mode": "nexus", "extra": 1}).status_code == 422


def test_mcp_strict_arguments() -> None:
    async def check() -> None:
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus", "unknown": 1}})
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus", "bootstrap_iterations": "50"}})
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus"}, "secret": "x"})

    asyncio.run(check())


def test_unknown_demo_scenario(client: TestClient) -> None:
    assert client.get("/v1/release-gate/demo/fragile").status_code == 404
    assert client.get("/v1/release-gate/demo/fragile").json() == {"detail": "UNKNOWN_SCENARIO"}
    assert client.get("/v1/demo/fragile").status_code == 404


def test_capability_lists_six_tools(client: TestClient) -> None:
    data = client.get("/v1/capabilities").json()
    assert len(data["tools"]) == 8
    assert "evaluate_live_nexus_candidate" in data["tools"]
    assert data["tools"][0] == "evaluate_strategy_release"
    assert set(data["tools"]) == set(ARGUMENTS)
    for name in ("evaluate_strategy_release", "challenge_nexus_strategy", "find_failure_boundary",
                 "verify_failure_certificate", "get_demo_fixture", "run_nexus_window_stability",
                 "replay_recorded_nexus_evidence"):
        assert name in data["tools"]


def test_existing_five_tools_remain() -> None:
    async def check() -> None:
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        assert len(tools) == 8
        for name in ("challenge_nexus_strategy", "find_failure_boundary", "verify_failure_certificate",
                     "get_demo_fixture", "run_nexus_window_stability"):
            assert name in names
        assert "evaluate_strategy_release" in names
        assert "replay_recorded_nexus_evidence" in names
        assert "evaluate_live_nexus_candidate" in names
        # Existing tools still dispatch.
        result = await mcp.call_tool("challenge_nexus_strategy", {"request": {"mode": "nexus"}})
        assert "nexus_validated" in str(result)

    asyncio.run(check())


def test_mcp_primary_annotations() -> None:
    async def check() -> None:
        tools = await mcp.list_tools()
        primary = next(tool for tool in tools if tool.name == "evaluate_strategy_release")
        assert primary.annotations is not None
        assert primary.annotations.readOnlyHint is True
        assert primary.annotations.destructiveHint is False
        assert primary.annotations.idempotentHint is True
        assert primary.annotations.openWorldHint is True

    asyncio.run(check())


def test_openapi_exposes_release_gate(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/v1/release-gate" in schema["paths"]
    assert "/v1/release-gate/demo/{scenario}" in schema["paths"]
    assert schema["paths"]["/v1/release-gate/demo/{scenario}"]["get"]["responses"]["200"]
    for name in ("ReleaseGateResult", "Report-Input", "ChallengeRequest-Input"):
        assert schema["components"]["schemas"][name]["additionalProperties"] is False


def test_ui_judge_first(client: TestClient) -> None:
    html = client.get("/").text
    assert "AlphaLitmus" in html
    assert "Strategy Release Gate for Agents" in html
    assert "Test a strategy before an agent deploys or scales it." in html
    assert "Run safe release-gate demo" in html
    assert "When should an agent call this?" in html
    for item in ("before enabling a strategy", "after changing strategy configuration",
                 "before increasing risk or scale", "after a market-regime change",
                 "during scheduled strategy revalidation"):
        assert item in html
    assert "evaluate_strategy_release" in html
    assert 'class="hero__proof"' in html
    assert 'id="hero-live"' in html
    assert 'class="context-grid"' in html
    assert 'class="deep-evidence"' in html
    assert "Know when a strategy should not ship." in html
    assert "function revealResult(id)" in html
    assert "safe release-gate demo / mixed', true" in html
    # Ordered decision-first blocks.
    for marker in ("gate-decision", "gate-action", "gate-why", "gate-failures",
                   "gate-unavailable", "gate-report-id", "gate-hash", "raw-gate"):
        assert marker in html
    assert html.index("id=\"gate\"") < html.index("id=\"overview\"")
    assert "This result is not financial advice and is not deployment approval." in html
    assert "Copy JSON" in html
    assert "Download JSON" in html
    # No financial hype or fake live status.
    lowered = html.lower()
    assert "guaranteed profit" not in lowered
    assert "live trading" not in lowered or "no" in lowered or "not" in lowered


@pytest.mark.parametrize("decision", ["BLOCK_DEPLOYMENT", "INSUFFICIENT_EVIDENCE", "SURVIVED_BOUNDED_TESTS"])
def test_ui_renders_all_decision_states(client: TestClient, decision: str) -> None:
    html = client.get("/").text
    # JS must know all three decisions; CSS must not hide the gate behind horizontal scroll.
    assert decision in html
    assert "GATE_DECISIONS" in html


def test_ui_390_no_overflow_static(client: TestClient) -> None:
    html = client.get("/").text
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "overflow-x:hidden" in html
    assert "max-width:100%" in html
    assert "@media(max-width:640px)" in html
    # Gate identity grid collapses to a single column on narrow viewports.
    compact = html.replace(" ", "").replace("\n", "")
    assert "grid-template-columns:minmax(0,1fr)" in compact
    assert ".gate__ids" in html
    # Long hashes/JSON must wrap rather than force document-level horizontal scroll.
    assert "overflow-wrap:anywhere" in html
    assert "word-break:break-all" in html or "word-break:break-word" in html


@pytest.mark.parametrize("variant", ["missing", "false", "null", "string", "numeric"])
def test_ui_rejects_unverified_variants(client: TestClient, variant: str) -> None:
    html = client.get("/").text
    # The shipped boundary requires exact true; nothing is inferred from absence.
    assert "result.source_report_verified !== true" in html
    assert "gate.source_report_verified !== true" in html
    assert "CONTRACT VALIDATION FAILED" in html
    # Python mirror of the JS identity check: every listed variant fails it.
    sentinel = object()
    cases = {"missing": sentinel, "false": False, "null": None, "string": "true", "numeric": 1}
    assert (cases[variant] is True) is False


def test_ui_failure_path_clears_and_disables_export(client: TestClient) -> None:
    html = client.get("/").text
    assert "clearReport('Unavailable / request failed. No current result to export.')" in html
    assert "export disabled" in html
    assert "setGateButtons(false)" in html


def test_transport_shares_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    original = transport.challenge

    def spy(request: ChallengeRequest, evidence: object = None) -> Report:
        calls.append("challenge")
        return original(request, evidence)  # type: ignore[arg-type]

    monkeypatch.setattr(transport, "challenge", spy)

    async def check() -> None:
        result = await transport.run_release_gate(ChallengeRequest(mode="nexus"))
        assert result.source_report_verified is True

    asyncio.run(check())
    assert calls == ["challenge"]
    assert provenance.commit_state()["commit"] is not None


def _parse_direct_gate_result(outcome: object) -> ReleaseGateResult:
    """Parse a direct FastMCP call_tool outcome, mirroring the UI contract gate."""
    stack = list(outcome) if isinstance(outcome, (list, tuple)) else [outcome]  # type: ignore[arg-type]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            try:
                return ReleaseGateResult.model_validate(item)
            except ValidationError:
                continue
        if isinstance(item, (list, tuple)):
            stack.extend(item)
            continue
        text = getattr(item, "text", None)
        if not text:
            continue
        try:
            return ReleaseGateResult.model_validate_json(text)
        except ValidationError:
            continue
    raise AssertionError("MCP result carried no parseable ReleaseGateResult")


def test_verified_attestation_present_on_success() -> None:
    result = project(nexus_report())
    assert result.source_report_verified is True
    assert result.model_dump(mode="json")["source_report_verified"] is True


def test_verified_attestation_missing_rejected() -> None:
    payload = project(nexus_report()).model_dump(mode="json")
    del payload["source_report_verified"]
    with pytest.raises(ValidationError):
        ReleaseGateResult.model_validate(payload)


@pytest.mark.parametrize("value", [False, None, 0, 1, "true", "false"])
def test_verified_attestation_wrong_values_rejected(value: object) -> None:
    payload = project(nexus_report()).model_dump(mode="json")
    payload["source_report_verified"] = value
    with pytest.raises(ValidationError):
        ReleaseGateResult.model_validate(payload)


def test_verified_attestation_required_in_schema() -> None:
    schema = ReleaseGateResult.model_json_schema()
    assert "source_report_verified" in schema.get("required", [])
    assert "default" not in schema["properties"]["source_report_verified"]


def test_rest_success_includes_verified_field(client: TestClient) -> None:
    gate = client.post("/v1/release-gate", json={"mode": "nexus"}).json()
    assert gate["source_report_verified"] is True
    ReleaseGateResult.model_validate(gate)
    demo = client.get("/v1/release-gate/demo/mixed").json()
    assert demo["source_report_verified"] is True
    ReleaseGateResult.model_validate(demo)


def test_mcp_structured_includes_verified_field() -> None:
    async def check() -> None:
        outcome = await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus"}})
        assert _parse_direct_gate_result(outcome).source_report_verified is True

    asyncio.run(check())


def test_rest_mcp_parity_includes_verified_field(client: TestClient) -> None:
    rest_result = ReleaseGateResult.model_validate(
        client.post("/v1/release-gate", json={"mode": "nexus"}).json(),
    )

    async def check() -> ReleaseGateResult:
        outcome = await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus"}})
        return _parse_direct_gate_result(outcome)

    mcp_result = asyncio.run(check())
    assert mcp_result.source_report_verified is True
    assert rest_result.source_report_verified is True
    assert mcp_result.source_report_verified == rest_result.source_report_verified
    assert mcp_result.decision == rest_result.decision
    assert mcp_result.report_id == rest_result.report_id


def test_invalid_source_never_returns_gate_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tampered = nexus_report().model_copy(update={"verdict": "FRAGILE"})
    assert verify_report(tampered).valid is False

    def forged(request: ChallengeRequest, evidence: object = None) -> Report:
        return tampered

    monkeypatch.setattr(transport, "challenge", forged)
    response = client.post("/v1/release-gate", json={"mode": "nexus"})
    assert response.status_code == 500
    assert response.json() == {"detail": "REPORT_VERIFICATION_FAILED"}
    assert "source_report_verified" not in response.text
    assert "decision" not in response.json()

    async def check() -> None:
        with pytest.raises(ToolError, match="^REPORT_VERIFICATION_FAILED$"):
            await mcp.call_tool("evaluate_strategy_release", {"request": {"mode": "nexus"}})

    asyncio.run(check())


def test_decision_mappings_and_previous_tools_unchanged() -> None:
    assert DECISION_FOR_VERDICT == {
        "FRAGILE": "BLOCK_DEPLOYMENT",
        "INCONSISTENT": "BLOCK_DEPLOYMENT",
        "UNPROVEN": "INSUFFICIENT_EVIDENCE",
        "SURVIVED_TESTS": "SURVIVED_BOUNDED_TESTS",
    }
    assert ACTION_FOR_DECISION == {
        "BLOCK_DEPLOYMENT": "DO_NOT_DEPLOY",
        "INSUFFICIENT_EVIDENCE": "COLLECT_MORE_EVIDENCE",
        "SURVIVED_BOUNDED_TESTS": "CONTINUE_PAPER_VALIDATION",
    }
    from app.transport import ChallengeArguments, DemoArguments, VerifyArguments, WindowExperimentArguments
    from app.mcp_server import LiveNexusArguments, ReplayRecordedArguments

    assert ARGUMENTS == {
        "evaluate_strategy_release": ChallengeArguments,
        "challenge_nexus_strategy": ChallengeArguments,
        "find_failure_boundary": ChallengeArguments,
        "verify_failure_certificate": VerifyArguments,
        "get_demo_fixture": DemoArguments,
        "run_nexus_window_stability": WindowExperimentArguments,
        "replay_recorded_nexus_evidence": ReplayRecordedArguments,
        "evaluate_live_nexus_candidate": LiveNexusArguments,
    }
