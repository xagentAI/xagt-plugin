"""
run_real_showcase.py · run the full MCPForge chain against a real, useful API that agents actually call,
producing checkable end-to-end evidence (real 2xx verification + real usage metering + real billing).

No deployment, no networked submission. It runs locally and calls real public endpoints for Verify and Metering.
Usage: NO_PROXY=* .venv/Scripts/python.exe examples/run_real_showcase.py
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import metering  # noqa: E402

SPEC = str(HERE / "github-openapi.json")
OUT = HERE / "real_showcase_result.json"
API_NAME = "github_live"


async def main() -> None:
    result: dict = {}

    # 1) VERIFY — call the public endpoints for real; only 2xx counts as passed
    verify = await core.verify_api_async(SPEC, max_ops=20)
    result["verify"] = {
        "base_url": verify["base_url"],
        "total_operations": verify["total_operations"],
        "filtered_operations": verify["filtered_operations"],
        "passed": verify["passed"],
        "verified": verify["verified"],
        "verdict": verify["verdict"],
        "detail": [
            {
                "operation_id": r["operation_id"],
                "http_status": r["http_status"],
                "passed": r["passed"],
                "status": r["status"],
                "latency_ms": r["latency_ms"],
            }
            for r in verify["results"]
        ],
    }

    # 2) BUILD / REGISTER — register the spec into the local registry (persisted)
    reg = await core._registry.register_async(API_NAME, SPEC)
    result["register"] = {"name": API_NAME, "ops": reg.get("operations")}

    # 3) Make several real calls — producing checkable real usage metering (the raw material for MONETIZE)
    calls = []
    for op_id in ["getZen", "getRateLimit", "listPublicEvents"]:
        for _ in range(2):
            r = await core._registry.call_async(API_NAME, op_id, {})
            calls.append(
                {
                    "operation_id": op_id,
                    "ok": r.get("ok"),
                    "status_code": r.get("status_code"),
                    "metered": r.get("metered", False),
                }
            )
    result["calls"] = calls

    # 4) MONETIZE — real usage report plus a tiered invoice
    report = metering.get_meter().report(API_NAME)
    result["usage_report"] = report
    invoice = metering.get_meter().simulate_invoice(API_NAME, pricing_tier="pro", basis="actual")
    result["invoice"] = invoice

    # 5) BUILD manifest — marketplace-format listing (pricing tier plus the real usage mapping)
    manifest = await core.build_manifest_async(
        API_NAME,
        source=SPEC,
        category="api-tool",
        pricing_tier="pro",
        description="GitHub public REST API: genuinely callable and ready for per-call billing.",
        currency="USD",
    )
    result["manifest"] = {
        "name": manifest.get("listing", {}).get("name"),
        "pricing_tier": manifest.get("pricing", {}).get("tier"),
        "currency": manifest.get("pricing", {}).get("currency"),
        "tool_count": len(manifest.get("tools", [])),
        "billing_model": manifest.get("pricing", {}).get("billing_model"),
    }

    # 6) Walkthrough page check: the health endpoint
    result["health"] = core.health_check()

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] evidence written to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
