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

from services.preview_service.service import PreviewService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import CreateOrderPreviewRequest  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = PreviewService(config=CONFIG)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clink Prediction Markets Preview Service",
        version="0.2.0",
        description="Creates non-executing, Clink Core-gated order previews for prediction markets.",
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
        return {"service": "prediction_markets_preview_service", "status": "ok", "mode": "preview_only", "storage": str(SERVICE.storage_file)}

    @app.post("/order-previews")
    def create_preview(request: CreateOrderPreviewRequest) -> dict:
        try:
            return SERVICE.create_order_preview(request).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/order-previews/{preview_id}")
    def get_preview(preview_id: str) -> dict:
        preview = SERVICE.get_order_preview(preview_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="order preview not found")
        return preview.model_dump()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink Prediction Markets preview service")
    parser.add_argument("--sample", action="store_true", help="Print service health instead of starting the server")
    args = parser.parse_args()
    if args.sample:
        print(json.dumps({"service": "prediction_markets_preview_service", "status": "ok", "mode": "preview_only"}, indent=2))
        return
    uvicorn.run(app, host=CONFIG.preview_host, port=CONFIG.preview_port)


if __name__ == "__main__":
    main()
