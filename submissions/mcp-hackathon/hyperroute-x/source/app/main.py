"""FastAPI Entrypoint for Agent DEX Co-Processor on X Layer.
Provides health monitoring, deployment proof, optimal routing, tx building, and simulation endpoints.
"""

from pathlib import Path
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Dict, Any

from app.config import SERVICE_NAME, SERVICE_SLUG, GIT_COMMIT
from app.models import (
    QuoteRequest, QuoteResponse,
    BuildTxRequest, BuildTxResponse,
    SimulateRequest, SimulateResponse,
    HealthResponse, DeploymentProofResponse
)
from app.router_engine import calculate_optimal_quote
from app.tx_builder import build_swap_calldata
from app.simulator import simulate_transaction
from app.mcp_schemas import get_mcp_manifest, MCP_TOOLS
from app.landing_page import get_landing_html

app = FastAPI(
    title="HyperRoute X",
    description="Autonomous DeFi Route & Execution Engine for AI Agents on X Layer",
    version="1.0.0"
)

ASSETS_PATH = Path(__file__).resolve().parent.parent / "assets"
if ASSETS_PATH.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_PATH)), name="assets")

# Enable CORS for agent web interfaces and ecosystem marketplaces
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_commit_header(request: Request, call_next):
    """Add mandatory x-source-commit header to all responses."""
    response = await call_next(request)
    response.headers["x-source-commit"] = GIT_COMMIT
    return response


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Mandatory public health check reporting status and Git commit SHA."""
    return HealthResponse(
        status="ok",
        commit=GIT_COMMIT,
        version=GIT_COMMIT,
        slug=SERVICE_SLUG,
        network="xlayer-mainnet"
    )


@app.get("/.well-known/xagent-verification.json", response_model=DeploymentProofResponse, tags=["System"])
async def deployment_proof():
    """Mandatory deployment-proof endpoint binding service origin, slug, and Git commit."""
    return DeploymentProofResponse(
        schemaVersion=1,
        slug=SERVICE_SLUG,
        commit=GIT_COMMIT
    )


@app.post("/api/v1/quote", response_model=QuoteResponse, tags=["Trading Engine"])
async def get_quote(req: QuoteRequest):
    """Calculate mathematically optimal swap route across X Layer DEX pools."""
    try:
        return calculate_optimal_quote(
            token_in_str=req.token_in,
            token_out_str=req.token_out,
            amount_in_str=req.amount_in,
            max_slippage_bps=req.max_slippage_bps or 50
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal routing error: {str(e)}")


@app.post("/api/v1/build-tx", response_model=BuildTxResponse, tags=["Trading Engine"])
async def build_transaction(req: BuildTxRequest):
    """Build raw, unsigned ABI-encoded calldata for the approved swap quote."""
    try:
        return build_swap_calldata(
            quote=req.quote,
            recipient_wallet=req.recipient_wallet,
            deadline_seconds=req.deadline_seconds or 1200
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transaction construction failed: {str(e)}")


@app.post("/api/v1/simulate", response_model=SimulateResponse, tags=["Trading Engine"])
async def simulate_tx(req: SimulateRequest):
    """Pre-validate transaction execution via eth_call simulation before broadcast."""
    return await simulate_transaction(req)


@app.get("/api/v1/mcp/tools", tags=["MCP Standardization"])
async def list_mcp_tools():
    """Expose standardized Model Context Protocol tool manifest for OKX.AI integration."""
    return get_mcp_manifest()


@app.get("/", tags=["System"])
async def root(request: Request):
    """Root interactive visual terminal demo and metadata entrypoint."""
    accept = request.headers.get("accept", "")
    format_query = request.query_params.get("format", "")
    if format_query == "json" or ("application/json" in accept and "text/html" not in accept):
        return {
            "service": SERVICE_NAME,
            "slug": SERVICE_SLUG,
            "commit": GIT_COMMIT,
            "docs_url": "/docs",
            "mcp_tools_url": "/api/v1/mcp/tools",
            "health_url": "/health",
            "status": "active"
        }
    return HTMLResponse(content=get_landing_html())
