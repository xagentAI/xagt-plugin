from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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
        return FileResponse(_frontend / "index.html")
    return {"service": "apivouch", "docs": "/docs"}


@app.get("/app.js", include_in_schema=False)
async def dashboard_script():
    return FileResponse(_frontend / "app.js", media_type="application/javascript")
