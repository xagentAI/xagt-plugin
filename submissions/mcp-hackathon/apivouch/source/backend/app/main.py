import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.demo import router as demo_router
from app.api.mcp import LEGACY_VERSIONS, MODERN_VERSION, OUTCOME_TOOL, RECEIPT_TOOL
from app.api.mcp import router as mcp_router
from app.api.outcomes import router as outcomes_router
from app.api.projects import router as projects_router
from app.core import config, signing
from app.core.config import APP_VERSION, CORS_ORIGINS, GIT_COMMIT, PROJECT_SLUG
from app.models.db import database_ready, init_db

app = FastAPI(
    title="APIVouch",
    version=APP_VERSION,
    description="Evidence-based API diagnostics, agent-contract generation, and dynamic MCP tools.",
    docs_url=None,
)
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "MCP-Protocol-Version", "Mcp-Method", "Mcp-Name"],
    )

try:
    init_db()
except SQLAlchemyError:
    pass  # Database outages must not prevent the liveness endpoint from serving.
app.include_router(projects_router, prefix="/api")
app.include_router(outcomes_router, prefix="/api")
app.include_router(mcp_router)
app.include_router(demo_router)


@app.get("/docs", include_in_schema=False)
async def api_docs():
    swagger = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
    )
    html = swagger.body.decode("utf-8")
    html = html.replace(
        "</head>",
        """
    <style>
      body { margin: 0; }
      .apivouch-docs-nav {
        align-items: center; background: #17211d; box-sizing: border-box;
        color: #dbe8e1; display: flex; font-family: system-ui, sans-serif;
        gap: 18px; min-height: 58px; padding: 10px 24px; position: sticky;
        top: 0; z-index: 10000;
      }
      .apivouch-docs-nav a {
        align-items: center; background: #dff7e9; border-radius: 9px;
        color: #17211d; display: inline-flex; font-weight: 700;
        padding: 9px 14px; text-decoration: none;
      }
      .apivouch-docs-nav a:hover, .apivouch-docs-nav a:focus-visible {
        background: #bff0d2; outline: 2px solid #fff; outline-offset: 2px;
      }
      .apivouch-docs-nav span { font-size: 14px; font-weight: 650; }
      @media (max-width: 520px) {
        .apivouch-docs-nav { padding: 9px 12px; }
        .apivouch-docs-nav span { display: none; }
      }
    </style>
  </head>""",
    ).replace(
        "<body>",
        """<body>
    <nav class="apivouch-docs-nav" aria-label="Documentation navigation">
      <a href="/" aria-label="Back to APIVouch home">← Back to APIVouch</a>
      <span>Interactive API reference</span>
    </nav>""",
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "apivouch", "version": APP_VERSION, "commit": GIT_COMMIT}


@app.get("/.well-known/apivouch-signing-key.json")
async def signing_key():
    return signing.SIGNING_CONFIG.public_document()


@app.get("/ready")
async def ready():
    checks = {"configuration": config.deployment_config_ready(), "signing": signing.SIGNING_CONFIG.ready,
              "database": await database_ready()}
    available = all(checks.values())
    return JSONResponse({"status": "ready" if available else "not_ready", "commit": GIT_COMMIT,
                         "checks": checks}, status_code=200 if available else 503)


@app.get("/.well-known/xagent-verification.json")
async def verification():
    if not config.deployment_config_ready():
        raise HTTPException(503, "Deployment configuration unavailable")
    base = config.PUBLIC_BASE_URL
    proof = {"schemaVersion": 1, "slug": PROJECT_SLUG, "commit": GIT_COMMIT,
             "apiBaseUrl": base, "healthCheckUrl": base + "/health", "readinessUrl": base + "/ready",
             "mcpEndpoint": base + "/mcp", "productTools": [OUTCOME_TOOL["name"], RECEIPT_TOOL["name"]],
             "mcpProtocolVersions": [*LEGACY_VERSIONS, MODERN_VERSION],
             "receiptFormats": ["apivouch-outcome-receipt-v1"]}
    if signing.SIGNING_CONFIG.enabled:
        proof["signingKeyUrl"] = base + "/.well-known/apivouch-signing-key.json"
        proof["receiptFormats"].append("apivouch-outcome-receipt-v2")
    return proof


_frontend_candidates = [
    Path(__file__).resolve().parents[2] / "frontend",
    Path(__file__).resolve().parents[1] / "frontend",
]
_frontend = next((path for path in _frontend_candidates if path.exists()), _frontend_candidates[0])


@app.get("/", include_in_schema=False)
async def dashboard():
    if (_frontend / "index.html").exists():
        return FileResponse(
            _frontend / "index.html",
            headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"},
        )
    return {"service": "apivouch", "docs": "/docs"}


@app.get("/app.js", include_in_schema=False)
async def dashboard_script():
    return FileResponse(
        _frontend / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, max-age=0, must-revalidate"},
    )


_RECEIPT_PAGE_PATTERN = re.compile(r"[0-9a-f]{24}\Z")


@app.get("/receipts/{receipt_id}", include_in_schema=False)
async def receipt_page(receipt_id: str):
    if _RECEIPT_PAGE_PATTERN.fullmatch(receipt_id) is None:
        raise HTTPException(404, "Receipt not found")
    if (_frontend / "index.html").exists():
        return FileResponse(
            _frontend / "index.html",
            headers={
                "Cache-Control": "no-cache, max-age=0, must-revalidate",
                "X-Robots-Tag": "noindex, nofollow",
            },
        )
    raise HTTPException(404, "Receipt not found")
