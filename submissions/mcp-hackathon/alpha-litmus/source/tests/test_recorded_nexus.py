"""Recorded Nexus evidence replay tests (synthetic fixtures only, never production).

All fixtures here are synthetic test data labeled as such. They exercise the
capture/replay plumbing without creating evidence/nexus-candidate-v1.
"""

import asyncio
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

import app.recorded_nexus as rec
from app.certificates import verify_report
from app.contracts import ChallengeRequest
from app.demo import fixture
from app.lab import challenge
from app.main import app
from app.mcp_server import ARGUMENTS, LiveNexusArguments, ReplayRecordedArguments, mcp
from tools.capture_nexus_snapshot import LIMITATIONS as CAPTURE_LIMITATIONS

ROOT = Path(__file__).resolve().parents[1]
CAPTURED_AT = "2026-09-19T12:00:00+00:00"
CAPTURED_TS = datetime.fromisoformat(CAPTURED_AT).timestamp()


def synthetic_surfaces() -> dict[str, dict]:
    # Synthetic test fixture only; small deterministic values that still
    # produce a genuine TRADE_SYMBOLS MISMATCH through the real engine.
    return {
        "signal": {"symbol": "BTC/USDT", "trade_intent": "HOLD", "timestamp": CAPTURED_TS - 10},
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


def canonical(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")


def write_synthetic_snapshot(directory: Path, surfaces: dict[str, dict] | None = None,
                             manifest_overrides: dict | None = None,
                             raw_overrides: dict[str, bytes] | None = None) -> tuple[dict, dict]:
    surfaces = copy.deepcopy(surfaces if surfaces is not None else synthetic_surfaces())
    directory.mkdir(parents=True, exist_ok=True)
    file_hashes = {}
    for label in ("signal", "metrics", "equity", "trades"):
        payload = canonical(surfaces[label])
        if raw_overrides and (label + ".json") in raw_overrides:
            payload = raw_overrides[label + ".json"]
        (directory / (label + ".json")).write_bytes(payload)
        file_hashes[label + ".json"] = hashlib.sha256(payload).hexdigest()
    manifest = {
        "captured_at": CAPTURED_AT,
        "evidence_classification": "nexus_snapshot",
        "expected_run_id": "bt-7544746ff32d",
        "files": dict(sorted(file_hashes.items())),
        "historical": True,
        "integrity_scope": "source_commit_bound_content_consistency_not_authenticity",
        "limitations": list(CAPTURE_LIMITATIONS) + ["Synthetic test fixture; not production evidence."],
        "live": False,
        "no_execution": True,
        "profitability_claimed": False,
        "schema_version": "nexus-recorded-snapshot-2",
        "snapshot_id": "candidate-v1",
        "source": "OlaXBT Nexus MCP",
        "strategy_identity_binding": "operator_asserted_strategy_bound_key_not_returned_by_read_surfaces",
        "strategy_id": "str_b840280ce037",
        "strategy_name": "SKLab AlphaLitmus Candidate v1",
        "symbol": "BTC/USDT",
        "tools": {
            "equity": "get_strategy_equity",
            "metrics": "get_strategy_metrics",
            "signal": "get_strategy_signal",
            "trades": "get_strategy_trades",
        },
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    if not manifest_overrides or "aggregate_snapshot_sha256" not in manifest_overrides:
        manifest["aggregate_snapshot_sha256"] = hashlib.sha256(canonical(manifest)).hexdigest()
    (directory / "manifest.json").write_bytes(canonical(manifest))
    return manifest, surfaces


@pytest.fixture
def synthetic_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory if snapshot_id == "candidate-v1" else (_ for _ in ()).throw(rec.RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")))
    return directory


def test_valid_snapshot_loads_and_verifies(synthetic_dir: Path) -> None:
    manifest, surfaces = rec.load_snapshot("candidate-v1")
    assert manifest["strategy_id"] == "str_b840280ce037"
    assert manifest["expected_run_id"] == "bt-7544746ff32d"
    assert manifest["symbol"] == "BTC/USDT"
    assert manifest["captured_at"] == CAPTURED_AT
    assert set(surfaces) == {"signal", "metrics", "equity", "trades"}


def test_repeated_replay_byte_identical(synthetic_dir: Path) -> None:
    first = rec.replay_recorded_nexus_evidence()
    second = rec.replay_recorded_nexus_evidence()
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert json.dumps(first.model_dump(mode="json"), sort_keys=True) == json.dumps(second.model_dump(mode="json"), sort_keys=True)


@pytest.mark.parametrize("filename", ["signal.json", "metrics.json", "equity.json", "trades.json"])
def test_each_file_tamper_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str) -> None:
    directory = tmp_path / "snapshot"
    manifest, surfaces = write_synthetic_snapshot(directory)
    # Tamper one file without updating manifest hashes.
    raw = json.loads((directory / filename).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        # Flip a value while staying valid JSON; integrity must still fail on hash.
        if filename == "signal.json":
            raw["trade_intent"] = "BUY" if raw.get("trade_intent") != "BUY" else "SELL"
        elif filename == "metrics.json":
            raw["sharpe_ratio"] = 9.99
        elif filename == "equity.json":
            raw["points"] = [{"t": 1, "equity": 100.0}, {"t": 2, "equity": 999.0}]
        else:
            raw["trades"] = [{"symbol": "BTC/USDT", "pnl": 999.0}, {"symbol": "BTC/USDT", "pnl": 1.0}]
    (directory / filename).write_bytes(canonical(raw))
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError) as excinfo:
        rec.load_snapshot("candidate-v1")
    assert excinfo.value.code in ("RECORDED_EVIDENCE_INTEGRITY_FAILED", "RECORDED_EVIDENCE_INVALID")


def test_manifest_tampering_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["strategy_id"] = "str_tampered"
    (directory / "manifest.json").write_bytes(canonical(manifest))
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_aggregate_mismatch_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    manifest, _ = write_synthetic_snapshot(directory)
    manifest["aggregate_snapshot_sha256"] = "0" * 64
    (directory / "manifest.json").write_bytes(canonical(manifest))
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError) as excinfo:
        rec.load_snapshot("candidate-v1")
    assert excinfo.value.code == "RECORDED_EVIDENCE_INTEGRITY_FAILED"


def test_noncanonical_json_rejected_even_with_matching_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "snapshot"
    manifest, _ = write_synthetic_snapshot(directory)
    noncanonical = json.dumps(synthetic_surfaces()["signal"], indent=2).encode("utf-8")
    (directory / "signal.json").write_bytes(noncanonical)
    manifest["files"]["signal.json"] = hashlib.sha256(noncanonical).hexdigest()
    manifest.pop("aggregate_snapshot_sha256")
    manifest["aggregate_snapshot_sha256"] = hashlib.sha256(canonical(manifest)).hexdigest()
    (directory / "manifest.json").write_bytes(canonical(manifest))
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError) as excinfo:
        rec.load_snapshot("candidate-v1")
    assert excinfo.value.code == "RECORDED_EVIDENCE_INVALID"


@pytest.mark.parametrize("payload", [
    b'{"a":1,"a":2}',
    b'{"signal":1,"signal":2}',
])
def test_duplicate_keys_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    (directory / "signal.json").write_bytes(payload)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_path_traversal_impossible() -> None:
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("../escape")
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1/../../etc")
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("other-snapshot")


@pytest.mark.parametrize("kind", ["oversize", "deep", "malformed", "extra_file", "missing_file"])
def test_bounds_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    if kind == "oversize":
        (directory / "signal.json").write_bytes(b'{"symbol":"' + b"A" * 20000 + b'"}')
    elif kind == "deep":
        nested: object = {"a": 1}
        for _ in range(40):
            nested = {"x": nested}
        (directory / "signal.json").write_bytes(canonical(nested))
    elif kind == "malformed":
        (directory / "signal.json").write_bytes(b"not json")
    elif kind == "extra_file":
        (directory / "extra.json").write_bytes(b"{}")
    else:
        (directory / "signal.json").unlink()
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_secret_shapes_never_appear(synthetic_dir: Path) -> None:
    replay = rec.replay_recorded_nexus_evidence()
    serialized = json.dumps(replay.model_dump(mode="json"), allow_nan=False)
    assert "nxk_" not in serialized
    assert "NEXUS_API_KEY" not in serialized
    assert "-----BEGIN" not in serialized
    # Synthetic surfaces themselves contain no secret shapes.
    _, surfaces = rec.load_snapshot("candidate-v1")
    assert "nxk_" not in json.dumps(surfaces)


def test_missing_snapshot_never_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": missing)
    with pytest.raises(rec.RecordedEvidenceError) as excinfo:
        rec.load_snapshot("candidate-v1")
    assert excinfo.value.code == "RECORDED_EVIDENCE_UNAVAILABLE"
    with pytest.raises(rec.RecordedEvidenceError):
        rec.replay_recorded_nexus_evidence()
    # REST must fail closed non-200, never synthetic.
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/nexus/replay/candidate-v1")
        assert response.status_code in (500, 503)
        assert "RECORDED_EVIDENCE_" in response.text
        assert "synthetic" not in response.text.lower() or "RECORDED" in response.text


@pytest.mark.parametrize("field, bad", [
    ("strategy_id", "str_wrong"),
    ("expected_run_id", "bt-wrong"),
    ("symbol", "ETH/USDT"),
    ("captured_at", "2026-09-19T12:00:00"),
    ("schema_version", "wrong-1"),
])
def test_identity_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, bad: str) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory, manifest_overrides={field: bad})
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_equity_trades_run_must_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    surfaces = synthetic_surfaces()
    surfaces["trades"]["run_id"] = "bt-other"
    write_synthetic_snapshot(directory, surfaces=surfaces)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_all_four_surfaces_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    (directory / "trades.json").unlink()
    (directory / "trades.json").write_bytes(canonical({}))
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    with pytest.raises(rec.RecordedEvidenceError):
        rec.load_snapshot("candidate-v1")


def test_trade_symbols_mismatch_verdict_decision(synthetic_dir: Path) -> None:
    replay = rec.replay_recorded_nexus_evidence()
    gate = replay.release_gate
    assert gate.source_verdict == "INCONSISTENT"
    assert gate.decision == "BLOCK_DEPLOYMENT"
    assert gate.recommended_action == "DO_NOT_DEPLOY"
    assert gate.source_report_verified is True
    assert gate.no_execution is True
    assert gate.profitability_claimed is False
    assert gate.evidence_classification == "nexus_snapshot"
    checks = {c.code: c for c in gate.report.reconciliation.result.results}  # type: ignore[union-attr]
    assert checks["TRADE_SYMBOLS"].status == "MISMATCH"
    assert replay.no_execution is True
    assert replay.profitability_claimed is False
    assert replay.historical is True
    assert replay.live is False
    assert replay.strategy_id == "str_b840280ce037"
    assert replay.run_id == "bt-7544746ff32d"
    assert replay.symbol == "BTC/USDT"
    assert "not a live" in replay.disclosure.lower() or "not live" in replay.disclosure.lower()


def test_source_report_verified_exact_true(synthetic_dir: Path) -> None:
    replay = rec.replay_recorded_nexus_evidence()
    assert replay.release_gate.source_report_verified is True
    payload = replay.model_dump(mode="json")
    assert payload["release_gate"]["source_report_verified"] is True
    assert verify_report(replay.release_gate.report).valid


def test_rest_mcp_parity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        rest_response = client.get("/v1/nexus/replay/candidate-v1")
        assert rest_response.status_code == 200
        rest_model = rec.RecordedNexusReplay.model_validate(rest_response.json())

    async def check() -> None:
        outcome = await mcp.call_tool("replay_recorded_nexus_evidence", {})
        if isinstance(outcome, dict):
            mcp_model = rec.RecordedNexusReplay.model_validate(outcome)
        else:
            stack: list = list(outcome) if isinstance(outcome, (list, tuple)) else [outcome]
            mcp_model = None  # type: ignore[assignment]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    try:
                        mcp_model = rec.RecordedNexusReplay.model_validate(item)
                        break
                    except Exception:
                        continue
                if isinstance(item, (list, tuple)):
                    stack.extend(item)
                    continue
                text = getattr(item, "text", None)
                if text:
                    try:
                        mcp_model = rec.RecordedNexusReplay.model_validate_json(text)
                        break
                    except Exception:
                        continue
            assert mcp_model is not None
        assert mcp_model.model_dump(mode="json") == rest_model.model_dump(mode="json")

    asyncio.run(check())


def test_zero_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("network attempted")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    replay = rec.replay_recorded_nexus_evidence()
    assert replay.snapshot_integrity == "verified"


def test_synthetic_demo_unchanged() -> None:
    report = challenge(ChallengeRequest(research=fixture("mixed")))
    assert report.evidence_classification == "synthetic_reference"
    assert report.verdict == "UNPROVEN"


def test_seven_tool_schemas_unchanged_plus_live_eighth() -> None:
    from app.transport import ChallengeArguments, DemoArguments, VerifyArguments, WindowExperimentArguments

    assert ARGUMENTS["evaluate_strategy_release"] is ChallengeArguments
    assert ARGUMENTS["challenge_nexus_strategy"] is ChallengeArguments
    assert ARGUMENTS["find_failure_boundary"] is ChallengeArguments
    assert ARGUMENTS["verify_failure_certificate"] is VerifyArguments
    assert ARGUMENTS["get_demo_fixture"] is DemoArguments
    assert ARGUMENTS["run_nexus_window_stability"] is WindowExperimentArguments
    assert ARGUMENTS["replay_recorded_nexus_evidence"] is ReplayRecordedArguments
    assert ARGUMENTS["evaluate_live_nexus_candidate"] is LiveNexusArguments
    assert len(ARGUMENTS) == 8

    async def check() -> None:
        tools = await mcp.list_tools()
        assert len(tools) == 8
        replay_tool = next(t for t in tools if t.name == "replay_recorded_nexus_evidence")
        assert replay_tool.annotations is not None
        assert replay_tool.annotations.readOnlyHint is True
        assert replay_tool.annotations.destructiveHint is False
        assert replay_tool.annotations.idempotentHint is True
        assert replay_tool.annotations.openWorldHint is False

    asyncio.run(check())


def test_mcp_empty_args_strict() -> None:
    async def check() -> None:
        with pytest.raises(ToolError, match="^INVALID_ARGUMENTS$"):
            await mcp.call_tool("replay_recorded_nexus_evidence", {"unexpected": 1})

    asyncio.run(check())


def test_dashboard_states() -> None:
    html = TestClient(app).get("/").text
    assert "Replay real Nexus evidence" in html
    assert "RECORDED NEXUS EVIDENCE" in html
    assert "Recorded historical Nexus evidence" in html
    assert "not a live market call" in html.lower() or "not a live" in html.lower()
    assert "recorded-decision" in html
    assert 'id="recorded-details"' in html
    assert "'READY TO REPLAY', 'Not replayed yet'" in html
    assert "revealResult('recorded')" in html
    assert "Unavailable / awaiting recorded replay" not in html
    assert "recorded-strategy-id" in html
    assert "recorded-run" in html
    assert "recorded-surfaces" in html
    assert "recorded-integrity" in html
    assert "recorded-report-id" in html
    assert "recorded-limitations" in html
    assert "copy-recorded" in html
    assert "download-recorded" in html
    assert "raw-recorded" in html
    # Safe DOM: existing helper uses textContent; no unsafe innerHTML with response.
    assert "textContent" in html
    assert "result.source_report_verified !== true" in html or "source_report_verified !== true" in html
    assert "RECORDED_EVIDENCE_" in html
    assert "REPLAY UNAVAILABLE" in html


def test_dashboard_no_overflow_static() -> None:
    html = TestClient(app).get("/").text
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert "overflow-x:hidden" in html
    compact = html.replace(" ", "").replace("\n", "")
    assert "grid-template-columns:minmax(0,1fr)" in compact
    assert ".gate__ids" in html
    assert "overflow-wrap:anywhere" in html
    # Recorded section reuses responsive gate classes.
    assert 'id="recorded"' in html
    assert 'id="recorded-metrics"' in html


def test_capture_requires_key_no_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.capture_nexus_snapshot as cap

    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cap, "_repo_root", lambda: repo)
    out = repo / "evidence" / "nexus-candidate-v1"
    code = cap.main([])
    assert code == 2
    assert not out.exists()


def test_capture_entrypoint_sanitizes_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
) -> None:
    import tools.capture_nexus_snapshot as cap

    marker = "SECRET_LOCAL_PATH_MARKER"

    def explode(argv: list[str] | None = None) -> int:
        raise RuntimeError(marker)

    monkeypatch.setattr(cap, "main", explode)
    assert cap._entrypoint() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "CAPTURE_FAILED"
    assert marker not in captured.err


def test_capture_never_logs_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import tools.capture_nexus_snapshot as cap

    key = "nxk_" + "synthetickey1234567890"
    monkeypatch.setenv("NEXUS_API_KEY", key)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cap, "_repo_root", lambda: repo)

    async def fake_read(symbol: str) -> dict:
        assert symbol == "BTC/USDT"
        return {
            label: {"status": "received", "data": data}
            for label, data in synthetic_surfaces().items()
        }

    monkeypatch.setattr(cap, "read_nexus", fake_read) if hasattr(cap, "read_nexus") else None
    # Patch via app.nexus.read_nexus since capture imports inside main.
    import app.nexus as nexus_mod

    monkeypatch.setattr(nexus_mod, "read_nexus", fake_read)
    out = repo / "evidence" / "nexus-candidate-v1"
    code = cap.main(["--allow-overwrite"])
    captured = capsys.readouterr()
    assert code == 0
    assert key not in captured.out + captured.err
    assert key not in json.dumps({})  # sanity
    for name in ("signal.json", "metrics.json", "equity.json", "trades.json", "manifest.json"):
        assert key not in (out / name).read_text(encoding="utf-8")


def test_capture_failure_leaves_no_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.nexus as nexus_mod
    import tools.capture_nexus_snapshot as cap

    monkeypatch.setenv("NEXUS_API_KEY", "nxk_" + "a" * 20)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cap, "_repo_root", lambda: repo)

    async def partial(symbol: str) -> dict:
        return {
            "signal": {"status": "received", "data": synthetic_surfaces()["signal"]},
            "metrics": {"status": "unavailable", "reason": "NEXUS_TIMEOUT"},
            "equity": {"status": "received", "data": synthetic_surfaces()["equity"]},
            "trades": {"status": "received", "data": synthetic_surfaces()["trades"]},
        }

    monkeypatch.setattr(nexus_mod, "read_nexus", partial)
    out = repo / "evidence" / "nexus-candidate-v1"
    code = cap.main([])
    assert code != 0
    assert not out.exists() or not any(out.iterdir())


def test_secret_scan_passes_over_outputs(tmp_path: Path) -> None:
    from tools.secret_scan import scan

    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    assert scan(directory) == []
    # Serialize a verified replay from the synthetic dir via monkeypatched loader.
    # Use a separate temp scan dir for serialized output.
    out_dir = tmp_path / "serialized"
    out_dir.mkdir()
    # Build replay without touching production paths by temporarily patching.
    import app.recorded_nexus as recmod

    original = recmod._snapshot_dir
    try:
        recmod._snapshot_dir = lambda snapshot_id="candidate-v1": directory  # type: ignore[assignment]
        replay_obj = recmod.replay_recorded_nexus_evidence()
        (out_dir / "replay.json").write_text(
            json.dumps(replay_obj.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
        )
    finally:
        recmod._snapshot_dir = original  # type: ignore[assignment]
    assert scan(out_dir) == []


def test_loader_never_mutates_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "snapshot"
    write_synthetic_snapshot(directory)
    monkeypatch.setattr(rec, "_snapshot_dir", lambda snapshot_id="candidate-v1": directory)
    _, loaded = rec.load_snapshot("candidate-v1")
    before_loaded = json.dumps(loaded, sort_keys=True)
    rec.replay_recorded_nexus_evidence()
    assert json.dumps(loaded, sort_keys=True) == before_loaded


def test_rest_rejects_query_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXUS_API_KEY", raising=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/nexus/replay/candidate-v1?snapshot=other")
        assert response.status_code == 400
        assert response.json() == {"detail": "QUERY_PARAMETERS_NOT_ALLOWED"}
        get_with_body = client.request(
            "GET",
            "/v1/nexus/replay/candidate-v1",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        assert get_with_body.status_code == 400
        assert get_with_body.json() == {"detail": "BODY_NOT_ALLOWED"}
        post = client.post("/v1/nexus/replay/candidate-v1", json={})
        assert post.status_code in (404, 405)


def test_openapi_exposes_replay() -> None:
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
        assert "/v1/nexus/replay/candidate-v1" in schema["paths"]
        assert "get" in schema["paths"]["/v1/nexus/replay/candidate-v1"]
        response = schema["paths"]["/v1/nexus/replay/candidate-v1"]["get"]["responses"]["200"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/RecordedNexusReplay")


def test_capture_rejects_arbitrary_output_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.nexus as nexus_mod
    import tools.capture_nexus_snapshot as cap

    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "must-not-touch"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("preserve", encoding="utf-8")
    called = False

    async def forbidden_read(symbol: str) -> dict:
        nonlocal called
        called = True
        raise AssertionError("network must not run")

    monkeypatch.setattr(cap, "_repo_root", lambda: repo)
    monkeypatch.setattr(nexus_mod, "read_nexus", forbidden_read)
    monkeypatch.setenv("NEXUS_API_KEY", "nxk_" + "a" * 20)
    code = cap.main(["--output-dir", str(outside), "--allow-overwrite"])
    assert code == 1
    assert called is False
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_capture_secret_scanner_finding_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.nexus as nexus_mod
    import tools.capture_nexus_snapshot as cap
    import tools.secret_scan as scanner

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cap, "_repo_root", lambda: repo)
    monkeypatch.setenv("NEXUS_API_KEY", "nxk_" + "a" * 20)

    async def fake_read(symbol: str) -> dict:
        return {
            label: {"status": "received", "data": data}
            for label, data in synthetic_surfaces().items()
        }

    monkeypatch.setattr(nexus_mod, "read_nexus", fake_read)
    monkeypatch.setattr(
        scanner,
        "scan",
        lambda root: [{"rule": "synthetic-finding", "path": ".", "line": 0}],
    )
    output = repo / "evidence" / "nexus-candidate-v1"
    assert cap.main([]) == 1
    assert not output.exists()


@pytest.mark.parametrize("argument", [
    ["--strategy-name", "Other"],
    ["--strategy-id", "str_other"],
    ["--expected-run-id", "bt-other"],
    ["--symbol", "ETH/USDT"],
])
def test_capture_rejects_unbound_identity(argument: list[str]) -> None:
    import tools.capture_nexus_snapshot as cap

    assert cap.main(argument) == 1


def test_docker_image_packages_recorded_evidence_directory() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "COPY evidence ./evidence" in dockerfile
    assert "evidence/.capture-*" in dockerignore
    assert (ROOT / "evidence").is_dir()
