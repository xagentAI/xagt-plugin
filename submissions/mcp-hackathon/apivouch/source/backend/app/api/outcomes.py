from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from app.core import config
from app.schemas.api import OutcomeRequest
from app.services.http_client import SafeResponse
from app.services.outcomes import (
    execute_verified_outcome,
    load_receipt,
    receipt_authenticity,
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
    value = load_receipt(receipt_id)
    if not value:
        raise HTTPException(404, "Receipt not found")
    return {"receipt": value, "integrity_valid": verify_receipt(value), "authenticity": receipt_authenticity(value)}
