"""Capture a recorded Nexus evidence snapshot using only read-only tools.

Uses the existing bounded ``app.nexus.read_nexus`` path (four read-only
tools: get_strategy_signal, get_strategy_metrics, get_strategy_equity,
get_strategy_trades). Never calls run_backtest, paper trading, orders,
wallet signing, or any state-changing Nexus operation.

The API key is read only from the process environment and is never
printed, logged, or persisted. Only sanitized, allowlisted evidence is
written, as canonical JSON (UTF-8, sorted keys, compact separators,
no NaN/Infinity).

If NEXUS_API_KEY is absent this tool reports CAPTURE REQUIRED and writes
nothing to the production snapshot directory.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOUND_STRATEGY_NAME = "SKLab AlphaLitmus Candidate v1"
BOUND_STRATEGY_ID = "str_b840280ce037"
BOUND_RUN_ID = "bt-7544746ff32d"
BOUND_SYMBOL = "BTC/USDT"
DEFAULT_OUTPUT_DIR = "evidence/nexus-candidate-v1"
MANIFEST_SCHEMA_VERSION = "nexus-recorded-snapshot-2"
SNAPSHOT_ID = "candidate-v1"
INTEGRITY_SCOPE = "source_commit_bound_content_consistency_not_authenticity"
EVIDENCE_FILES = ("signal.json", "metrics.json", "equity.json", "trades.json")
TOOL_FOR_SURFACE = {
    "signal": "get_strategy_signal",
    "metrics": "get_strategy_metrics",
    "equity": "get_strategy_equity",
    "trades": "get_strategy_trades",
}
SURFACE_FOR_FILE = {
    "signal.json": "signal",
    "metrics.json": "metrics",
    "equity.json": "equity",
    "trades.json": "trades",
}

LIMITATIONS = [
    "Recorded historical Nexus snapshot; not a live Nexus call.",
    "Not independent authenticity attestation of the strategy or run.",
    "Not proof of profitability and not trading authorization.",
    "Signal and metrics do not expose a run ID; full metrics-to-run binding is unavailable.",
    "Trades are recent fills, not an attested complete history.",
    "Hashes establish content integrity, not authorship or future performance.",
    "Strategy identity is operator asserted from the strategy-bound key; the read surfaces do not return it.",
]


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy-name", default=BOUND_STRATEGY_NAME)
    parser.add_argument("--strategy-id", default=BOUND_STRATEGY_ID)
    parser.add_argument("--expected-run-id", default=BOUND_RUN_ID)
    parser.add_argument("--symbol", default=BOUND_SYMBOL)
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Must resolve to the fixed repository path {DEFAULT_OUTPUT_DIR!r}.",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Permit replacing an existing production snapshot.",
    )
    return parser


def safe_command(args: argparse.Namespace) -> str:
    return "python -m tools.capture_nexus_snapshot"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _fixed_output(raw_output: str | None) -> Path:
    """Resolve only the repository-owned production snapshot destination."""
    root = _repo_root().resolve(strict=True)
    expected = root / "evidence" / "nexus-candidate-v1"
    if raw_output is None:
        candidate = expected
    else:
        candidate = Path(raw_output)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ValueError("invalid output path") from exc
    if resolved != expected:
        raise ValueError("output path is not the fixed snapshot destination")
    parent = expected.parent
    if parent.exists() and _is_link_or_junction(parent):
        raise ValueError("evidence directory cannot be a link")
    if expected.exists() and _is_link_or_junction(expected):
        raise ValueError("snapshot directory cannot be a link")
    return expected


def _validate_bound_identity(args: argparse.Namespace) -> bool:
    return (
        args.strategy_name == BOUND_STRATEGY_NAME
        and args.strategy_id == BOUND_STRATEGY_ID
        and args.expected_run_id == BOUND_RUN_ID
        and args.symbol == BOUND_SYMBOL
    )


def _validate_existing_snapshot(output: Path) -> None:
    """Refuse to replace an unexpected tree, even at the fixed destination."""
    if not output.exists():
        return
    if not output.is_dir() or _is_link_or_junction(output):
        raise ValueError("invalid existing snapshot")
    allowed = {*EVIDENCE_FILES, "manifest.json"}
    entries = list(output.iterdir())
    if {entry.name for entry in entries} != allowed:
        raise ValueError("existing snapshot has unexpected entries")
    if any(not entry.is_file() or _is_link_or_junction(entry) for entry in entries):
        raise ValueError("existing snapshot contains non-files")


def aggregate_manifest_hash(manifest_without_aggregate: dict[str, Any]) -> str:
    """Bind file hashes and all security-relevant manifest metadata."""
    return sha256_bytes(canonical_bytes(manifest_without_aggregate))


def secret_scan_texts(texts: list[bytes], key: str) -> bool:
    """Return True when no secret-shaped content is present."""
    if key and any(key.encode("utf-8") in text for text in texts):
        return False
    # Reuse the repository heuristic without importing file-system side effects.
    # Never print matching text; only return a boolean.
    import re

    patterns = [
        re.compile(r"\bnxk_[A-Za-z0-9_-]{20,}\b"),
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ]
    for text in texts:
        try:
            decoded = text.decode("utf-8")
        except UnicodeDecodeError:
            return False
        for pattern in patterns:
            if pattern.search(decoded):
                # The allowlisted run/strategy identifiers are not nxk_ keys, so
                # any match here is a genuine secret-shaped finding.
                return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not _validate_bound_identity(args):
        print("CAPTURE_FAILED: identity must match Candidate v1 constants", file=sys.stderr)
        return 1
    try:
        output = _fixed_output(args.output_dir)
        _validate_existing_snapshot(output)
    except (OSError, ValueError):
        print("CAPTURE_FAILED: unsafe output destination", file=sys.stderr)
        return 1
    key = os.getenv("NEXUS_API_KEY", "")
    if not key:
        print("CAPTURE REQUIRED")
        print(
            "NEXUS_API_KEY is absent. No production snapshot was written. "
            "Synthetic fixtures remain test-only and no public replay is exposed."
        )
        print("Run later with an authorized strategy-bound key in the environment:")
        print("  " + safe_command(args))
        return 2
    # Refuse to overwrite an existing production snapshot unless explicitly allowed.
    if output.exists() and not args.allow_overwrite:
        print(
            "Refusing to overwrite existing snapshot. "
            "Pass --allow-overwrite to replace it explicitly.",
            file=sys.stderr,
        )
        return 1
    # Late import so --help and CAPTURE REQUIRED paths never require Nexus deps.
    try:
        from app.nexus import SURFACES, read_nexus, sanitize
    except ImportError:
        print("CAPTURE_FAILED", file=sys.stderr)
        return 1

    try:
        evidence = asyncio.run(read_nexus(args.symbol))
    except Exception:
        print("CAPTURE_FAILED", file=sys.stderr)
        return 1
    # Require all four surfaces to have status=received.
    for label in SURFACES:
        surface = evidence.get(label)
        if not isinstance(surface, dict) or surface.get("status") != "received":
            print(f"CAPTURE_FAILED: surface {label} not received", file=sys.stderr)
            return 1
        data = surface.get("data")
        if not isinstance(data, dict) or not data:
            print(f"CAPTURE_FAILED: surface {label} empty", file=sys.stderr)
            return 1
    # Verify equity and trades both identify exactly the expected run ID.
    try:
        equity_data = sanitize("equity", evidence["equity"].get("data"))
        trades_data = sanitize("trades", evidence["trades"].get("data"))
        signal_data = sanitize("signal", evidence["signal"].get("data"))
        metrics_data = sanitize("metrics", evidence["metrics"].get("data"))
    except (ValueError, TypeError, RecursionError):
        print("CAPTURE_FAILED: sanitization rejected evidence", file=sys.stderr)
        return 1
    if equity_data.get("run_id") != args.expected_run_id or trades_data.get("run_id") != args.expected_run_id:
        print("CAPTURE_FAILED: run ID binding mismatch", file=sys.stderr)
        return 1
    # Preserve the documented limitation: signal and metrics do not expose a run ID.
    if "run_id" in signal_data or "run_id" in metrics_data:
        print("CAPTURE_FAILED: unexpected run binding in signal/metrics", file=sys.stderr)
        return 1
    # Persist only sanitized, allowlisted evidence.
    sanitized: dict[str, Any] = {
        "signal": signal_data,
        "metrics": metrics_data,
        "equity": equity_data,
        "trades": trades_data,
    }
    if not all(sanitized[label] for label in SURFACES):
        print("CAPTURE_FAILED: sanitized evidence empty", file=sys.stderr)
        return 1
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    file_payloads: dict[str, bytes] = {}
    for filename in EVIDENCE_FILES:
        label = SURFACE_FOR_FILE[filename]
        file_payloads[filename] = canonical_bytes(sanitized[label])
    file_hashes = {name: sha256_bytes(payload) for name, payload in file_payloads.items()}
    manifest: dict[str, Any] = {
        "captured_at": captured_at,
        "evidence_classification": "nexus_snapshot",
        "expected_run_id": args.expected_run_id,
        "files": dict(sorted(file_hashes.items())),
        "historical": True,
        "limitations": list(LIMITATIONS),
        "live": False,
        "no_execution": True,
        "profitability_claimed": False,
        "integrity_scope": INTEGRITY_SCOPE,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "snapshot_id": SNAPSHOT_ID,
        "source": "OlaXBT Nexus MCP",
        "strategy_identity_binding": "operator_asserted_strategy_bound_key_not_returned_by_read_surfaces",
        "strategy_id": args.strategy_id,
        "strategy_name": args.strategy_name,
        "symbol": args.symbol,
        "tools": dict(sorted(TOOL_FOR_SURFACE.items())),
    }
    aggregate = aggregate_manifest_hash(manifest)
    manifest["aggregate_snapshot_sha256"] = aggregate
    manifest_payload = canonical_bytes(manifest)
    # Final recursive secret scan before writing success.
    if not secret_scan_texts([*file_payloads.values(), manifest_payload], key):
        print("CAPTURE_FAILED: secret scan rejected evidence", file=sys.stderr)
        return 1
    # Atomic writes: temporary directory in the same parent, then rename.
    parent = output.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        print("CAPTURE_FAILED", file=sys.stderr)
        return 1
    temp_dir: str | None = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=".capture-tmp-", dir=str(parent))
        temp_path = Path(temp_dir)
        for filename in [*EVIDENCE_FILES, "manifest.json"]:
            payload = manifest_payload if filename == "manifest.json" else file_payloads[filename]
            (temp_path / filename).write_bytes(payload)
        # Verify what was written before publishing.
        for filename in [*EVIDENCE_FILES, "manifest.json"]:
            expected = manifest_payload if filename == "manifest.json" else file_payloads[filename]
            if (temp_path / filename).read_bytes() != expected:
                raise OSError("write verification failed")
        # Run the repository's complete scanner over the exact staged snapshot.
        from tools.secret_scan import scan

        if scan(temp_path):
            raise OSError("secret scan rejected staged snapshot")
        backup_path: Path | None = None
        if output.exists():
            if not args.allow_overwrite:
                raise OSError("snapshot exists")
            backup_path = Path(tempfile.mkdtemp(prefix=".capture-backup-", dir=str(parent)))
            backup_path.rmdir()
            os.replace(output, backup_path)
        try:
            os.replace(temp_dir, output)
        except OSError:
            if backup_path is not None and backup_path.exists() and not output.exists():
                os.replace(backup_path, output)
            raise
        temp_dir = None
        if backup_path is not None:
            # This path is generated inside the fixed evidence directory and never
            # derived from caller input. Cleanup is best-effort after publication.
            shutil.rmtree(backup_path, ignore_errors=True)
    except OSError:
        print("CAPTURE_FAILED", file=sys.stderr)
        return 1
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
    # Success output contains only hashes and identity, never the key.
    print("CAPTURE_OK")
    print(f"snapshot: {output.as_posix()}")
    print(f"strategy: {args.strategy_name} {args.strategy_id}")
    print(f"run: {args.expected_run_id} symbol: {args.symbol}")
    print(f"aggregate: {aggregate}")
    return 0


def _entrypoint() -> int:
    """Keep unexpected local/runtime details out of terminal capture logs."""
    try:
        return main()
    except Exception:
        print("CAPTURE_FAILED", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
