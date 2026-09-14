# -*- coding: utf-8 -*-
"""FastAPI application entry point.

Provides:
- GET  /v1                                  API endpoint directory
- POST /v1/diff                             detect breaking changes between two contracts
- GET  /v1/formats                          list supported contract formats
- GET  /health                              health check returning the deployed commit
- GET  /.well-known/xagent-verification.json   deployment proof
- GET  /                                    web demo page
- MCP  /mcp                                 remote streamable-HTTP MCP endpoint
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .config import PROJECT_NAME, PROJECT_SLUG, PROJECT_VERSION, get_settings
from .diff_core import DiffError, detect_changes, normalize_format
from .migration import suggest_migration
from .mcp_server import mcp
from .models import SUPPORTED_FORMATS
from .sarif import export_sarif
from .schemas import (
    ChainDiffRequest,
    ChainDiffResponse,
    ChainDiffStepResponse,
    DiffRequest,
    DiffResponse,
    ErrorResponse,
    FindingResponse,
    HealthResponse,
    MigrationResponse,
    MigrationSuggestionResponse,
    SemverResponse,
    VerificationResponse,
)
from .semver import generate_changelog, suggest_version_bump

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

mcp_app = None
try:
    mcp_app = mcp.http_app(path="/mcp")
    logger.info("MCP streamable HTTP endpoint ready at /mcp")
except Exception:  # noqa: BLE001
    logger.exception("Failed to build MCP HTTP endpoint")

app = FastAPI(
    title=PROJECT_NAME,
    description=(
        "Deterministic API breaking-change detector for AI agents. Compares two "
        "OpenAPI / GraphQL / JSON Schema contracts and returns structured, "
        "reproducible findings — no LLM required for the core diff."
    ),
    version=PROJECT_VERSION,
    lifespan=mcp_app.lifespan if mcp_app is not None else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", commit=settings.commit)


@app.get(
    "/.well-known/xagent-verification.json",
    response_model=VerificationResponse,
    tags=["meta"],
)
def verification() -> VerificationResponse:
    return VerificationResponse(schemaVersion=1, slug=PROJECT_SLUG, commit=settings.commit)


@app.get("/v1", tags=["meta"])
def api_index() -> dict:
    return {
        "service": PROJECT_NAME,
        "version": PROJECT_VERSION,
        "description": "Deterministic API breaking-change detector for AI agents.",
        "endpoints": {
            "POST /v1/diff": "detect breaking changes between two contracts",
            "POST /v1/chain-diff": "chain multi-version analysis (v1->v2->...->vN)",
            "POST /v1/semver": "suggest SemVer bump from a diff result",
            "POST /v1/migration": "generate migration suggestions for breaking changes",
            "POST /v1/sarif": "export diff results as SARIF 2.1.0",
            "GET /v1/formats": "list supported contract formats",
            "GET /health": "health check (deployed commit)",
            "GET /.well-known/xagent-verification.json": "deployment proof",
            "GET /mcp": "remote MCP endpoint (streamable HTTP)",
        },
    }


@app.get("/v1/formats", tags=["meta"])
def list_formats() -> dict:
    return {
        "formats": [
            {"id": "openapi", "label": "OpenAPI 3.x", "accepts": "JSON or YAML"},
            {"id": "graphql", "label": "GraphQL SDL", "accepts": "schema definition language"},
            {"id": "json-schema", "label": "JSON Schema", "accepts": "JSON"},
        ],
    }


@app.post("/v1/diff", response_model=DiffResponse, tags=["diff"])
async def diff_contracts(req: DiffRequest) -> DiffResponse:
    total_chars = len(req.old_spec) + len(req.new_spec)
    if total_chars > settings.max_spec_chars:
        raise HTTPException(
            status_code=413,
            detail=f"Contract text too large (limit {settings.max_spec_chars} chars).",
        )

    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    use_llm = req.use_llm and bool(settings.llm_api_key)

    try:
        report = await asyncio.to_thread(
            detect_changes, req.old_spec, req.new_spec, req.format, use_llm=use_llm
        )
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DiffResponse(
        schema_version=report.schema_version,
        format=report.format,
        breaking=report.breaking,
        total_changes=report.total_changes,
        breaking_count=report.breaking_count,
        counts=report.counts,
        summary=report.summary,
        llm_enabled=report.llm_enabled,
        findings=[FindingResponse(**f.as_dict()) for f in report.findings],
    )


@app.post("/v1/chain-diff", response_model=ChainDiffResponse, tags=["diff"])
async def chain_diff_contracts(req: ChainDiffRequest) -> ChainDiffResponse:
    if len(req.specs) < 2:
        raise HTTPException(status_code=400, detail="At least 2 spec versions required for chain diff.")

    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    steps: list[ChainDiffStepResponse] = []
    cumulative_breaking_count = 0

    for i in range(len(req.specs) - 1):
        try:
            report = await asyncio.to_thread(
                detect_changes, req.specs[i], req.specs[i + 1], req.format,
                use_llm=req.use_llm and bool(settings.llm_api_key),
            )
        except DiffError as exc:
            raise HTTPException(status_code=400, detail=f"Step {i+1}: {exc}") from exc

        steps.append(ChainDiffStepResponse(
            step=i + 1,
            from_version=f"v{i+1}",
            to_version=f"v{i+2}",
            breaking=report.breaking,
            breaking_count=report.breaking_count,
            total_changes=report.total_changes,
            summary=report.summary,
            findings=[FindingResponse(**f.as_dict()) for f in report.findings],
        ))
        cumulative_breaking_count += report.breaking_count

    return ChainDiffResponse(
        format=req.format,
        total_steps=len(steps),
        cumulative_breaking=cumulative_breaking_count > 0,
        cumulative_breaking_count=cumulative_breaking_count,
        steps=steps,
        summary=f"Analyzed {len(steps)} transition(s); {cumulative_breaking_count} cumulative breaking change(s).",
    )


@app.post("/v1/semver", response_model=SemverResponse, tags=["analysis"])
async def suggest_semver(req: DiffRequest) -> SemverResponse:
    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        report = await asyncio.to_thread(
            detect_changes, req.old_spec, req.new_spec, req.format,
            use_llm=req.use_llm and bool(settings.llm_api_key),
        )
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = suggest_version_bump(report)
    return SemverResponse(**result)


@app.post("/v1/migration", response_model=MigrationResponse, tags=["analysis"])
async def suggest_migration_endpoint(req: DiffRequest) -> MigrationResponse:
    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        report = await asyncio.to_thread(
            detect_changes, req.old_spec, req.new_spec, req.format,
            use_llm=req.use_llm and bool(settings.llm_api_key),
        )
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = suggest_migration(report)
    return MigrationResponse(
        total_breaking=result["total_breaking"],
        has_migration_path=result["has_migration_path"],
        suggestions=[MigrationSuggestionResponse(**s) for s in result["suggestions"]],
    )


@app.post("/v1/sarif", tags=["analysis"])
async def export_sarif_endpoint(req: DiffRequest) -> dict:
    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        report = await asyncio.to_thread(
            detect_changes, req.old_spec, req.new_spec, req.format,
            use_llm=req.use_llm and bool(settings.llm_api_key),
        )
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return export_sarif(report)


@app.post("/v1/changelog", tags=["analysis"])
async def generate_changelog_endpoint(req: DiffRequest) -> dict:
    try:
        normalize_format(req.format)
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        report = await asyncio.to_thread(
            detect_changes, req.old_spec, req.new_spec, req.format,
            use_llm=req.use_llm and bool(settings.llm_api_key),
        )
    except DiffError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"changelog": generate_changelog(report)}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    html = Path(__file__).resolve().parent.parent / "web" / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return HTMLResponse(
        f"<h1>{PROJECT_NAME}</h1><p>See <a href='/docs'>/docs</a> for the API.</p>"
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=str(exc.detail)).model_dump(),
    )


if mcp_app is not None:
    app.mount("/", mcp_app)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()