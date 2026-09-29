from __future__ import annotations

import secrets
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.funding_adapter_service.schemas import (  # noqa: E402
    AdvancePolymarketFundingOperationRequest,
    ConfirmPolymarketFundingOperationRequest,
    CreatePolymarketBridgeDepositRequest,
    CreatePolymarketFundingOperationRequest,
)
from services.funding_adapter_service.coordinator import (  # noqa: E402
    FundingCoordinatorError,
    PolymarketFundingCoordinator,
)
from services.funding_adapter_service.service import (  # noqa: E402
    BridgeAdapterError,
    PolymarketFundingAdapterService,
)
from services.funding_adapter_service.production_gateways import (  # noqa: E402
    build_production_funding_coordinator,
)
from shared.config import AppConfig  # noqa: E402


_MAX_REQUEST_BODY_BYTES = 16_384


def _funding_operation_json(view) -> dict:
    """Keep the legacy funding JSON shape while preserving explicit OPC scope."""
    payload = view.model_dump(mode="json")
    if payload.get("opc_installation_id") is None:
        payload.pop("opc_installation_id", None)
    return payload


class StrictInternalBearerMiddleware:
    def __init__(self, app, *, token: str) -> None:
        self.app = app
        self.expected = str(token).strip().encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return

        authorization_values = [
            value
            for key, value in scope.get("headers", [])
            if key.lower() == b"authorization"
        ]
        expected_header = b"Bearer " + self.expected
        if (
            not self.expected
            or len(authorization_values) != 1
            or not secrets.compare_digest(authorization_values[0], expected_header)
        ):
            await JSONResponse(
                {"detail": "invalid internal bearer token"}, status_code=401
            )(scope, receive, send)
            return

        if scope.get("method") in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > _MAX_REQUEST_BODY_BYTES:
                    await JSONResponse(
                        {"detail": "request body is too large"}, status_code=413
                    )(scope, receive, send)
                    return
                more_body = bool(message.get("more_body", False))

            sent = False

            async def replay_body():
                nonlocal sent
                if sent:
                    return {"type": "http.request", "body": b"", "more_body": False}
                sent = True
                return {
                    "type": "http.request",
                    "body": bytes(body),
                    "more_body": False,
                }

            await self.app(scope, replay_body, send)
            return

        await self.app(scope, receive, send)


def create_app(
    *,
    config: AppConfig | None = None,
    service: PolymarketFundingAdapterService | None = None,
    coordinator: PolymarketFundingCoordinator | None = None,
) -> FastAPI:
    selected_config = config or AppConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.funding_adapter_service is None:
            app.state.funding_adapter_service = PolymarketFundingAdapterService(
                selected_config
            )
        assemble_coordinator()
        try:
            yield
        finally:
            close_owned_coordinator()

    app = FastAPI(
        title="Clink Prediction Markets Funding Adapter",
        lifespan=lifespan,
    )
    app.state.funding_adapter_service = service
    app.state.funding_coordinator = coordinator
    app.state.funding_coordinator_assembly_attempted = coordinator is not None
    app.state.funding_coordinator_owned = False
    app.add_middleware(
        StrictInternalBearerMiddleware,
        token=selected_config.prediction_markets_internal_api_token,
    )

    def current_service() -> PolymarketFundingAdapterService:
        selected = app.state.funding_adapter_service
        if selected is None:
            selected = PolymarketFundingAdapterService(selected_config)
            app.state.funding_adapter_service = selected
        return selected

    def current_coordinator() -> PolymarketFundingCoordinator:
        assemble_coordinator()
        selected = app.state.funding_coordinator
        if selected is None:
            raise FundingCoordinatorError(
                "funding operations are unavailable", status_code=503
            )
        return selected

    def assemble_coordinator() -> None:
        if (
            app.state.funding_coordinator is not None
            or app.state.funding_coordinator_assembly_attempted
        ):
            return
        app.state.funding_coordinator_assembly_attempted = True
        try:
            selected = build_production_funding_coordinator(
                selected_config,
                funding_adapter=current_service(),
            )
            app.state.funding_coordinator = selected
            app.state.funding_coordinator_owned = True
        except Exception:
            app.state.funding_coordinator = None
            app.state.funding_coordinator_owned = False

    def close_owned_coordinator() -> None:
        if not app.state.funding_coordinator_owned:
            return
        app.state.funding_coordinator_owned = False
        selected = app.state.funding_coordinator
        close = getattr(getattr(selected, "core_gateway", None), "close", None)
        if callable(close):
            close()

    @app.exception_handler(BridgeAdapterError)
    async def bridge_adapter_error_handler(_request, exc: BridgeAdapterError):
        detail = str(exc)
        status_code = 409 if "context" in detail or "unavailable" in detail else 502
        return JSONResponse({"detail": detail}, status_code=status_code)

    @app.exception_handler(FundingCoordinatorError)
    async def funding_coordinator_error_handler(
        _request, exc: FundingCoordinatorError
    ):
        return JSONResponse(
            {"detail": str(exc)}, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(_request, _exc):
        return JSONResponse({"detail": "request is invalid"}, status_code=422)

    @app.get("/healthz")
    def healthz() -> dict:
        assemble_coordinator()
        coordinator_assembled = app.state.funding_coordinator is not None
        risk_context_available = (
            coordinator_assembled
            and app.state.funding_coordinator.risk_assessment_available
        )
        risk_mode = (
            getattr(
                app.state.funding_coordinator.risk_assessments,
                "health_mode",
                "context_available",
            )
            if risk_context_available
            else "unavailable"
        )
        return {
            "service": "prediction_markets_funding_adapter_service",
            "status": (
                "ok"
                if coordinator_assembled and risk_context_available
                else "degraded"
            ),
            "profile": selected_config.profile,
            "bridge_scope": "user_binding_wallet_address",
            "funding_coordinator": (
                "assembled" if coordinator_assembled else "unavailable"
            ),
            "risk_assessment": risk_mode,
            "risk_authority": (
                "core_policy" if risk_context_available else "unavailable"
            ),
        }

    @app.post("/polymarket/deposit-address", status_code=201)
    def create_deposit_address(
        request: CreatePolymarketBridgeDepositRequest,
    ) -> dict:
        return current_service().create_deposit_address(request).model_dump(
            mode="json"
        )

    @app.get("/polymarket/bridge-status/{bridge_address}")
    def get_bridge_status(
        bridge_address: str,
        user_id: str = Query(min_length=1, max_length=96),
        binding_id: str = Query(min_length=1, max_length=96),
        venue_wallet_address: str = Query(min_length=42, max_length=42),
        expected_amount_atomic: str = Query(min_length=1, max_length=78),
        not_before_time_ms: int = Query(ge=0),
        expected_bridge_tx_hash: str | None = Query(
            default=None, min_length=66, max_length=66
        ),
    ) -> dict:
        return current_service().get_bridge_status(
            user_id=user_id,
            binding_id=binding_id,
            venue_wallet_address=venue_wallet_address,
            bridge_address=bridge_address,
            expected_amount_atomic=expected_amount_atomic,
            not_before_time_ms=not_before_time_ms,
            expected_bridge_tx_hash=expected_bridge_tx_hash,
        ).model_dump(mode="json")

    @app.get("/polymarket/account-balance")
    def get_account_balance(
        user_id: str = Query(min_length=1, max_length=96),
    ) -> dict:
        gateway = current_coordinator().venue_accounts
        account = gateway.resolve_active_account(user_id=user_id)
        amount_atomic = gateway.get_buying_power_atomic(
            user_id=user_id,
            binding_id=account.binding_id,
            venue_wallet_address=account.venue_wallet_address,
        )
        return {
            "status": "ready",
            "user_id": user_id,
            "venue": "polymarket",
            "venue_wallet_address": account.venue_wallet_address,
            "asset": "USDC",
            "available_amount_atomic": amount_atomic,
            "available_amount_usdc": format(
                Decimal(amount_atomic).scaleb(-6), ".6f"
            ),
        }

    @app.post("/polymarket/funding-operations", status_code=201)
    def create_funding_operation(
        request: CreatePolymarketFundingOperationRequest,
    ) -> dict:
        selected = current_coordinator()
        return _funding_operation_json(selected.view(selected.prepare(request)))

    @app.get("/polymarket/funding-operations/{operation_id}")
    def get_funding_operation(
        operation_id: str,
        user_id: str = Query(min_length=1, max_length=96),
    ) -> dict:
        selected = current_coordinator()
        return _funding_operation_json(
            selected.view(selected.get(user_id=user_id, operation_id=operation_id))
        )

    @app.get("/polymarket/funding-history/{operation_id}")
    def get_funding_history(
        operation_id: str,
        user_id: str = Query(min_length=1, max_length=96),
    ) -> dict:
        selected = current_coordinator()
        return _funding_operation_json(
            selected.view(
                selected.get_history(user_id=user_id, operation_id=operation_id)
            )
        )

    @app.post("/polymarket/funding-operations/{operation_id}/confirm")
    def confirm_funding_operation(
        operation_id: str,
        request: ConfirmPolymarketFundingOperationRequest,
    ) -> dict:
        selected = current_coordinator()
        return _funding_operation_json(
            selected.view(selected.confirm(operation_id, request))
        )

    @app.post("/polymarket/funding-operations/{operation_id}/advance")
    def advance_funding_operation(
        operation_id: str,
        request: AdvancePolymarketFundingOperationRequest,
    ) -> dict:
        selected = current_coordinator()
        return _funding_operation_json(
            selected.view(
                selected.advance(
                    user_id=request.user_id,
                    operation_id=operation_id,
                    opc_installation_id=request.opc_installation_id,
                )
            )
        )

    return app


CONFIG = AppConfig.from_env()
APP = create_app(config=CONFIG)


def main() -> None:
    uvicorn.run(APP, host=CONFIG.funding_adapter_host, port=CONFIG.funding_adapter_port)


if __name__ == "__main__":
    main()
