"""Run the reviewer-facing APIVouch capability and verify its evidence receipt."""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def _source_commit() -> str:
    configured = os.environ.get("GIT_COMMIT", "").strip()
    if configured:
        return configured
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("GIT_COMMIT", _source_commit())
os.environ.setdefault("PROJECT_SLUG", "apivouch")

from fastapi.testclient import TestClient

from app.main import app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call three independent public exchange-rate providers.",
    )
    args = parser.parse_args()
    client = TestClient(app)

    initialized = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
    )
    initialized.raise_for_status()
    listed = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    listed.raise_for_status()

    capability_path = "/api/outcomes/live-demo" if args.live else "/api/outcomes/demo"
    capability = client.post(capability_path)
    capability.raise_for_status()
    receipt = capability.json()

    verified = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "apivouch_verify_receipt",
                "arguments": {"receipt_id": receipt["receipt_id"]},
            },
        },
    )
    verified.raise_for_status()
    verification = verified.json()["result"]["structuredContent"]
    health = client.get("/health").json()
    deployment_proof = client.get("/.well-known/xagent-verification.json").json()

    tools = [tool["name"] for tool in listed.json()["result"]["tools"]]
    result = {
        "mode": "live" if args.live else "deterministic-fixture",
        "mcp_server": initialized.json()["result"]["serverInfo"]["name"],
        "mcp_tools": tools,
        "verdict": receipt["verdict"],
        "selected_provider": receipt["selected_provider"],
        "agreement": receipt["agreement"],
        "receipt_id": receipt["receipt_id"],
        "receipt_integrity_valid": verification["integrity_valid"],
        "health_commit": health["commit"],
        "deployment_proof": deployment_proof,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    expected_tools = {
        "apivouch_resolve_verified_outcome",
        "apivouch_verify_receipt",
    }
    passed = (
        receipt["verdict"] == "VERIFIED"
        and verification["integrity_valid"] is True
        and expected_tools <= set(tools)
        and health["commit"] == deployment_proof["commit"]
        and deployment_proof["slug"] == "apivouch"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
