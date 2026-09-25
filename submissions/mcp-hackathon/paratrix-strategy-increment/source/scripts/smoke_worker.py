#!/usr/bin/env python3
"""Exercise a local Worker over HTTP, then verify persistence after a dev restart.

Run ``--phase before-restart`` against a local Wrangler process, restart that
process with the same local state directory, then run ``--phase after-restart``.
State contains temporary session cookies and is written with mode 0600. Only
local hosts are accepted; this suite creates disposable quota test records.
Reported durations are local end-to-end wall times, not Cloudflare CPU timings.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import http.cookies
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request

COOKIE_NAME = "strategy_increment_session"


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def require(condition, description):
    if not condition:
        raise AssertionError(description)


class Session:
    def __init__(self, origin, cookie=""):
        self.origin = origin
        self.cookie = cookie

    def call(self, path, body=None, *, headers=None, raw=None):
        supplied = dict(headers or {})
        if body is not None:
            raw = encoded(body)
        if raw is not None:
            supplied.setdefault("Content-Type", "application/json")
        if self.cookie:
            supplied["Cookie"] = f"{COOKIE_NAME}={self.cookie}"
        request = Request(self.origin + path, data=raw, headers=supplied)
        start = perf_counter()
        try:
            response = build_opener(ProxyHandler({})).open(request, timeout=120)
        except HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            cookie = http.cookies.SimpleCookie(response.headers.get("Set-Cookie", ""))
            if COOKIE_NAME in cookie:
                self.cookie = cookie[COOKIE_NAME].value
            content_type = response.headers.get("Content-Type", "")
            value = json.loads(payload) if "application/json" in content_type else payload
            return response.status, value, perf_counter() - start

    def expect(self, path, status=200, body=None, **kwargs):
        actual, value, elapsed = self.call(path, body, **kwargs)
        require(actual == status, f"{path}: expected HTTP {status}, received {actual}")
        return value, elapsed


def make_curve(name, size, variant):
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)

    def stamp(day):
        return (start + timedelta(days=day)).isoformat().replace("+00:00", "Z")

    with localcontext() as context:
        context.prec = 28
        points = [
            {
                "timestamp": stamp(day),
                "equity": str(
                    Decimal(10000 + (day * (31 + variant)) % 970 - day % 53)
                    + Decimal(day) / Decimal(97 + variant * 2)
                ),
            }
            for day in range(1, size + 1)
        ]
    return {
        "schema_version": 1,
        "name": name,
        "strategy_id": "worker-smoke-" + name,
        "run_id": "local-disposable-v1",
        "source_kind": "inline_simulation",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "smoke-synthetic-zero-fees-v1",
        "initial": {"timestamp": stamp(0), "equity": "10000.12345678901234567890123"},
        "points": points,
        "provenance": {
            "description": "Generated simulation for local runtime verification; no market or account data.",
            "data_version": "worker-smoke-v1",
            "observed_before": False,
        },
    }


def pair(session, size):
    snapshots = [
        session.expect("/v1/data-snapshots", 201, {"curve": make_curve(name, size, index)})[0]
        for index, name in enumerate(("baseline", "candidate"))
    ]
    return {
        "baseline_snapshot_id": snapshots[0]["snapshot_id"],
        "candidate_snapshot_id": snapshots[1]["snapshot_id"],
        "mode": "declared_holdout",
        "data_seen": False,
    }


def parallel_requests(session, path, body, count=8):
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(lambda _: session.call(path, body), range(count)))


def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def replay(source, evidence):
    result = subprocess.run(
        [sys.executable, "-m", "app.reproduce", str(evidence)],
        cwd=source, capture_output=True, text=True, check=False,
    )
    require(result.returncode == 0, "Offline evidence reproduction failed")
    value = json.loads(result.stdout)
    require(value["verified"] is True, "Offline evidence reproduction was not verified")
    return {key: value[key] for key in ("verified", "method_version", "payload_sha256")}


def installed_toolchain(source):
    bundle = source / "runtime" / "worker-bundle"
    command = [
        str(bundle / ".venv" / "bin" / "python"), "-c",
        "import importlib.metadata,json; "
        "print(json.dumps({name: importlib.metadata.version(name) "
        "for name in ('workers-py','workers-runtime-sdk','fastapi')}))",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    versions = json.loads(result.stdout)
    versions["wrangler"] = json.loads((bundle / "node_modules/wrangler/package.json").read_text())["version"]
    return versions


def before_restart(args):
    started_at = utc_now()
    toolchain = installed_toolchain(args.source_dir)
    args.output.mkdir(parents=True, exist_ok=True)
    session = Session(args.base_url)
    health, _ = session.expect("/health")
    root, _ = session.expect("/")
    require(b"<html" in root.lower(), "Frontend HTML was not returned")
    session.expect("/static/app.js")
    session.expect("/static/not-public.py", 404)
    source_status, _ = session.expect("/v1/source-status")
    require(source_status["nexus"]["configured"] is False, "Unexpected external Nexus connection")
    session.expect("/v1/nexus/import", 503, {"strategy_ref": "unconfigured"})
    demo_session = Session(args.base_url)
    demo, _ = demo_session.expect("/v1/demo-cases/aimm-weight")
    demo_snapshots = [demo_session.expect("/v1/data-snapshots", 201, {"curve": demo[key]})[0]
                      for key in ("baseline", "candidate")]
    demo_config = {
        "baseline_snapshot_id": demo_snapshots[0]["snapshot_id"],
        "candidate_snapshot_id": demo_snapshots[1]["snapshot_id"],
        "criteria": demo["criteria"], "data_seen": True, "mode": "historical_exploration",
    }
    demo_experiment, _ = demo_session.expect("/v1/experiments", 201, demo_config)
    require(demo_experiment["result"]["display_language"] == "en", "New API results must use English")
    demo_evidence, _ = demo_session.expect(demo_experiment["evidence_url"])
    demo_file = args.output / "aimm-evidence.json"
    demo_file.write_bytes(encoded(demo_evidence) + b"\n")
    demo_replay = replay(args.source_dir, demo_file)
    config = pair(session, 64)
    validation, _ = session.expect(
        "/v1/comparison-inputs/validate", body={key: value for key, value in config.items() if key.endswith("_id")}
    )
    require(validation["comparable"] is True, "Generated daily curves were not comparable")
    concurrent = parallel_requests(session, "/v1/experiments", config)
    require(all(item[0] == 201 for item in concurrent), "Concurrent experiment creation failed")
    modes = [item[1]["provenance"]["effective_mode"] for item in concurrent]
    require(modes.count("declared_holdout") == 1, "Concurrent history lock did not preserve exactly one holdout")
    require(modes.count("historical_exploration") == 7, "Overlapping experiments were not marked exploratory")
    history, _ = session.expect("/v1/experiments")
    require(len(history["experiments"]) == 8, "Concurrent experiments were lost or duplicated")
    example = concurrent[0][1]
    evidence, _ = session.expect(example["evidence_url"])
    evidence_file = args.output / "concurrency-evidence.json"
    evidence_file.write_bytes(encoded(evidence) + b"\n")
    ordinary_replay = replay(args.source_dir, evidence_file)

    foreign = Session(args.base_url)
    foreign.expect("/health")
    foreign.expect(f'/v1/experiments/{example["experiment_id"]}', 404)
    foreign.expect(example["evidence_url"], 404)
    foreign.expect("/v1/comparison-inputs/validate", 404, {
        key: value for key, value in config.items() if key.endswith("_id")
    })
    csrf_error, _ = session.expect("/v1/experiments", 403, config, headers={"Origin": "https://cross-site.invalid"})
    json_error, _ = session.expect("/v1/data-snapshots", 422, raw=b'{"curve":{},"curve":{}}')
    require(encoded(csrf_error).isascii() and encoded(json_error).isascii(), "Technical API errors must use English")

    quota_session = Session(args.base_url)
    quota_session.expect("/health")
    small = {"curve": make_curve("quota", 1, 0)}
    for _ in range(98):
        quota_session.expect("/v1/data-snapshots", 201, small)
    quota_results = parallel_requests(quota_session, "/v1/data-snapshots", small)
    statuses = [item[0] for item in quota_results]
    require(statuses.count(201) == 2 and statuses.count(429) == 6, "Concurrent snapshot quota was not atomic")
    quota_session.expect("/v1/data-snapshots", 429, small)

    large_session = Session(args.base_url)
    large_session.expect("/health")
    large_config = pair(large_session, 5000)
    large, create_seconds = large_session.expect("/v1/experiments", 201, large_config)
    result_bytes = len(encoded(large["result"]))
    require(result_bytes > 2 * 1024 * 1024, "Large test result did not exceed the SQLite row size boundary")
    reread, read_seconds = large_session.expect(f'/v1/experiments/{large["experiment_id"]}')
    require(large == reread, "Large experiment did not round-trip unchanged")
    large_evidence, export_seconds = large_session.expect(large["evidence_url"])
    require(large_evidence["result"] == large["result"], "Large export differs from the saved experiment")
    large_file = args.output / "large-evidence.json"
    large_file.write_bytes(encoded(large_evidence) + b"\n")
    large_replay = replay(args.source_dir, large_file)
    large_history, history_seconds = large_session.expect("/v1/experiments")
    require(len(large_history["experiments"]) == 1, "Large experiment is missing from history")
    require(len(encoded(large_history)) < 4096, "History unexpectedly contains full large results")

    report = {
        "runtime": "local Wrangler/workerd with Python Workers and SQLite Durable Objects",
        "started_at_utc": started_at,
        "http_checks_completed_at_utc": utc_now(),
        "installed_toolchain": toolchain,
        "scope": {"local_only": True, "production_deployment": False, "cloudflare_account_access": False,
                  "data": "Generated simulations and bundled public AIMM examples; no live account data."},
        "health": health,
        "timing_scope": "Local end-to-end wall time; not CPU time or a hosted performance guarantee.",
        "concurrent_experiments": {"requests": 8, "declared_holdout": 1, "historical_exploration": 7},
        "snapshot_quota": {"existing": 98, "concurrent_requests": 8, "created": 2, "http_429": 6},
        "security": {"cross_session_detail_and_export": 404, "cross_session_pair": 404,
                     "cross_origin_write": 403, "duplicate_json_key": 422, "unlisted_static_asset": 404,
                     "technical_errors_ascii": True},
        "recorded_aimm_reproduction": demo_replay,
        "ordinary_reproduction": ordinary_replay,
        "large_record": {
            "daily_points_per_curve": 5000,
            "result_json_bytes": result_bytes,
            "evidence_json_bytes": large_file.stat().st_size,
            "round_trip_equal": True,
            "reproduction": large_replay,
            "wall_seconds": {"create": create_seconds, "read": read_seconds,
                             "export": export_seconds, "history": history_seconds},
        },
        "persistence_after_restart": "not_yet_checked",
    }
    private_state = {
        "base_url": args.base_url,
        "source_sha256": health["source_sha256"],
        "regular": {"cookie": session.cookie, "history_hash": sha(history),
                    "evidence_url": example["evidence_url"], "evidence_hash": sha(evidence)},
        "large": {"cookie": large_session.cookie, "history_hash": sha(large_history),
                  "evidence_url": large["evidence_url"], "evidence_hash": sha(large_evidence)},
    }
    write_private(args.state, private_state)
    (args.output / "worker-smoke-report.json").write_bytes(encoded(report) + b"\n")
    return report


def after_restart(args):
    require(args.state.stat().st_mode & 0o077 == 0, "Session state must have owner-only permissions")
    state = json.loads(args.state.read_text())
    require(state["base_url"] == args.base_url, "Restart verification must use the same local origin")
    health, _ = Session(args.base_url).expect("/health")
    require(health["source_sha256"] == state["source_sha256"], "Source changed across persistence restart")
    for name in ("regular", "large"):
        saved = state[name]
        session = Session(args.base_url, saved["cookie"])
        history, _ = session.expect("/v1/experiments")
        evidence, _ = session.expect(saved["evidence_url"])
        require(sha(history) == saved["history_hash"], f"{name} history changed across restart")
        require(sha(evidence) == saved["evidence_hash"], f"{name} evidence changed across restart")
    report_file = args.output / "worker-smoke-report.json"
    report = json.loads(report_file.read_text())
    report["persistence_after_restart"] = {"regular_history_and_evidence_equal": True,
                                           "large_history_and_evidence_equal": True}
    report["restart_checks_completed_at_utc"] = utc_now()
    report_file.write_bytes(encoded(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--phase", choices=("before-restart", "after-restart"), required=True)
    parser.add_argument("--output", type=Path, default=Path("runtime/worker-smoke"))
    parser.add_argument("--state", type=Path, default=Path("runtime/worker-smoke/session-state.json"))
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    origin = urlsplit(args.base_url)
    require(origin.hostname in {"127.0.0.1", "localhost", "::1"} and origin.scheme == "http",
            "This destructive quota suite only accepts a local HTTP origin")
    args.output = args.output.resolve()
    args.state = args.state.resolve()
    args.source_dir = args.source_dir.resolve()
    report = before_restart(args) if args.phase == "before-restart" else after_restart(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
