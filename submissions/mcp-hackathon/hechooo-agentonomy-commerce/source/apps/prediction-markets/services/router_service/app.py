from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.router_service.service import score_markets, search_markets  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import ScoreMarketsRequest, SearchMarketsRequest  # noqa: E402

CONFIG = AppConfig.from_env()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clink Prediction Markets Router",
        version="0.1.0",
        description="Cross-platform prediction market discovery and scoring for agent runtimes.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"service": "prediction_markets_router_service", "status": "ok", "mode": "read_only"}

    @app.post("/markets/search")
    def search(request: SearchMarketsRequest) -> dict:
        return search_markets(
            query=request.query,
            platforms=[str(item) for item in request.platforms],
            limit=request.limit,
            tradable_only=request.tradable_only,
            config=CONFIG,
        ).model_dump()

    @app.post("/markets/score")
    def score(request: ScoreMarketsRequest) -> dict:
        opportunities = score_markets(request.query, request.markets, request.max_results)
        return {"source": "clink_prediction_markets_router", "query": request.query, "opportunities": [item.model_dump() for item in opportunities], "count": len(opportunities)}

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink Prediction Markets router service")
    parser.add_argument("--sample", action="store_true", help="Print service health instead of starting the server")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps({"service": "prediction_markets_router_service", "status": "ok", "mode": "read_only"}, indent=2))
        return
    uvicorn.run(app, host=CONFIG.router_host, port=CONFIG.router_port)


if __name__ == "__main__":
    main()
