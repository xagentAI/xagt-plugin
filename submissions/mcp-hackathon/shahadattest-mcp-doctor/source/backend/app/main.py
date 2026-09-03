from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.projects import router as projects_router
from app.core.config import APP_VERSION, GIT_COMMIT, PROJECT_SLUG
from app.models.db import init_db

app = FastAPI(title="MCP Doctor", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()
app.include_router(projects_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-doctor", "version": APP_VERSION, "commit": GIT_COMMIT}


@app.get("/.well-known/xagent-verification.json")
async def verification():
    return {"schemaVersion": 1, "slug": PROJECT_SLUG, "commit": GIT_COMMIT}
