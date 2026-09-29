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

from services.portfolio_service.service import PortfolioService  # noqa: E402
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = PortfolioService(config=CONFIG)


def create_app(service: PortfolioService | None = None) -> FastAPI:
    portfolio_service = service or SERVICE
    app = FastAPI(
        title="Clink Prediction Markets Portfolio Service",
        version="0.1.0",
        description="Read-only Agent Money Console portfolio, PnL, pending action, and audit timeline service.",
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
        return {"service": "prediction_markets_portfolio_service", "status": "ok", "mode": "read_only"}

    @app.get("/portfolio/snapshot")
    def snapshot() -> dict:
        return portfolio_service.build_snapshot().model_dump()

    @app.get("/portfolio/summary")
    def summary() -> dict:
        return portfolio_service.build_snapshot().summary.model_dump()

    @app.get("/portfolio/positions")
    def positions() -> dict:
        return {"positions": [position.model_dump() for position in portfolio_service.build_snapshot().positions]}

    @app.get("/portfolio/timeline")
    def timeline() -> dict:
        return {"timeline": [item.model_dump() for item in portfolio_service.build_snapshot().timeline]}

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink Prediction Markets portfolio service")
    parser.add_argument("--sample", action="store_true", help="Print service health instead of starting the server")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps({"service": "prediction_markets_portfolio_service", "status": "ok", "mode": "read_only"}, indent=2))
        return
    uvicorn.run(app, host=CONFIG.portfolio_host, port=CONFIG.portfolio_port)


if __name__ == "__main__":
    main()
