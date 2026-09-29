from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.decision_service.service import DecisionService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import PredictionMarketContextRequest, PredictionMarketDecisionRequest  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = DecisionService(config=CONFIG)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clink Prediction Markets Context Service",
        version="0.5.1",
        description="Builds cross-platform prediction-market context and evidence for Hermes-owned decisions.",
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
        return {"service": "prediction_markets_context_service", "status": "ok", "mode": "hermes_context_layer"}

    @app.post("/context/build")
    def build_context(request: PredictionMarketContextRequest) -> dict:
        try:
            return SERVICE.build_context(request).model_dump()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/decision/analyze")
    def analyze_topic(request: PredictionMarketDecisionRequest) -> dict:
        try:
            return SERVICE.analyze_topic(request).model_dump()
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink Prediction Markets context service")
    parser.add_argument("--sample", action="store_true", help="Print service health instead of starting the server")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps({"service": "prediction_markets_context_service", "status": "ok", "mode": "hermes_context_layer"}, indent=2))
        return
    uvicorn.run(app, host=CONFIG.decision_host, port=CONFIG.decision_port)


if __name__ == "__main__":
    main()
