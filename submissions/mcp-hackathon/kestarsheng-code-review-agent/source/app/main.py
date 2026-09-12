# -*- coding: utf-8 -*-
"""FastAPI application entry point.

Provides:
- GET  /v1                    API base URL endpoint directory
- POST /v1/review            dual-engine review of source code
- POST /v1/review_diff       dual-engine review of a unified diff
- POST /v1/review_files      multi-file batch review
- POST /v1/suggest_fix       generate corrected code for known issues
- GET  /v1/rules             list all built-in rule engine rules
- GET  /v1/rules/{rule_id}   explain one rule in detail
- GET  /health               health check returning the deployed commit
- GET  /.well-known/xagent-verification.json   deployment proof
- GET  /                     minimal web demo page
- MCP  /mcp                  remote streamable-HTTP MCP endpoint (same server)
"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from .config import PROJECT_SLUG, get_settings
from .mcp_server import mcp
from .reviewer import (
    ReviewError,
    explain_issue,
    review_code,
    review_diff,
    review_files,
    suggest_fix_for_code,
)
from .rules_engine import RULES, run_rules
from .schemas import (
    DiffReviewRequest,
    DiffReviewResponse,
    FilesReviewRequest,
    FilesReviewResponse,
    HealthResponse,
    ReviewRequest,
    ReviewResponse,
    VerificationResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

# Remote MCP endpoint (streamable HTTP transport). Created before app so its
# lifespan can be wired into the FastAPI app; mounted after all REST routes.
mcp_app = None
try:
    mcp_app = mcp.http_app(path="/mcp")
    logger.info("MCP streamable HTTP endpoint ready at /mcp")
except Exception:  # noqa: BLE001
    logger.exception("Failed to build MCP HTTP endpoint")

app = FastAPI(
    title="Code Review Agent",
    description="Dual-engine AI code quality review: rule-based static analysis "
    "+ LLM semantic review with cross-validation.",
    version="2.1.0",
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
    return VerificationResponse(
        schemaVersion=1, slug=PROJECT_SLUG, commit=settings.commit
    )


@app.get("/v1", tags=["meta"])
def api_index() -> dict:
    """API base URL: return the endpoint directory so /v1 is never a 404."""
    return {
        "service": "Code Review Agent",
        "version": "2.1.0",
        "endpoints": {
            "POST /v1/review": "review source code (dual-engine)",
            "POST /v1/review_diff": "review a unified diff",
            "POST /v1/review_files": "multi-file batch review",
            "POST /v1/suggest_fix": "generate corrected code",
            "GET /v1/rules": "list built-in rule engine rules",
            "GET /v1/rules/{rule_id}": "explain one rule",
            "GET /health": "health check (deployed commit)",
            "GET /.well-known/xagent-verification.json": "deployment proof",
            "GET /mcp": "remote MCP endpoint",
        },
    }


@app.post("/v1/review", response_model=ReviewResponse, tags=["review"])
async def review(req: ReviewRequest) -> ReviewResponse:
    if len(req.code) > settings.max_code_chars:
        raise HTTPException(
            status_code=413,
            detail=f"code 过长（限制 {settings.max_code_chars} 字符）",
        )
    try:
        report = review_code(code=req.code, language=req.language, context=req.context)
    except ReviewError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ReviewResponse(language=req.language, model=settings.llm_model, report=report)


@app.post("/v1/review_diff", response_model=DiffReviewResponse, tags=["review"])
async def review_diff_endpoint(req: DiffReviewRequest) -> DiffReviewResponse:
    if len(req.diff) > settings.max_code_chars:
        raise HTTPException(
            status_code=413,
            detail=f"diff 过长（限制 {settings.max_code_chars} 字符）",
        )
    try:
        result = review_diff(diff=req.diff, language=req.language, context=req.context)
    except ReviewError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    diff_meta = result.get("diff_meta", {})
    report = {k: v for k, v in result.items() if k != "diff_meta"}
    return DiffReviewResponse(
        files_changed=diff_meta.get("files_changed", []),
        added_lines=diff_meta.get("added_lines", 0),
        removed_lines=diff_meta.get("removed_lines", 0),
        model=settings.llm_model,
        report=report,
    )


@app.post("/v1/review_files", response_model=FilesReviewResponse, tags=["review"])
async def review_files_endpoint(req: FilesReviewRequest) -> FilesReviewResponse:
    total_chars = sum(len(f.content) for f in req.files)
    if total_chars > settings.max_code_chars:
        raise HTTPException(
            status_code=413,
            detail=f"文件内容总过长（限制 {settings.max_code_chars} 字符）",
        )
    files = [
        {"filename": f.filename, "content": f.content, "language": f.language}
        for f in req.files
    ]
    try:
        result = review_files(files=files, context=req.context)
    except ReviewError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return FilesReviewResponse(
        model=settings.llm_model,
        total_files=len(files),
        file_reports=result["file_reports"],
        overall_report=result["overall_report"],
    )


@app.get("/v1/rules", tags=["review"])
def list_rules() -> dict:
    """List all built-in rule engine rules."""
    return {
        "total": len(RULES),
        "rules": [
            {
                "id": r.id,
                "language": r.language,
                "severity": r.severity,
                "category": r.category,
                "confidence": r.confidence,
                "title": r.title,
            }
            for r in RULES
        ],
    }


@app.get("/v1/rules/{rule_id}", tags=["review"])
def get_rule(rule_id: str) -> dict:
    """Explain a single rule-engine rule in detail."""
    result = explain_issue(rule_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@app.post("/v1/suggest_fix", tags=["review"])
async def suggest_fix(req: ReviewRequest) -> dict:
    """Generate a full corrected version of code with known issues."""
    if len(req.code) > settings.max_code_chars:
        raise HTTPException(
            status_code=413,
            detail=f"code 过长（限制 {settings.max_code_chars} 字符）",
        )
    try:
        result = suggest_fix_for_code(
            code=req.code, language=req.language, context=req.context
        )
    except ReviewError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "model": settings.llm_model, "result": result}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    html = Path(__file__).resolve().parent.parent / "web" / "index.html"
    if html.exists():
        return HTMLResponse(html.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Code Review Agent</h1><p>See /docs for API.</p>")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail},
    )


# Mount MCP catch-all AFTER all REST routes so /health, /v1/* etc. win.
if mcp_app is not None:
    app.mount("/", mcp_app)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
