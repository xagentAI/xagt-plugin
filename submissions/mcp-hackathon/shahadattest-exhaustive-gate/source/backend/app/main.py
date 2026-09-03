from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.core.config import APP_VERSION, GIT_COMMIT, XAGENT_SLUG
from app.models.db import init_db

app = FastAPI(title="ExhaustiveGate", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

init_db()
app.include_router(sessions_router, prefix="/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "exhaustive-gate", "version": APP_VERSION, "commit": GIT_COMMIT}


@app.get("/.well-known/xagent-verification.json")
async def verification():
    return {"schemaVersion": 1, "slug": XAGENT_SLUG, "commit": GIT_COMMIT}
