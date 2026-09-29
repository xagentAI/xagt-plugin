from __future__ import annotations

import argparse
import hmac
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

ROOT_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.execution_service.repository import (  # noqa: E402
    OrderSigningSessionRepositoryError,
)
from services.execution_service.service import (  # noqa: E402
    ExecutionService,
    OrderSigningCapabilityError,
    OrderSigningPayloadError,
)
from shared.config import AppConfig  # noqa: E402
from shared.schemas import (  # noqa: E402
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    ExecutePredictionMarketOrderRequest,
)

CONFIG = AppConfig.from_env()
SERVICE = ExecutionService(config=CONFIG)

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'self' https://web.telegram.org "
        "https://*.telegram.org"
    ),
}
_PUBLIC_ASSETS = {
    "polymarket_order_signing.css": "text/css; charset=utf-8",
    "polymarket_order_signing.bundle.js": "application/javascript; charset=utf-8",
}


def _public_origin(config: object) -> str:
    parsed = urlsplit(str(getattr(config, "execution_console_base_url", "")))
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("execution console public origin is invalid")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _bearer_token(value: str | None) -> str | None:
    if not value or not value.startswith("Bearer "):
        return None
    token = value[7:]
    return token if token and len(token) <= 512 else None


def _model_dump(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


def _browser_status_projection(value) -> dict:
    data = _model_dump(value)
    return {
        "session_id": data.get("session_id"),
        "status": data.get("status"),
        "reason": data.get("reason"),
        "next_action": data.get("next_action"),
        "execution_id": data.get("execution_id"),
    }


def create_app(
    *,
    service: ExecutionService | object | None = None,
    config: AppConfig | object | None = None,
) -> FastAPI:
    active_service = service or SERVICE
    active_config = config or CONFIG
    allowed_origin = _public_origin(active_config)
    internal_token = str(
        getattr(active_config, "prediction_markets_internal_api_token", "") or ""
    )
    app = FastAPI(
        title="Clink Prediction Markets Execution Service",
        version="0.5.0",
        description="Executes Core-approved prediction market orders with browser signatures.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[allowed_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Clink-Origin"],
    )

    @app.middleware("http")
    async def exact_public_origin(request: Request, call_next):
        supplied_origin = request.headers.get("origin")
        if supplied_origin and supplied_origin != allowed_origin:
            return JSONResponse(
                status_code=403,
                content={"detail": "request origin is not allowed"},
                headers=_SECURITY_HEADERS,
            )
        response = await call_next(request)
        if request.url.path.startswith(
            "/execution/polymarket/order-signing-console"
        ) or request.url.path.startswith(
            "/execution/polymarket/order-signing-assets/"
        ) or request.url.path.startswith(
            "/execution/polymarket/browser-order-signing-session"
        ):
            response.headers.update(_SECURITY_HEADERS)
        return response

    def require_internal_authorization(authorization: str | None) -> None:
        supplied = _bearer_token(authorization)
        if (
            not internal_token
            or supplied is None
            or not hmac.compare_digest(supplied, internal_token)
        ):
            raise HTTPException(
                status_code=401,
                detail="internal authorization is required",
            )

    def browser_authorization(
        authorization: str | None,
        origin: str | None,
        explicit_origin: str | None,
    ) -> tuple[str, str]:
        supplied = _bearer_token(authorization)
        browser_origin = origin or explicit_origin
        if supplied is None or browser_origin != allowed_origin:
            raise HTTPException(
                status_code=401,
                detail="order signing capability is invalid",
            )
        return supplied, browser_origin

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "service": "prediction_markets_execution_service",
            "status": "ok",
            "mode": "live_adapter_gated",
        }

    @app.get("/execution/readiness")
    def readiness() -> dict:
        return active_service.check_readiness().model_dump()

    @app.post("/execution/order-preview")
    def execute_order_preview(request: ExecutePredictionMarketOrderRequest) -> dict:
        try:
            return active_service.execute_order_preview(request).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/execution/polymarket/order-signing-sessions")
    def create_polymarket_order_signing_session(
        request: CreatePolymarketOrderSigningSessionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        require_internal_authorization(authorization)
        try:
            return _model_dump(
                active_service.create_polymarket_order_signing_session(request)
            )
        except (ValueError, RuntimeError, OrderSigningSessionRepositoryError):
            raise HTTPException(
                status_code=400,
                detail="order signing session could not be created",
            ) from None

    @app.get("/execution/polymarket/order-signing-sessions/{session_id}")
    def get_polymarket_order_signing_session(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        require_internal_authorization(authorization)
        session = active_service.get_polymarket_order_signing_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="order signing session not found")
        return _model_dump(session)

    @app.post(
        "/execution/polymarket/order-signing-sessions/{session_id}/complete"
    )
    def complete_internal_polymarket_order_signing_session(
        session_id: str,
        request: CompletePolymarketOrderSigningSessionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        require_internal_authorization(authorization)
        try:
            return _model_dump(
                active_service.complete_polymarket_order_signing_session(
                    session_id, request
                )
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="order signing request was rejected",
            ) from None

    def resolve_browser_session(
        *,
        authorization: str | None,
        origin: str | None,
        explicit_origin: str | None,
        status_only: bool,
    ) -> dict:
        access_token, browser_origin = browser_authorization(
            authorization, origin, explicit_origin
        )
        try:
            return active_service.get_polymarket_order_signing_session_by_capability(
                access_token=access_token,
                origin=browser_origin,
                status_only=status_only,
            )
        except (ValueError, RuntimeError, OrderSigningSessionRepositoryError):
            raise HTTPException(
                status_code=401,
                detail="order signing capability is invalid",
            ) from None

    @app.get("/execution/polymarket/browser-order-signing-session")
    def get_browser_order_signing_session(
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        x_clink_origin: str | None = Header(default=None),
    ) -> dict:
        return resolve_browser_session(
            authorization=authorization,
            origin=origin,
            explicit_origin=x_clink_origin,
            status_only=False,
        )

    @app.get("/execution/polymarket/browser-order-signing-session/status")
    def get_browser_order_signing_session_status(
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        x_clink_origin: str | None = Header(default=None),
    ) -> dict:
        return resolve_browser_session(
            authorization=authorization,
            origin=origin,
            explicit_origin=x_clink_origin,
            status_only=True,
        )

    @app.post("/execution/polymarket/browser-order-signing-session/complete")
    def complete_browser_order_signing_session(
        request: CompletePolymarketOrderSigningSessionRequest,
        authorization: str | None = Header(default=None),
        origin: str | None = Header(default=None),
        x_clink_origin: str | None = Header(default=None),
    ) -> dict:
        access_token, browser_origin = browser_authorization(
            authorization, origin, x_clink_origin
        )
        try:
            return _browser_status_projection(
                active_service.complete_polymarket_order_signing_session_by_capability(
                    access_token=access_token,
                    origin=browser_origin,
                    request=request,
                )
            )
        except OrderSigningCapabilityError:
            raise HTTPException(
                status_code=401,
                detail="order signing capability is invalid",
            ) from None
        except OrderSigningPayloadError:
            raise HTTPException(
                status_code=400,
                detail="signed order payload is invalid",
            ) from None
        except (ValueError, RuntimeError, OrderSigningSessionRepositoryError):
            raise HTTPException(
                status_code=400,
                detail="order signing request was rejected",
            ) from None

    @app.get("/execution/polymarket/order-signing-console/")
    def polymarket_order_signing_console() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "polymarket_order_signing.html",
            media_type="text/html",
            headers=_SECURITY_HEADERS,
        )

    @app.get("/execution/polymarket/order-signing-assets/{filename}")
    def polymarket_order_signing_asset(filename: str) -> FileResponse:
        media_type = _PUBLIC_ASSETS.get(filename)
        if media_type is None:
            raise HTTPException(status_code=404, detail="asset not found")
        return FileResponse(
            STATIC_DIR / filename,
            media_type=media_type,
            headers=_SECURITY_HEADERS,
        )

    @app.get("/execution/{execution_id}")
    def get_execution(execution_id: str) -> dict:
        execution = active_service.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return execution.model_dump()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clink Prediction Markets execution service"
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Print service health instead of starting the server",
    )
    args = parser.parse_args()
    if args.sample:
        print(
            json.dumps(
                {
                    "service": "prediction_markets_execution_service",
                    "status": "ok",
                    "mode": "live_adapter_gated",
                },
                indent=2,
            )
        )
        return
    uvicorn.run(app, host=CONFIG.execution_host, port=CONFIG.execution_port)


if __name__ == "__main__":
    main()
