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

from services.authorization_service.schemas import (  # noqa: E402
    CheckAuthorizationRequest,
    CreateAuthorizationRequest,
    SpendAuthorizationRequest,
)
from services.authorization_service.service import AuthorizationService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.auth import require_internal_token  # noqa: E402

APP_CONFIG = AppConfig.from_env()
SERVICE = AuthorizationService()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Authorization Service",
        version="0.1.0",
        description="Budget authorization service for Clink Core.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.middleware("http")(require_internal_token(APP_CONFIG))

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "service": "authorization_service",
            "status": "ok",
            "storage": APP_CONFIG.authorization_session_file,
        }

    @app.post("/authorizations")
    def create_authorization(request: CreateAuthorizationRequest) -> dict:
        return SERVICE.create_authorization(request).to_dict()

    @app.get("/authorizations/{authorization_id}")
    def get_authorization(authorization_id: str) -> dict:
        authorization = SERVICE.get_authorization(authorization_id)
        if authorization is None:
            raise HTTPException(status_code=404, detail="authorization not found")
        return authorization.to_dict()

    @app.post("/authorizations/{authorization_id}/check")
    def check_authorization(authorization_id: str, request: CheckAuthorizationRequest) -> dict:
        result = SERVICE.check_authorization(authorization_id, request)
        if result is None:
            raise HTTPException(status_code=404, detail="authorization not found")
        return result.to_dict()

    @app.post("/authorizations/{authorization_id}/spend")
    def spend_authorization(authorization_id: str, request: SpendAuthorizationRequest) -> dict:
        result = SERVICE.spend_authorization(authorization_id, request)
        if result is None:
            raise HTTPException(status_code=404, detail="authorization not found")
        return result.to_dict()

    @app.post("/authorizations/{authorization_id}/revoke")
    def revoke_authorization(authorization_id: str) -> dict:
        authorization = SERVICE.revoke_authorization(authorization_id)
        if authorization is None:
            raise HTTPException(status_code=404, detail="authorization not found")
        return authorization.to_dict()

    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Clink authorization service")
    parser.add_argument("--sample", action="store_true", help="Print a sample authorization instead of starting the server")
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--agent-id", default="agent_001")
    parser.add_argument("--max-amount-usdc", default="0.1")
    args = parser.parse_args()

    if args.sample:
        result = SERVICE.create_authorization(
            CreateAuthorizationRequest(
                user_id=args.user_id,
                agent_id=args.agent_id,
                max_amount_usdc=args.max_amount_usdc,
            )
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        app,
        host=APP_CONFIG.authorization_service_host,
        port=APP_CONFIG.authorization_service_port,
    )


if __name__ == "__main__":
    main()
