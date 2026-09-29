"""Recorded Nexus evidence replay: historical snapshot, never live.

Loads only the allowlisted ``candidate-v1`` snapshot from
``evidence/nexus-candidate-v1/``, verifies integrity with the existing
Nexus sanitizer, and replays through the existing production
reconciliation and release-gate engine.

This is recorded historical evidence, not a live Nexus call, not
independent attestation, not proof of profitability, and not trading
authorization. No network calls are performed here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app.contracts import ReleaseGateResult, StrictModel

SNAPSHOT_ID = "candidate-v1"
SNAPSHOT_DIRNAME = "nexus-candidate-v1"
STRATEGY_NAME = "SKLab AlphaLitmus Candidate v1"
STRATEGY_ID = "str_b840280ce037"
EXPECTED_RUN_ID = "bt-7544746ff32d"
SYMBOL = "BTC/USDT"
MANIFEST_SCHEMA_VERSION = "nexus-recorded-snapshot-2"
REPLAY_SCHEMA_VERSION: Literal["alphalitmus-recorded-replay-1"] = "alphalitmus-recorded-replay-1"
SOURCE = "OlaXBT Nexus MCP"
INTEGRITY_SCOPE: Literal["source_commit_bound_content_consistency_not_authenticity"] = (
    "source_commit_bound_content_consistency_not_authenticity"
)
STRATEGY_IDENTITY_BINDING = "operator_asserted_strategy_bound_key_not_returned_by_read_surfaces"
TOOL_FOR_SURFACE = {
    "equity": "get_strategy_equity",
    "metrics": "get_strategy_metrics",
    "signal": "get_strategy_signal",
    "trades": "get_strategy_trades",
}
EVIDENCE_FILES = ("signal.json", "metrics.json", "equity.json", "trades.json")
ALLOWED_FILES = frozenset([*EVIDENCE_FILES, "manifest.json"])

MAX_SNAPSHOT_BYTES = 2_000_000
MAX_FILE_BYTES = 2_000_000
MAX_DEPTH = 32
MAX_ROWS = 10_000
MAX_STRING_CHARS = 10_000
MAX_NUMBER_ABS = 1e15
MAX_FILES = 5

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CREATED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

DISCLOSURE = (
    "Recorded historical Nexus evidence — not a live market call, not independently "
    "source-authenticated, and not evidence of future profitability."
)

PUBLIC_CODES = ("RECORDED_EVIDENCE_UNAVAILABLE", "RECORDED_EVIDENCE_INVALID", "RECORDED_EVIDENCE_INTEGRITY_FAILED")


class RecordedEvidenceError(Exception):
    def __init__(self, code: str) -> None:
        if code not in PUBLIC_CODES:
            code = "RECORDED_EVIDENCE_INVALID"
        super().__init__(code)
        self.code = code


class RecordedNexusReplay(StrictModel):
    replay_schema_version: Literal["alphalitmus-recorded-replay-1"] = "alphalitmus-recorded-replay-1"
    snapshot_id: Literal["candidate-v1"] = "candidate-v1"
    strategy_name: Literal["SKLab AlphaLitmus Candidate v1"] = "SKLab AlphaLitmus Candidate v1"
    strategy_id: Literal["str_b840280ce037"] = "str_b840280ce037"
    run_id: Literal["bt-7544746ff32d"] = "bt-7544746ff32d"
    symbol: Literal["BTC/USDT"] = "BTC/USDT"
    captured_at: str
    historical: Literal[True] = True
    live: Literal[False] = False
    no_execution: Literal[True] = True
    profitability_claimed: Literal[False] = False
    evidence_surfaces: list[str]
    file_hashes: dict[str, str]
    aggregate_snapshot_sha256: str
    snapshot_integrity: Literal["verified"] = "verified"
    integrity_scope: Literal["source_commit_bound_content_consistency_not_authenticity"] = INTEGRITY_SCOPE
    disclosure: str
    limitations: list[str]
    release_gate: ReleaseGateResult


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _snapshot_dir(snapshot_id: str) -> Path:
    if snapshot_id != SNAPSHOT_ID:
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
    if any(token in snapshot_id for token in ("/", "\\", ".", ":")):
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
    return _repo_root() / "evidence" / SNAPSHOT_DIRNAME


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON key")
        result[name] = value
    return result


def _check_bounds(value: object, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("depth exceeded")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or len(key) > MAX_STRING_CHARS:
                raise ValueError("invalid key")
            _check_bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ROWS:
            raise ValueError("row count exceeded")
        for child in value:
            _check_bounds(child, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise ValueError("string too long")
    elif isinstance(value, bool):
        return
    elif isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or abs(float(value)) > MAX_NUMBER_ABS:
            raise ValueError("number out of bounds")
    elif value is not None:
        raise ValueError("unsupported JSON value")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode("utf-8")


def _load_json_file(raw: bytes) -> Any:
    if len(raw) > MAX_FILE_BYTES:
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
    try:
        _check_bounds(value)
    except (ValueError, RecursionError, OverflowError):
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
    if raw != _canonical_bytes(value):
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
    return value


def load_snapshot(snapshot_id: str = SNAPSHOT_ID) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and verify the allowlisted snapshot. Never mutates loaded input."""
    try:
        directory = _snapshot_dir(snapshot_id)
        try:
            entries = sorted(entry.name for entry in directory.iterdir())
        except OSError:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_UNAVAILABLE") from None
        if sorted(entries) != sorted(ALLOWED_FILES) or len(entries) != MAX_FILES:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        raw_files: dict[str, bytes] = {}
        total = 0
        for name in sorted(ALLOWED_FILES):
            candidate = directory / name
            # Reject traversal/symlink escapes without exposing paths.
            try:
                if candidate.is_symlink() or candidate.resolve().parent != directory.resolve():
                    raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
                raw = candidate.read_bytes()
            except OSError:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_UNAVAILABLE") from None
            total += len(raw)
            if total > MAX_SNAPSHOT_BYTES:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            raw_files[name] = raw
        manifest = _load_json_file(raw_files["manifest.json"])
        if not isinstance(manifest, dict):
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        # Manifest invariants.
        if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("snapshot_id") != SNAPSHOT_ID:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("strategy_name") != STRATEGY_NAME or manifest.get("strategy_id") != STRATEGY_ID:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("expected_run_id") != EXPECTED_RUN_ID or manifest.get("symbol") != SYMBOL:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        captured_at = manifest.get("captured_at")
        if not isinstance(captured_at, str) or _CREATED_AT.fullmatch(captured_at) is None:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        try:
            parsed = datetime.fromisoformat(captured_at)
            if parsed.tzinfo != timezone.utc or parsed.isoformat(timespec="seconds") != captured_at:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            as_of = parsed.timestamp()
            if not math.isfinite(as_of) or not 0 <= as_of <= 253402214400:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        except (ValueError, OverflowError):
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
        if manifest.get("evidence_classification") != "nexus_snapshot":
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("tools") != TOOL_FOR_SURFACE:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        files = manifest.get("files")
        if not isinstance(files, dict) or sorted(files) != sorted(EVIDENCE_FILES):
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        for name in EVIDENCE_FILES:
            digest = files.get(name)
            if not isinstance(digest, str) or _HEX64.fullmatch(digest) is None:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            actual = hashlib.sha256(raw_files[name]).hexdigest()
            if actual != digest:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INTEGRITY_FAILED")
        aggregate = manifest.get("aggregate_snapshot_sha256")
        if not isinstance(aggregate, str) or _HEX64.fullmatch(aggregate) is None:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        aggregate_input = copy.deepcopy(manifest)
        aggregate_input.pop("aggregate_snapshot_sha256", None)
        recomputed_aggregate = hashlib.sha256(_canonical_bytes(aggregate_input)).hexdigest()
        if recomputed_aggregate != aggregate:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INTEGRITY_FAILED")
        if manifest.get("source") != SOURCE:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("integrity_scope") != INTEGRITY_SCOPE:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("strategy_identity_binding") != STRATEGY_IDENTITY_BINDING:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("historical") is not True or manifest.get("live") is not False:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if manifest.get("no_execution") is not True or manifest.get("profitability_claimed") is not False:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        limitations = manifest.get("limitations")
        if (
            not isinstance(limitations, list)
            or not 1 <= len(limitations) <= 20
            or not all(isinstance(item, str) and 1 <= len(item) <= 2000 for item in limitations)
        ):
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        joined = " ".join(limitations).lower()
        for required in ("not a live", "run", "recent fills", "integrity", "profitability"):
            if required not in joined:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        # Load and re-sanitize every surface.
        from app.nexus import sanitize

        surfaces: dict[str, Any] = {}
        for filename in EVIDENCE_FILES:
            label = filename.removesuffix(".json")
            data = _load_json_file(raw_files[filename])
            if not isinstance(data, dict) or not data:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            before = copy.deepcopy(data)
            try:
                cleaned = sanitize(label, data)
            except (ValueError, TypeError, RecursionError):
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
            if cleaned != before or cleaned != data:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            if data != before:
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
            surfaces[label] = cleaned
        # Identity bindings.
        if surfaces["signal"].get("symbol") != SYMBOL:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if surfaces["equity"].get("run_id") != EXPECTED_RUN_ID:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if surfaces["trades"].get("run_id") != EXPECTED_RUN_ID:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        if "run_id" in surfaces["signal"] or "run_id" in surfaces["metrics"]:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        manifest_copy = copy.deepcopy(manifest)
        surfaces_copy = copy.deepcopy(surfaces)
        return manifest_copy, surfaces_copy
    except RecordedEvidenceError:
        raise
    except Exception:
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None


def replay_recorded_nexus_evidence(snapshot_id: str = SNAPSHOT_ID) -> RecordedNexusReplay:
    """Inject verified recorded evidence into the production engine.

    Uses existing reconcile/challenge/release-gate/verify path with the
    snapshot capture time as historical as_of. Deterministic and
    byte-identical across repeated calls. Performs zero network calls.
    """
    from app.certificates import verify_report
    from app.contracts import ChallengeRequest
    from app.lab import _challenge_impl
    from app.release_gate import project
    from app.transport import TransportError

    try:
        manifest, surfaces = load_snapshot(snapshot_id)
        captured_at = manifest["captured_at"]
        assert isinstance(captured_at, str)
        as_of = datetime.fromisoformat(captured_at).timestamp()
        request = ChallengeRequest(mode="nexus", symbol=SYMBOL, as_of=as_of)
        evidence = {
            label: {"status": "received", "data": copy.deepcopy(surfaces[label])}
            for label in ("signal", "metrics", "equity", "trades")
        }
        before_surfaces = copy.deepcopy(surfaces)
        report = _challenge_impl(request, evidence, captured_at)
        if surfaces != before_surfaces:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID")
        try:
            gate = project(report)
        except TransportError as exc:
            if exc.code == "REPORT_VERIFICATION_FAILED":
                raise RecordedEvidenceError("RECORDED_EVIDENCE_INTEGRITY_FAILED") from None
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
        if not verify_report(report).valid:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INTEGRITY_FAILED")
        if gate.source_report_verified is not True:
            raise RecordedEvidenceError("RECORDED_EVIDENCE_INTEGRITY_FAILED")
        return RecordedNexusReplay(
            captured_at=captured_at,
            evidence_surfaces=sorted(surfaces.keys()),
            file_hashes=dict(sorted(manifest["files"].items())),
            aggregate_snapshot_sha256=manifest["aggregate_snapshot_sha256"],
            disclosure=DISCLOSURE,
            limitations=list(manifest["limitations"]),
            release_gate=gate,
        )
    except RecordedEvidenceError:
        raise
    except Exception:
        raise RecordedEvidenceError("RECORDED_EVIDENCE_INVALID") from None
