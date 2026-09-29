from __future__ import annotations

import importlib.util
import os
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__
from .models import ConvertRequest, EventScore, ImpactResult, MacroEvent, MacroHeadline, RadarRequest, ScenarioRequest, TranslateRequest
from .service import (
    compare_scenarios,
    convert_request,
    get_demo_events,
    get_demo_radar,
    get_energy_event,
    get_live_fx_event,
    get_official_headlines,
    get_policy_rate_event,
    rank_request,
    translate_request,
)


def _commit() -> str:
    return os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("RENDER_GIT_COMMIT") or os.getenv("REVIEW_COMMIT", "dev-local")


def _base_url() -> str:
    configured = os.getenv("PUBLIC_BASE_URL")
    if configured:
        return configured.rstrip("/")
    platform_host = os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL")
    return f"https://{platform_host}" if platform_host else "http://localhost:8000"


def _transport_security():
    from mcp.server.transport_security import TransportSecuritySettings

    public = urlsplit(_base_url())
    if public.scheme not in {"http", "https"} or not public.hostname or public.username or public.password:
        raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) URL without credentials")
    public_host = f"[{public.hostname}]" if ":" in public.hostname else public.hostname
    local_hosts = ["localhost", "127.0.0.1", "[::1]"]
    allowed_hosts = [value for host in local_hosts for value in (host, f"{host}:*")]
    allowed_hosts.extend([public_host, public.netloc])
    local_origins = [value for host in local_hosts for value in (f"http://{host}", f"http://{host}:*")]
    return TransportSecuritySettings(
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(dict.fromkeys([*local_origins, f"{public.scheme}://{public.netloc}"])),
    )


MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None
_mcp = None
_mcp_app = None
if MCP_AVAILABLE:
    from .mcp_server import mcp as _mcp

    _mcp_app = _mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Mounted ASGI applications do not run their own lifespan.
    if _mcp is not None:
        async with _mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(
    title="Life Exchange Rate API",
    version=__version__,
    description="Translate macroeconomic shocks into concrete, user-specific life impacts.",
    lifespan=lifespan,
)

if _mcp_app is not None:
    app.mount("/mcp", _mcp_app)


@app.exception_handler(RequestValidationError)
async def invalid_request_handler(request, exc: RequestValidationError):
    # Do not echo raw input: nonfinite JSON values cannot be serialized safely,
    # and validation responses need only the field location and explanation.
    return JSONResponse(status_code=422, content={
        "detail": [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                   for error in exc.errors()]
    })


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "commit": _commit(),
        "mcp": "enabled" if MCP_AVAILABLE else "dependency-not-installed",
    }


@app.get("/.well-known/xagent-verification.json")
def xagent_verification() -> dict:
    return {
        "schemaVersion": 1,
        "slug": os.getenv("SUBMISSION_SLUG", "kongkoukk-life-exchange-rate"),
        "version": __version__,
        "commit": _commit(),
        "apiBaseUrl": _base_url(),
        "health": f"{_base_url()}/health",
        "openapi": f"{_base_url()}/openapi.json",
        "mcp": f"{_base_url()}/mcp/" if MCP_AVAILABLE else None,
    }


@app.get("/v1/events/demo", response_model=list[MacroEvent])
def events_demo() -> list[dict]:
    return [event.model_dump(mode="json") for event in get_demo_events()]


@app.get("/v1/radar/demo", response_model=list[EventScore])
def radar_demo() -> list[dict]:
    return get_demo_radar()


@app.get("/v1/events/fx", response_model=MacroEvent)
async def events_fx(
    base: str = Query(pattern="^[A-Za-z]{3}$"),
    quote: str = Query(pattern="^[A-Za-z]{3}$"),
    lookback_days: int = Query(default=7, ge=2, le=90),
) -> dict:
    if base.upper() == quote.upper():
        raise HTTPException(status_code=422, detail="FX base and quote currencies must differ")
    try:
        event = await get_live_fx_event(base=base, quote=quote, lookback_days=lookback_days)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="FX provider unavailable; retry later.") from exc


@app.get("/v1/events/policy-rate", response_model=MacroEvent)
async def events_policy_rate(
    lookback_days: int = Query(default=30, ge=2, le=365),
    mode: Literal["live", "fixture", "live_or_fixture"] = "live_or_fixture",
) -> dict:
    try:
        event = await get_policy_rate_event(lookback_days=lookback_days, mode=mode)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Policy-rate provider unavailable; retry later or use fixture mode.") from exc


@app.get("/v1/events/energy", response_model=MacroEvent)
async def events_energy(
    lookback_days: int = Query(default=7, ge=2, le=365),
    mode: Literal["live", "fixture", "live_or_fixture"] = "live_or_fixture",
) -> dict:
    try:
        event = await get_energy_event(lookback_days=lookback_days, mode=mode)
        return event.model_dump(mode="json")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Energy provider unavailable; retry later or use fixture mode.") from exc


@app.get("/v1/headlines/official", response_model=list[MacroHeadline])
async def headlines_official(
    source: Literal["fed", "ecb"],
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    try:
        return await get_official_headlines(source=source, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Official headline provider unavailable; retry later.") from exc


@app.post("/v1/radar/rank", response_model=list[EventScore])
def radar_rank(request: RadarRequest) -> list[dict]:
    return rank_request(request)


@app.post("/v1/translate", response_model=ImpactResult)
def translate(request: TranslateRequest) -> dict:
    try:
        return translate_request(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/convert")
def convert(request: ConvertRequest) -> dict:
    try:
        return convert_request(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/scenarios")
def scenarios(request: ScenarioRequest) -> list[dict]:
    try:
        return compare_scenarios(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

