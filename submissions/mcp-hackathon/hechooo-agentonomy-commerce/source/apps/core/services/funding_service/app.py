import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.funding_service.schemas import (  # noqa: E402
    CreateDirectTransferRequest,
    CreateSpendingReservationRequest,
    FinalizeSpendingReservationRequest,
    FinalizeExternalPaymentRequest,
    FinalizeProxyPaymentRequest,
    IssuePaymentCapabilityRequest,
    HostedExecutionAuthorityRequest,
    HostedPreflightAuthorityRequest,
    PrepareProxyPaymentRequest,
    ReleaseSpendingReservationRequest,
    ReconcileSpendingReservationRequest,
    SettleSpendingReservationRequest,
)
from services.funding_service.service import FundingService  # noqa: E402
from services.funding_service.transfer_service import DirectTransferService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.auth import require_internal_token

APP_CONFIG = AppConfig.from_env()
SERVICE = FundingService(config=APP_CONFIG)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Clink Funding Service",
        version="0.1.0",
        description="Wallet-signed funding authorization and x402-style top-up receipt service.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(require_internal_token(APP_CONFIG))

    @app.post("/funding/transfers")
    def create_direct_transfer(request: CreateDirectTransferRequest) -> dict:
        try:
            return DirectTransferService(SERVICE).create(request)
        except ValueError as exc:
            raise HTTPException(409, DirectTransferService._safe_reason(str(exc))) from None

    @app.get("/funding/transfers/{transfer_id}")
    def get_direct_transfer(
        transfer_id: str, user_id: str = Query(min_length=1, max_length=96),
        agent_id: str = Query(min_length=1, max_length=96),
        opc_installation_id: str | None = Query(default=None, max_length=96),
    ) -> dict:
        try:
            return DirectTransferService(SERVICE).get(
                transfer_id, user_id=user_id, agent_id=agent_id,
                opc_installation_id=opc_installation_id,
            )
        except ValueError:
            raise HTTPException(404, "TRANSFER_NOT_FOUND") from None

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.endswith("/proxy-prepare"):
            return JSONResponse(
                status_code=409,
                content={
                    "detail": {
                        "code": "PROXY_INCOMPATIBLE",
                        "message": "merchant proxy payment requirement is invalid",
                    }
                },
            )
        return JSONResponse(
            status_code=422,
            content={"detail": "request could not be completed"},
        )

    @app.get("/healthz")
    def healthz() -> dict:
        readiness = SERVICE.get_funding_readiness()
        return {
            "service": "funding_service",
            "status": "ok",
            "storage": APP_CONFIG.funding_session_file,
            "network": APP_CONFIG.x402_payment_network,
            "token": APP_CONFIG.x402_payment_token,
            "live_funding_enabled": APP_CONFIG.clink_live_funding,
            "funding_readiness": readiness,
            "settlement_rail": readiness["settlement_rail"],
        }

    @app.get("/funding/spending-authorizations/{spending_authorization_id}")
    def get_spending_authorization(spending_authorization_id: str) -> dict:
        authorization = SERVICE.get_spending_authorization(spending_authorization_id)
        if authorization is None:
            raise HTTPException(status_code=404, detail="spending authorization not found")
        return authorization.to_dict()

    @app.get("/funding/status")
    def get_funding_status(user_id: str | None = None, venue: str | None = None) -> dict:
        return SERVICE.get_funding_status(user_id=user_id, venue=venue).to_dict()

    @app.get("/funding/readiness")
    def get_funding_readiness() -> dict:
        return SERVICE.get_funding_readiness()

    @app.get("/funding/hosted-wallet-readiness")
    def hosted_wallet_readiness(user_id: str) -> dict:
        try:
            return SERVICE.get_hosted_wallet_readiness(user_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="user identity is invalid") from None

    @app.post("/funding/spending-reservations")
    def reserve(request: CreateSpendingReservationRequest) -> dict:
        try: return SERVICE.reserve_spending(request)
        except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/funding/spending-reservations/{reservation_id}")
    def reservation(reservation_id: str) -> dict:
        row=SERVICE.get_reservation(reservation_id)
        if not row: raise HTTPException(status_code=404,detail="reservation not found")
        return row

    @app.post("/funding/spending-reservations/{reservation_id}/payment-capability")
    def payment_capability(
        reservation_id: str, request: IssuePaymentCapabilityRequest
    ) -> dict:
        try:
            return SERVICE.issue_payment_capability(reservation_id, request).model_dump(
                mode="json"
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/hosted-authority")
    def hosted_authority(
        reservation_id: str, request: HostedExecutionAuthorityRequest
    ) -> dict:
        try:
            return SERVICE.authorize_hosted_execution(
                reservation_id, request
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/funding/spending-reservations/{reservation_id}/hosted-preflight-authority"
    )
    def hosted_preflight_authority(
        reservation_id: str, request: HostedPreflightAuthorityRequest
    ) -> dict:
        try:
            return SERVICE.authorize_hosted_preflight(
                reservation_id, request
            ).model_dump(mode="json")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/settle")
    def settle(reservation_id: str, request: SettleSpendingReservationRequest) -> dict:
        try: return SERVICE.settle_reservation(reservation_id,request)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/reconcile")
    def reconcile(
        reservation_id: str,
        request: ReconcileSpendingReservationRequest | None = None,
    ) -> dict:
        try:
            return SERVICE.reconcile_reservation(
                reservation_id,
                operator_reconcile=bool(request and request.operator_reconcile),
            )
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/finalize")
    def finalize(reservation_id: str, request: FinalizeSpendingReservationRequest) -> dict:
        try: return SERVICE.finalize_reservation(reservation_id,request)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/release")
    def release(reservation_id: str, request: ReleaseSpendingReservationRequest) -> dict:
        try: return SERVICE.release_reservation(reservation_id,request)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/external-finalize")
    def external_finalize(reservation_id: str, request: FinalizeExternalPaymentRequest) -> dict:
        try: return SERVICE.finalize_external_payment(reservation_id,request)
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/proxy-prepare")
    def proxy_prepare(reservation_id: str, request: PrepareProxyPaymentRequest) -> dict:
        try:
            return SERVICE.prepare_proxy_payment(reservation_id, request)
        except ValueError as exc:
            message = str(exc)
            incompatibility_messages = {
                "merchant challenge drift",
                "merchant token domain does not match trusted Core configuration",
            }
            code = (
                "PROXY_INCOMPATIBLE"
                if message in incompatibility_messages
                else "PROXY_PREPARE_CONFLICT"
            )
            raise HTTPException(
                status_code=409,
                detail={"code": code, "message": message},
            ) from exc

    @app.post("/funding/spending-reservations/{reservation_id}/proxy-finalize")
    def proxy_finalize(reservation_id: str, request: FinalizeProxyPaymentRequest) -> dict:
        try:
            return SERVICE.finalize_proxy_payment(reservation_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host=APP_CONFIG.funding_service_host, port=APP_CONFIG.funding_service_port)


if __name__ == "__main__":
    main()
