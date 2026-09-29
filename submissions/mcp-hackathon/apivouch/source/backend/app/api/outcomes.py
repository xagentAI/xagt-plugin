from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Request

from app.core import config
from app.schemas.api import OutcomeRequest
from app.services.http_client import SafeResponse
from app.services.outcomes import (
    LabStorageUnavailable,
    LabTiming,
    LabWriteConflict,
    canonical_json,
    execute_verified_outcome,
    load_lab_receipt,
    load_receipt_any,
    receipt_authenticity,
    store_lab_receipt,
    store_receipt,
    verify_receipt,
)

router = APIRouter(prefix="/outcomes", tags=["verified outcomes"])

_DEMO_PROVIDER_RESPONSES = {
    "/demo/providers/atlas": (200, {"provider": "atlas", "quote": {"amount_usd": 18.40, "eta_minutes": 38}}),
    "/demo/providers/beacon": (200, {"provider": "beacon", "quote": {"amount_usd": 18.44, "eta_minutes": 35}}),
    "/demo/providers/legacy": (200, {"provider": "legacy", "quote": {"amount_usd": "call us", "eta_minutes": None}}),
    "/demo/providers/offline": (503, {"error": "temporarily unavailable"}),
}


async def _demo_request(_method: str, url: str) -> SafeResponse:
    """Deterministic in-process provider transport for the public failure demo."""
    path = next((path for path in _DEMO_PROVIDER_RESPONSES if url.endswith(path)), None)
    if path is None:
        raise ValueError("Unknown demo provider")
    status, payload = _DEMO_PROVIDER_RESPONSES[path]
    return SafeResponse(
        status,
        {"content-type": "application/json"},
        json.dumps(payload).encode("utf-8"),
        url,
    )


async def run_and_store(body: OutcomeRequest) -> dict:
    try:
        receipt = await execute_verified_outcome(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    store_receipt(receipt)
    return receipt


@router.post("/execute")
async def execute(body: OutcomeRequest):
    """Resolve one outcome across independent providers and issue an integrity receipt."""
    return await run_and_store(body)


@router.post("/demo")
async def demo(request: Request):
    if not config.deployment_config_ready():
        raise HTTPException(503, "Deployment configuration unavailable")
    base = config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    expected = {"type": "number", "minimum": 0}
    body = OutcomeRequest.model_validate(
        {
            "goal": "Get a verified same-day delivery quote for parcel DEMO-42",
            "providers": [
                {"name": "Atlas Courier", "url": f"{base}/demo/providers/atlas", "result_path": "quote.amount_usd", "expected_schema": expected, "price_usd": 0.004},
                {"name": "Beacon Logistics", "url": f"{base}/demo/providers/beacon", "result_path": "quote.amount_usd", "expected_schema": expected, "price_usd": 0.003},
                {"name": "Legacy Ship", "url": f"{base}/demo/providers/legacy", "result_path": "quote.amount_usd", "expected_schema": expected, "price_usd": 0.001},
                {"name": "Offline Express", "url": f"{base}/demo/providers/offline", "result_path": "quote.amount_usd", "expected_schema": expected, "price_usd": 0.002},
            ],
            "constraints": {"max_price_usd": 0.01, "max_latency_ms": 3000, "minimum_agreement": 2, "numeric_tolerance_percent": 1},
        }
    )
    receipt = await execute_verified_outcome(
        body.model_dump(),
        require_independent_origins=False,
        request_fn=_demo_request,
    )
    store_receipt(receipt)
    return receipt


@router.post("/live-demo")
async def live_demo():
    """Resolve one public fact across three independently operated data origins."""
    expected = {"type": "number", "exclusiveMinimum": 0}
    body = OutcomeRequest.model_validate(
        {
            "goal": "Resolve the latest public USD to EUR reference rate",
            "providers": [
                {"name": "Frankfurter", "url": "https://api.frankfurter.app/latest?from=USD&to=EUR", "result_path": "rates.EUR", "expected_schema": expected, "price_usd": 0},
                {"name": "Floatrates", "url": "https://www.floatrates.com/daily/usd.json", "result_path": "eur.rate", "expected_schema": expected, "price_usd": 0},
                {"name": "ExchangeRate-API", "url": "https://open.er-api.com/v6/latest/USD", "result_path": "rates.EUR", "expected_schema": expected, "price_usd": 0},
            ],
            "constraints": {"max_price_usd": 0, "max_latency_ms": 8000, "minimum_agreement": 2, "numeric_tolerance_percent": 2},
        }
    )
    return await run_and_store(body)


@router.get("/receipts/{receipt_id}")
async def receipt(receipt_id: str):
    value = load_receipt_any(receipt_id)
    if not value:
        raise HTTPException(404, "Receipt not found")
    return {"receipt": value, "integrity_valid": verify_receipt(value), "authenticity": receipt_authenticity(value)}


# Server-owned Chaos Lab fixture clock. Fixed and documented so repeated runs
# of the same scenario produce identical canonical receipts. This timestamp is
# deterministic fixture evidence and must never be read as live-provider
# freshness. Production execution always uses the real UTC clock instead.
LAB_FIXED_CREATED_AT = "2026-01-01T00:00:00Z"
LAB_FIXED_LATENCY_MS = 5


_LAB_NUMERIC_SCHEMA = {"type": "number", "minimum": 0}
_LAB_CONSTRAINTS = {
    "max_price_usd": 0.01,
    "max_latency_ms": 3000,
    "minimum_agreement": 2,
    "numeric_tolerance_percent": 1,
}

_LAB_SCENARIO_META = {
    "consensus-success": {
        "title": "Consensus success",
        "description": "Two valid numeric providers agree within tolerance; the best eligible provider is selected.",
        "expected_verdict": "VERIFIED",
    },
    "provider-disagreement": {
        "title": "Provider disagreement",
        "description": "Valid provider results fall outside the allowed tolerance, so no consensus group forms.",
        "expected_verdict": "UNVERIFIED",
    },
    "schema-invalid": {
        "title": "Schema invalid",
        "description": "Providers return values that violate the declared numeric schema.",
        "expected_verdict": "UNVERIFIED",
    },
    "upstream-failure": {
        "title": "Upstream failure",
        "description": "Upstream providers deterministically return HTTP failures with no usable result.",
        "expected_verdict": "UNVERIFIED",
    },
    "over-budget": {
        "title": "Over budget",
        "description": "Every provider exceeds the maximum price, so no provider request is attempted.",
        "expected_verdict": "UNVERIFIED",
    },
    "origin-convergence": {
        "title": "Origin convergence",
        "description": "Distinct configured origins resolve to the same final origin and are rejected for provider independence.",
        "expected_verdict": "UNVERIFIED",
    },
}

_LAB_SCENARIO_IDS = tuple(_LAB_SCENARIO_META.keys())


def _lab_payload(scenario_id: str) -> dict:
    """Server-owned goal, providers, and constraints for one lab scenario."""
    schema = dict(_LAB_NUMERIC_SCHEMA)
    constraints = dict(_LAB_CONSTRAINTS)
    if scenario_id == "consensus-success":
        return {
            "goal": "Lab consensus success: agree on a deterministic delivery quote",
            "providers": [
                {"name": "Lab Alpha", "url": "https://lab-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.004},
                {"name": "Lab Beta", "url": "https://lab-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.003},
                {"name": "Lab Gamma", "url": "https://lab-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.002},
            ],
            "constraints": constraints,
        }
    if scenario_id == "provider-disagreement":
        return {
            "goal": "Lab provider disagreement: refuse without independent agreement",
            "providers": [
                {"name": "Lab Alpha", "url": "https://lab-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.004},
                {"name": "Lab Beta", "url": "https://lab-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.003},
                {"name": "Lab Gamma", "url": "https://lab-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.002},
            ],
            "constraints": constraints,
        }
    if scenario_id == "schema-invalid":
        return {
            "goal": "Lab schema invalid: reject values that violate the numeric schema",
            "providers": [
                {"name": "Lab Alpha", "url": "https://lab-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.004},
                {"name": "Lab Beta", "url": "https://lab-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.003},
                {"name": "Lab Gamma", "url": "https://lab-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.002},
            ],
            "constraints": constraints,
        }
    if scenario_id == "upstream-failure":
        return {
            "goal": "Lab upstream failure: refuse when providers are unavailable",
            "providers": [
                {"name": "Lab Alpha", "url": "https://lab-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.004},
                {"name": "Lab Beta", "url": "https://lab-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.003},
                {"name": "Lab Gamma", "url": "https://lab-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.002},
            ],
            "constraints": constraints,
        }
    if scenario_id == "over-budget":
        return {
            "goal": "Lab over budget: refuse when every provider exceeds the price limit",
            "providers": [
                {"name": "Lab Alpha", "url": "https://lab-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.05},
                {"name": "Lab Beta", "url": "https://lab-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.06},
                {"name": "Lab Gamma", "url": "https://lab-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.07},
            ],
            "constraints": constraints,
        }
    if scenario_id == "origin-convergence":
        return {
            "goal": "Lab origin convergence: reject distinct origins that resolve to one origin",
            "providers": [
                {"name": "Lab Alpha", "url": "https://converge-alpha.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.004},
                {"name": "Lab Beta", "url": "https://converge-beta.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.003},
                {"name": "Lab Gamma", "url": "https://converge-gamma.example/quote", "result_path": "quote.amount_usd", "expected_schema": schema, "price_usd": 0.002},
            ],
            "constraints": constraints,
        }
    raise HTTPException(404, "Unknown lab scenario")


def _lab_mapping(scenario_id: str) -> dict[str, tuple[int, dict, str | None]]:
    """Deterministic in-process responses: (status, payload, final_url or None)."""
    if scenario_id == "consensus-success":
        return {
            "https://lab-alpha.example/quote": (200, {"quote": {"amount_usd": 18.40}}, None),
            "https://lab-beta.example/quote": (200, {"quote": {"amount_usd": 18.44}}, None),
            "https://lab-gamma.example/quote": (200, {"quote": {"amount_usd": 52.00}}, None),
        }
    if scenario_id == "provider-disagreement":
        return {
            "https://lab-alpha.example/quote": (200, {"quote": {"amount_usd": 10.00}}, None),
            "https://lab-beta.example/quote": (200, {"quote": {"amount_usd": 20.00}}, None),
            "https://lab-gamma.example/quote": (200, {"quote": {"amount_usd": 30.00}}, None),
        }
    if scenario_id == "schema-invalid":
        return {
            "https://lab-alpha.example/quote": (200, {"quote": {"amount_usd": "call us"}}, None),
            "https://lab-beta.example/quote": (200, {"quote": {"amount_usd": "unavailable"}}, None),
            "https://lab-gamma.example/quote": (200, {"quote": {"amount_usd": None}}, None),
        }
    if scenario_id == "upstream-failure":
        return {
            "https://lab-alpha.example/quote": (503, {"error": "temporarily unavailable"}, None),
            "https://lab-beta.example/quote": (503, {"error": "temporarily unavailable"}, None),
            "https://lab-gamma.example/quote": (500, {"error": "upstream error"}, None),
        }
    if scenario_id == "over-budget":
        return {
            "https://lab-alpha.example/quote": (200, {"quote": {"amount_usd": 18.40}}, None),
            "https://lab-beta.example/quote": (200, {"quote": {"amount_usd": 18.44}}, None),
            "https://lab-gamma.example/quote": (200, {"quote": {"amount_usd": 18.42}}, None),
        }
    if scenario_id == "origin-convergence":
        converged = "https://converged-lab.example/final"
        return {
            "https://converge-alpha.example/quote": (200, {"quote": {"amount_usd": 18.40}}, converged),
            "https://converge-beta.example/quote": (200, {"quote": {"amount_usd": 18.44}}, converged),
            "https://converge-gamma.example/quote": (200, {"quote": {"amount_usd": 18.42}}, converged),
        }
    raise HTTPException(404, "Unknown lab scenario")


def _lab_checks(scenario_id: str, receipt: dict, calls: list[str]) -> list[dict]:
    attempts = receipt.get("attempts", [])
    selected = receipt.get("selected_provider")
    checks: list[dict] = []
    if scenario_id == "consensus-success":
        eligible_names = {item.get("name") for item in attempts if item.get("status") in {"ELIGIBLE", "SELECTED"}}
        group_size = receipt.get("agreement", {}).get("providers", 0)
        required = receipt.get("agreement", {}).get("required", 0)
        checks.append({
            "id": "agreement-met",
            "passed": bool(selected) and group_size >= required >= 2,
            "summary": f"Agreement {group_size}/{required} with selected provider {selected or 'none'}",
        })
        checks.append({
            "id": "selected-provider-eligible",
            "passed": bool(selected) and selected in eligible_names,
            "summary": "Selected provider is an eligible agreeing provider" if selected in eligible_names else "Selected provider is not eligible",
        })
    else:
        checks.append({
            "id": "refusal-selects-nothing",
            "passed": selected is None and receipt.get("result") is None and receipt.get("selected_price_usd") == 0,
            "summary": "No provider or result selected for the refusal" if selected is None else f"Unexpected selection: {selected}",
        })
    if scenario_id == "provider-disagreement":
        checks.append({
            "id": "disagreement-rejection",
            "passed": all(item.get("status") == "REJECTED" for item in attempts),
            "summary": "All providers rejected without sufficient agreement",
        })
    if scenario_id == "schema-invalid":
        checks.append({
            "id": "schema-rejection",
            "passed": any("Schema mismatch" in str(item.get("reason") or "") for item in attempts),
            "summary": "Schema-invalid values rejected against the numeric schema",
        })
    if scenario_id == "upstream-failure":
        checks.append({
            "id": "upstream-rejection",
            "passed": all(str(item.get("reason") or "").startswith("HTTP ") for item in attempts if item.get("status") == "REJECTED") and all(item.get("status") == "REJECTED" for item in attempts),
            "summary": "Upstream HTTP failures rejected with no usable result",
        })
    if scenario_id == "over-budget":
        checks.append({
            "id": "zero-provider-calls",
            "passed": len(calls) == 0,
            "summary": f"Provider request function called {len(calls)} time(s); expected 0",
        })
        checks.append({
            "id": "budget-rejection",
            "passed": all("budget" in str(item.get("reason") or "").lower() for item in attempts),
            "summary": "Every provider rejected as over budget",
        })
    if scenario_id == "origin-convergence":
        checks.append({
            "id": "final-origin-rejection",
            "passed": any("independence" in str(item.get("reason") or "").lower() for item in attempts),
            "summary": "Converged final origin rejected for provider independence",
        })
    return checks


@router.get("/lab")
async def lab_catalog():
    """Read-only catalog of the six server-owned deterministic fixture scenarios."""
    return {
        "schema_version": 1,
        "evidence": "deterministic-fixture",
        "scenarios": [
            {"id": scenario_id, **_LAB_SCENARIO_META[scenario_id]}
            for scenario_id in _LAB_SCENARIO_IDS
        ],
    }


async def _require_empty_lab_body(request: Request) -> None:
    """Enforce the exact zero-byte body contract without buffering caller bytes.

    - Any Transfer-Encoding combined with any Content-Length is ambiguous
      framing and fails closed immediately, before the stream is touched,
      even when the declared length is zero.
    - Content-Length alone: exactly one header, decimal digits only after
      outer whitespace handling, value exactly zero; anything else rejects
      before stream access. A valid single zero passes untouched.
    - Transfer-Encoding alone: exactly one header containing exactly the
      single coding ``chunked`` (comma-separated tokens parsed exactly;
      empty, duplicate, or any other coding fails closed). An exact single
      ``chunked`` falls through to stream inspection below.
    - Neither header: the stream is inspected directly.
    - Stream inspection rejects on the first non-empty chunk. Chunks are
      never accumulated, parsed, or echoed; even whitespace is a body.
    - An actually empty body passes without touching caller bytes.
    """
    encodings = request.headers.getlist("transfer-encoding")
    lengths = request.headers.getlist("content-length")
    if encodings and lengths:
        raise HTTPException(400, "Lab scenarios accept no request body")
    if lengths:
        if len(lengths) != 1 or re.fullmatch(r"0+", lengths[0].strip() or "") is None:
            raise HTTPException(400, "Lab scenarios accept no request body")
        return
    if encodings:
        if len(encodings) != 1:
            raise HTTPException(400, "Lab scenarios accept no request body")
        codings = [token.strip().lower() for token in encodings[0].split(",")]
        if len(codings) != 1 or codings[0] != "chunked":
            raise HTTPException(400, "Lab scenarios accept no request body")
    async for chunk in request.stream():
        if chunk:
            raise HTTPException(400, "Lab scenarios accept no request body")


@router.post("/lab/{scenario_id}")
async def lab_run(scenario_id: str, request: Request):
    """Run one allowlisted deterministic fixture scenario.

    Contract A: this endpoint accepts no request body. Any non-empty body is
    safely rejected with HTTP 400 and can never influence the server-owned
    fixture. Only the six catalog scenario IDs may run.
    """
    await _require_empty_lab_body(request)
    if scenario_id not in _LAB_SCENARIO_META:
        raise HTTPException(404, "Unknown lab scenario")
    meta = _LAB_SCENARIO_META[scenario_id]
    mapping = _lab_mapping(scenario_id)
    calls: list[str] = []

    async def _lab_request(_method: str, url: str) -> SafeResponse:
        calls.append(url)
        entry = mapping.get(url)
        if entry is None:
            raise ValueError("Unknown lab provider")
        status, payload, final_url = entry
        return SafeResponse(
            status,
            {"content-type": "application/json"},
            json.dumps(payload).encode("utf-8"),
            final_url or url,
        )

    try:
        body = OutcomeRequest.model_validate(_lab_payload(scenario_id))
    except ValueError as exc:
        raise HTTPException(400, "Invalid lab scenario") from exc
    timing = LabTiming(created_at=LAB_FIXED_CREATED_AT, latency_ms=LAB_FIXED_LATENCY_MS)
    try:
        receipt = await execute_verified_outcome(body.model_dump(), request_fn=_lab_request, lab_timing=timing)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        store_lab_receipt(receipt)
    except LabWriteConflict:
        raise HTTPException(409, "Lab receipt conflict") from None
    except LabStorageUnavailable:
        raise HTTPException(503, "Lab storage unavailable") from None
    stored = load_lab_receipt(receipt["receipt_id"])
    roundtrip_equal = stored is not None and canonical_json(stored) == canonical_json(receipt)
    integrity_after = bool(stored) and verify_receipt(stored)
    integrity_now = verify_receipt(receipt)
    observed = receipt.get("verdict")
    expected = meta["expected_verdict"]
    checks: list[dict] = [
        {
            "id": "verdict-matches-expectation",
            "passed": observed == expected,
            "summary": f"Expected {expected}, observed {observed}",
        },
        {
            "id": "integrity-valid",
            "passed": bool(integrity_now),
            "summary": "Receipt passes canonical integrity verification" if integrity_now else "Receipt failed integrity verification",
        },
        {
            "id": "storage-roundtrip-equal",
            "passed": bool(roundtrip_equal and integrity_after),
            "summary": "Stored receipt retrieved canonical JSON round-trip exactly equal" if roundtrip_equal else "Stored receipt did not match",
        },
        *_lab_checks(scenario_id, receipt, calls),
    ]
    passed = observed == expected and all(check.get("passed") for check in checks)
    return {
        "schema_version": 1,
        "scenario": {"id": scenario_id, **meta},
        "evidence": "deterministic-fixture",
        "fixture_note": "Fixed fixture timestamp; not live-provider freshness.",
        "passed": bool(passed),
        "observed_verdict": observed,
        "checks": checks,
        "receipt": receipt,
        "integrity_valid_after_storage": bool(integrity_after and roundtrip_equal),
    }
