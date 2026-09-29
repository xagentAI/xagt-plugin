from __future__ import annotations

import argparse
import json
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.sync_service.service import PortfolioSyncService  # noqa: E402
from shared.config import AppConfig  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = PortfolioSyncService(config=CONFIG)


def _run_sync_loop(service: PortfolioSyncService, stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        service.sync_once()
        stop_event.wait(max(1, service.config.sync_interval_seconds))


def create_app(service: PortfolioSyncService | None = None, enable_background: bool = True) -> FastAPI:
    sync_service = service or SERVICE

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop_event: threading.Event | None = None
        thread: threading.Thread | None = None
        if enable_background:
            stop_event = threading.Event()
            thread = threading.Thread(target=_run_sync_loop, args=(sync_service, stop_event), daemon=True)
            thread.start()
        try:
            yield
        finally:
            if stop_event is not None:
                stop_event.set()
            if thread is not None:
                thread.join(timeout=5)

    app = FastAPI(
        title="Clink Prediction Markets Sync Service",
        version="0.1.0",
        description="Reconciles local previews/executions into the trading ledger every 20 seconds.",
        lifespan=lifespan,
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
        return {
            "service": "prediction_markets_sync_service",
            "status": "ok",
            "mode": "ledger_and_venue_account_reconciliation",
            "interval_seconds": sync_service.config.sync_interval_seconds,
            "venue_account_sync_enabled": sync_service.config.sync_venue_accounts,
        }

    @app.post("/sync/run")
    def run_sync() -> dict:
        return sync_service.sync_once().model_dump()

    @app.get("/sync/status")
    def sync_status() -> dict:
        return sync_service.latest_sync_status()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink Prediction Markets sync service")
    parser.add_argument("--sample", action="store_true", help="Run one sync and print the result instead of starting the server")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps(SERVICE.sync_once().model_dump(), indent=2))
        return
    uvicorn.run(app, host=CONFIG.sync_host, port=CONFIG.sync_port)


if __name__ == "__main__":
    main()
